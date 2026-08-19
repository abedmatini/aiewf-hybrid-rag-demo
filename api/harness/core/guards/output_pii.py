"""
PII output-redaction guard (Core, universal).

Redacts PII (email, SSN, credit-card, phone) from the model's draft answer
before it reaches the user — a safety net against the model surfacing personal
data from retrieved context, history, or hallucination. Policy = FAIL_OPEN; it
never blocks, it rewrites the answer.

Reuses the same detection logic as the input-side PII guard.
"""
from __future__ import annotations

from harness.contracts import FAIL_OPEN, STAGE_OUTPUT, GuardContext, GuardResult
from harness.core.guards.pii import redact


class PIIOutputGuard:
    """Redacts PII from the model's answer before it is streamed to the user."""

    name = "pii_output_redaction"
    stage = STAGE_OUTPUT
    policy = FAIL_OPEN

    async def check(self, ctx: GuardContext) -> GuardResult:
        text, redactions = redact(ctx.draft_response)
        if redactions:
            return GuardResult(blocked=False, redactions=redactions, redacted_message=text)
        return GuardResult(blocked=False)
