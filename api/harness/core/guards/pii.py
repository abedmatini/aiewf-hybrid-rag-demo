"""
PII redaction input guard (Core, universal).

Policy = FAIL_OPEN. This guard never blocks — it rewrites the working message,
replacing detected PII with ``[REDACTED_*]`` placeholders so the cleaned text is
what gets logged, embedded, retrieved on, and sent to the model.
"""
from __future__ import annotations

import re

from harness.contracts import FAIL_OPEN, STAGE_INPUT, GuardContext, GuardResult

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD = re.compile(r"\b(?:\d{4}[ -]){3}\d{4}\b|\b\d{13,16}\b")
_PHONE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"
)

# Order matters: more specific / structured patterns first so a phone match does
# not consume digits that belong to an SSN or card number.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", _EMAIL),
    ("SSN", _SSN),
    ("CREDIT_CARD", _CREDIT_CARD),
    ("PHONE", _PHONE),
]


def redact(text: str) -> tuple[str, list[str]]:
    """
    Replace any detected PII in ``text`` with ``[REDACTED_*]`` placeholders.

    Returns ``(possibly_rewritten_text, labels)`` where ``labels`` is the list
    of PII categories that were redacted (empty if the text was clean).
    Shared by the input guard (redacts the user message) and the output guard
    (redacts the model's answer).
    """
    redactions: list[str] = []
    for label, pat in _PATTERNS:
        def _sub(_m: re.Match[str], _label: str = label) -> str:
            redactions.append(_label)
            return f"[REDACTED_{_label}]"

        text = pat.sub(_sub, text)
    return text, redactions


class PIIRedactionGuard:
    """Redacts email, SSN, credit-card and phone PII from the user message."""

    name = "pii_redaction"
    stage = STAGE_INPUT
    policy = FAIL_OPEN

    async def check(self, ctx: GuardContext) -> GuardResult:
        text, redactions = redact(ctx.message)
        if redactions:
            return GuardResult(blocked=False, redactions=redactions, redacted_message=text)
        return GuardResult(blocked=False)
