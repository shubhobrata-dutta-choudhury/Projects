"""
Quantitative Market Data, Volatility, Value-at-Risk (VaR), and Macro Stress-Testing Tool.

Decorated with `@redis_cached_tool` for Redis cache-aside lookup and integrated
with `maybe_inject_transient_fault` to demonstrate automated retry recovery.
"""

from __future__ import annotations

import math
from typing import Any

from finflow.resilience.cache import redis_cached_tool
from finflow.tools.chaos_injector import maybe_inject_transient_fault

# Institutional reference dataset for deterministic quantitative calculations
_MARKET_PROFILES: dict[str, dict[str, float]] = {
    "NVDA": {
        "spot_price": 138.50,
        "annualized_volatility_pct": 48.20,
        "sharpe_ratio": 2.15,
        "sortino_ratio": 3.10,
        "max_drawdown_pct": 27.40,
        "beta_to_sp500": 1.72,
    },
    "MSFT": {
        "spot_price": 428.75,
        "annualized_volatility_pct": 22.80,
        "sharpe_ratio": 1.64,
        "sortino_ratio": 2.35,
        "max_drawdown_pct": 14.20,
        "beta_to_sp500": 1.05,
    },
    "AAPL": {
        "spot_price": 226.40,
        "annualized_volatility_pct": 24.10,
        "sharpe_ratio": 1.48,
        "sortino_ratio": 2.12,
        "max_drawdown_pct": 16.50,
        "beta_to_sp500": 1.12,
    },
    "JPM": {
        "spot_price": 242.10,
        "annualized_volatility_pct": 21.50,
        "sharpe_ratio": 1.52,
        "sortino_ratio": 2.20,
        "max_drawdown_pct": 15.80,
        "beta_to_sp500": 1.08,
    },
    "TSLA": {
        "spot_price": 345.00,
        "annualized_volatility_pct": 62.40,
        "sharpe_ratio": 1.18,
        "sortino_ratio": 1.65,
        "max_drawdown_pct": 42.10,
        "beta_to_sp500": 2.15,
    },
}

_SCENARIO_SHOCK_MULTIPLIERS: dict[str, float] = {
    "baseline": 1.0,
    "hawkish_rate_shock": 1.35,
    "stagflation": 1.50,
    "liquidity_crunch": 1.75,
}


@redis_cached_tool(namespace="quant_metrics", ttl_seconds=1800)
def compute_ticker_quant_metrics(
    ticker: str,
    macro_scenario: str = "baseline",
    chaos_mode: bool = False,
    thread_id: str = "default",
) -> dict[str, Any]:
    """
    Calculate parametric 1-day 95% Value-at-Risk (VaR), Expected Shortfall (CVaR),
    Sharpe/Sortino ratios, and scenario stress loss for `ticker`.
    """
    symbol = ticker.upper().strip()
    maybe_inject_transient_fault(
        operation_key=f"quant:{thread_id}:{symbol}",
        chaos_mode=chaos_mode,
        fail_first_n=1,
    )

    profile = _MARKET_PROFILES.get(
        symbol,
        {
            "spot_price": 150.00,
            "annualized_volatility_pct": 30.00,
            "sharpe_ratio": 1.25,
            "sortino_ratio": 1.80,
            "max_drawdown_pct": 20.00,
            "beta_to_sp500": 1.15,
        },
    )

    shock_mult = _SCENARIO_SHOCK_MULTIPLIERS.get(macro_scenario, 1.0)
    ann_vol = profile["annualized_volatility_pct"] * shock_mult
    # Daily volatility = Annualized Vol / sqrt(252 trading days)
    daily_vol = ann_vol / math.sqrt(252.0)
    # 95% Parametric 1-day VaR = 1.645 * daily_vol
    daily_var_95 = round(1.645 * daily_vol, 2)
    # 95% Expected Shortfall (CVaR) ~= 2.063 * daily_vol
    expected_shortfall_95 = round(2.063 * daily_vol, 2)
    stress_loss_pct = round(profile["max_drawdown_pct"] * shock_mult * 0.65, 2)

    return {
        "ticker": symbol,
        "spot_price": round(profile["spot_price"], 2),
        "annualized_volatility_pct": round(ann_vol, 2),
        "daily_var_95_pct": daily_var_95,
        "expected_shortfall_95_pct": expected_shortfall_95,
        "sharpe_ratio": round(profile["sharpe_ratio"] / math.sqrt(shock_mult), 2),
        "sortino_ratio": round(profile["sortino_ratio"] / math.sqrt(shock_mult), 2),
        "max_drawdown_pct": round(profile["max_drawdown_pct"], 2),
        "beta_to_sp500": round(profile["beta_to_sp500"], 2),
        "stress_loss_pct": stress_loss_pct,
    }
