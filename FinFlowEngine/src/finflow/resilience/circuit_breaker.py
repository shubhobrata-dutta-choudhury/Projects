"""
Redis-backed Distributed Circuit Breaker (`CLOSED` -> `OPEN` -> `HALF_OPEN`).

Prevents cascading failures when an upstream LLM provider or financial market
data feed degrades. Because state is stored in Redis, all concurrent agent branches
and worker processes share the same real-time circuit health state.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, TypeVar

from finflow.config import get_settings
from finflow.resilience.redis_client import get_redis_client

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit breaker is OPEN."""

    def __init__(self, service_name: str, retry_after_seconds: float) -> None:
        self.service_name = service_name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Circuit breaker for '{service_name}' is OPEN. Retry after {retry_after_seconds:.1f}s."
        )


class DistributedCircuitBreaker:
    """
    Distributed Circuit Breaker synchronized across processes via Redis keys.
    """

    def __init__(
        self,
        service_name: str,
        failure_threshold: int | None = None,
        recovery_timeout_seconds: float | None = None,
        redis_client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.service_name = service_name
        self.failure_threshold = failure_threshold or settings.cb_failure_threshold
        self.recovery_timeout = (
            recovery_timeout_seconds
            if recovery_timeout_seconds is not None
            else settings.cb_recovery_timeout_seconds
        )
        self._redis = redis_client or get_redis_client()

    @property
    def _state_key(self) -> str:
        return f"finflow:cb:{self.service_name}:state"

    @property
    def _failures_key(self) -> str:
        return f"finflow:cb:{self.service_name}:failures"

    @property
    def _opened_at_key(self) -> str:
        return f"finflow:cb:{self.service_name}:opened_at"

    def get_state(self) -> CircuitState:
        raw_state = self._redis.get(self._state_key)
        if not raw_state or raw_state == CircuitState.CLOSED.value:
            return CircuitState.CLOSED

        if raw_state == CircuitState.OPEN.value:
            opened_at = float(self._redis.get(self._opened_at_key) or 0.0)
            elapsed = time.time() - opened_at
            if elapsed >= self.recovery_timeout:
                self._redis.set(self._state_key, CircuitState.HALF_OPEN.value)
                return CircuitState.HALF_OPEN
            return CircuitState.OPEN

        return CircuitState.HALF_OPEN

    def record_success(self) -> None:
        """Reset failure count and transition circuit back to CLOSED."""
        self._redis.set(self._state_key, CircuitState.CLOSED.value)
        self._redis.set(self._failures_key, "0")
        self._redis.delete(self._opened_at_key)

    def record_failure(self) -> CircuitState:
        """Increment failure count and trip to OPEN if threshold is reached."""
        current_state = self.get_state()
        failures = self._redis.incr(self._failures_key)

        if current_state == CircuitState.HALF_OPEN or failures >= self.failure_threshold:
            self._redis.set(self._state_key, CircuitState.OPEN.value)
            self._redis.set(self._opened_at_key, str(time.time()))
            return CircuitState.OPEN

        return CircuitState.CLOSED

    def reset(self) -> None:
        """Explicitly clear circuit breaker state (useful for tests/CLI)."""
        self.record_success()

    def execute(
        self,
        primary_fn: Callable[[], T],
        fallback_fn: Callable[[], T] | None = None,
    ) -> tuple[T, dict[str, Any]]:
        """
        Execute `primary_fn` guarded by the circuit breaker.
        If the circuit is OPEN or `primary_fn` fails and trips the breaker,
        automatically route to `fallback_fn` if provided.
        """
        state = self.get_state()
        telemetry: dict[str, Any] = {
            "service": self.service_name,
            "initial_circuit_state": state.value,
            "used_fallback": False,
        }

        if state == CircuitState.OPEN:
            opened_at = float(self._redis.get(self._opened_at_key) or time.time())
            retry_after = max(0.0, self.recovery_timeout - (time.time() - opened_at))
            if fallback_fn is not None:
                telemetry["used_fallback"] = True
                telemetry["fallback_reason"] = "circuit_already_open"
                return fallback_fn(), telemetry
            raise CircuitBreakerOpenError(self.service_name, retry_after)

        try:
            result = primary_fn()
            self.record_success()
            telemetry["final_circuit_state"] = CircuitState.CLOSED.value
            return result, telemetry
        except Exception as exc:
            new_state = self.record_failure()
            telemetry["final_circuit_state"] = new_state.value
            telemetry["primary_error"] = str(exc)
            if fallback_fn is not None:
                telemetry["used_fallback"] = True
                telemetry["fallback_reason"] = f"primary_failed:{type(exc).__name__}"
                return fallback_fn(), telemetry
            raise
