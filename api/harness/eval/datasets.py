"""
Dataset loader — merges the universal Core cases with the active pack's cases.
"""
from __future__ import annotations

from harness.eval.core_cases import CORE_CASES
from harness.eval.runner import EvalCase
from harness.registry import AVAILABLE_DOMAINS


def load_cases(domain: str) -> list[EvalCase]:
    """Return Core cases + the pack's domain-specific cases for ``domain``."""
    domain = domain.strip().lower()

    if domain == "health":
        from packs.health.eval.cases import CASES
    elif domain == "hr":
        from packs.hr.eval.cases import CASES
    elif domain == "ecommerce":
        from packs.ecommerce.eval.cases import CASES
    else:
        raise ValueError(
            f"Unknown DOMAIN '{domain}'. Available packs: {', '.join(AVAILABLE_DOMAINS)}."
        )

    return [*CORE_CASES, *CASES]
