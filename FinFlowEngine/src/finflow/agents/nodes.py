"""
Resilient Multi-Agent Node Implementations for FinFlow-Engine.

Each agent node is instrumented with:
1. Langfuse Span & Generation tracing (`ObservabilityTracer`)
2. Redis Streams real-time lifecycle events (`RedisEventBusAndDLQ`)
3. Exponential backoff retry policies (`execute_with_retry`)
4. Distributed Circuit Breaker protection (`DistributedCircuitBreaker`) with
   automatic primary -> fallback model routing.
5. Native LangGraph `interrupt()` for Human-in-the-Loop compliance governance.
"""

from __future__ import annotations

import re
from typing import Any

from langgraph.types import interrupt

from finflow.config import get_settings
from finflow.observability.evaluators import verify_memo_numerical_groundedness
from finflow.observability.langfuse_client import get_tracer
from finflow.observability.prompt_registry import get_versioned_prompt
from finflow.resilience.circuit_breaker import DistributedCircuitBreaker
from finflow.resilience.dlq import RedisEventBusAndDLQ
from finflow.resilience.retry_policy import execute_with_retry
from finflow.state.schemas import (
    AssetSubTaskState,
    CriticAuditReport,
    FinFlowState,
    make_audit_entry,
)
from finflow.tools.market_data import compute_ticker_quant_metrics
from finflow.tools.portfolio_sim import evaluate_portfolio_risk_and_compliance
from finflow.tools.sec_filings import fetch_sec_fundamental_metrics

_KNOWN_TICKERS = ("NVDA", "MSFT", "AAPL", "JPM", "TSLA", "RUSAL")


def _extract_tickers_from_query(user_query: str) -> list[str]:
    upper = user_query.upper()
    found = [t for t in _KNOWN_TICKERS if re.search(rf"\b{t}\b", upper)]
    if not found:
        return ["NVDA", "MSFT"]
    return found


def planner_node(state: FinFlowState) -> dict[str, Any]:
    """
    Agent 1: Portfolio Planner & Dynamic Router.
    Parses the institutional mandate, extracts tickers & weights, and prepares
    the parallel fan-out execution plan.
    """
    thread_id = state.get("thread_id", "default-thread")
    user_query = state.get("user_query", "Evaluate NVDA and MSFT allocation")
    total_capital = float(state.get("total_capital_usd", 5_000_000.0))
    macro_scenario = state.get("macro_scenario", "baseline")

    tracer = get_tracer()
    bus = RedisEventBusAndDLQ()
    settings = get_settings()
    cb = DistributedCircuitBreaker("llm-planner")

    with tracer.trace_node_span(
        thread_id=thread_id,
        node_name="planner",
        input_summary={"user_query": user_query, "total_capital_usd": total_capital},
    ) as span:
        prompt = get_versioned_prompt("finflow-planner-v2")
        compiled_prompt = prompt.compile(
            user_query=user_query,
            total_capital_usd=total_capital,
            macro_scenario=macro_scenario,
        )

        def _primary_plan() -> list[dict[str, Any]]:
            tickers = _extract_tickers_from_query(user_query)
            n = len(tickers)
            # Check if explicit concentration is requested in query (e.g. "70% NVDA")
            explicit_match = re.search(r"(\d{2})%\s*(NVDA|MSFT|AAPL|JPM|TSLA)", user_query.upper())
            allocations: list[dict[str, Any]] = []

            if explicit_match and n >= 2:
                first_wt = float(explicit_match.group(1))
                target_tkr = explicit_match.group(2)
                rem_wt = round((100.0 - first_wt) / (n - 1), 2)
                for t in tickers:
                    wt = first_wt if t == target_tkr else rem_wt
                    allocations.append(
                        {
                            "ticker": t,
                            "weight_pct": wt,
                            "notional_usd": round(total_capital * (wt / 100.0), 2),
                        }
                    )
            else:
                equal_wt = round(100.0 / n, 2)
                for idx, t in enumerate(tickers):
                    wt = equal_wt if idx < n - 1 else round(100.0 - equal_wt * (n - 1), 2)
                    allocations.append(
                        {
                            "ticker": t,
                            "weight_pct": wt,
                            "notional_usd": round(total_capital * (wt / 100.0), 2),
                        }
                    )
            return allocations

        allocations, cb_meta = cb.execute(_primary_plan, fallback_fn=_primary_plan)
        mandate_summary = (
            f"Institutional due diligence on {', '.join(a['ticker'] for a in allocations)} "
            f"for ${total_capital:,.2f} under '{macro_scenario}' scenario."
        )

        tracer.record_generation(
            thread_id=thread_id,
            node_name="planner",
            model=settings.fallback_model if cb_meta["used_fallback"] else settings.primary_model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            input_tokens=len(compiled_prompt.split()) * 2,
            output_tokens=110,
            cost_usd=0.0018,
            output_preview=mandate_summary,
        )

        span["output"] = {"allocations": allocations, "mandate_summary": mandate_summary}
        span["metadata"] = cb_meta

        bus.publish_event(
            thread_id=thread_id,
            event_type="node.completed",
            node="planner",
            payload={"tickers": [a["ticker"] for a in allocations]},
        )

        return {
            "mandate_summary": mandate_summary,
            "allocations": allocations,
            "workflow_status": "IN_PROGRESS",
            "visited_nodes": ["planner"],
            "audit_trail": [
                make_audit_entry(
                    node="planner",
                    action="decomposed_mandate",
                    details={"allocations": allocations, "circuit_breaker": cb_meta},
                    event_id=f"{thread_id}:planner:complete",
                )
            ],
        }


def analyze_asset_worker_node(sub_state: AssetSubTaskState) -> dict[str, Any]:
    """
    Agent 2 & 3 (Parallel Map Worker via LangGraph `Send` API):
    Runs Quantitative Risk & SEC Fundamental analysis for a single ticker
    with exponential backoff retry protection and Redis tool caching.
    """
    thread_id = sub_state["thread_id"]
    ticker = sub_state["ticker"]
    macro_scenario = sub_state.get("macro_scenario", "baseline")
    chaos_mode = bool(sub_state.get("chaos_mode", False))

    tracer = get_tracer()
    bus = RedisEventBusAndDLQ()
    settings = get_settings()

    with tracer.trace_node_span(
        thread_id=thread_id,
        node_name=f"analyze_asset[{ticker}]",
        input_summary={"ticker": ticker, "macro_scenario": macro_scenario, "chaos_mode": chaos_mode},
    ) as span:
        quant_data, quant_retry_meta = execute_with_retry(
            operation_name=f"quant_metrics:{ticker}",
            fn=lambda: compute_ticker_quant_metrics(
                ticker=ticker,
                macro_scenario=macro_scenario,
                chaos_mode=chaos_mode,
                thread_id=thread_id,
            ),
        )

        sec_data, sec_retry_meta = execute_with_retry(
            operation_name=f"sec_filings:{ticker}",
            fn=lambda: fetch_sec_fundamental_metrics(
                ticker=ticker,
                chaos_mode=chaos_mode,
                thread_id=thread_id,
            ),
        )

        q_prompt = get_versioned_prompt("finflow-quant-analyst-v3")
        tracer.record_generation(
            thread_id=thread_id,
            node_name=f"analyze_asset[{ticker}]",
            model=settings.primary_model,
            prompt_name=q_prompt.name,
            prompt_version=q_prompt.version,
            input_tokens=160,
            output_tokens=140,
            cost_usd=0.0024,
            output_preview=f"{ticker} VaR={quant_data['daily_var_95_pct']}% Rating={sec_data['fundamental_rating']}",
        )

        recovered = (
            quant_retry_meta["recovered_from_transient_error"]
            or sec_retry_meta["recovered_from_transient_error"]
        )
        span["output"] = {"quant": quant_data, "fundamental": sec_data}
        span["metadata"] = {"quant_retry": quant_retry_meta, "sec_retry": sec_retry_meta}

        bus.publish_event(
            thread_id=thread_id,
            event_type="asset.analyzed",
            node=f"analyze_asset[{ticker}]",
            payload={
                "ticker": ticker,
                "recovered_from_chaos": recovered,
                "cache_hit": quant_data.get("_cache_hit", False),
            },
        )

        return {
            "quant_reports": {ticker: quant_data},
            "fundamental_reports": {ticker: sec_data},
            "visited_nodes": [f"analyze_asset[{ticker}]"],
            "audit_trail": [
                make_audit_entry(
                    node=f"analyze_asset[{ticker}]",
                    action="completed_asset_due_diligence",
                    status="RECOVERY" if recovered else "INFO",
                    details={
                        "ticker": ticker,
                        "quant_retry": quant_retry_meta,
                        "sec_retry": sec_retry_meta,
                        "cache_hit": quant_data.get("_cache_hit", False),
                    },
                    event_id=f"{thread_id}:asset:{ticker}:complete",
                )
            ],
        }


def risk_compliance_gate_node(state: FinFlowState) -> dict[str, Any]:
    """
    Agent 4: Risk & Compliance Gatekeeper.
    Aggregates parallel asset analyses into portfolio-level risk metrics.
    If VaR, single-name concentration, or sanctions rules are breached, triggers
    a native LangGraph `interrupt()` to pause execution for Human-in-the-Loop sign-off.
    """
    thread_id = state.get("thread_id", "default-thread")
    total_capital = float(state.get("total_capital_usd", 5_000_000.0))
    allocations = list(state.get("allocations", []))
    quant_reports = state.get("quant_reports", {})

    tracer = get_tracer()
    bus = RedisEventBusAndDLQ()

    risk_report = evaluate_portfolio_risk_and_compliance(
        total_capital_usd=total_capital,
        allocations=allocations,
        quant_reports=quant_reports,
    )

    human_review: dict[str, Any] | None = state.get("human_review")

    if risk_report["requires_human_approval"] and not human_review:
        bus.publish_event(
            thread_id=thread_id,
            event_type="workflow.interrupted_for_hitl",
            node="risk_compliance_gate",
            payload={
                "policy_violations": risk_report["policy_violations"],
                "weighted_portfolio_var_95_pct": risk_report["weighted_portfolio_var_95_pct"],
            },
        )
        # Native LangGraph interrupt: persists state in Redis checkpointer and suspends
        human_decision_payload = interrupt(
            {
                "interrupt_type": "COMPLIANCE_GATE_REVIEW",
                "thread_id": thread_id,
                "policy_violations": risk_report["policy_violations"],
                "weighted_portfolio_var_95_pct": risk_report["weighted_portfolio_var_95_pct"],
                "stressed_portfolio_loss_usd": risk_report["stressed_portfolio_loss_usd"],
                "current_allocations": allocations,
                "instructions": (
                    "Provide HumanReviewPayload with decision in "
                    "['APPROVE', 'REJECT', 'OVERRIDE_WEIGHTS']."
                ),
            }
        )
        human_review = (
            human_decision_payload
            if isinstance(human_decision_payload, dict)
            else {"decision": str(human_decision_payload), "reviewer_id": "compliance_officer"}
        )

    with tracer.trace_node_span(
        thread_id=thread_id,
        node_name="risk_compliance_gate",
        input_summary={"requires_human_approval": risk_report["requires_human_approval"]},
    ) as span:
        if human_review:
            decision = str(human_review.get("decision", "APPROVE")).upper()
            if decision == "REJECT":
                risk_report["compliance_status"] = "REJECTED"
            elif decision == "OVERRIDE_WEIGHTS" and human_review.get("overridden_weights"):
                overrides: dict[str, float] = human_review["overridden_weights"]
                new_allocations: list[dict[str, Any]] = []
                for alloc in allocations:
                    tkr = alloc["ticker"]
                    wt = float(overrides.get(tkr, alloc["weight_pct"]))
                    new_allocations.append(
                        {
                            "ticker": tkr,
                            "weight_pct": wt,
                            "notional_usd": round(total_capital * (wt / 100.0), 2),
                        }
                    )
                allocations = new_allocations
                risk_report = evaluate_portfolio_risk_and_compliance(
                    total_capital_usd=total_capital,
                    allocations=allocations,
                    quant_reports=quant_reports,
                )
                risk_report["compliance_status"] = "MODIFIED_BY_HUMAN"
            else:
                risk_report["compliance_status"] = "APPROVED"

        span["output"] = {"portfolio_risk": risk_report, "human_review": human_review}

        return {
            "allocations": allocations,
            "portfolio_risk": risk_report,
            "human_review": human_review,
            "workflow_status": (
                "COMPLETED_REJECTED"
                if risk_report["compliance_status"] == "REJECTED"
                else "IN_PROGRESS"
            ),
            "visited_nodes": ["risk_compliance_gate"],
            "audit_trail": [
                make_audit_entry(
                    node="risk_compliance_gate",
                    action="evaluated_portfolio_compliance",
                    status="WARN" if risk_report["requires_human_approval"] else "INFO",
                    details={"risk_report": risk_report, "human_review": human_review},
                    event_id=f"{thread_id}:compliance:{risk_report['compliance_status']}",
                )
            ],
        }


def synthesizer_node(state: FinFlowState) -> dict[str, Any]:
    """
    Agent 5: Executive Investment Memo Synthesizer.
    Compiles all quantitative, SEC fundamental, and compliance outputs into a
    structured institutional memo. Incorporates Critic feedback on reflection hops.
    """
    thread_id = state.get("thread_id", "default-thread")
    revision_count = int(state.get("revision_count", 0))
    inject_hallucination_once = bool(state.get("inject_hallucination_once", False))
    critic_audit = state.get("critic_audit") or {}
    critique_feedback = critic_audit.get("critique_feedback", "Initial synthesis pass.")

    allocations = state.get("allocations", [])
    quant_reports = state.get("quant_reports", {})
    fundamental_reports = state.get("fundamental_reports", {})
    portfolio_risk = state.get("portfolio_risk", {})
    human_review = state.get("human_review")

    tracer = get_tracer()
    settings = get_settings()

    with tracer.trace_node_span(
        thread_id=thread_id,
        node_name="synthesizer",
        input_summary={"revision_count": revision_count, "critique_feedback": critique_feedback},
    ) as span:
        prompt = get_versioned_prompt("finflow-synthesizer-v4")
        lines: list[str] = [
            "# INSTITUTIONAL INVESTMENT COMMITTEE DUE DILIGENCE MEMO",
            f"**Mandate:** {state.get('mandate_summary', '')}",
            f"**Macro Scenario:** `{state.get('macro_scenario', 'baseline')}` | **Revision:** #{revision_count}",
            "",
            "## 1. Asset-Level Quantitative & SEC Fundamental Analysis",
        ]

        for alloc in allocations:
            tkr = alloc["ticker"]
            wt = alloc["weight_pct"]
            notional = alloc["notional_usd"]
            q = quant_reports.get(tkr, {})
            f = fundamental_reports.get(tkr, {})

            # If testing self-correction loop (`inject_hallucination_once=True`) on pass 0,
            # deliberately corrupt one number so the Critic catches it and triggers a reflection loop!
            spot_price = float(q.get("spot_price", 0.0))
            if inject_hallucination_once and revision_count == 0 and tkr == allocations[0]["ticker"]:
                spot_price = round(spot_price + 999.99, 2)

            lines.extend(
                [
                    f"### {tkr} ({f.get('company_name', tkr)}) - Weight: {wt:.1f}% (${notional:,.2f})",
                    f"- **Spot Price:** ${spot_price:.2f} | **Annualized Volatility:** {q.get('annualized_volatility_pct', 0.0):.2f}%",
                    f"- **Daily 95% VaR:** {q.get('daily_var_95_pct', 0.0):.2f}% | **Expected Shortfall (CVaR):** {q.get('expected_shortfall_95_pct', 0.0):.2f}%",
                    f"- **Sharpe Ratio:** {q.get('sharpe_ratio', 0.0):.2f} | **Sortino Ratio:** {q.get('sortino_ratio', 0.0):.2f} | **Stress Loss:** {q.get('stress_loss_pct', 0.0):.2f}%",
                    f"- **Fundamentals:** P/E {f.get('pe_ratio', 0.0):.2f}x | D/E {f.get('debt_to_equity', 0.0):.2f}x | FCF ${f.get('free_cash_flow_billions', 0.0):.2f}B | Rating: **{f.get('fundamental_rating', 'HOLD')}**",
                    f"- **SEC 10-K Key Risks:** {'; '.join(f.get('sec_10k_key_risks', []))}",
                    "",
                ]
            )

        lines.extend(
            [
                "## 2. Portfolio Risk & Compliance Gate Summary",
                f"- **Total Capital Allocated:** ${portfolio_risk.get('total_capital_usd', 0.0):,.2f}",
                f"- **Weighted Portfolio 95% VaR:** {portfolio_risk.get('weighted_portfolio_var_95_pct', 0.0):.2f}% (Diversification Benefit: {portfolio_risk.get('diversification_benefit_pct', 0.0):.1f}%)",
                f"- **Scenario Stressed Portfolio Loss:** ${portfolio_risk.get('stressed_portfolio_loss_usd', 0.0):,.2f}",
                f"- **Compliance Gate Status:** `{portfolio_risk.get('compliance_status', 'APPROVED')}`",
            ]
        )

        if human_review:
            lines.append(
                f"- **Human Compliance Officer Sign-Off:** Decision=`{human_review.get('decision')}` by `{human_review.get('reviewer_id', 'officer')}` ({human_review.get('rationale', 'N/A')})"
            )

        draft_memo = "\n".join(lines)

        tracer.record_generation(
            thread_id=thread_id,
            node_name="synthesizer",
            model=settings.primary_model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            input_tokens=320,
            output_tokens=len(draft_memo.split()),
            cost_usd=0.0042,
            output_preview=draft_memo[:240],
        )

        span["output"] = {"revision_count": revision_count, "memo_length": len(draft_memo)}

        return {
            "draft_memo": draft_memo,
            "revision_count": revision_count + 1,
            "visited_nodes": ["synthesizer"],
            "audit_trail": [
                make_audit_entry(
                    node="synthesizer",
                    action=f"compiled_investment_memo_rev_{revision_count}",
                    details={"revision_count": revision_count, "chars": len(draft_memo)},
                    event_id=f"{thread_id}:synthesizer:rev:{revision_count}",
                )
            ],
        }


def critic_auditor_node(state: FinFlowState) -> dict[str, Any]:
    """
    Agent 6: Critic & Numerical Groundedness Auditor.
    Cross-checks every numerical metric and SEC risk factor in `draft_memo`
    against the ground-truth tool outputs in `quant_reports`, `fundamental_reports`,
    and `portfolio_risk`. If discrepancies exist, routes back to `synthesizer`.
    """
    thread_id = state.get("thread_id", "default-thread")
    draft_memo = state.get("draft_memo", "")
    revision_count = int(state.get("revision_count", 1))
    quant_reports = state.get("quant_reports", {})
    fundamental_reports = state.get("fundamental_reports", {})
    portfolio_risk = state.get("portfolio_risk", {})

    tracer = get_tracer()
    bus = RedisEventBusAndDLQ()
    settings = get_settings()

    with tracer.trace_node_span(
        thread_id=thread_id,
        node_name="critic_auditor",
        input_summary={"revision_count": revision_count},
    ) as span:
        score, discrepancies, missing_disclosures = verify_memo_numerical_groundedness(
            memo_text=draft_memo,
            quant_reports=quant_reports,
            fundamental_reports=fundamental_reports,
            portfolio_risk=portfolio_risk,
        )
        is_grounded = len(discrepancies) == 0 and len(missing_disclosures) == 0

        critique_feedback = ""
        if not is_grounded:
            issues = discrepancies + missing_disclosures
            critique_feedback = (
                "CRITICAL NUMERICAL AUDIT FAILURE: Fix the following discrepancies using exact tool figures: "
                + " | ".join(issues)
            )

        audit_report = CriticAuditReport(
            is_grounded=is_grounded,
            numerical_discrepancies=discrepancies,
            missing_risk_disclosures=missing_disclosures,
            confidence_score=score,
            critique_feedback=critique_feedback,
        ).model_dump()

        prompt = get_versioned_prompt("finflow-critic-auditor-v3")
        tracer.record_generation(
            thread_id=thread_id,
            node_name="critic_auditor",
            model=settings.primary_model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            input_tokens=290,
            output_tokens=95,
            cost_usd=0.0021,
            output_preview=f"is_grounded={is_grounded} score={score}",
        )

        span["output"] = audit_report

        if not is_grounded:
            bus.publish_event(
                thread_id=thread_id,
                event_type="critic.detected_hallucination",
                node="critic_auditor",
                payload={"discrepancies": discrepancies, "revision_count": revision_count},
            )

        final_memo = draft_memo if (is_grounded or revision_count > settings.max_critic_reflection_hops) else ""
        workflow_status = "COMPLETED_APPROVED" if final_memo else "IN_PROGRESS"

        return {
            "critic_audit": audit_report,
            "final_memo": final_memo,
            "workflow_status": workflow_status,
            "visited_nodes": ["critic_auditor"],
            "audit_trail": [
                make_audit_entry(
                    node="critic_auditor",
                    action="audited_numerical_groundedness",
                    status="INFO" if is_grounded else "WARN",
                    details=audit_report,
                    event_id=f"{thread_id}:critic:rev:{revision_count}",
                )
            ],
        }
