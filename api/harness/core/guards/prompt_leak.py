"""
Prompt-leak output guard (Core, universal).

Blocks the model from echoing its own configured system prompt / instructions
back to the user. Deterministic: if a substantial verbatim line of the
configured ``system_prompt`` reappears in the draft answer, we treat it as a
leak. Policy = FAIL_OPEN (a detection bug must not break normal answers).

Only the *configured instruction* is compared — never the retrieved RAG context
— so the model quoting a source passage is never mistaken for a prompt leak.
"""
from __future__ import annotations

import re

from harness.contracts import FAIL_OPEN, STAGE_OUTPUT, GuardContext, GuardResult

# Minimum verbatim overlap (normalized chars) to count as a leak.
_MIN_OVERLAP = 50

_SAFE_MESSAGE = (
    "I'm sorry, but I can't share that. How else can I help you with your question?"
)

# Obvious leak markers the model sometimes emits when coerced.
_LEAK_MARKERS = [
    re.compile(r"\bmy\s+(?:system\s+)?(?:prompt|instructions?)\s+(?:is|are|say|state)\b", re.I),
    re.compile(r"\bI\s+was\s+(?:instructed|told|programmed|configured)\s+to\b", re.I),
    re.compile(r"\bhere\s+(?:is|are)\s+my\s+(?:system\s+)?(?:prompt|instructions?)\b", re.I),
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


class PromptLeakGuard:
    """Blocks answers that echo the configured system prompt back to the user."""

    name = "prompt_leak"
    stage = STAGE_OUTPUT
    policy = FAIL_OPEN

    async def check(self, ctx: GuardContext) -> GuardResult:
        draft = _normalize(ctx.draft_response)
        if not draft:
            return GuardResult(blocked=False)

        for marker in _LEAK_MARKERS:
            if marker.search(ctx.draft_response):
                return GuardResult(
                    blocked=True,
                    reason="prompt_leak:marker",
                    escalation_override=_SAFE_MESSAGE,
                )

        system_prompt = ctx.system_prompt or ""
        # Compare line-by-line; a single long instruction line reappearing
        # verbatim in the answer is a strong leak signal.
        for line in re.split(r"[\n.!?]+", system_prompt):
            norm = _normalize(line)
            if len(norm) >= _MIN_OVERLAP and norm in draft:
                return GuardResult(
                    blocked=True,
                    reason="prompt_leak:verbatim_system_prompt",
                    escalation_override=_SAFE_MESSAGE,
                )

        return GuardResult(blocked=False)
