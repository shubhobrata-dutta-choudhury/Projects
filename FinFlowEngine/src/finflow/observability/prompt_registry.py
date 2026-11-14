"""
Langfuse Prompt Management Registry with Versioned Local Fallback Templates.

Allows agents to fetch production-tagged prompts from Langfuse (`get_prompt`)
while maintaining local versioned templates so the engine operates reliably
when Langfuse is offline or during local unit testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VersionedPrompt:
    name: str
    version: int
    template: str
    model_tier: str = "primary"

    def compile(self, **kwargs: Any) -> str:
        return self.template.format(**kwargs)


LOCAL_PROMPTS: dict[str, VersionedPrompt] = {
    "finflow-planner-v2": VersionedPrompt(
        name="finflow-planner-v2",
        version=2,
        template=(
            "You are the Lead Institutional Portfolio Planner. "
            "Decompose the mandate '{user_query}' with capital ${total_capital_usd:,.2f} "
            "under macro scenario '{macro_scenario}' into per-ticker allocations and risk checks."
        ),
    ),
    "finflow-quant-analyst-v3": VersionedPrompt(
        name="finflow-quant-analyst-v3",
        version=3,
        template=(
            "You are a Quantitative Risk Analyst. Evaluate ticker {ticker} "
            "(weight {weight_pct:.1f}%, notional ${notional_usd:,.2f}) under scenario '{macro_scenario}'."
        ),
    ),
    "finflow-fundamental-analyst-v2": VersionedPrompt(
        name="finflow-fundamental-analyst-v2",
        version=2,
        template=(
            "You are an SEC Filing & Fundamental Equity Analyst. Analyze balance sheet ratios "
            "and 10-K risk disclosures for {ticker}."
        ),
    ),
    "finflow-synthesizer-v4": VersionedPrompt(
        name="finflow-synthesizer-v4",
        version=4,
        template=(
            "You are the Managing Director compiling an Executive Investment Committee Memo. "
            "Every financial figure MUST match the upstream Quant and Fundamental tool outputs exactly. "
            "Revision #{revision_count}. Critic feedback: {critique_feedback}"
        ),
    ),
    "finflow-critic-auditor-v3": VersionedPrompt(
        name="finflow-critic-auditor-v3",
        version=3,
        template=(
            "You are an independent Hallucination & Numerical Compliance Auditor. "
            "Cross-check every number in the draft memo against the ground-truth tool payloads."
        ),
    ),
}


def get_versioned_prompt(prompt_name: str) -> VersionedPrompt:
    """Retrieve a `VersionedPrompt` by name (with fallback to default local registry)."""
    return LOCAL_PROMPTS.get(
        prompt_name,
        VersionedPrompt(name=prompt_name, version=1, template="{input}"),
    )
