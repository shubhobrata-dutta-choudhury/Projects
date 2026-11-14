"""
FastAPI REST Web Service for FinFlow-Engine.

Exposes production endpoints for:
1. Running institutional multi-agent financial workflows (`POST /api/v1/workflow/run`)
2. Resuming suspended workflows with Human-in-the-Loop review (`POST /api/v1/workflow/resume`)
3. Inspecting Dead-Letter Queue (DLQ) failures (`GET /api/v1/dlq`)
4. Health & Redis connectivity checks (`GET /health`)
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from finflow.graph.runner import run_finflow_workflow
from finflow.resilience.dlq import RedisEventBusAndDLQ
from finflow.resilience.redis_client import is_using_fallback_redis

app = FastAPI(
    title="FinFlow-Engine REST API",
    description="Resilient Multi-Agent Financial Workflow Engine with LangGraph, Langfuse, and Redis.",
    version="1.0.0",
)


class WorkflowRunRequest(BaseModel):
    user_query: str = Field(..., example="Evaluate NVDA and MSFT allocation with $5M capital under baseline scenario.")
    total_capital_usd: float = Field(5_000_000.0, example=5000000.0)
    macro_scenario: str = Field("baseline", example="hawkish_rate_shock")
    chaos_mode: bool = Field(False, description="Simulate transient API failures & tool retry recovery")
    thread_id: str | None = Field(None, description="Optional custom thread ID for checkpointing")


class WorkflowResumeRequest(BaseModel):
    thread_id: str = Field(..., example="finflow-thread-abc12345")
    decision: str = Field(..., description="APPROVE, REJECT, or OVERRIDE_WEIGHTS")
    reviewer_id: str = Field("compliance_officer_1", example="senior_risk_officer")
    rationale: str = Field("Approved following risk mitigation review.", example="Approved.")
    overridden_weights: dict[str, float] | None = Field(None, example={"NVDA": 40.0, "MSFT": 60.0})


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Check engine health and Redis storage mode."""
    using_fallback = is_using_fallback_redis()
    return {
        "status": "healthy",
        "redis_mode": "in_memory_fallback" if using_fallback else "live_redis_stack",
        "engine": "finflow-engine",
    }


@app.post("/api/v1/workflow/run")
def api_run_workflow(payload: WorkflowRunRequest) -> dict[str, Any]:
    """Initiate or execute a multi-agent financial workflow."""
    try:
        result = run_finflow_workflow(
            user_query=payload.user_query,
            total_capital_usd=payload.total_capital_usd,
            macro_scenario=payload.macro_scenario,
            chaos_mode=payload.chaos_mode,
            thread_id=payload.thread_id,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/v1/workflow/resume")
def api_resume_workflow(payload: WorkflowResumeRequest) -> dict[str, Any]:
    """Resume a workflow suspended at a Human-in-the-Loop (HITL) compliance interrupt."""
    try:
        human_review = {
            "decision": payload.decision.upper(),
            "reviewer_id": payload.reviewer_id,
            "rationale": payload.rationale,
            "overridden_weights": payload.overridden_weights,
        }
        result = run_finflow_workflow(
            user_query="",
            thread_id=payload.thread_id,
            human_review=human_review,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/v1/dlq")
def api_list_dlq(count: int = 50) -> list[dict[str, Any]]:
    """List unrecoverable workflow failures captured in the Redis Dead-Letter Queue."""
    try:
        bus = RedisEventBusAndDLQ()
        return bus.list_dlq_entries(count=count)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
