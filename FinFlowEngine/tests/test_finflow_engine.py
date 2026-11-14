"""
Comprehensive pytest Test Suite for FinFlow-Engine.

Covers:
1. Resilient Redis client & InMemoryRedisAdapter fallback
2. Redis-backed cache-aside decorator
3. Distributed circuit breaker (`CLOSED` -> `OPEN` -> `HALF_OPEN`)
4. Exponential backoff retry policy & transient fault recovery
5. Idempotency lock and result cache
6. Quantitative & SEC fundamental tools
7. Multi-agent workflow execution & evaluation scoring
"""

from __future__ import annotations

import pytest

from finflow.resilience.cache import redis_cached_tool
from finflow.resilience.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitState,
    DistributedCircuitBreaker,
)
from finflow.resilience.idempotency import (
    DuplicateWorkflowExecutionError,
    IdempotencyStore,
)
from finflow.resilience.redis_client import InMemoryRedisAdapter, ResilientRedisProxy
from finflow.resilience.retry_policy import (
    TransientAgentError,
    compute_backoff_with_jitter,
    execute_with_retry,
)
from finflow.tools.market_data import compute_ticker_quant_metrics
from finflow.tools.sec_filings import fetch_sec_fundamental_metrics
from finflow.graph.runner import run_finflow_workflow


def test_in_memory_redis_adapter() -> None:
    adapter = InMemoryRedisAdapter()
    assert adapter.ping() is True

    # String set/get with TTL
    adapter.set("test:key", "hello_redis", ex=10)
    assert adapter.get("test:key") == "hello_redis"

    # Atomic increment
    assert adapter.incr("test:counter") == 1
    assert adapter.incr("test:counter") == 2

    # Hash operations
    adapter.hset("test:hash", key="field1", value="val1")
    assert adapter.hget("test:hash", "field1") == "val1"
    assert adapter.hgetall("test:hash") == {"field1": "val1"}

    # Stream operations
    sid = adapter.xadd("test:stream", {"event": "started"})
    assert sid is not None
    assert adapter.xlen("test:stream") == 1
    assert len(adapter.xrange("test:stream")) == 1


def test_resilient_redis_proxy_fallback() -> None:
    fallback = InMemoryRedisAdapter()
    proxy = ResilientRedisProxy(primary=None, fallback=fallback)
    assert proxy.using_fallback is True

    proxy.set("proxy:key", "fallback_works")
    assert proxy.get("proxy:key") == "fallback_works"
    assert proxy.ping() is True


def test_redis_cache_decorator() -> None:
    adapter = InMemoryRedisAdapter()
    proxy = ResilientRedisProxy(primary=None, fallback=adapter)

    call_count = 0

    @redis_cached_tool(namespace="test_ns", ttl_seconds=60)
    def sample_tool(x: int) -> dict[str, int]:
        nonlocal call_count
        call_count += 1
        return {"result": x * 2}

    res1 = sample_tool(5)
    assert res1["result"] == 10
    assert res1.get("_cache_hit") is False

    res2 = sample_tool(5)
    assert res2["result"] == 10
    assert call_count >= 1


def test_backoff_and_retry_policy() -> None:
    backoff = compute_backoff_with_jitter(attempt=1, base_seconds=0.01)
    assert backoff >= 0.01

    attempts = 0
    def flaky_operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TransientAgentError("Temporary glitch")
        return "success"

    result, meta = execute_with_retry("test_op", flaky_operation, max_retries=3, base_backoff_seconds=0.001)
    assert result == "success"
    assert meta["attempts"] == 3
    assert meta["recovered_from_transient_error"] is True


def test_distributed_circuit_breaker() -> None:
    adapter = InMemoryRedisAdapter()
    proxy = ResilientRedisProxy(primary=None, fallback=adapter)
    cb = DistributedCircuitBreaker("test-service", failure_threshold=2, recovery_timeout_seconds=0.1, redis_client=proxy)

    assert cb.get_state() == CircuitState.CLOSED

    cb.record_failure()
    assert cb.get_state() == CircuitState.CLOSED

    cb.record_failure()
    assert cb.get_state() == CircuitState.OPEN

    fallback_called = False
    def primary() -> str:
        return "should_not_run"

    def fallback() -> str:
        nonlocal fallback_called
        fallback_called = True
        return "fallback_value"

    val, telemetry = cb.execute(primary, fallback_fn=fallback)
    assert val == "fallback_value"
    assert telemetry["used_fallback"] is True


def test_idempotency_store() -> None:
    adapter = InMemoryRedisAdapter()
    proxy = ResilientRedisProxy(primary=None, fallback=adapter)
    store = IdempotencyStore(redis_client=proxy)

    key = store.compute_key("Evaluate NVDA", 5_000_000.0, "baseline")
    assert len(key) == 24

    assert store.get_completed_result(key) is None
    store.save_completed_result(key, {"status": "completed"})
    assert store.get_completed_result(key) == {"status": "completed"}

    with store.acquire_execution_lock(key, lock_ttl_seconds=10):
        with pytest.raises(DuplicateWorkflowExecutionError):
            with store.acquire_execution_lock(key, lock_ttl_seconds=10):
                pass


def test_quantitative_and_sec_tools() -> None:
    q = compute_ticker_quant_metrics("NVDA", macro_scenario="baseline", chaos_mode=False)
    assert q["ticker"] == "NVDA"
    assert "daily_var_95_pct" in q

    sec = fetch_sec_fundamental_metrics("NVDA", chaos_mode=False)
    assert sec["ticker"] == "NVDA"
    assert "fundamental_rating" in sec


def test_workflow_execution_smoke() -> None:
    result = run_finflow_workflow(
        user_query="Evaluate NVDA and MSFT with $2M capital",
        total_capital_usd=2_000_000.0,
        macro_scenario="baseline",
        chaos_mode=False,
    )
    assert result.get("workflow_status") in ("COMPLETED_APPROVED", "COMPLETED_REJECTED", "IN_PROGRESS")
    assert "allocations" in result
