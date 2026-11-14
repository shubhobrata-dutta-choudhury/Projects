"""
Redis Distributed Locking (`SET NX EX`) and Workflow Idempotency Guard.

In financial orchestration engines, submitting the same workflow request twice
(due to client retries or webhook replays) must never trigger duplicate LLM runs
or duplicate capital allocation orders.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from typing import Any, Iterator

from finflow.config import get_settings
from finflow.resilience.redis_client import get_redis_client


class DuplicateWorkflowExecutionError(RuntimeError):
    """Raised when a workflow with the same idempotency key is currently locked/running."""


class IdempotencyStore:
    """
    Manages Redis distributed execution locks (`SET NX EX`) and completed result
    deduplication records (`finflow:idempotency:result:<key>`).
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client or get_redis_client()
        self._settings = get_settings()

    @staticmethod
    def compute_key(user_query: str, total_capital_usd: float, macro_scenario: str) -> str:
        """Deterministically hash workflow parameters into a canonical idempotency key."""
        payload = f"{user_query.strip().lower()}|{round(total_capital_usd, 2)}|{macro_scenario.strip().lower()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _lock_key(self, idempotency_key: str) -> str:
        return f"finflow:idempotency:lock:{idempotency_key}"

    def _result_key(self, idempotency_key: str) -> str:
        return f"finflow:idempotency:result:{idempotency_key}"

    def get_completed_result(self, idempotency_key: str) -> dict[str, Any] | None:
        """Return cached completed workflow state if this idempotency key already finished."""
        raw = self._redis.get(self._result_key(idempotency_key))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def save_completed_result(
        self,
        idempotency_key: str,
        result_summary: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        """Persist completed workflow outcome under the idempotency key."""
        ttl = ttl_seconds or self._settings.idempotency_ttl_seconds
        self._redis.set(
            self._result_key(idempotency_key),
            json.dumps(result_summary),
            ex=ttl,
        )

    @contextmanager
    def acquire_execution_lock(
        self,
        idempotency_key: str,
        lock_ttl_seconds: int = 120,
    ) -> Iterator[None]:
        """
        Acquire an atomic Redis `SET NX EX` lock for `idempotency_key`.
        Raises `DuplicateWorkflowExecutionError` if another worker holds the lock.
        """
        lock_key = self._lock_key(idempotency_key)
        acquired = self._redis.set(lock_key, "LOCKED", ex=lock_ttl_seconds, nx=True)
        if not acquired:
            raise DuplicateWorkflowExecutionError(
                f"Workflow with idempotency_key='{idempotency_key}' is already in progress."
            )
        try:
            yield
        finally:
            self._redis.delete(lock_key)
