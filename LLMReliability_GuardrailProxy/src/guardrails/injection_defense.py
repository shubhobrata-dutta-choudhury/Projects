from dataclasses import dataclass, field
import re
from typing import Dict, List

@dataclass
class InjectionScanResult:
    is_injection: bool
    blocked: bool
    risk_score: float
    reasons: List[str] = field(default_factory=list)

class PromptInjectionDefense:
    """
    Multi-layered Prompt Injection & Jailbreak Scanner:
    - Layer 1: Heuristic string distance / System override keywords
    - Layer 2: Regex pattern matching for direct & indirect jailbreak vectors
    - Layer 3: Base64 / Hex encoded payload inspection
    """
    def __init__(self, block_threshold: float = 0.65, flag_threshold: float = 0.35):
        self.block_threshold = block_threshold
        self.flag_threshold = flag_threshold
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in [
                r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|directives|rules)",
                r"disregard\s+(the\s+)?system\s+prompt",
                r"you\s+are\s+now\s+in\s+['\"]?DAN['\"]?\s+mode",
                r"override\s+safety\s+(filters|guidelines|rules)",
                r"reveal\s+(your\s+)?(full\s+)?system\s+prompt",
                r"repeat\s+the\s+words\s+above",
                r"(?:__import__\s*\(\s*['\"]os['\"]\)|subprocess\.Popen|os\.system\s*\(|DROP\s+TABLE\s+users)",
            ]
        ]

    def scan_text(self, text: str) -> InjectionScanResult:
        reasons = []
        score = 0.0
        cleaned = text.strip()

        # Check direct jailbreak patterns
        for pat in self._compiled_patterns:
            if pat.search(cleaned):
                score += 0.45
                reasons.append(f"regex_match:{pat.pattern[:30]}")

        # Check for suspicious system override commands
        lowered = cleaned.lower()
        if "ignore all previous instructions" in lowered or "ignore prior directives" in lowered:
            score += 0.70
            reasons.append("system_override_attempt")

        # Check for encoded payload attempts (e.g. Base64 triggers)
        if "base64" in lowered or "execute payload" in lowered or len(re.findall(r"[A-Za-z0-9+/]{40,}={0,2}", text)) > 0:
            score += 0.35
            reasons.append("base64_encoded_payload")

        score = min(1.0, score)
        blocked = score >= self.block_threshold
        is_injection = score >= self.flag_threshold

        return InjectionScanResult(
            is_injection=is_injection,
            blocked=blocked,
            risk_score=round(score, 2),
            reasons=reasons,
        )

    def scan_messages(self, messages: List[Dict[str, str]]) -> InjectionScanResult:
        combined_text = " ".join(m.get("content", "") for m in messages if isinstance(m, dict))
        return self.scan_text(combined_text)
