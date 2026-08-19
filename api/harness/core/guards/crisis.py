"""
Crisis / self-harm input guard (Core, universal).

Policy = FAIL_CLOSED: if this guard errors, we err on the side of escalating
rather than letting a possible crisis message reach the model. A blocking match
supplies its own escalation message (helpline guidance) instead of the generic
domain escalation copy.
"""
from __future__ import annotations

import os
import re

from harness.contracts import FAIL_CLOSED, STAGE_INPUT, GuardContext, GuardResult

# Operator-overridable. Intentionally generic / region-agnostic for on-prem use.
CRISIS_MESSAGE = os.getenv(
    "CRISIS_MESSAGE",
    (
        "It sounds like you may be going through something really difficult. "
        "I'm not able to help with this safely, but you don't have to face it alone. "
        "Please reach out right now to a trained person — contact your local emergency "
        "services or a crisis/suicide helpline in your area. If you are in immediate "
        "danger, call your local emergency number."
    ),
)

_CRISIS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:kill|hurt|harm|cut)(?:ing)?\s+(?:myself|herself|himself|themselves)\b", re.I),
    re.compile(r"\bsuicid(?:e|al)\b", re.I),
    re.compile(r"\b(?:want|wanna|going|going\s+to)\s+to\s+die\b", re.I),
    re.compile(r"\bwant\s+to\s+die\b", re.I),
    re.compile(r"\bend(?:ing)?\s+(?:my\s+life|it\s+all)\b", re.I),
    re.compile(r"\btake\s+my\s+own\s+life\b", re.I),
    re.compile(r"\bself[\s-]?harm\b", re.I),
    re.compile(r"\bno\s+(?:reason|point)\s+(?:to|in)\s+(?:live|living|go\s+on|going\s+on)\b", re.I),
    re.compile(r"\bbetter\s+off\s+dead\b", re.I),
    re.compile(r"\bdon'?t\s+want\s+to\s+(?:live|be\s+(?:here|alive))\b", re.I),
]


class CrisisGuard:
    """Detects self-harm / suicidal intent and escalates with helpline guidance."""

    name = "crisis_self_harm"
    stage = STAGE_INPUT
    policy = FAIL_CLOSED

    async def check(self, ctx: GuardContext) -> GuardResult:
        for pat in _CRISIS_PATTERNS:
            if pat.search(ctx.message):
                return GuardResult(
                    blocked=True,
                    reason=f"crisis:{pat.pattern[:30]}",
                    escalation_override=CRISIS_MESSAGE,
                )
        return GuardResult(blocked=False)
