"""
Strongly-typed State Schemas and Domain Models for FinFlow-Engine.

Combines Pydantic v2 domain models (for structured agent outputs & validation)
with LangGraph TypedDict state definitions using custom Annotated reducers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from finflow.state.reducers import (
    deduplicated_audit_reducer,
    deduplicated_string_list_reducer,
    merge_dict_by_key,
)


class AllocationTarget(BaseModel):
    """Target capital allocation for a single ticker."""

    ticker: str = Field(..., description="Stock ticker symbol in uppercase, e.g. NVDA")
    weight_pct: float = Field(..., ge=0.0, le=100.0, description="Portfolio weight percentage")
    notional_usd: float = Field(..., ge=0.0, description="Dollar notional allocation")


class ExecutionPlan(BaseModel):
    """Structured output produced by the Planner Agent."""

    mandate_summary: str
    macro_scenario: Literal["baseline", "hawkish_rate_shock", "stagflation", "liquidity_crunch"]
    total_capital_usd: float
    allocations: list[AllocationTarget]
    required_checks: list[str]


class QuantMetrics(BaseModel):
    """Quantitative risk and return metrics for a single ticker."""

    ticker: str
    spot_price: float
    annualized_volatility_pct: float
    daily_var_95_pct: float
    expected_shortfall_95_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    beta_to_sp500: float
    stress_loss_pct: float


class FundamentalMetrics(BaseModel):
    """SEC filing & fundamental financial health metrics for a single ticker."""

    ticker: str
    company_name: str
    sector: str
    pe_ratio: float
    debt_to_equity: float
    free_cash_flow_billions: float
    revenue_growth_yoy_pct: float
    gross_margin_pct: float
    sec_10k_key_risks: list[str]
    fundamental_rating: Literal["STRONG_BUY", "BUY", "HOLD", "UNDERPERFORM"]


class PortfolioRiskReport(BaseModel):
    """Aggregated portfolio-level quantitative & compliance evaluation."""

    total_capital_usd: float
    weighted_portfolio_var_95_pct: float
    stressed_portfolio_loss_usd: float
    diversification_benefit_pct: float
    max_single_ticker_weight_pct: float
    concentration_breach: bool
    var_breach: bool
    sanctions_clear: bool
    policy_violations: list[str]
    requires_human_approval: bool
    compliance_status: Literal["APPROVED", "PENDING_HITL", "REJECTED", "MODIFIED_BY_HUMAN"]


class CriticAuditReport(BaseModel):
    """Output of the Critic / Hallucination Auditor Agent."""

    is_grounded: bool = Field(
        ..., description="True if all numbers and claims match upstream tool outputs."
    )
    numerical_discrepancies: list[str] = Field(default_factory=list)
    missing_risk_disclosures: list[str] = Field(default_factory=list)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    critique_feedback: str = Field(
        default="", description="Specific instructions for the Synthesizer if revision is needed."
    )


class HumanReviewPayload(BaseModel):
    """Payload supplied when resuming a workflow from a Human-in-the-Loop interrupt."""

    reviewer_id: str
    decision: Literal["APPROVE", "REJECT", "OVERRIDE_WEIGHTS"]
    rationale: str
    overridden_weights: dict[str, float] | None = None


def make_audit_entry(
    node: str,
    action: str,
    details: dict[str, Any] | None = None,
    status: Literal["INFO", "WARN", "ERROR", "RECOVERY"] = "INFO",
    event_id: str | None = None,
) -> dict[str, Any]:
    """Helper to construct a standardized, deduplicatable audit trail entry."""
    return {
        "event_id": event_id or str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node": node,
        "action": action,
        "status": status,
        "details": details or {},
    }


class AssetSubTaskState(TypedDict):
    """Input state sent to parallel asset worker branches via LangGraph `Send` API."""

    thread_id: str
    ticker: str
    weight_pct: float
    notional_usd: float
    macro_scenario: str
    chaos_mode: bool


class FinFlowState(TypedDict, total=False):
    """
    Root LangGraph State for FinFlow-Engine.

    Uses `Annotated` channels with custom deterministic reducers so concurrent
    `Send()` branches and node retries merge cleanly without data loss or duplication.
    """

    # Core workflow identity & input
    thread_id: str
    idempotency_key: str
    user_query: str
    total_capital_usd: float
    macro_scenario: str
    chaos_mode: bool

    # Planner output
    mandate_summary: str
    allocations: list[dict[str, Any]]

    # Parallel fan-out (`Send`) merged dictionaries keyed by ticker symbol
    quant_reports: Annotated[dict[str, dict[str, Any]], merge_dict_by_key]
    fundamental_reports: Annotated[dict[str, dict[str, Any]], merge_dict_by_key]

    # Portfolio & Compliance Gatekeeper state
    portfolio_risk: dict[str, Any]
    human_review: dict[str, Any] | None

    # Synthesis & Critic self-reflection loop state
    draft_memo: str
    revision_count: int
    inject_hallucination_once: bool
    critic_audit: dict[str, Any]
    final_memo: str
    workflow_status: Literal[
        "IN_PROGRESS",
        "AWAITING_HUMAN_APPROVAL",
        "COMPLETED_APPROVED",
        "COMPLETED_REJECTED",
        "FAILED_DLQ",
    ]

    # Observability, Resilience & Evaluation telemetry accumulated across nodes
    visited_nodes: Annotated[list[str], deduplicated_string_list_reducer]
    audit_trail: Annotated[list[dict[str, Any]], deduplicated_audit_reducer]
    evaluation_scores: Annotated[dict[str, float], merge_dict_by_key]
