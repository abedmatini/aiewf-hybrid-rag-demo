"""
Health pack — the medical safety domain.

Wraps the existing 3-tier medical guardrail (`guardrails.py`) as Guard objects
behind the harness contract. Behavior is identical to the pre-harness code:

  Tier 1 + 2  → MedicalIntentGuard   (regex intent + clinical term dictionary, sync)
  Tier 3      → MedicalLLMGuard       (async YES/NO classifier on Ollama, fails open)

The guard functions are called via module attribute access (`guardrails.check_medical`)
so tests can monkeypatch them on the `guardrails` module.
"""
from __future__ import annotations

from typing import Sequence

import guardrails
from harness.contracts import (
    FAIL_CLOSED,
    FAIL_OPEN,
    STAGE_INPUT,
    Guard,
    GuardContext,
    GuardResult,
)


class MedicalIntentGuard:
    """Tier 1 + Tier 2 — regex intent patterns and clinical term dictionary."""

    name = "medical_intent_terms"
    stage = STAGE_INPUT
    policy = FAIL_CLOSED  # deterministic + safety-critical

    async def check(self, ctx: GuardContext) -> GuardResult:
        res = guardrails.check_medical(ctx.message)
        return GuardResult(blocked=res.blocked, reason=res.reason)


class MedicalLLMGuard:
    """Tier 3 — async LLM YES/NO classifier for paraphrases regex misses."""

    name = "medical_llm_classifier"
    stage = STAGE_INPUT
    policy = FAIL_OPEN  # never block a legitimate user on classifier error

    def __init__(self, model: str | None) -> None:
        self._model = model

    async def check(self, ctx: GuardContext) -> GuardResult:
        if not self._model or self._model.lower() == "none":
            return GuardResult(blocked=False, reason="")
        res = await guardrails.check_medical_llm(ctx.message, ctx.ollama_url, self._model)
        return GuardResult(blocked=res.blocked, reason=res.reason)


class HealthPack:
    """The health Domain Pack."""

    name = "health"
    version = "1.0.0"

    def __init__(self, classifier_model: str | None = None) -> None:
        self._classifier_model = classifier_model

    def input_guards(self) -> Sequence[Guard]:
        return [
            MedicalIntentGuard(),
            MedicalLLMGuard(self._classifier_model),
        ]

    def output_guards(self) -> Sequence[Guard]:
        return []  # Phase 3
