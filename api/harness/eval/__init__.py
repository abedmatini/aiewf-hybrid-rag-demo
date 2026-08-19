"""
Offline, deterministic eval harness for Domain Packs.

Provability is the selling point: every deployment ships a labeled red-team
dataset (jailbreaks, self-harm, PII, domain-specific manipulations + benign
controls) and a runner that reports a pass rate per category. The eval runs the
**deterministic** guard tiers only — Core (crisis / injection / PII) plus the
pack's Tier 1+2 regex/dictionary — so it is fully offline, reproducible, and
CI-friendly (no Ollama, no GUARD_MODEL). The LLM Tier 3 and Llama Guard layers
are additive at runtime and intentionally excluded here.

Public surface:
  - ``EvalCase`` / ``CaseResult`` / ``EvalReport`` data models
  - ``run_eval(domain)`` → ``EvalReport``
  - ``load_cases(domain)`` → core + pack datasets
"""
from harness.eval.runner import CaseResult, EvalCase, EvalReport, run_eval
from harness.eval.datasets import load_cases

__all__ = ["EvalCase", "CaseResult", "EvalReport", "run_eval", "load_cases"]
