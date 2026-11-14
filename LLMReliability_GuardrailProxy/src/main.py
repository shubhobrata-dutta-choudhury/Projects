import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from src.config import load_config
from src.guardrails.pipeline import GuardrailPipeline
from src.providers.mock_chaos_provider import (
    UpstreamProviderCluster,
    UpstreamRateLimitError,
    UpstreamServiceUnavailableError,
)
from src.router.load_balancer import AdaptiveLoadBalancer
from src.schemas.openai_compat import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChoiceUsage,
    GuardrailReportSummary,
    RoutingMetadata,
)
from src.telemetry.collector import TelemetryCollector, TelemetryEvent
from src.telemetry.cost_calculator import CostCalculator
from src.telemetry.prometheus_metrics import export_prometheus_metrics

class GuardrailGatewayService:
    def __init__(self, fast_test_mode: bool = False):
        self.fast_test_mode = fast_test_mode
        self.config = load_config()
        self.load_balancer = AdaptiveLoadBalancer(self.config)
        self.provider_cluster = UpstreamProviderCluster(self.config.models)
        self.guardrails = GuardrailPipeline()
        self.cost_calc = CostCalculator(self.config.models)
        self.telemetry = TelemetryCollector()

    async def handle_chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        start_ns = time.perf_counter_ns()
        request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        
        # 1. Input Guardrails
        t_input_start = time.perf_counter_ns()
        raw_messages = [m.model_dump() for m in request.messages]
        input_report = await self.guardrails.run_input_guardrails(raw_messages)
        input_guardrail_latency_ms = (time.perf_counter_ns() - t_input_start) / 1_000_000

        sanitized_messages = input_report.redacted_messages
        pii_vault = input_report.vault_mapping

        # Block direct prompt injections
        if input_report.injection_blocked:
            total_latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            event = TelemetryEvent(
                request_id=request_id,
                timestamp=time.time(),
                tenant_id=request.tenant_id,
                requested_model=request.model,
                routed_model="blocked",
                provider="none",
                routing_strategy=request.proxy_options.strategy or self.config.gateway.default_routing_strategy,
                status="blocked_injection",
                fallback_triggered=False,
                attempts=0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_usd=0.0,
                upstream_latency_ms=0.0,
                total_gateway_latency_ms=round(total_latency_ms, 2),
                input_guardrail_latency_ms=round(input_guardrail_latency_ms, 2),
                output_verification_latency_ms=0.0,
                pii_redacted_count=input_report.pii_redacted_count,
                injection_risk_score=input_report.injection_risk_score,
                injection_blocked=True,
                groundedness_score=1.0,
                hallucination_flagged=False,
                selection_reason="Blocked by real-time Prompt Injection Guardrail",
            )
            self.telemetry.record_event(event)

            return ChatCompletionResponse(
                id=request_id,
                created=int(time.time()),
                model="blocked",
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatCompletionMessage(
                            role="assistant",
                            content="[BLOCKED] Request rejected due to detected prompt injection payload.",
                        ),
                        finish_reason="content_filter",
                    )
                ],
                usage=ChoiceUsage(
                    prompt_tokens=0, completion_tokens=0, total_tokens=0, estimated_cost_usd=0.0
                ),
                routing_metadata=RoutingMetadata(
                    requested_model=request.model,
                    routed_model="blocked",
                    routing_strategy=event.routing_strategy,
                    selection_reason="Prompt injection blocked",
                    fallback_triggered=False,
                    attempts=0,
                    p99_latency_ms=0.0,
                ),
                guardrail_report=GuardrailReportSummary(
                    pii_redacted_count=input_report.pii_redacted_count,
                    injection_risk_score=input_report.injection_risk_score,
                    injection_blocked=True,
                    groundedness_score=1.0,
                    hallucination_flagged=False,
                ),
            )

        # 2. Select Candidate Upstream Models
        candidates = self.load_balancer.select_order_of_candidates(
            requested_model=request.model,
            strategy=request.proxy_options.strategy,
            sla_max_latency_ms=request.proxy_options.sla_max_latency_ms,
        )

        selected_candidate = None
        provider_result = None
        output_report = None
        attempts = 0
        excluded_models = set()
        force_halluc = request.proxy_options.force_hallucination_simulation

        # 3. Execution & SLA/Verification Fallback Loop
        for candidate in candidates:
            m_cfg = candidate.model_config
            if m_cfg.id in excluded_models:
                continue
            attempts += 1
            try:
                res = await self.provider_cluster.generate(
                    model_id=m_cfg.id,
                    messages=sanitized_messages,
                    context_documents=request.context_documents,
                    response_format=request.response_format,
                    force_hallucination=(force_halluc and attempts == 1),
                    fast_test_mode=self.fast_test_mode,
                )
                self.load_balancer.latency_tracker.record(m_cfg.id, res.latency_ms)
                self.load_balancer.rate_limiter.record_usage(
                    m_cfg.id, res.prompt_tokens + res.completion_tokens, res.remaining_requests_header
                )
                self.load_balancer.circuit_breaker.record_success(m_cfg.id)

                t_out_start = time.perf_counter_ns()
                out_v = await self.guardrails.run_output_verification(
                    res.content, request.context_documents
                )
                output_verification_latency_ms = (time.perf_counter_ns() - t_out_start) / 1_000_000

                if out_v.hallucination_flagged and attempts < len(candidates):
                    excluded_models.add(m_cfg.id)
                    continue

                selected_candidate = candidate
                provider_result = res
                output_report = out_v
                break

            except UpstreamRateLimitError as e:
                self.load_balancer.rate_limiter.mark_rate_limited(m_cfg.id, e.retry_after_sec)
                excluded_models.add(m_cfg.id)
            except UpstreamServiceUnavailableError:
                self.load_balancer.circuit_breaker.record_failure(m_cfg.id)
                excluded_models.add(m_cfg.id)
            except Exception:
                self.load_balancer.circuit_breaker.record_failure(m_cfg.id)
                excluded_models.add(m_cfg.id)

        if not selected_candidate or not provider_result:
            raise HTTPException(
                status_code=503,
                detail="All upstream model endpoints failed or exceeded SLA/rate limits.",
            )

        # 4. PII Rehydration & Telemetry Recording
        final_content = self.guardrails.pii_redactor.rehydrate_text(
            provider_result.content, pii_vault
        )
        total_gateway_latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        cost_usd = self.cost_calc.calculate_cost(
            selected_candidate.model_config.id,
            provider_result.prompt_tokens,
            provider_result.completion_tokens,
        )
        fallback_triggered = attempts > 1 or selected_candidate.model_config.id != request.model

        event = TelemetryEvent(
            request_id=request_id,
            timestamp=time.time(),
            tenant_id=request.tenant_id,
            requested_model=request.model,
            routed_model=selected_candidate.model_config.id,
            provider=selected_candidate.model_config.provider,
            routing_strategy=request.proxy_options.strategy or self.config.gateway.default_routing_strategy,
            status="success",
            fallback_triggered=fallback_triggered,
            attempts=attempts,
            prompt_tokens=provider_result.prompt_tokens,
            completion_tokens=provider_result.completion_tokens,
            total_tokens=provider_result.prompt_tokens + provider_result.completion_tokens,
            cost_usd=cost_usd,
            upstream_latency_ms=provider_result.latency_ms,
            total_gateway_latency_ms=round(total_gateway_latency_ms, 2),
            input_guardrail_latency_ms=round(input_guardrail_latency_ms, 2),
            output_verification_latency_ms=round(0.5, 2),
            pii_redacted_count=input_report.pii_redacted_count,
            injection_risk_score=input_report.injection_risk_score,
            injection_blocked=False,
            groundedness_score=output_report.groundedness_score if output_report else 1.0,
            hallucination_flagged=output_report.hallucination_flagged if output_report else False,
            selection_reason=selected_candidate.reason,
        )
        self.telemetry.record_event(event, p99_snapshot=selected_candidate.p99_snapshot)

        return ChatCompletionResponse(
            id=request_id,
            created=int(time.time()),
            model=selected_candidate.model_config.id,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionMessage(role="assistant", content=final_content),
                    finish_reason="stop",
                )
            ],
            usage=ChoiceUsage(
                prompt_tokens=provider_result.prompt_tokens,
                completion_tokens=provider_result.completion_tokens,
                total_tokens=provider_result.prompt_tokens + provider_result.completion_tokens,
                estimated_cost_usd=cost_usd,
            ),
            routing_metadata=RoutingMetadata(
                requested_model=request.model,
                routed_model=selected_candidate.model_config.id,
                routing_strategy=event.routing_strategy,
                selection_reason=selected_candidate.reason,
                fallback_triggered=fallback_triggered,
                attempts=attempts,
                p99_latency_ms=selected_candidate.p99_snapshot.get(
                    selected_candidate.model_config.id, selected_candidate.model_config.base_latency_ms
                ),
            ),
            guardrail_report=GuardrailReportSummary(
                pii_redacted_count=input_report.pii_redacted_count,
                injection_risk_score=input_report.injection_risk_score,
                injection_blocked=False,
                groundedness_score=output_report.groundedness_score if output_report else 1.0,
                hallucination_flagged=output_report.hallucination_flagged if output_report else False,
            ),
        )

# FastAPI Application Factory
gateway_service = GuardrailGatewayService()
app = FastAPI(
    title="LLM Reliability & P99 SLA Guardrail Proxy",
    version="1.0.0",
    description="Production-grade LLM Gateway with P99 SLA routing, PII redaction, prompt injection defense & real-time telemetry",
)

static_dir = Path(__file__).resolve().parent / "dashboard" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    res = await gateway_service.handle_chat_completion(request)
    if res.guardrail_report.injection_blocked:
        raise HTTPException(
            status_code=400,
            detail=f"Request blocked by Prompt Injection Guardrail (Risk Score: {res.guardrail_report.injection_risk_score})",
        )
    return res

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>GuardrailProxy Service Running</h1>")

@app.get("/api/dashboard/state")
async def get_dashboard_state():
    return {
        "telemetry": gateway_service.telemetry.get_dashboard_summary(),
        "cluster": gateway_service.load_balancer.get_cluster_state(),
        "chaos": gateway_service.provider_cluster.get_chaos_snapshot(),
    }

@app.post("/api/chaos/configure")
async def configure_chaos(payload: Dict[str, Any]):
    model_id = payload.get("model_id")
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id required")
    st = gateway_service.provider_cluster.update_chaos(
        model_id=model_id,
        added_latency_ms=payload.get("added_latency_ms"),
        force_429_rate=payload.get("force_429_rate"),
        force_503_rate=payload.get("force_503_rate"),
        hallucination_rate=payload.get("hallucination_rate"),
    )
    return {"status": "updated", "model_id": model_id, "state": st}

@app.post("/api/chaos/reset")
async def reset_chaos():
    gateway_service.provider_cluster.reset_all_chaos()
    return {"status": "reset_all"}

@app.post("/api/chaos/simulate-burst")
async def simulate_burst(count: int = Query(default=10, ge=1, le=50)):
    async def _single_req():
        req = ChatCompletionRequest(
            model="auto",
            messages=[
                {
                    "role": "user",
                    "content": "Customer John Doe (email: john@acme.com, SSN: 123-45-6789) asked for Q3 metrics.",
                }
            ],
            context_documents=[
                "Acme Corp Q3 revenue increased by 18.4% YoY to $42.5 million."
            ],
        )
        try:
            return await gateway_service.handle_chat_completion(req)
        except Exception:
            return None

    results = await asyncio.gather(*[_single_req() for _ in range(count)])
    successful = sum(1 for r in results if r is not None)
    return {"status": "burst_completed", "requested": count, "successful": successful}

@app.get("/metrics")
async def prometheus_metrics():
    content, content_type = export_prometheus_metrics()
    return Response(content=content, media_type=content_type)
