from collections import deque
from dataclasses import dataclass
import time
from typing import Deque, Dict, Optional

@dataclass
class RateLimitStatus:
    model_id: str
    rpm_used: int
    rpm_limit: int
    tpm_used: int
    tpm_limit: int
    cooldown_remaining_sec: float
    is_throttled: bool
    utilization_ratio: float

class RateLimitTracker:
    """
    Tracks sliding-window Requests-Per-Minute (RPM), Tokens-Per-Minute (TPM),
    upstream rate-limit headers (x-ratelimit-remaining-requests, Retry-After),
    and HTTP 429 cooldown windows per model.
    """
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self._rpm_limits: Dict[str, int] = {}
        self._tpm_limits: Dict[str, int] = {}
        self._request_log: Dict[str, Deque[tuple[float, int]]] = {}
        self._cooldown_until: Dict[str, float] = {}
        self._header_remaining_reqs: Dict[str, Optional[int]] = {}

    def register_model(self, model_id: str, rpm_limit: int, tpm_limit: int) -> None:
        self._rpm_limits[model_id] = rpm_limit
        self._tpm_limits[model_id] = tpm_limit
        if model_id not in self._request_log:
            self._request_log[model_id] = deque()
        self._cooldown_until.setdefault(model_id, 0.0)
        self._header_remaining_reqs.setdefault(model_id, None)

    def _evict_old(self, model_id: str, now: float) -> None:
        q = self._request_log.get(model_id)
        if not q:
            return
        cutoff = now - self.window_seconds
        while q and q[0][0] < cutoff:
            q.popleft()

    def record_usage(
        self,
        model_id: str,
        tokens: int,
        remaining_requests_header: Optional[int] = None,
    ) -> None:
        now = time.monotonic()
        if model_id not in self._request_log:
            self._request_log[model_id] = deque()
        self._evict_old(model_id, now)
        self._request_log[model_id].append((now, tokens))
        if remaining_requests_header is not None:
            self._header_remaining_reqs[model_id] = remaining_requests_header

    def mark_rate_limited(self, model_id: str, retry_after_seconds: float = 10.0) -> None:
        now = time.monotonic()
        self._cooldown_until[model_id] = max(
            self._cooldown_until.get(model_id, 0.0), now + retry_after_seconds
        )

    def clear_cooldown(self, model_id: str) -> None:
        self._cooldown_until[model_id] = 0.0
        if model_id in self._request_log:
            self._request_log[model_id].clear()
        self._header_remaining_reqs[model_id] = None

    def get_status(self, model_id: str, estimated_new_tokens: int = 0) -> RateLimitStatus:
        now = time.monotonic()
        self._evict_old(model_id, now)
        q = self._request_log.get(model_id, deque())
        rpm_used = len(q)
        tpm_used = sum(t for _, t in q)
        rpm_limit = self._rpm_limits.get(model_id, 100)
        tpm_limit = self._tpm_limits.get(model_id, 100000)
        cooldown_rem = max(0.0, self._cooldown_until.get(model_id, 0.0) - now)
        header_rem = self._header_remaining_reqs.get(model_id)
        rpm_ratio = rpm_used / max(1, rpm_limit)
        tpm_ratio = (tpm_used + estimated_new_tokens) / max(1, tpm_limit)
        utilization = round(max(rpm_ratio, tpm_ratio), 4)
        is_throttled = (
            cooldown_rem > 0.0
            or rpm_used >= rpm_limit
            or (tpm_used + estimated_new_tokens) > tpm_limit
            or (header_rem is not None and header_rem <= 1)
        )
        return RateLimitStatus(
            model_id=model_id,
            rpm_used=rpm_used,
            rpm_limit=rpm_limit,
            tpm_used=tpm_used,
            tpm_limit=tpm_limit,
            cooldown_remaining_sec=round(cooldown_rem, 2),
            is_throttled=is_throttled,
            utilization_ratio=utilization,
        )
