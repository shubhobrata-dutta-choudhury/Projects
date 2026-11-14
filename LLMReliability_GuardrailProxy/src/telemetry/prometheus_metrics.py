from typing import Dict, Tuple
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
except ImportError:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    _FALLBACK_METRICS: Dict[str, float] = {}
    class _LabeledMetric:
        def __init__(self, key: str):
            self.key = key
        def inc(self, amount: float = 1.0) -> None:
            _FALLBACK_METRICS[self.key] = _FALLBACK_METRICS.get(self.key, 0.0) + amount
        def observe(self, value: float) -> None:
            sum_key = f"{self.key}_sum"
            cnt_key = f"{self.key}_count"
            _FALLBACK_METRICS[sum_key] = _FALLBACK_METRICS.get(sum_key, 0.0) + value
            _FALLBACK_METRICS[cnt_key] = _FALLBACK_METRICS.get(cnt_key, 0.0) + 1.0
        def set(self, value: float) -> None:
            _FALLBACK_METRICS[self.key] = value
    class _BaseFallbackMetric:
        def __init__(self, name: str, doc: str, labelnames=(), buckets=()):
            self.name = name
            self.doc = doc
        def labels(self, **kwargs) -> _LabeledMetric:
            lbl_str = ",".join(f'{k}="{v}"' for k, v in sorted(kwargs.items()))
            return _LabeledMetric(f"{self.name}{{{lbl_str}}}")
    Counter = Gauge = Histogram = _BaseFallbackMetric  # type: ignore
    def generate_latest() -> bytes:
        lines = [f"{k} {v}" for k, v in sorted(_FALLBACK_METRICS.items())]
        return ("\n".join(lines) + "\n").encode("utf-8")

REQUEST_COUNT = Counter(
    "guardrail_proxy_requests_total",
    "Total LLM proxy requests processed",
    ["routed_model", "provider", "status", "fallback_triggered"],
)
UPSTREAM_LATENCY_MS = Histogram(
    "guardrail_proxy_upstream_latency_ms",
    "Upstream LLM generation latency in milliseconds",
    ["routed_model"],
    buckets=(50, 100, 200, 350, 500, 750, 1000, 1500, 2500, 5000),
)
GUARDRAIL_LATENCY_MS = Histogram(
    "guardrail_proxy_guardrail_latency_ms",
    "Guardrail execution latency in milliseconds",
    ["stage"],
    buckets=(0.5, 1, 2.5, 5, 10, 25, 50, 100),
)
TOKENS_PROCESSED = Counter(
    "guardrail_proxy_tokens_total",
    "Total tokens processed by model and token type",
    ["routed_model", "token_type"],
)
COST_USD_TOTAL = Counter(
    "guardrail_proxy_cost_usd_total",
    "Cumulative estimated LLM spend in USD",
    ["routed_model", "tenant_id"],
)
GUARDRAIL_INTERVENTIONS = Counter(
    "guardrail_proxy_interventions_total",
    "Total guardrail interventions (PII redactions, blocked injections, hallucination fallbacks)",
    ["intervention_type"],
)
MODEL_P99_GAUGE = Gauge(
    "guardrail_proxy_model_p99_latency_ms",
    "Real-time sliding-window P99 latency per model in milliseconds",
    ["model_id"],
)

def export_prometheus_metrics() -> Tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
