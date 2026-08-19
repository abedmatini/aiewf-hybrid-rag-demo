"""
Tier 3 = Guard Model (Llama Guard 3, local in Ollama). Core, universal.

A guard model is a small LLM fine-tuned only for safety classification: the
input is a conversation (optionally including the assistant's draft answer) and
the output is ``safe`` or ``unsafe\\n<category>``. Llama Guard 3 already knows the
standard hazard taxonomy (violent crimes, self-harm, hate, sexual content, PII,
jailbreak, …), so it replaces the hand-written YES/NO prompts with a single
robust classifier used on both input and output.

Operationally:
  - Pull the model once:  ``ollama pull llama-guard3``
  - Enable per deployment: set ``GUARD_MODEL=llama-guard3`` (env).
  - Disabled by default (``GUARD_MODEL`` unset / ``"none"``) → guards no-op with
    zero network calls, so the cheap deterministic tiers run alone.

Policy = FAIL_OPEN on both stages: any classification error (timeout, model not
pulled, bad response) returns *allow*, so a guard-model outage never breaks UX.
The deterministic Crisis / injection / PII tiers still run first and remain the
hard safety floor.
"""
from __future__ import annotations

import os

import httpx

from harness.contracts import FAIL_OPEN, STAGE_INPUT, STAGE_OUTPUT, GuardContext, GuardResult


def _guard_model() -> str:
    """Configured guard model, or "" when disabled."""
    model = os.getenv("GUARD_MODEL", "").strip()
    return "" if model.lower() in ("", "none") else model


async def classify_conversation(
    messages: list[dict],
    ollama_url: str,
    model: str,
    *,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """
    Classify a conversation with Llama Guard 3.

    Returns ``(unsafe, reason)``. Llama Guard always classifies the *last*
    message in ``messages`` (a user turn on input, an assistant turn on output).
    Fails open: any error returns ``(False, "")``.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{ollama_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 20},
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "").strip()
    except Exception:
        return (False, "")  # fail open — never block on classification error

    if content.lower().startswith("unsafe"):
        parts = content.split("\n", 1)
        category = parts[1].strip() if len(parts) > 1 else "unsafe"
        return (True, f"llama_guard:{category}")
    return (False, "")


class LlamaGuardInputGuard:
    """Guard-model safety check on the inbound user message (Tier 3, input)."""

    name = "llama_guard_input"
    stage = STAGE_INPUT
    policy = FAIL_OPEN

    def __init__(self, model: str | None = None):
        self._model = model if model is not None else _guard_model()

    async def check(self, ctx: GuardContext) -> GuardResult:
        if not self._model:
            return GuardResult(blocked=False)
        messages = [*ctx.history, {"role": "user", "content": ctx.message}]
        unsafe, reason = await classify_conversation(messages, ctx.ollama_url, self._model)
        return GuardResult(blocked=unsafe, reason=reason)


class LlamaGuardOutputGuard:
    """Guard-model safety check on the assistant's draft answer (Tier 3, output)."""

    name = "llama_guard_output"
    stage = STAGE_OUTPUT
    policy = FAIL_OPEN

    def __init__(self, model: str | None = None):
        self._model = model if model is not None else _guard_model()

    async def check(self, ctx: GuardContext) -> GuardResult:
        if not self._model:
            return GuardResult(blocked=False)
        messages = [
            *ctx.history,
            {"role": "user", "content": ctx.message},
            {"role": "assistant", "content": ctx.draft_response},
        ]
        unsafe, reason = await classify_conversation(messages, ctx.ollama_url, self._model)
        return GuardResult(blocked=unsafe, reason=reason)
