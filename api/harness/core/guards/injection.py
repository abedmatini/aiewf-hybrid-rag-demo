"""
Prompt-injection / jailbreak input guard (Core, universal).

Deterministic regex over the user message. Policy = FAIL_OPEN: a regex bug must
never take the bot down. High-signal patterns only, to keep false positives low
for ordinary FAQ-style questions.
"""
from __future__ import annotations

import re

from harness.contracts import FAIL_OPEN, STAGE_INPUT, GuardContext, GuardResult

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # "ignore / disregard / forget the previous instructions"
    re.compile(
        r"\b(?:ignore|disregard|forget)\b.{0,30}\b"
        r"(?:previous|prior|above|preceding|earlier|all)\b.{0,20}\b"
        r"(?:instruction|prompt|message|rule|context|direction)s?\b",
        re.I,
    ),
    # "forget everything above / ignore all that I told you"
    re.compile(
        r"\b(?:forget|ignore|disregard)\s+(?:everything|all|what(?:ever)?)\b.{0,25}\b"
        r"(?:above|previous|prior|before|said|told|instruction|rule)\b",
        re.I,
    ),
    # role reassignment / persona override
    re.compile(r"\byou\s+are\s+now\s+(?:a|an|the|my)\b", re.I),
    re.compile(r"\bact\s+as\b", re.I),
    re.compile(r"\bpretend\s+(?:to\s+be|you\s+are|that\s+you)\b", re.I),
    # well-known jailbreak handles
    re.compile(r"\b(?:do\s+anything\s+now|dan\s+mode|developer\s+mode|jailbreak)\b", re.I),
    re.compile(r"\bact\s+as\s+dan\b", re.I),
    re.compile(r"\bunfiltered\b.{0,15}\b(?:mode|response|answer|model|version|ai|assistant)\b", re.I),
    # disable / bypass the safety layer
    re.compile(
        r"\b(?:bypass|override|disable|turn\s+off|ignore)\b.{0,25}\b"
        r"(?:rule|guardrail|restriction|filter|safety|guideline|policy)s?\b",
        re.I,
    ),
    # system-prompt extraction
    re.compile(
        r"\b(?:reveal|show|print|repeat|display|output|leak|expose|give)\b.{0,25}\b"
        r"(?:system\s+prompt|your\s+(?:system\s+)?(?:prompt|instructions?)"
        r"|initial\s+prompt|prompt\s+above)\b",
        re.I,
    ),
    re.compile(
        r"\bwhat(?:'?s|\s+is|\s+are)\b.{0,15}\byour\s+(?:system\s+)?(?:prompt|instructions?)\b",
        re.I,
    ),
    # injected chat-template / control tokens
    re.compile(r"<\|?(?:im_start|im_end|system|endoftext)\|?>", re.I),
]


class PromptInjectionGuard:
    """Blocks jailbreak / prompt-injection attempts before retrieval or the agent."""

    name = "prompt_injection"
    stage = STAGE_INPUT
    policy = FAIL_OPEN

    async def check(self, ctx: GuardContext) -> GuardResult:
        for pat in _INJECTION_PATTERNS:
            if pat.search(ctx.message):
                return GuardResult(blocked=True, reason=f"prompt_injection:{pat.pattern[:40]}")
        return GuardResult(blocked=False)
