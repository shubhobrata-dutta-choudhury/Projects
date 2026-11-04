"""Auto-generated acceptance test suite for spec_01_rate_limiter: Token Bucket Rate Limiter."""
import pytest
import math
import time
from rate_limiter import *

# [test_initial_capacity_and_consumption] Bucket starts full and consumes tokens accurately without refill at same timestamp.
def test_initial_capacity_and_consumption():
    limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0, initial_time=10.0)
    assert math.isclose(limiter.available_tokens(now=10.0), 5.0)
    assert limiter.allow_request(tokens=3.0, now=10.0) is True
    assert math.isclose(limiter.available_tokens(now=10.0), 2.0)
    assert limiter.allow_request(tokens=3.0, now=10.0) is False
    assert math.isclose(limiter.available_tokens(now=10.0), 2.0)

# [test_continuous_refill_and_cap] Bucket refills proportionally to elapsed time and caps at capacity.
def test_continuous_refill_and_cap():
    limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0, initial_time=0.0)
    assert limiter.allow_request(tokens=8.0, now=0.0) is True
    assert math.isclose(limiter.available_tokens(now=2.5), 7.0)
    assert math.isclose(limiter.available_tokens(now=100.0), 10.0)
    assert limiter.allow_request(tokens=10.0, now=100.0) is True
	
# [test_invalid_parameters_raise_value_error] Invalid capacity, refill_rate, or requested token count must raise ValueError.
def test_invalid_parameters_raise_value_error():
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(capacity=0.0, refill_rate=1.0)
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(capacity=5.0, refill_rate=-2.0)
    limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0)
    with pytest.raises(ValueError):
        limiter.allow_request(tokens=0.0, now=1.0)