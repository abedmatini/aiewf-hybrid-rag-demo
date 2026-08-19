"""
Harness contracts — the interfaces every guard and domain pack implements.

These are intentionally tiny and dependency-free so that Core guards and
Pack guards are interchangeable: the pipeline just runs a list of `Guard`
objects and reacts to their `GuardResult`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable


# ── Fail policy / stage / tier string constants ───────────────────────────────
FAIL_OPEN = "fail_open"      # on error → allow (never break UX)
FAIL_CLOSED = "fail_closed"  # on error → block (safety-critical)

STAGE_INPUT = "input"
STAGE_OUTPUT = "output"


@dataclass
class GuardResult:
    """Outcome of a single guard check."""
    blocked: bool
    reason: str = ""                       # logged server-side; never shown to user
    redactions: list[str] = field(default_factory=list)
    redacted_message: str | None = None    # set by redaction guards (e.g. PII)
    escalation_override: str | None = None  # blocking guard can supply its own message


@dataclass
class InputGuardOutcome:
    """Aggregate result of running the full input-guard stage."""
    blocked: bool
    reason: str = ""
    message: str = ""                       # effective (possibly redacted) message
    redactions: list[str] = field(default_factory=list)
    escalation_override: str | None = None


@dataclass
class OutputGuardOutcome:
    """Aggregate result of running the full output-guard stage."""
    blocked: bool
    reason: str = ""
    response: str = ""                      # effective (possibly redacted) answer
    redactions: list[str] = field(default_factory=list)
    escalation_override: str | None = None



@dataclass
class GuardContext:
    """
    Everything a guard might need to inspect.

    Input guards use `message` (and optionally `history`). Output guards
    (added in Phase 3) also populate `draft_response`, `sources` and
    `system_prompt` (the configured instruction, used for prompt-leak checks).
    """
    message: str
    ollama_url: str
    history: list[dict] = field(default_factory=list)
    draft_response: str = ""
    sources: list[dict] = field(default_factory=list)
    system_prompt: str = ""


@runtime_checkable
class Guard(Protocol):
    """A single safety check. Core and Pack guards both implement this."""
    name: str
    stage: str    # STAGE_INPUT | STAGE_OUTPUT
    policy: str   # FAIL_OPEN | FAIL_CLOSED

    async def check(self, ctx: GuardContext) -> GuardResult: ...


@runtime_checkable
class Pack(Protocol):
    """A domain pack: the rules + config layered on top of the Core."""
    name: str
    version: str

    def input_guards(self) -> Sequence[Guard]: ...
    def output_guards(self) -> Sequence[Guard]: ...
