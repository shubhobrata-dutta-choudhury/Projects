"""Agent-generated edge-case tests for TokenBucketRateLimiter."""
import math
import pytest
from rate_limiter import TokenBucketRateLimiter


def test_non_monotonic_timestamp_does_not_drain_tokens():
    limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0, initial_time=10.0)
    assert limiter.allow_request(tokens=2.0, now=10.0) is True
    assert math.isclose(limiter.available_tokens(now=5.0), 3.0)


def test_exact_boundary_consumption():
    limiter = TokenBucketRateLimiter(capacity=4.0, refill_rate=2.0, initial_time=0.0)
    assert limiter.allow_request(tokens=4.0, now=0.0) is True
    assert math.isclose(limiter.available_tokens(now=0.0), 0.0)
    assert limiter.allow_request(tokens=1.0, now=0.5) is True