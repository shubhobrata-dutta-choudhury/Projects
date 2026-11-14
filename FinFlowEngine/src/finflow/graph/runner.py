"""
Resilient Workflow Execution Runner for FinFlow-Engine.

Provides synchronous and asynchronous entry points (`run_finflow_workflow`) to kick off
LangGraph executions, handle Human-in-the-Loop (HITL) resumption, record workflow-level
telemetry, and route unrecoverable execution crashes to the Redis Dead-Letter Queue (DLQ).
"""

from __f12__ import annotations

import uuid
from typing import Any

from langgraph.types import Command

from finflow.graph.builder import compiled_graph
from finflow.observability.evaluators import evaluate_and_score_workflow
from finflow.observability.langfuse_client import get_tracer
from finflow.resilience.dlq import RedisEventBusAndDLQ
from finflow.resilience.idempotency import IdempotencyStore


def run_finflow_workflow(
    user_query: str,
    total_capital_usd: float = 5_000_000.0,
    macro_scenario: str = "baseline",
    chaos_mode: bool = False,
    thread_id: str | None = None,
    human_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute the resilient multi-agent FinFlow workflow end-to-end.
    Supports thread resumption, idempotency caching, Langfuse tracing, and DLQ error routing.
    """
    t_id = thread_id or f"finflow-thread-{uuid.uuid4().hex[:8]}"
    tracer = get_tracer()
    bus = RedisEventBusAndDLQ()
    idempotency_store = IdempotencyStore()

    # 1. Compute idempotency key and check completed store
    idempotency_key = IdempotencyStore.compute_key(user_query, total_capital_usd, macro_scenario)
    if not human_review:
        completed = idempotency_store.get_completed_result(idempotency_key)
        if completed is not None:
            completed["_idempotency_cache_hit"] = True
            return completed

    # 2. Initialize root Langfuse trace
    tracer.start_trace(
        thread_id=t_id,
        name="finflow-main-orchestration",
        user_query=user_query,
        metadata={"total_capital_usd": total_capital_usd, "macro_scenario": macro_scenario},
        tags=["finflow", "production", macro_scenario],
    )

    bus.publish_event(
        thread_id=t_id,
        event_type="workflow.started",
        node="runner",
        payload={"user_query": user_query, "capital": total_capital_usd, "scenario": macro_scenario},
    )

    config = {"configurable": {"thread_id": t_id}}

    try:
        if human_review is not None:
            # Resume suspended graph execution past `interrupt()` using LangGraph Command
            result_state = compiled_graph.invoke(Command(resume=human_review), config=config)
        else:
            initial_state = {
                "thread_id": t_id,
                "user_query": user_query,
                "total_capital_usd": total_capital_usd,
                "macro_scenario": macro_scenario,
                "chaos_mode": chaos_mode,
                "allocations": [],
                "quant_reports": {},
                "fundamental_reports": {},
                "portfolio_risk": {},
                "draft_memo": "",
                "final_memo": "",
                "revision_count": 0,
                "critic_audit": {},
                "human_review": None,
                "workflow_status": "STARTED",
                "visited_nodes": [],
                "audit_trail": [],
            }
            result_state = compiled_graph.invoke(initial_state, config=config)

        # Run automated evaluation metrics & report to Langfuse
        eval_scores = evaluate_and_score_workflow(thread_id=t_id, state=result_state)
        result_state["evaluation_scores"] = eval_scores

        # Cache completed result if successfully approved
        if result_state.get("workflow_status") in ("COMPLETED_APPROVED", "COMPLETED_REJECTED"):
            idempotency_store.save_completed_result(idempotency_key, result_state)

        bus.publish_event(
            thread_id=t_id,
            event_type="workflow.completed",
            node="runner",
            payload={"status": result_state.get("workflow_status"), "scores": eval_scores},
        )

        return result_state

    except Exception as exc:
        # Route unrecoverable workflow failures to Redis Dead-Letter Queue (DLQ)
        error_type = type(exc).__name__
        error_msg = str(exc)
        dlq_id = bus.push_to_dlq(
            thread_id=t_id,
            failed_node="runner_orchestration",
            error_type=error_type,
            error_message=error_msg,
            state_snapshot={"user_query": user_query, "capital": total_capital_usd},
        )
        tracer.record_score(
            thread_id=t_id,
            name="workflow_execution_success",
            value=0.0,
            comment=f"Failed with {error_type}: {error_msg} (DLQ ID: {dlq_id})",
        )
        raise RuntimeError(
            f"FinFlow workflow execution crashed with {error_type}: {error_msg}. "
            f"Captured in Redis DLQ under ID '{dlq_id}'."
        ) from exc
