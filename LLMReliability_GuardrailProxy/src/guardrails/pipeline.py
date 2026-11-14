import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from src.guardrails.injection_defense import InjectionScanResult, PromptInjectionDefense
from src.guardrails.output_verifier import OutputVerificationResult, OutputVerifier
from src.guardrails.pii_redactor import PIIRedactResult, PIIRedactor

@dataclass
class InputGuardrailReport:
    redacted_messages: List[Dict[str, str]]
    vault_mapping: Dict[str, str]
    pii_redacted_count: int
    injection_blocked: bool
    injection_risk_score: float
    injection_flagged: bool
    reasons: List[str] = field(default_factory=list)

@dataclass
class PipelineExecutionReport:
    input_report: InputGuardrailReport
    output_report: Optional[OutputVerificationResult] = None
    input_guardrail_latency_ms: float = 0.0
    output_verification_latency_ms: float = 0.0

class GuardrailPipeline:
    """
    Parallel Async Guardrail Pipeline:
    - Parallel Input Stage: Runs PII Redaction & Prompt Injection Defense concurrently via asyncio.gather
    - Output Stage: Performs groundedness and hallucination verification against RAG contexts
    """
    def __init__(self, pii_threshold: float = 0.7, injection_block_threshold: float = 0.65):
        self.pii_redactor = PIIRedactor()
        self.injection_defense = PromptInjectionDefense(block_threshold=injection_block_threshold)
        self.output_verifier = OutputVerifier()

    async def run_input_guardrails(self, raw_messages: List[Dict[str, str]]) -> InputGuardrailReport:
        async def _check_injection() -> InjectionScanResult:
            return await asyncio.to_thread(self.injection_defense.scan_messages, raw_messages)

        async def _redact_pii() -> Tuple[List[Dict[str, str]], Dict[str, str], int]:
            redacted_msgs = []
            vault: Dict[str, str] = {}
            total_count = 0
            for msg in raw_messages:
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    res: PIIRedactResult = await asyncio.to_thread(self.pii_redactor.redact_text, content)
                    redacted_msgs.append({**msg, "content": res.redacted_text})
                    vault.update(res.vault_mapping)
                    total_count += res.redacted_count
                else:
                    redacted_msgs.append(msg)
            return redacted_msgs, vault, total_count

        inj_res, (redacted_msgs, vault, pii_count) = await asyncio.gather(
            _check_injection(), _redact_pii()
        )

        return InputGuardrailReport(
            redacted_messages=redacted_msgs,
            vault_mapping=vault,
            pii_redacted_count=pii_count,
            injection_blocked=inj_res.blocked,
            injection_risk_score=inj_res.risk_score,
            injection_flagged=inj_res.is_injection,
            reasons=inj_res.reasons,
        )

    async def run_output_verification(
        self, generated_text: str, context_documents: Optional[List[str]] = None
    ) -> OutputVerificationResult:
        return await asyncio.to_thread(
            self.output_verifier.verify_output, generated_text, context_documents
        )
