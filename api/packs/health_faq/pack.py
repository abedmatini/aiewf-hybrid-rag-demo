"""
HealthFAQ pack — informational health content domain.

Purpose: power a health FAQ chatbot that answers general questions about
medical conditions, symptoms, treatments, when to seek care, and lifestyle
advice. Designed for FAQ document sets (appendicitis, bronchitis, etc.).

Contrast with the ``health`` pack which blocks all medical discussion (built
for consumer-product chatbots where health topics are out-of-scope).

Guard tiers:
  Tier 1 — PersonalDiagnosisGuard  : regex — blocks first-person diagnosis /
                                      personalised prescribing requests.
                                      Informational questions pass freely.
  Tier 3 — HealthFAQLLMGuard       : async YES/NO classifier — catches
                                      paraphrases that slip past Tier 1.
                                      Fails open; never blocks on error.

What is BLOCKED (personal advice-seeking):
  "Do I have appendicitis?"
  "What's wrong with me?"
  "Am I sick?"
  "What medication should I personally take?"

What is ALLOWED (informational / educational):
  "What are the symptoms of appendicitis?"
  "How is bronchitis treated?"
  "When should someone see a doctor for appendicitis?"
  "Is appendicitis dangerous?"
  "Can ibuprofen be used for bronchitis?"
  "What causes bronchitis?"
  "What are the risk factors for appendicitis?"
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

# ---------------------------------------------------------------------------
# Tier 1 — first-person diagnosis / personalised prescribing (FAIL_CLOSED)
# Patterns are intentionally narrow: only unambiguous "tell ME what I have"
# requests. Informational third-person or general questions are not caught.
# ---------------------------------------------------------------------------
_PERSONAL_ADVICE_PATTERNS: list[re.Pattern] = [
    # Personal diagnosis
    re.compile(r"\bdo\s+i\s+have\b", re.I),
    re.compile(r"\bcould\s+i\s+(?:have|be\s+(?:sick|ill|infected|allergic))\b", re.I),
    re.compile(r"\bmight\s+i\s+have\b", re.I),
    re.compile(r"\bi\s+(?:think|believe|suspect)\s+i\s+(?:have|might\s+have)\b", re.I),
    re.compile(r"\bwhat(?:'s|\s+is)\s+wrong\s+with\s+me\b", re.I),
    re.compile(r"\bdiagnose\s+me\b", re.I),
    re.compile(r"\bam\s+i\s+(?:sick|ill|infected|allergic|dying)\b", re.I),
    re.compile(r"\bam\s+i\s+(?:deficient|low\s+in|lacking)\b", re.I),
    # Personalised prescribing — "what should I specifically take"
    re.compile(r"\bwhat\s+(?:medication|medicine|drug|pill|antibiotic)s?\s+should\s+i\s+take\b", re.I),
    re.compile(r"\bprescribe\s+(?:me|something\s+for\s+me)\b", re.I),
    re.compile(r"\bwhat\s+exact\s+(?:dose|dosage)\s+should\s+i\b", re.I),
    re.compile(r"\boverdo(?:se|sed|sing)\b", re.I),
    # Dangerous / lethal content
    re.compile(r"\b(?:lethal|toxic)\s+dose\b", re.I),
    re.compile(r"\bld50\b", re.I),
]

# ---------------------------------------------------------------------------
# Tier 3 — LLM classifier prompt (FAIL_OPEN)
# Trained to distinguish informational FAQ questions from personal diagnosis.
# ---------------------------------------------------------------------------
_LLM_SYSTEM = """You are a safety classifier for a health FAQ chatbot.
The chatbot answers general health and medical information questions based on
approved FAQ documents. It cannot diagnose users or prescribe personalised treatment.

Your task: determine if the user message is asking for PERSONALISED medical advice —
meaning they want the chatbot to tell THEM specifically what disease they have right
now, or exactly what medication THEY personally should take.

Respond ONLY with YES or NO.

YES (block — personalised diagnosis or personalised prescribing for self):
  "Do I have appendicitis?"
  "What's wrong with me?"
  "Tell me if I have an infection"
  "Am I sick?"
  "What medication should I personally take given my symptoms right now?"

NO (allow — general health information and educational questions):
  "What are the symptoms of appendicitis?"
  "How is bronchitis treated?"
  "When should someone see a doctor for appendicitis?"
  "Is appendicitis dangerous?"
  "Can ibuprofen be used for bronchitis?"
  "What causes appendicitis?"
  "What are the warning signs that need emergency care?"
  "When should I go to the emergency room?" (general guidance)
  "Is it normal to have pain after appendix surgery?" (general post-op info)
  "What dietary choices support immunity against bronchitis?"
  "What is the difference between acute and chronic bronchitis?"
"""


class PersonalDiagnosisGuard:
    """Tier 1 — blocks unambiguous first-person diagnosis / personalised prescribing."""

    name = "personal_diagnosis"
    stage = STAGE_INPUT
    policy = FAIL_CLOSED

    async def check(self, ctx: GuardContext) -> GuardResult:
        for pattern in _PERSONAL_ADVICE_PATTERNS:
            if pattern.search(ctx.message):
                return GuardResult(
                    blocked=True,
                    reason=f"personal_advice:{pattern.pattern[:60]}",
                )
        return GuardResult(blocked=False, reason="")


class HealthFAQLLMGuard:
    """Tier 3 — LLM classifier that only blocks personalised diagnosis / prescribing."""

    name = "health_faq_llm"
    stage = STAGE_INPUT
    policy = FAIL_OPEN

    def __init__(self, model: str | None) -> None:
        self._model = model

    async def check(self, ctx: GuardContext) -> GuardResult:
        if not self._model or self._model.lower() in ("none", ""):
            return GuardResult(blocked=False, reason="")
        blocked = await classify_yes_no(
            message=ctx.message,
            ollama_url=ctx.ollama_url,
            model=self._model,
            system_prompt=_LLM_SYSTEM,
        )
        return GuardResult(
            blocked=blocked,
            reason="health_faq_llm:personalised_advice" if blocked else "",
        )


class HealthFAQPack:
    """Domain Pack for informational health FAQ chatbots."""

    name = "health_faq"
    version = "1.0.0"

    def __init__(self, classifier_model: str | None = None) -> None:
        self._classifier_model = classifier_model

    def input_guards(self) -> Sequence[Guard]:
        return [
            PersonalDiagnosisGuard(),
            HealthFAQLLMGuard(self._classifier_model),
        ]

    def output_guards(self) -> Sequence[Guard]:
        return []
