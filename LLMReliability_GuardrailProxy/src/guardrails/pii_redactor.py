from dataclasses import dataclass, field
import re
from typing import Dict, List

@dataclass
class PIIRedactResult:
    redacted_text: str
    vault_mapping: Dict[str, str]
    redacted_count: int

class PIIRedactor:
    """
    Zero-Trust PII Redaction & Vault Engine:
    Detects Sensitive Personal Data (SSN, Email, Phone, API Keys, Credit Cards)
    and replaces them with deterministic vault placeholders (e.g., <PII:EMAIL_1>).
    """
    def __init__(self):
        self._patterns = [
            ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
            ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
            ("PHONE", re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
            ("API_KEY", re.compile(r"\bsk-[A-Za-z0-9-_]{20,}\b")),
            ("CREDIT_CARD", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
        ]

    def redact_text(self, text: str) -> PIIRedactResult:
        redacted = text
        vault: Dict[str, str] = {}
        count = 0
        counters: Dict[str, int] = {}

        for pii_type, regex in self._patterns:
            matches = list(regex.finditer(redacted))
            for match in reversed(matches):
                val = match.group(0)
                counters.setdefault(pii_type, 0)
                counters[pii_type] += 1
                token = f"<PII:{pii_type}_{counters[pii_type]}>"
                vault[token] = val
                start, end = match.span()
                redacted = redacted[:start] + token + redacted[end:]
                count += 1

        return PIIRedactResult(
            redacted_text=redacted,
            vault_mapping=vault,
            redacted_count=count,
        )

    def rehydrate_text(self, text: str, vault_mapping: Dict[str, str]) -> str:
        restored = text
        for token, original in vault_mapping.items():
            restored = restored.replace(token, original)
        return restored
