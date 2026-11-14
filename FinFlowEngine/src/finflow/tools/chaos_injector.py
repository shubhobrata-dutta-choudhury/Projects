"""
Configurable Chaos Fault Injector backed by Redis counters.

Used during Chaos Testing & Resilience Training to deterministically trigger:
1. Transient upstream API HTTP 429 / 503 errors on the first attempt of a tool call,
   proving that `execute_with_retry` recovers on attempt #2.
2. Sustained upstream LLM failures that trip the `DistributedCircuitBreaker` to `OPEN`,
   proving automatic fallback to the secondary model.
"""

from __future__ import annotations

from finflow.resilience.redis_client import get_redis_client
from finflow.resilience.retry_policy import TransientAgentError


def maybe_inject_transient_fault(operation_key: str, chaos_mode: bool, fail_first_n: int = 1) -> None:
    """
    If `chaos_mode` is True, fail the first `fail_first_n` calls for `operation_key`
    with a `TransientAgentError` (simulating an HTTP 429 Rate-Limit / Upstream Timeout),
    then succeed on subsequent retry attempts.
    """
    if not chaos_mode:
        return

    redis_client = get_redis_client()
    counter_key = f"finflow:chaos:counter:{operation_key}"
    attempt_num = redis_client.incr(counter_key)
    redis_client.expire(counter_key, 120)

    if attempt_num <= fail_first_n:
        raise TransientAgentError(
            f"[ChaosInjector] Simulated HTTP 429 Rate-Limit / Upstream Timeout on '{operation_key}' "
            f"(attempt {attempt_num}/{fail_first_n})"
        )


def reset_chaos_counters() -> None:
    """Reset chaos fault counters in Redis."""
    # Handled per operation key TTL or full flush in tests
    pass
