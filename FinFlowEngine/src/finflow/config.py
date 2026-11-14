"""
Centralized configuration management for FinFlow-Engine using Pydantic Settings.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FinFlowSettings(BaseSettings):
    """Typed application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Execution & LLM Settings
    finflow_llm_mode: Literal["mock", "openai"] = Field(
        default="mock",
        alias="FINFLOW_LLM_MODE",
        description="Use 'mock' for deterministic local execution or 'openai' for live LLM calls.",
    )

    openai_api_key: str = Field(default="sk-mock-key", alias="OPENAI_API_KEY")
    primary_model: str = Field(default="gpt-4o", alias="FINFLOW_PRIMARY_MODEL")
    fallback_model: str = Field(default="gpt-4o-mini", alias="FINFLOW_FALLBACK_MODEL")

    # Redis Infrastructure Settings
    redis_url: str = Field(default="redis://localhost:6379/0", alias="FINFLOW_REDIS_URL")
    redis_fallback_memory: bool = Field(
        default=True,
        alias="FINFLOW_REDIS_FALLBACK_MEMORY",
        description="Automatically fall back to in-memory FakeRedis if Redis server is offline.",
    )
    cache_ttl_seconds: int = Field(default=3600, alias="FINFLOW_CACHE_TTL_SECONDS")
    idempotency_ttl_seconds: int = Field(default=86400, alias="FINFLOW_IDEMPOTENCY_TTL_SECONDS")

    # Circuit Breaker & Retry Policy
    cb_failure_threshold: int = Field(default=3, alias="FINFLOW_CB_FAILURE_THRESHOLD")
    cb_recovery_timeout_seconds: float = Field(
        default=30.0, alias="FINFLOW_CB_RECOVERY_TIMEOUT_SECONDS"
    )
    max_retries: int = Field(default=3, alias="FINFLOW_MAX_RETRIES")
    base_backoff_seconds: float = Field(default=0.2, alias="FINFLOW_BASE_BACKOFF_SECONDS")

    # Risk & Compliance Gatekeeper Thresholds
    max_portfolio_var_95_pct: float = Field(
        default=3.5,
        alias="FINFLOW_MAX_PORTFOLIO_VAR_95_PCT",
        description="Maximum 1-day 95% Value-at-Risk percentage before triggering HITL interrupt.",
    )
    max_single_asset_weight_pct: float = Field(
        default=40.0,
        alias="FINFLOW_MAX_SINGLE_ASSET_WEIGHT_PCT",
        description="Maximum single-asset concentration weight (%) before triggering compliance flag.",
    )
    max_critic_reflection_hops: int = Field(
        default=2,
        alias="FINFLOW_MAX_CRITIC_REFLECTION_HOPS",
        description="Maximum self-correction loops between Synthesizer and Critic.",
    )

    # Langfuse Observability Settings
    langfuse_enabled: bool = Field(default=True, alias="LANGFUSE_ENABLED")
    langfuse_public_key: str = Field(default="pk-lf-local-dev", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="sk-lf-local-dev", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="http://localhost:3000", alias="LANGFUSE_HOST")


@lru_cache(maxsize=1)
def get_settings() -> FinFlowSettings:
    """Return cached FinFlowSettings singleton."""
    return FinFlowSettings()
