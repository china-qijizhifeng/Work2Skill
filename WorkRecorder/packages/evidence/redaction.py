"""Local deterministic redaction before text becomes agent-readable."""

from __future__ import annotations

import re


class SensitiveTextRedactor:
    """Redact common local secrets before canonical text indexing."""

    _patterns = (
        re.compile(r"(?i)((?:authorization\s*:\s*)?bearer\s+)[A-Za-z0-9._~+/=-]+"),
        re.compile(r"(?i)(authorization\s*:\s*)(?!bearer\s+)[^\s\"'<>]{3,}"),
        re.compile(
            r"(?i)((?:api[-_ ]?key|token|secret|password|credential|jwt|session(?:\s*id)?|csrf|xsrf)\s*[:=]\s*)[^\s\"'<>]{3,}"
        ),
        re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9_=-]{6,}\b", re.IGNORECASE),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        re.compile(r"\bSHOULD_NOT_LEAK_[A-Z0-9_]+\b"),
        re.compile(r"\b[A-Za-z0-9_+/=-]{32,}\b"),
        re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    )

    def redact(self, text: str) -> str:
        """Return text with high-risk tokens replaced by stable placeholders.

        Args:
            text: Candidate agent-readable text.

        Returns:
            Text with common credentials and sentinel secrets redacted.
        """

        redacted = text
        for pattern in self._patterns:
            if pattern.groups:
                redacted = pattern.sub(r"\1[REDACTED]", redacted)
            else:
                redacted = pattern.sub("[REDACTED]", redacted)
        return redacted.strip()
