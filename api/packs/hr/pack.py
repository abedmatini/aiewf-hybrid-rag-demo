"""
HR pack — workplace / employment safety domain.

Mirrors the health pack's 3-tier shape behind the harness contract:

  Tier 1 + 2  → HRIntentGuard   (regex intent + employment-law term dictionary,
                                  plus third-party PII like "what's Jane's salary",
                                  sync, FAIL_CLOSED)
  Tier 3      → HRLLMGuard       (async YES/NO classifier: individual legal /
                                  grievance action vs. general policy info,
                                  FAIL_OPEN)

A blocking guard escalates to the deployment's configured channel (e.g. an HR
representative / formal grievance process) via the standard escalation message.
"""
from __future__ import annotations

import re
from typing import Sequence

from harness.contracts import (
    FAIL_CLOSED,
    FAIL_OPEN,
    STAGE_INPUT,
    Guard,
    GuardContext,
    GuardResult,
)
from harness.llm_classifier import classify_yes_no

# ── Tier 1 — intent patterns (individual legal / grievance action) ───────────
_INTENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:can|should)\s+i\s+sue\b", re.I),
    re.compile(r"\bsue\s+(?:my|the)\s+(?:company|employer|manager|boss|organization)\b", re.I),
    re.compile(r"\breport\s+(?:my\s+)?(?:manager|boss|supervisor|coworker|colleague|employer)\b", re.I),
    re.compile(r"\bam\s+i\s+being\s+(?:discriminated|harassed|bullied|retaliated)\b", re.I),
    re.compile(r"\b(?:file|filing|submit|lodge)\s+a\s+(?:grievance|complaint|claim|lawsuit|case)\b", re.I),
    re.compile(r"\bwrongful(?:ly)?\s+(?:dismiss|dismissal|terminat|fir)\w*\b", re.I),
    re.compile(r"\bunfair(?:ly)?\s+(?:dismissed|fired|terminated|treated)\b", re.I),
    re.compile(r"\bwhistleblow(?:er|ing)?\b", re.I),
    re.compile(r"\bhostile\s+work\s+environment\b", re.I),
    re.compile(r"\bsexual(?:ly)?\s+harass\w*\b", re.I),
    # Third-party PII — other employees' compensation / personal data
    re.compile(r"\bwhat(?:'s|\s+is)\s+\w+'?s?\s+salary\b", re.I),
    re.compile(r"\bhow\s+much\s+does\s+\w+(?:\s+\w+)?\s+(?:make|earn|get\s+paid)\b", re.I),
    re.compile(r"\b(?:salary|pay|compensation|wage)\s+of\s+(?:my\s+)?(?:coworker|colleague|manager|boss)\b", re.I),
]

# ── Tier 2 — standalone employment-law terms (substring, lowercased) ─────────
_HR_TERMS: frozenset[str] = frozenset({
    "wrongful dismissal",
    "wrongful termination",
    "constructive dismissal",
    "unfair dismissal",
    "harassment claim",
    "discrimination claim",
    "retaliation claim",
    "wage theft",
    "whistleblower",
    "hostile work environment",
})

# ── Tier 3 — LLM classifier prompt ───────────────────────────────────────────
_HR_LLM_SYSTEM = """You are a safety classifier for a company HR assistant chatbot.
Determine if the user message is seeking INDIVIDUAL legal or grievance action,
advice about their own employment dispute, or another person's private HR data
(salary, performance, disciplinary records).

Respond with ONLY the word YES or NO — nothing else.

YES examples:
  "Can I sue my employer for firing me?"
  "How do I file a harassment claim against my boss?"
  "Am I being discriminated against because of my age?"
  "What is my coworker's salary?"

NO examples:
  What is the company's PTO policy?
  How many vacation days do I get per year?
  What is the parental leave policy?
  How do I submit an expense report?"""


class HRIntentGuard:
    """Tier 1 + 2 — regex intent, employment-law terms, third-party PII."""

    name = "hr_intent_terms"
    stage = STAGE_INPUT
    policy = FAIL_CLOSED

    async def check(self, ctx: GuardContext) -> GuardResult:
        text = ctx.message
        lower = text.lower()
        for pattern in _INTENT_PATTERNS:
            if pattern.search(text):
                return GuardResult(blocked=True, reason=f"hr_intent:{pattern.pattern[:40]}")
        for term in _HR_TERMS:
            if term in lower:
                return GuardResult(blocked=True, reason=f"hr_term:{term}")
        return GuardResult(blocked=False)


class HRLLMGuard:
    """Tier 3 — async LLM YES/NO classifier for paraphrases regex misses."""

    name = "hr_llm_classifier"
    stage = STAGE_INPUT
    policy = FAIL_OPEN

    def __init__(self, model: str | None) -> None:
        self._model = model

    async def check(self, ctx: GuardContext) -> GuardResult:
        if not self._model or self._model.lower() == "none":
            return GuardResult(blocked=False)
        blocked = await classify_yes_no(
            ctx.message, ctx.ollama_url, self._model, system_prompt=_HR_LLM_SYSTEM
        )
        return GuardResult(blocked=blocked, reason="hr_llm_classifier" if blocked else "")


class HRPack:
    """The HR Domain Pack."""

    name = "hr"
    version = "1.0.0"

    def __init__(self, classifier_model: str | None = None) -> None:
        self._classifier_model = classifier_model

    def input_guards(self) -> Sequence[Guard]:
        return [
            HRIntentGuard(),
            HRLLMGuard(self._classifier_model),
        ]

    def output_guards(self) -> Sequence[Guard]:
        return []  # domain output rules arrive with the eval phase
