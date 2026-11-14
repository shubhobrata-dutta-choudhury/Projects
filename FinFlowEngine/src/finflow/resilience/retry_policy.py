"""
Exponential Backoff with Full Jitter and Error Classification (`Transient` vs `Fatal`).

Distinguishes retriable infrastructure failures (HTTP 429, 503, network timeouts,
malformed LLM JSON output) from fatal domain/policy errors so agents never waste
tokens retrying unrecoverable faults.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, TypeVar

from finflow.config import get_settings

T = TypeVar("T")


class TransientAgentError(RuntimeError):
    """Retriable error (e.g., upstream rate limit, network timeout, transient API 503)."""


class FatalWorkflowError(RuntimeError):
    """Non-retriable error (e.g., invalid schema contract, sanctions violation)."""


def compute_backoff_with_jitter(attempt: int, base_seconds: float, max_seconds: float = 5.0) -> float:
    """
    AWS-style Full Jitter exponential backoff:
    sleep = random(0, min(max_seconds, base_seconds * 2 ** attempt))
    """
    ceiling = min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    return random.uniform(0.01, max(0.02, ceiling))


def execute_with_retry(
    operation_name: str,
    fn: Callable[[], T],
    max_retries: int | None = None,
    base_backoff_seconds: float | None = None,
) -> tuple[T, dict[str, Any]]:
    """
    Execute `fn` with bounded exponential backoff retries on `TransientAgentError`
    or `TimeoutError` / `ConnectionError`. Immediately re-raises `FatalWorkflowError`.
    """
    settings = get_settings()
    retries_limit = max_retries if max_retries is not None else settings.max_retries
    base_backoff = (
        base_backoff_seconds
        if base_backoff_seconds is not None
        else settings.base_backoff_seconds
    )

    attempts = 0
    errors_seen: list[str] = []
    total_backoff_sec = 0.0

    while True:
        attempts += 1
        try:
            result = fn()
            return result, {
                "operation": operation_name,
                "attempts": attempts,
                "recovered_from_transient_error": attempts > 1,
                "errors_seen": errors_seen,
                "total_backoff_seconds": round(total_backoff_sec, 4),
            }
        except FatalWorkflowError:
            raise
        except (TransientAgentError, TimeoutError, ConnectionError) as exc:
            errors_seen.append(f"attempt_{attempts}:{type(exc).__name__}:{exc}")
            if attempts > retries_limit:
                raise
            sleep_sec = compute_backoff_with_jitter(attempts, base_backoff)
            total_backoff_sec += sleep_sec
            time.sleep(sleep_sec)
