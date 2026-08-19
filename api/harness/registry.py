"""
Domain registry — resolves the active Domain Pack for this deployment.

Per-deployment model: a single `DOMAIN` env var selects exactly one pack.
Defaults to "health" to preserve the current behavior of this codebase.
"""
from __future__ import annotations

import os

from harness.contracts import Pack

AVAILABLE_DOMAINS = ("health_faq", "health", "hr", "ecommerce")


def get_pack(domain: str | None = None, *, classifier_model: str | None = None) -> Pack:
    """
    Load the Domain Pack for `domain` (or the DOMAIN env var, default "health").

    `classifier_model` is forwarded to packs that use an LLM tier (e.g. health's
    Tier 3 medical classifier).
    """
    domain = (domain or os.getenv("DOMAIN", "health")).strip().lower()

    if domain == "health_faq":
        from packs.health_faq.pack import HealthFAQPack
        return HealthFAQPack(classifier_model=classifier_model)

    if domain == "health":
        from packs.health.pack import HealthPack
        return HealthPack(classifier_model=classifier_model)

    if domain == "hr":
        from packs.hr.pack import HRPack
        return HRPack(classifier_model=classifier_model)

    if domain == "ecommerce":
        from packs.ecommerce.pack import EcommercePack
        return EcommercePack(classifier_model=classifier_model)

    # Unknown domain — fall back to health_faq (safe for demo deployments)
    from packs.health_faq.pack import HealthFAQPack
    return HealthFAQPack(classifier_model=classifier_model)
