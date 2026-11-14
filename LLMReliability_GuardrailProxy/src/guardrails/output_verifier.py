from dataclasses import dataclass, field
import re
from typing import List, Optional, Tuple

@dataclass
class OutputVerificationResult:
    is_valid: bool
    groundedness_score: float
    hallucination_flagged: bool
    unsupported_claims: List[str] = field(default_factory=list)

class OutputVerifier:
    """
    Real-Time Hallucination & Groundedness Verification Guardrail:
    Computes groundedness scores against context documents (RAG references)
    and flags ungrounded claims/hallucinations for automated fallback.
    """
    def __init__(self, min_groundedness_score: float = 0.55):
        self.min_groundedness_score = min_groundedness_score

    @staticmethod
    def _extract_sentences(text: str) -> List[str]:
        cleaned = text.strip()
        if not cleaned:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        return [s.strip() for s in sentences if len(s.strip()) > 5]

    @staticmethod
    def _word_overlap_ratio(claim: str, context: str) -> float:
        claim_words = set(re.findall(r"\w+", claim.lower()))
        if not claim_words:
            return 1.0
        # Ignore common stop words
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "and", "or", "in", "on", "at", "to", "for", "of", "with", "by"}
        filtered_claim = claim_words - stop_words
        if not filtered_claim:
            filtered_claim = claim_words
        context_words = set(re.findall(r"\w+", context.lower()))
        matched = filtered_claim.intersection(context_words)
        return len(matched) / float(len(filtered_claim))

    def evaluate_groundedness(
        self, output_text: str, context_documents: List[str]
    ) -> Tuple[float, List[str]]:
        if not context_documents:
            return 1.0, []
        combined_context = " ".join(context_documents)
        claims = self._extract_sentences(output_text)
        if not claims:
            return 1.0, []
        unsupported = []
        scores = []
        for claim in claims:
            overlap = self._word_overlap_ratio(claim, combined_context)
            scores.append(overlap)
            if overlap < 0.30:
                unsupported.append(claim)
        avg_score = sum(scores) / len(scores) if scores else 1.0
        return round(avg_score, 4), unsupported

    def verify_output(
        self, output_text: str, context_documents: Optional[List[str]] = None
    ) -> OutputVerificationResult:
        if not context_documents:
            return OutputVerificationResult(
                is_valid=True,
                groundedness_score=1.0,
                hallucination_flagged=False,
                unsupported_claims=[],
            )
        score, unsupported = self.evaluate_groundedness(output_text, context_documents)
        hallucination_flagged = score < self.min_groundedness_score or len(unsupported) > 0
        return OutputVerificationResult(
            is_valid=not hallucination_flagged,
            groundedness_score=score,
            hallucination_flagged=hallucination_flagged,
            unsupported_claims=unsupported,
        )
