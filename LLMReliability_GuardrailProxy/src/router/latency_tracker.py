from collections import deque
from dataclasses import dataclass
import math
import time
from typing import Deque, Dict

@dataclass
class LatencyStats:
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float

class SlidingWindowLatencyTracker:
    """
    High-performance rolling time-window latency monitor computing real-time
    P50, P95, and P99 latencies per upstream model endpoint.
    """
    def __init__(self, window_seconds: int = 60, max_samples: int = 2000):
        self.window_seconds = window_seconds
        self.max_samples = max_samples
        self._samples: Dict[str, Deque[tuple[float, float]]] = {}
        self._defaults: Dict[str, float] = {}

    def register_model(self, model_id: str, default_latency_ms: float = 300.0) -> None:
        if model_id not in self._samples:
            self._samples[model_id] = deque(maxlen=self.max_samples)
            self._defaults[model_id] = default_latency_ms

    def record(self, model_id: str, latency_ms: float) -> None:
        now = time.monotonic()
        if model_id not in self._samples:
            self._samples[model_id] = deque(maxlen=self.max_samples)
        self._samples[model_id].append((now, float(latency_ms)))
        self._evict_expired(model_id, now)

    def _evict_expired(self, model_id: str, now: float) -> None:
        q = self._samples.get(model_id)
        if not q:
            return
        cutoff = now - self.window_seconds
        while q and q[0][0] < cutoff:
            q.popleft()

    @staticmethod
    def _percentile(sorted_vals: list[float], pct: float) -> float:
        if not sorted_vals:
            return 0.0
        n = len(sorted_vals)
        if n == 1:
            return sorted_vals[0]
        rank = (pct / 100.0) * (n - 1)
        lower = int(math.floor(rank))
        upper = int(math.ceil(rank))
        if lower == upper:
            return sorted_vals[lower]
        weight = rank - lower
        return sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight

    def get_stats(self, model_id: str) -> LatencyStats:
        now = time.monotonic()
        self._evict_expired(model_id, now)
        q = self._samples.get(model_id)
        if not q:
            base = self._defaults.get(model_id, 300.0)
            return LatencyStats(
                count=0,
                p50_ms=round(base, 2),
                p95_ms=round(base * 1.15, 2),
                p99_ms=round(base * 1.25, 2),
                mean_ms=round(base, 2),
            )
        vals = sorted(v for _, v in q)
        count = len(vals)
        mean_val = sum(vals) / count
        return LatencyStats(
            count=count,
            p50_ms=round(self._percentile(vals, 50.0), 2),
            p95_ms=round(self._percentile(vals, 95.0), 2),
            p99_ms=round(self._percentile(vals, 99.0), 2),
            mean_ms=round(mean_val, 2),
        )

    def get_all_stats(self) -> Dict[str, LatencyStats]:
        return {m: self.get_stats(m) for m in self._samples.keys()}

    def clear_model(self, model_id: str) -> None:
        if model_id in self._samples:
            self._samples[model_id].clear()
