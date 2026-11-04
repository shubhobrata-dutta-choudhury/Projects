"""
Configuration Management for the Autonomous Spec-to-Code Pipeline.

Centralizes environment variables, retry budgets, sandbox timeouts, and LLM provider settings.
"""

from __future__ import annotations

import os
from typing import Literal
from pydantic import BaseModel, Field


class PipelineConfig(BaseModel):
    """
    Validated configuration for running the Spec-to-Code FSM pipeline and Evaluations.
    """

    llm_provider: Literal["mock", "openai"] = Field(
        default_factory=lambda: os.getenv("SPEC2CODE_LLM_PROVIDER", "mock"),  # type: ignore[arg-type]
        description="LLM backend to use: 'mock' for deterministic self-correction learning simulator, 'openai' for live OpenAI-compatible APIs.",
    )
    model_name: str = Field(
        default_factory=lambda: os.getenv("SPEC2CODE_MODEL", "gpt-4o-mini"),
        description="Model name for code generation and repair.",
    )
    judge_model_name: str = Field(
        default_factory=lambda: os.getenv("SPEC2CODE_JUDGE_MODEL", "gpt-4o-mini"),
        description="Model name for LLM-as-a-Judge evaluations.",
    )
    openai_api_key: str | None = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY"),
        description="API key for OpenAI-compatible endpoints.",
    )
    openai_base_url: str | None = Field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL"),
        description="Optional custom base URL (e.g. Ollama, Groq, vLLM, Azure).",
    )
    max_retries: int = Field(
        default_factory=lambda: int(os.getenv("SPEC2CODE_MAX_RETRIES", "3")),
        ge=0,
        le=10,
        description="Maximum number of self-correction repair attempts after initial generation.",
    )
    sandbox_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("SPEC2CODE_SANDBOX_TIMEOUT_SECONDS", "10.0")),
        gt=0.5,
        le=120.0,
        description="Hard timeout in seconds for each sandboxed pytest execution.",
    )
    simulate_bug_on_first_try: bool = Field(
        default=True,
        description="In 'mock' mode, intentionally inject a realistic bug on Attempt 1 so the FSM demonstrates self-correction.",
    )