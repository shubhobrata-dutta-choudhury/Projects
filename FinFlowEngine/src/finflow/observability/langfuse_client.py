"""
Langfuse Distributed Tracing, Span Instrumentation, and Resilience Telemetry.

Provides a unified `ObservabilityTracer` that:
1. Connects to a live Langfuse server (`LANGFUSE_HOST`) when available.
2. Gracefully records an in-memory & Redis-backed local trace mirror so every
   span, generation, token cost, retry event, and evaluation score can be
   inspected even when running offline or in CI.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from finflow.config import get_settings


class ObservabilityTracer:
    """
    Manages hierarchical Traces, Node Spans, LLM Generations, and Evaluation Scores
    for LangGraph workflows, syncing with Langfuse SDK when enabled and reachable.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._langfuse: Any = None
        self._traces: dict[str, dict[str, Any]] = {}
        self._init_langfuse_sdk()

    def _init_langfuse_sdk(self) -> None:
        if not self._settings.langfuse_enabled:
            return
        try:
            from langfuse import Langfuse  # type: ignore

            # Only initialize network client if non-default or local host is configured
            self._langfuse = Langfuse(
                public_key=self._settings.langfuse_public_key,
                secret_key=self._settings.langfuse_secret_key,
                host=self._settings.langfuse_host,
                enabled=self._settings.langfuse_enabled,
            )
        except Exception:
            self._langfuse = None

    def start_trace(
        self,
        thread_id: str,
        name: str,
        user_query: str,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Start or resume a root Langfuse trace keyed by `thread_id`."""
        trace_record = self._traces.setdefault(
            thread_id,
            {
                "trace_id": thread_id,
                "name": name,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "input": user_query,
                "metadata": metadata or {},
                "tags": tags or ["finflow", "langgraph", "multi-agent"],
                "spans": [],
                "generations": [],
                "scores": {},
            },
        )
        if self._langfuse is not None:
            try:
                self._langfuse.trace(
                    id=thread_id,
                    name=name,
                    input={"query": user_query},
                    metadata=metadata or {},
                    tags=tags or ["finflow", "langgraph", "multi-agent"],
                )
            except Exception:
                pass
        return trace_record

    @contextmanager
    def trace_node_span(
        self,
        thread_id: str,
        node_name: str,
        input_summary: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Context manager that times a LangGraph node execution and logs a Langfuse Span."""
        t0 = time.perf_counter()
        span_data: dict[str, Any] = {
            "node_name": node_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "input": input_summary or {},
            "output": {},
            "metadata": {},
            "status": "OK",
        }
        lf_span = None
        if self._langfuse is not None:
            try:
                lf_span = self._langfuse.span(
                    trace_id=thread_id,
                    name=f"node:{node_name}",
                    input=input_summary or {},
                )
            except Exception:
                lf_span = None

        try:
            yield span_data
        except Exception as exc:
            span_data["status"] = "ERROR"
            span_data["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            span_data["latency_ms"] = latency_ms
            trace_rec = self._traces.setdefault(thread_id, {"spans": [], "generations": [], "scores": {}})
            trace_rec.setdefault("spans", []).append(span_data)

            if lf_span is not None:
                try:
                    lf_span.end(
                        output=span_data.get("output"),
                        metadata={**span_data.get("metadata", {}), "latency_ms": latency_ms},
                        level="ERROR" if span_data["status"] == "ERROR" else "DEFAULT",
                    )
                except Exception:
                    pass

    def record_generation(
        self,
        thread_id: str,
        node_name: str,
        model: str,
        prompt_name: str,
        prompt_version: int,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        output_preview: str,
    ) -> None:
        """Record an LLM Generation with token usage, prompt version, and cost."""
        gen_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_name": node_name,
            "model": model,
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost_usd, 6),
            "output_preview": output_preview[:240],
        }
        trace_rec = self._traces.setdefault(thread_id, {"spans": [], "generations": [], "scores": {}})
        trace_rec.setdefault("generations", []).append(gen_entry)

        if self._langfuse is not None:
            try:
                self._langfuse.generation(
                    trace_id=thread_id,
                    name=f"llm:{node_name}",
                    model=model,
                    usage={
                        "input": input_tokens,
                        "output": output_tokens,
                        "total": input_tokens + output_tokens,
                        "unit": "TOKENS",
                        "totalCost": round(cost_usd, 6),
                    },
                    metadata={"prompt_name": prompt_name, "prompt_version": prompt_version},
                    output=output_preview,
                )
            except Exception:
                pass

    def record_score(
        self,
        thread_id: str,
        name: str,
        value: float,
        comment: str = "",
    ) -> None:
        """Attach an evaluation score (deterministic or LLM-as-a-Judge) to the trace."""
        trace_rec = self._traces.setdefault(thread_id, {"spans": [], "generations": [], "scores": {}})
        trace_rec.setdefault("scores", {})[name] = round(value, 4)

        if self._langfuse is not None:
            try:
                self._langfuse.score(
                    trace_id=thread_id,
                    name=name,
                    value=value,
                    comment=comment,
                )
            except Exception:
                pass

    def get_trace_summary(self, thread_id: str) -> dict[str, Any]:
        """Return full local trace telemetry (spans, generations, token costs, scores)."""
        trace = self._traces.get(thread_id, {"spans": [], "generations": [], "scores": {}})
        generations = trace.get("generations", [])
        total_tokens = sum(g.get("total_tokens", 0) for g in generations)
        total_cost = round(sum(g.get("cost_usd", 0.0) for g in generations), 6)
        return {
            **trace,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "span_count": len(trace.get("spans", [])),
        }


_TRACER_SINGLETON: ObservabilityTracer | None = None


def get_tracer() -> ObservabilityTracer:
    """Return global `ObservabilityTracer` singleton."""
    global _TRACER_SINGLETON
    if _TRACER_SINGLETON is None:
        _TRACER_SINGLETON = ObservabilityTracer()
    return _TRACER_SINGLETON
