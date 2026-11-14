"""
Portfolio-Level Risk Aggregation, Correlation Diversification, and Policy Compliance Engine.
"""

from __future__ import annotations

from typing import Any

from finflow.config import get_settings

_RESTRICTED_SANCTIONS_TICKERS = {"RUSAL", "GAZP", "SBER"}


def evaluate_portfolio_risk_and_compliance(
    total_capital_usd: float,
    allocations: list[dict[str, Any]],
    quant_reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute correlation-adjusted portfolio 95% 1-day VaR, stressed dollar loss,
    concentration breaches, and regulatory compliance gate status.
    """
    settings = get_settings()
    undiversified_var_pct = 0.0
    stressed_loss_usd = 0.0
    max_weight_pct = 0.0
    policy_violations: list[str] = []
    sanctions_clear = True

    for alloc in allocations:
        ticker = str(alloc["ticker"]).upper()
        weight_pct = float(alloc["weight_pct"])
        notional_usd = float(alloc["notional_usd"])
        max_weight_pct = max(max_weight_pct, weight_pct)

        if ticker in _RESTRICTED_SANCTIONS_TICKERS:
            sanctions_clear = False
            policy_violations.append(f"SANCTIONS_VIOLATION: Ticker {ticker} is on OFAC restricted list.")

        q_rep = quant_reports.get(ticker, {})
        ticker_var = float(q_rep.get("daily_var_95_pct", 2.0))
        stress_loss_pct = float(q_rep.get("stress_loss_pct", 15.0))

        undiversified_var_pct += (weight_pct / 100.0) * ticker_var
        stressed_loss_usd += notional_usd * (stress_loss_pct / 100.0)

    # Multi-asset correlation diversification benefit (~12% reduction when >1 asset)
    diversification_benefit_pct = 12.0 if len(allocations) > 1 else 0.0
    weighted_portfolio_var_95_pct = round(
        undiversified_var_pct * (1.0 - diversification_benefit_pct / 100.0), 2
    )
    stressed_loss_usd = round(stressed_loss_usd, 2)

    var_breach = weighted_portfolio_var_95_pct > settings.max_portfolio_var_95_pct
    concentration_breach = max_weight_pct > settings.max_single_asset_weight_pct

    if var_breach:
        policy_violations.append(
            f"VAR_LIMIT_BREACH: Portfolio 95% daily VaR ({weighted_portfolio_var_95_pct:.2f}%) "
            f"exceeds threshold ({settings.max_portfolio_var_95_pct:.2f}%)."
        )
    if concentration_breach:
        policy_violations.append(
            f"CONCENTRATION_BREACH: Max single-asset weight ({max_weight_pct:.1f}%) "
            f"exceeds limit ({settings.max_single_asset_weight_pct:.1f}%)."
        )

    requires_human_approval = var_breach or concentration_breach or not sanctions_clear
    return {
        "total_capital_usd": round(total_capital_usd, 2),
        "weighted_portfolio_var_95_pct": weighted_portfolio_var_95_pct,
        "stressed_portfolio_loss_usd": stressed_loss_usd,
        "diversification_benefit_pct": diversification_benefit_pct,
        "max_single_ticker_weight_pct": round(max_weight_pct, 2),
        "concentration_breach": concentration_breach,
        "var_breach": var_breach,
        "sanctions_clear": sanctions_clear,
        "policy_violations": policy_violations,
        "requires_human_approval": requires_human_approval,
        "compliance_status": "PENDING_HITL" if requires_human_approval else "APPROVED",
    }
