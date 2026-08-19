#!/usr/bin/env python
"""
Per-pack eval CLI — provable, offline guardrail scorecard.

Runs the deterministic guard floor (Core + the pack's Tier 1+2) against each
pack's labeled red-team dataset and prints a per-category pass rate. No Ollama,
no models — fully reproducible, suitable for CI and for showing a buyer exactly
what the guardrails catch.

Usage (from kenvue-agentic/api):
  python eval_packs.py                 # all domains
  python eval_packs.py health          # one domain
  python eval_packs.py --threshold 1.0 # fail (exit 1) below this pass rate

Exit code is non-zero if any evaluated domain falls below the threshold.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from harness.eval import EvalReport, run_eval
from harness.registry import AVAILABLE_DOMAINS


def _print_report(report: EvalReport) -> None:
    print(f"\n=== {report.domain.upper()} pack ===")
    print(f"{'category':<22} {'passed':>8} {'total':>7}  rate")
    print("-" * 48)
    for category, (passed, total) in report.by_category().items():
        rate = passed / total if total else 1.0
        flag = "" if passed == total else "  <-- FAIL"
        print(f"{category:<22} {passed:>8} {total:>7}  {rate:5.0%}{flag}")
    print("-" * 48)
    print(f"{'OVERALL':<22} {report.passed:>8} {report.total:>7}  {report.pass_rate:5.0%}")

    failures = report.failures()
    if failures:
        print(f"\n  {len(failures)} failing case(s):")
        for r in failures:
            verb = "blocked" if r.blocked else ("redacted" if r.redacted else "allowed")
            exp = "block" if r.case.expect_blocked else ("redact" if r.case.expect_redacted else "allow")
            print(f"   - [{r.case.category}] expected {exp}, got {verb}: {r.case.prompt!r}")


async def _main(domains: list[str], threshold: float) -> int:
    overall_ok = True
    for domain in domains:
        report = await run_eval(domain)
        _print_report(report)
        if report.pass_rate < threshold:
            overall_ok = False

    print()
    if overall_ok:
        print(f"PASS — all domains at or above {threshold:.0%}.")
        return 0
    print(f"FAIL — one or more domains below {threshold:.0%}.")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run per-pack guardrail evals.")
    parser.add_argument(
        "domains",
        nargs="*",
        choices=AVAILABLE_DOMAINS,
        help="Domains to evaluate (default: all).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Minimum pass rate (0-1) required to exit 0. Default 1.0.",
    )
    args = parser.parse_args()
    domains = args.domains or list(AVAILABLE_DOMAINS)
    sys.exit(asyncio.run(_main(domains, args.threshold)))


if __name__ == "__main__":
    main()
