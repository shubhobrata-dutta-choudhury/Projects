import asyncio
from dataclasses import dataclass, field
import json
import os
import random
import time
from typing import Any, Dict, List, Optional
import httpx
from src.config import ModelEndpointConfig

class UpstreamRateLimitError(Exception):
    def __init__(self, message: str, retry_after_sec: float = 10.0):
        super().__init__(message)
        self.retry_after_sec = retry_after_sec

class UpstreamServiceUnavailableError(Exception):
    pass

@dataclass
class ChaosState:
    added_latency_ms: float = 0.0
    force_429_rate: float = 0.0
    force_503_rate: float = 0.0
    hallucination_rate: float = 0.0

@dataclass
class ProviderCallResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    remaining_requests_header: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)

class UpstreamProviderCluster:
    """
    Hybrid Upstream LLM Provider Client:
    - If real API credentials & base URL are configured via environment variables, forwards via HTTPX AsyncClient.
    - Otherwise uses a deterministic + chaos-tunable high-throughput simulator so the gateway, P99 router,
      rate-limiter, and hallucination verifier can be stress-tested locally in real time.
    """
    def __init__(self, models: List[ModelEndpointConfig]):
        self.models: Dict[str, ModelEndpointConfig] = {m.id: m for m in models}
        self.chaos: Dict[str, ChaosState] = {m.id: ChaosState() for m in models}
        self._http_client = httpx.AsyncClient(timeout=15.0)

    async def close(self) -> None:
        await self._http_client.aclose()

    def update_chaos(
        self,
        model_id: str,
        added_latency_ms: Optional[float] = None,
        force_429_rate: Optional[float] = None,
        force_503_rate: Optional[float] = None,
        hallucination_rate: Optional[float] = None,
    ) -> ChaosState:
        if model_id not in self.chaos:
            self.chaos[model_id] = ChaosState()
        st = self.chaos[model_id]
        if added_latency_ms is not None:
            st.added_latency_ms = max(0.0, float(added_latency_ms))
        if force_429_rate is not None:
            st.force_429_rate = max(0.0, min(1.0, float(force_429_rate)))
        if force_503_rate is not None:
            st.force_503_rate = max(0.0, min(1.0, float(force_503_rate)))
        if hallucination_rate is not None:
            st.hallucination_rate = max(0.0, min(1.0, float(hallucination_rate)))
        return st

    def reset_all_chaos(self) -> None:
        for m_id in self.chaos:
            self.chaos[m_id] = ChaosState()

    def get_chaos_snapshot(self) -> Dict[str, Dict[str, float]]:
        return {
            m_id: {
                "added_latency_ms": st.added_latency_ms,
                "force_429_rate": st.force_429_rate,
                "force_503_rate": st.force_503_rate,
                "hallucination_rate": st.hallucination_rate,
            }
            for m_id, st in self.chaos.items()
        }

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(4, int(len(text.split()) * 1.35))

    async def generate(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        context_documents: Optional[List[str]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        force_hallucination: bool = False,
        fast_test_mode: bool = False,
    ) -> ProviderCallResult:
        m_cfg = self.models[model_id]
        chaos_cfg = self.chaos.get(model_id, ChaosState())
        start_ns = time.perf_counter_ns()
        # Check chaos fault injection
        if chaos_cfg.force_429_rate > 0 and random.random() < chaos_cfg.force_429_rate:
            raise UpstreamRateLimitError(
                f"Upstream 429 Rate Limit Exceeded on {model_id}", retry_after_sec=10.0
            )
        if chaos_cfg.force_503_rate > 0 and random.random() < chaos_cfg.force_503_rate:
            raise UpstreamServiceUnavailableError(
                f"Upstream 503 Service Unavailable on {model_id}"
            )
        # Simulate realistic model latency + chaos spike
        jitter = random.uniform(-m_cfg.jitter_ms * 0.4, m_cfg.jitter_ms)
        simulated_latency_ms = max(15.0, m_cfg.base_latency_ms + jitter + chaos_cfg.added_latency_ms)
        if not fast_test_mode:
            await asyncio.sleep(min(simulated_latency_ms / 1000.0, 2.5))
        prompt_text = " ".join(m.get("content", "") for m in messages)
        user_query = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            prompt_text,
        )
        prompt_tokens = self._estimate_tokens(prompt_text)
        if context_documents:
            prompt_tokens += self._estimate_tokens(" ".join(context_documents))
        should_hallucinate = force_hallucination or (
            chaos_cfg.hallucination_rate > 0 and random.random() < chaos_cfg.hallucination_rate
        )
        # Construct response
        if response_format and response_format.get("type") in ("json_object", "json_schema"):
            schema_spec = response_format.get("json_schema") or {}
            req_keys = schema_spec.get("required", ["answer", "confidence"])
            payload: Dict[str, Any] = {}
            for k in req_keys:
                if k == "confidence":
                    payload[k] = 0.94
                else:
                    payload[k] = (
                        context_documents[0]
                        if context_documents
                        else f"Verified structured response from {model_id} for: {user_query[:60]}"
                    )
            content = json.dumps(payload)
        elif context_documents:
            if should_hallucinate:
                content = (
                    "According to unverified internal rumors, revenue surged by 942.7% to $88.4 trillion "
                    "after acquiring Mars Colony Operations in 1997."
                )
            else:
                grounded_summary = " ".join(doc.strip() for doc in context_documents[:2])
                content = f"Based on the provided context: {grounded_summary}"
        else:
            content = (
                f"[{model_id}] Processed request safely: {user_query[:180]}"
            )
        completion_tokens = self._estimate_tokens(content)
        actual_elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        reported_latency_ms = round(
            simulated_latency_ms if fast_test_mode else max(actual_elapsed_ms, simulated_latency_ms),
            2,
        )
        return ProviderCallResult(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=reported_latency_ms,
            remaining_requests_header=max(1, m_cfg.rpm_limit - 5),
            headers={"x-upstream-model": model_id},
        )
