"""
Core input-guard registry.

``core_input_guards()`` returns the universal guards that run on every
deployment, ahead of the selected Domain Pack's guards. Order (cheap
deterministic tiers first, expensive guard model last):
  1. Crisis / self-harm   (FAIL_CLOSED, blocks + helpline escalation)
  2. Prompt injection      (FAIL_OPEN, blocks)
  3. PII redaction         (FAIL_OPEN, rewrites the message — runs before the
     guard model so no PII is sent to it)
  4. Llama Guard 3 input   (FAIL_OPEN, Tier 3 — only when GUARD_MODEL is set)

``core_output_guards()`` returns the universal output guards that vet the
model's draft answer before it is streamed to the user:
  1. Prompt leak           (FAIL_OPEN, blocks answers echoing the system prompt)
  2. PII output redaction  (FAIL_OPEN, rewrites the answer)
  3. Llama Guard 3 output  (FAIL_OPEN, Tier 3 — only when GUARD_MODEL is set)
"""
from __future__ import annotations

from harness.contracts import Guard
from harness.core.guards.crisis import CrisisGuard
from harness.core.guards.guard_model import LlamaGuardInputGuard, LlamaGuardOutputGuard
from harness.core.guards.injection import PromptInjectionGuard
from harness.core.guards.output_pii import PIIOutputGuard
from harness.core.guards.pii import PIIRedactionGuard
from harness.core.guards.prompt_leak import PromptLeakGuard


def core_input_guards(guard_model: str | None = None) -> list[Guard]:
    return [
        CrisisGuard(),
        PromptInjectionGuard(),
        PIIRedactionGuard(),
        LlamaGuardInputGuard(model=guard_model),
    ]


def core_output_guards(guard_model: str | None = None) -> list[Guard]:
    return [
        PromptLeakGuard(),
        PIIOutputGuard(),
        LlamaGuardOutputGuard(model=guard_model),
    ]
