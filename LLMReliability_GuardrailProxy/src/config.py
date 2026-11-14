from pathlib import Path
from typing import List, Optional
import yaml
from pydantic import BaseModel, Field

class PIIConfig(BaseModel):
    enabled: bool = True
    rehydrate_on_output: bool = False
    redact_entities: List[str] = Field(
        default_factory=lambda: [
            "EMAIL",
            "PHONE",
            "SSN",
            "CREDIT_CARD",
            "API_KEY",
            "IP_ADDRESS",
            "PERSON_NAME",
        ]
    )

class PromptInjectionConfig(BaseModel):
    enabled: bool = True
    block_threshold: float = 0.65
    flag_threshold: float = 0.35

class OutputVerificationConfig(BaseModel):
    enabled: bool = True
    min_groundedness_score: float = 0.55
    auto_fallback_on_hallucination: bool = True
    enforce_json_schema: bool = True
    block_secret_leakage: bool = True

class GuardrailsConfig(BaseModel):
    pii: PIIConfig = Field(default_factory=PIIConfig)
    prompt_injection: PromptInjectionConfig = Field(
        default_factory=PromptInjectionConfig
    )
    output_verification: OutputVerificationConfig = Field(
        default_factory=OutputVerificationConfig
    )

class ModelEndpointConfig(BaseModel):
    id: str
    provider: str
    tier: str = "flagship"
    priority: int = 1
    weight: int = 50
    sla_p99_target_ms: float = 1000.0
    rpm_limit: int = 120
    tpm_limit: int = 150000
    cost_per_1k_prompt_tokens: float = 0.0025
    cost_per_1k_completion_tokens: float = 0.0100
    base_latency_ms: float = 300.0
    jitter_ms: float = 80.0
    quality_score: float = 0.95
    api_base: Optional[str] = None
    api_key_env: Optional[str] = None

class GatewaySettings(BaseModel):
    name: str = "GuardrailProxy"
    version: str = "1.0.0"
    default_routing_strategy: str = "sla_aware_p99"
    global_sla_p99_ms: float = 1200.0
    max_retries: int = 2
    latency_window_seconds: int = 60

class ProxyConfig(BaseModel):
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    models: List[ModelEndpointConfig] = Field(default_factory=list)

def load_config(config_path: Optional[str] = None) -> ProxyConfig:
    if config_path is None:
        default_path = Path(__file__).resolve().parent.parent / "config" / "proxy_config.yaml"
    else:
        default_path = Path(config_path)
    if default_path.exists():
        with open(default_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}
        return ProxyConfig(**raw_data)
    return ProxyConfig()
