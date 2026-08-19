"""
Eval data models + runner.

A case is a labeled prompt with an expected guard outcome. The runner drives
each case through the real input-guard pipeline (Core + Pack, deterministic
tiers only — no classifier model is supplied, so LLM/guard-model tiers no-op)
and scores whether the deterministic floor caught it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from harness.core.guards import core_input_guards
from harness.pipeline import run_input_guards
from harness.registry import get_pack

_DEFAULT_OLLAMA = "http://localhost:11434"


@dataclass(frozen=True)
class EvalCase:
    """A single labeled red-team / control prompt."""

    prompt: str
    category: str                 # e.g. "injection", "crisis", "pii", "hr_intent", "benign"
    expect_blocked: bool = False  # deterministic guards should block it
    expect_redacted: bool = False # deterministic guards should redact it (e.g. PII)
    note: str = ""


@dataclass
class CaseResult:
    case: EvalCase
    blocked: bool
    redacted: bool
    reason: str

    @property
    def passed(self) -> bool:
        return (
            self.blocked == self.case.expect_blocked
            and self.redacted == self.case.expect_redacted
        )


@dataclass
class EvalReport:
    domain: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0

    def failures(self) -> list[CaseResult]:
        return [r for r in self.results if not r.passed]

    def by_category(self) -> dict[str, tuple[int, int]]:
        """category -> (passed, total)."""
        out: dict[str, tuple[int, int]] = {}
        for r in self.results:
            p, t = out.get(r.case.category, (0, 0))
            out[r.case.category] = (p + (1 if r.passed else 0), t + 1)
        return dict(sorted(out.items()))


async def run_eval(
    domain: str,
    cases: list[EvalCase] | None = None,
    *,
    ollama_url: str = _DEFAULT_OLLAMA,
) -> EvalReport:
    """
    Run the deterministic input-guard floor for ``domain`` over ``cases``.

    ``classifier_model`` is intentionally None so the pack's LLM tier no-ops,
    and GUARD_MODEL is left unset so Llama Guard no-ops — the eval measures only
    the offline regex/dictionary guarantees.
    """
    # Imported here to avoid a circular import at module load.
    from harness.eval.datasets import load_cases

    cases = cases if cases is not None else load_cases(domain)
    pack = get_pack(domain, classifier_model=None)
    core = core_input_guards()

    report = EvalReport(domain=domain)
    for case in cases:
        outcome = await run_input_guards(
            message=case.prompt,
            ollama_url=ollama_url,
            pack=pack,
            core_guards=core,
        )
        report.results.append(
            CaseResult(
                case=case,
                blocked=outcome.blocked,
                redacted=bool(outcome.redactions),
                reason=outcome.reason,
            )
        )
    return report
