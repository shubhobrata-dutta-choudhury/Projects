"""Token Bucket Rate Limiter implementation."""


class TokenBucketRateLimiter:
    """Deterministic Token Bucket Rate Limiter with continuous refill."""

    def __init__(self, capacity: float, refill_rate: float, initial_time: float = 0.0) -> None:
        if capacity <= 0 or refill_rate <= 0:
            raise ValueError("capacity and refill_rate must be strictly positive.")
        self.capacity: float = float(capacity)
        self.refill_rate: float = float(refill_rate)
        self._tokens: float = float(capacity)
        self._last_time: float = float(initial_time)

    def _refill(self, now: float) -> None:
        if now > self._last_time:
            elapsed = now - self._last_time
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last_time = float(now)

    def available_tokens(self, now: float = 0.0) -> float:
        """Returns the current number of available tokens at timestamp `now`."""
        self._refill(now)
        return self._tokens

    def allow_request(self, tokens: float = 1.0, now: float = 0.0) -> bool:
        """Attempts to consume `tokens` at timestamp `now`. Returns True if allowed."""
        if tokens <= 0:
            raise ValueError("Requested tokens must be > 0.")
        self._refill(now)
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False