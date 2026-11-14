"""
SEC 10-K/10-Q Filing & Fundamental Equity Balance Sheet Analysis Tool.

Decorated with `@redis_cached_tool` and integrated with `maybe_inject_transient_fault`
for resilience testing.
"""

from __future__ import annotations

from typing import Any

from finflow.resilience.cache import redis_cached_tool
from finflow.tools.chaos_injector import maybe_inject_transient_fault

_SEC_FUNDAMENTALS: dict[str, dict[str, Any]] = {
    "NVDA": {
        "company_name": "NVIDIA Corporation",
        "sector": "Semiconductors & AI Infrastructure",
        "pe_ratio": 46.80,
        "debt_to_equity": 0.19,
        "free_cash_flow_billions": 58.40,
        "revenue_growth_yoy_pct": 94.20,
        "gross_margin_pct": 75.10,
        "sec_10k_key_risks": [
            "Export control restrictions on advanced AI accelerators to restricted jurisdictions",
            "Foundry wafer and CoWoS packaging supply concentration at TSMC",
            "Hyperscaler capex cyclicality and custom ASIC competition",
        ],
        "fundamental_rating": "STRONG_BUY",
    },
    "MSFT": {
        "company_name": "Microsoft Corporation",
        "sector": "Enterprise Cloud & Software",
        "pe_ratio": 34.20,
        "debt_to_equity": 0.24,
        "free_cash_flow_billions": 74.10,
        "revenue_growth_yoy_pct": 16.40,
        "gross_margin_pct": 69.80,
        "sec_10k_key_risks": [
            "AI data center infrastructure depreciation headwinds on cloud margins",
            "Global antitrust and regulatory scrutiny on cloud bundling",
            "Cybersecurity and sovereign cloud compliance obligations",
        ],
        "fundamental_rating": "STRONG_BUY",
    },
    "AAPL": {
        "company_name": "Apple Inc.",
        "sector": "Consumer Hardware & Services",
        "pe_ratio": 31.50,
        "debt_to_equity": 1.45,
        "free_cash_flow_billions": 108.80,
        "revenue_growth_yoy_pct": 6.10,
        "gross_margin_pct": 46.20,
        "sec_10k_key_risks": [
            "Greater China smartphone market share competition and geopolitical tariffs",
            "App Store regulatory fee compression under EU Digital Markets Act",
            "Consumer hardware upgrade cycle elongation under high interest rates",
        ],
        "fundamental_rating": "BUY",
    },
    "JPM": {
        "company_name": "JPMorgan Chase & Co.",
        "sector": "Global Money Center Banking",
        "pe_ratio": 13.40,
        "debt_to_equity": 1.28,
        "free_cash_flow_billions": 42.50,
        "revenue_growth_yoy_pct": 11.20,
        "gross_margin_pct": 56.00,
        "sec_10k_key_risks": [
            "Net Interest Income (NII) sensitivity to yield curve inversions",
            "Basel III Endgame capital adequacy surcharge requirements",
            "Commercial real estate (CRE) credit loss provisioning",
        ],
        "fundamental_rating": "BUY",
    },
    "TSLA": {
        "company_name": "Tesla, Inc.",
        "sector": "Automotive & Autonomous Mobility",
        "pe_ratio": 88.50,
        "debt_to_equity": 0.11,
        "free_cash_flow_billions": 3.80,
        "revenue_growth_yoy_pct": 7.80,
        "gross_margin_pct": 18.20,
        "sec_10k_key_risks": [
            "Automotive gross margin compression from global EV price competition",
            "Regulatory approval timelines for unsupervised Full Self-Driving (FSD)",
            "Battery raw material supply chain and tariff exposure",
        ],
        "fundamental_rating": "HOLD",
    },
}


@redis_cached_tool(namespace="sec_fundamentals", ttl_seconds=3600)
def fetch_sec_fundamental_metrics(
    ticker: str,
    chaos_mode: bool = False,
    thread_id: str = "default",
) -> dict[str, Any]:
    """
    Retrieve balance sheet ratios, cash flow metrics, and extracted SEC 10-K
    risk disclosures for `ticker`.
    """
    symbol = ticker.upper().strip()
    maybe_inject_transient_fault(
        operation_key=f"sec:{thread_id}:{symbol}",
        chaos_mode=chaos_mode,
        fail_first_n=1,
    )

    data = _SEC_FUNDAMENTALS.get(
        symbol,
        {
            "company_name": f"{symbol} Holdings Corp.",
            "sector": "Diversified Industrials",
            "pe_ratio": 22.00,
            "debt_to_equity": 0.55,
            "free_cash_flow_billions": 8.50,
            "revenue_growth_yoy_pct": 9.50,
            "gross_margin_pct": 42.00,
            "sec_10k_key_risks": [
                f"Macroeconomic demand sensitivity and FX headwinds for {symbol}",
                "Refinancing risk under elevated benchmark interest rates",
            ],
            "fundamental_rating": "HOLD",
        },
    )

    return {"ticker": symbol, **data}
