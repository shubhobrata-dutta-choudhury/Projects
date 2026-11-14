from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None

# Alias for OpenAI schema compatibility
ChatCompletionMessage = ChatMessage

class ProxyRoutingOptions(BaseModel):
    strategy: Optional[Literal["sla_aware_p99", "cost_optimal", "weighted_round_robin"]] = None
    sla_max_latency_ms: Optional[float] = None
    force_hallucination_simulation: bool = False

class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: List[ChatMessage]
    tenant_id: str = "default_tenant"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 512
    response_format: Optional[Dict[str, Any]] = None
    context_documents: Optional[List[str]] = None
    proxy_options: ProxyRoutingOptions = Field(default_factory=ProxyRoutingOptions)

class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"

class ChoiceUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float

class RoutingMetadata(BaseModel):
    requested_model: str
    routed_model: str
    routing_strategy: str
    selection_reason: str
    fallback_triggered: bool
    attempts: int
    p99_latency_ms: float

class GuardrailReportSummary(BaseModel):
    pii_redacted_count: int
    injection_risk_score: float
    injection_blocked: bool
    groundedness_score: float
    hallucination_flagged: bool

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChoiceUsage
    routing_metadata: RoutingMetadata
    guardrail_report: GuardrailReportSummary
