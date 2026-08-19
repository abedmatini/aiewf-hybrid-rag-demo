"""
Harness pipeline — runs guard lists (Core + Pack) with fail-policy handling.

Phase 1 implements the input-guard stage only. Output guards (Phase 3) will
add `run_output_guards` following the same pattern.

Ordering and fail policy:
  - Guards run in the order given (cheap deterministic ones first; the pack
    is responsible for that ordering today).
  - First guard that blocks short-circuits and returns immediately.
  - On a guard raising an exception: fail-closed guards block; fail-open
    guards are skipped (never break UX).
"""
from __future__ import annotations

from typing import Sequence

from harness.contracts import (
    FAIL_CLOSED,
    GuardContext,
    GuardResult,
    InputGuardOutcome,
    OutputGuardOutcome,
    Guard,
    Pack,
)


async def run_input_guards(
    *,
    message: str,
    ollama_url: str,
    pack: Pack,
    core_guards: Sequence[Guard] = (),
    history: list[dict] | None = None,
) -> InputGuardOutcome:
    """
    Run Core input guards then the pack's input guards.

    Redaction guards (e.g. PII) may rewrite the working message via
    ``GuardResult.redacted_message``; later guards and the returned outcome see
    the rewritten text. The first blocking guard short-circuits and may supply
    its own ``escalation_override`` message.
    """
    ctx = GuardContext(
        message=message,
        ollama_url=ollama_url,
        history=history or [],
    )

    guards: list[Guard] = [*core_guards, *pack.input_guards()]
    redactions: list[str] = []

    for guard in guards:
        try:
            result = await guard.check(ctx)
        except Exception as exc:  # noqa: BLE001 — fail policy decides
            if getattr(guard, "policy", FAIL_CLOSED) == FAIL_CLOSED:
                return InputGuardOutcome(
                    blocked=True,
                    reason=f"error_fail_closed:{getattr(guard, 'name', 'unknown')}:{exc}",
                    message=ctx.message,
                    redactions=redactions,
                )
            continue  # fail open — skip this guard

        if result.redactions:
            redactions.extend(result.redactions)
        if result.redacted_message is not None:
            ctx.message = result.redacted_message

        if result.blocked:
            return InputGuardOutcome(
                blocked=True,
                reason=result.reason,
                message=ctx.message,
                redactions=redactions,
                escalation_override=result.escalation_override,
            )

    return InputGuardOutcome(
        blocked=False,
        reason="",
        message=ctx.message,
        redactions=redactions,
    )


async def run_output_guards(
    *,
    message: str,
    draft_response: str,
    ollama_url: str,
    pack: Pack,
    core_guards: Sequence[Guard] = (),
    sources: list[dict] | None = None,
    history: list[dict] | None = None,
    system_prompt: str = "",
) -> OutputGuardOutcome:
    """
    Run Core output guards then the pack's output guards over a *buffered*
    draft answer (buffer-then-stream).

    Redaction guards (e.g. PII) rewrite the working answer via
    ``GuardResult.redacted_message``; later guards and the returned outcome see
    the rewritten text. The first blocking guard short-circuits and may supply
    its own ``escalation_override`` replacement message.
    """
    ctx = GuardContext(
        message=message,
        ollama_url=ollama_url,
        history=history or [],
        draft_response=draft_response,
        sources=sources or [],
        system_prompt=system_prompt,
    )

    guards: list[Guard] = [*core_guards, *pack.output_guards()]
    redactions: list[str] = []

    for guard in guards:
        try:
            result = await guard.check(ctx)
        except Exception as exc:  # noqa: BLE001 — fail policy decides
            if getattr(guard, "policy", FAIL_CLOSED) == FAIL_CLOSED:
                return OutputGuardOutcome(
                    blocked=True,
                    reason=f"error_fail_closed:{getattr(guard, 'name', 'unknown')}:{exc}",
                    response=ctx.draft_response,
                    redactions=redactions,
                )
            continue  # fail open — skip this guard

        if result.redactions:
            redactions.extend(result.redactions)
        if result.redacted_message is not None:
            ctx.draft_response = result.redacted_message

        if result.blocked:
            return OutputGuardOutcome(
                blocked=True,
                reason=result.reason,
                response=ctx.draft_response,
                redactions=redactions,
                escalation_override=result.escalation_override,
            )

    return OutputGuardOutcome(
        blocked=False,
        reason="",
        response=ctx.draft_response,
        redactions=redactions,
    )

