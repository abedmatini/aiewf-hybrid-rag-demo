"""
Tests for the offline per-pack eval harness.

Two jobs:
  1. Verify the eval *framework* (report aggregation, dataset loading).
  2. Use the framework as a guardrail regression gate — every labeled case in
     every pack must be caught by the deterministic floor (pass rate == 100%).

Fully offline: no Ollama, no GUARD_MODEL (LLM tiers no-op by design).
"""
import pytest

from harness.eval import EvalReport, load_cases, run_eval
from harness.eval.runner import CaseResult, EvalCase
from harness.registry import AVAILABLE_DOMAINS

pytestmark = pytest.mark.asyncio


class TestReportModel:
    def _report(self) -> EvalReport:
        a = EvalCase("x", "cat_a", expect_blocked=True)
        b = EvalCase("y", "cat_a", expect_blocked=True)
        c = EvalCase("z", "cat_b")
        return EvalReport(
            domain="demo",
            results=[
                CaseResult(a, blocked=True, redacted=False, reason="hit"),    # pass
                CaseResult(b, blocked=False, redacted=False, reason=""),       # fail
                CaseResult(c, blocked=False, redacted=False, reason=""),       # pass
            ],
        )

    async def test_totals(self):
        r = self._report()
        assert r.total == 3
        assert r.passed == 2
        assert r.failed == 1
        assert r.pass_rate == pytest.approx(2 / 3)

    async def test_by_category(self):
        assert self._report().by_category() == {"cat_a": (1, 2), "cat_b": (1, 1)}

    async def test_failures(self):
        failures = self._report().failures()
        assert len(failures) == 1
        assert failures[0].case.prompt == "y"

    async def test_empty_report_is_full_pass(self):
        assert EvalReport(domain="demo").pass_rate == 1.0

    async def test_redaction_pass_logic(self):
        case = EvalCase("email me", "pii", expect_redacted=True)
        assert CaseResult(case, blocked=False, redacted=True, reason="").passed is True
        assert CaseResult(case, blocked=False, redacted=False, reason="").passed is False


class TestDatasets:
    @pytest.mark.parametrize("domain", AVAILABLE_DOMAINS)
    async def test_load_includes_core_and_pack(self, domain):
        cases = load_cases(domain)
        cats = {c.category for c in cases}
        assert {"crisis", "injection", "pii", "benign"} <= cats   # core present
        assert any(c.category.startswith(domain[:2]) or domain in c.category for c in cases) or len(cases) > 20

    async def test_unknown_domain_raises(self):
        with pytest.raises(ValueError):
            load_cases("legal")


class TestGuardrailRegression:
    @pytest.mark.parametrize("domain", AVAILABLE_DOMAINS)
    async def test_pack_passes_100_percent(self, domain):
        report = await run_eval(domain)
        assert report.total > 0
        # Any failure means a labeled red-team case slipped the deterministic floor.
        assert report.pass_rate == 1.0, [
            (f.case.category, f.case.prompt, f"blocked={f.blocked} redacted={f.redacted}")
            for f in report.failures()
        ]

    @pytest.mark.parametrize("domain", AVAILABLE_DOMAINS)
    async def test_benign_controls_not_blocked(self, domain):
        report = await run_eval(domain)
        for r in report.results:
            if r.case.category == "benign":
                assert r.blocked is False, f"benign blocked in {domain}: {r.case.prompt!r}"
                assert r.redacted is False, f"benign redacted in {domain}: {r.case.prompt!r}"
