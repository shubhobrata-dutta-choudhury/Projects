"""
Automated Financial Groundedness, Compliance Adherence, and Cost/Efficiency Evaluators.

Computes objective quality scores on every workflow run and reports them to
Langfuse (`tracer.record_score(...)`). Also powers the Critic Agent's
deterministic numerical verification pass.
"""

from __future__ import annotations

from typing import Any

from finflow.observability.langfuse_client import get_tracer


def verify_memo_numerical_groundedness(
    memo_text: str,
    quant_reports: dict[str, dict[str, Any]],
    fundamental_reports: dict[str, dict[str, Any]],
    portfolio_risk: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    """
    Verify that canonical metrics for each analyzed ticker and portfolio VaR
    are accurately cited in `memo_text` without hallucinated figures.

    Returns `(groundedness_score_0_to_1, discrepancies, missing_disclosures)`.
    """
    discrepancies: list[str] = []
    missing_disclosures: list[str] = []
    total_checks = 0
    passed_checks = 0

    for ticker, q_rep in sorted(quant_reports.items()):
        # 1. Check Spot Price citation
        total_checks += 1
        expected_spot = f"${q_rep.get('spot_price', 0.0):,.2f}"
        if expected_spot in memo_text:
            passed_checks += 1
        else:
            discrepancies.append(
                f"Ticker {ticker}: Expected spot price '{expected_spot}' not found or altered in memo."
            )

        # 2. Check Daily 95% VaR citation
        total_checks += 1
        expected_var = f"{q_rep.get('daily_var_95_pct', 0.0):.2f}%"
        if expected_var in memo_text:
            passed_checks += 1
        else:
            discrepancies.append(
                f"Ticker {ticker}: Expected 95% daily VaR '{expected_var}' missing or mismatched."
            )

        # 3. Check Sharpe ratio citation
        total_checks += 1
        expected_sharpe = f"{q_rep.get('sharpe_ratio', 0.0):.2f}"
        if expected_sharpe in memo_text:
            passed_checks += 1
        else:
            discrepancies.append(
                f"Ticker {ticker}: Expected Sharpe ratio '{expected_sharpe}' missing or mismatched."
            )

    for ticker, f_rep in sorted(fundamental_reports.items()):
        # 4. Check rating citation
        rating = f_rep.get("fundamental_rating", "")
        if rating:
            total_checks += 1
            if rating in memo_text:
                passed_checks += 1
            else:
                discrepancies.append(
                    f"Ticker {ticker}: Fundamental rating '{rating}' not explicitly cited."
                )

        # 5. Check risk factors disclosure coverage
        sec_risks = f_rep.get("sec_10k_key_risks", [])
        if sec_risks:
            total_checks += 1
            if any(risk[:15].lower() in memo_text.lower() for risk in sec_risks):
                passed_checks += 1
            else:
                missing_disclosures.append(
                    f"Ticker {ticker}: Key SEC 10-K risk factors not cited in memo."
                )

    # 6. Check weighted portfolio VaR citation
    if portfolio_risk:
        total_checks += 1
        port_var = f"{portfolio_risk.get('weighted_portfolio_var_95_pct', 0.0):.2f}%"
        if port_var in memo_text:
            passed_checks += 1
        else:
            discrepancies.append(
                f"Portfolio: Weighted 95% VaR figure '{port_var}' missing from executive memo."
            )

    score = round(passed_checks / max(1, total_checks), 4)
    return score, discrepancies, missing_disclosures


def evaluate_and_score_workflow(
    thread_id: str,
    state: dict[str, Any],
) -> dict[str, float]:
    """
    Run post-execution evaluators on the workflow state and push scores to Langfuse:
    - `numerical_groundedness` (0.0 - 1.0)
    - `compliance_gate_adherence` (0.0 - 1.0)
    - `resilience_recovery_health` (0.0 - 1.0)
    """
    tracer = get_tracer()
    memo = state.get("final_memo") or state.get("draft_memo") or ""
    quant_reports = state.get("quant_reports", {})
    fundamental_reports = state.get("fundamental_reports", {})
    portfolio_risk = state.get("portfolio_risk", {})

    groundedness_score, discrepancies, _ = verify_memo_numerical_groundedness(
        memo_text=memo,
        quant_reports=quant_reports,
        fundamental_reports=fundamental_reports,
        portfolio_risk=portfolio_risk,
    )

    # Compliance policy adherence check
    requires_hitl = bool(portfolio_risk.get("requires_human_approval", False))
    human_review = state.get("human_review")
    if not requires_hitl:
        compliance_score = 1.0
    elif human_review is not None:
        compliance_score = 1.0
    else:
        compliance_score = 0.0

    # Resilience & self-correction score
    revision_count = int(state.get("revision_count", 0))
    resilience_score = 1.0 if len(discrepancies) == 0 else max(0.0, 1.0 - 0.25 * revision_count)

    scores = {
        "numerical_groundedness": groundedness_score,
        "compliance_gate_adherence": compliance_score,
        "resilience_recovery_health": round(resilience_score, 4),
    }

    for metric_name, val in scores.items():
        tracer.record_score(
            thread_id=thread_id,
            name=metric_name,
            value=val,
            comment=f"Automated FinFlow evaluator for {metric_name}",
        )

    return scores
