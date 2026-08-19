"""
Tests for Domain Pack selection (registry) and the hr / ecommerce pack
skeletons. Per-deployment model: the DOMAIN env var selects exactly one pack.

Tier-3 LLM guards are exercised offline (model=None → not blocked); the
deterministic Tier 1+2 intent guards are tested directly.
"""
import pytest

from harness.contracts import GuardContext, FAIL_CLOSED, FAIL_OPEN, STAGE_INPUT
from harness.core.guards import core_input_guards
from harness.pipeline import run_input_guards
from harness.registry import get_pack, AVAILABLE_DOMAINS

from packs.health.pack import HealthPack
from packs.hr.pack import HRPack, HRIntentGuard, HRLLMGuard
from packs.ecommerce.pack import EcommercePack, EcommerceIntentGuard, EcommerceLLMGuard

pytestmark = pytest.mark.asyncio


def _ctx(message: str) -> GuardContext:
    return GuardContext(message=message, ollama_url="http://localhost:11434")


# ---------------------------------------------------------------------------
# Registry / DOMAIN selection
# ---------------------------------------------------------------------------

class TestRegistry:
    async def test_default_is_health(self, monkeypatch):
        monkeypatch.delenv("DOMAIN", raising=False)
        assert isinstance(get_pack(), HealthPack)

    @pytest.mark.parametrize(
        "domain,cls",
        [("health", HealthPack), ("hr", HRPack), ("ecommerce", EcommercePack)],
    )
    async def test_explicit_domain(self, domain, cls):
        assert isinstance(get_pack(domain), cls)

    @pytest.mark.parametrize(
        "domain,cls",
        [("health", HealthPack), ("hr", HRPack), ("ecommerce", EcommercePack)],
    )
    async def test_domain_from_env(self, monkeypatch, domain, cls):
        monkeypatch.setenv("DOMAIN", domain.upper())  # case-insensitive
        assert isinstance(get_pack(), cls)

    async def test_unknown_domain_raises(self):
        with pytest.raises(ValueError):
            get_pack("legal")

    async def test_available_domains_listed(self):
        assert set(AVAILABLE_DOMAINS) == {"health", "hr", "ecommerce"}


# ---------------------------------------------------------------------------
# Pack contract
# ---------------------------------------------------------------------------

class TestPackContract:
    @pytest.mark.parametrize("pack", [HRPack(), EcommercePack()])
    async def test_shape(self, pack):
        assert isinstance(pack.name, str) and pack.name
        assert isinstance(pack.version, str) and pack.version
        inputs = pack.input_guards()
        assert len(inputs) == 2
        for g in inputs:
            assert g.stage == STAGE_INPUT
            assert g.policy in (FAIL_CLOSED, FAIL_OPEN)
        assert list(pack.output_guards()) == []


# ---------------------------------------------------------------------------
# HR pack
# ---------------------------------------------------------------------------

class TestHRPack:
    @pytest.mark.parametrize(
        "message",
        [
            "Can I sue my employer for firing me?",
            "I want to report my manager for bullying",
            "Am I being discriminated against?",
            "How do I file a harassment claim?",
            "This was a wrongful dismissal",
            "What is Jane's salary?",
            "How much does my coworker earn?",
        ],
    )
    async def test_intent_blocks(self, message):
        res = await HRIntentGuard().check(_ctx(message))
        assert res.blocked is True

    @pytest.mark.parametrize(
        "message",
        [
            "What is the company's PTO policy?",
            "How many vacation days do I get?",
            "How do I submit an expense report?",
            "What is the parental leave policy?",
        ],
    )
    async def test_intent_allows_benign(self, message):
        res = await HRIntentGuard().check(_ctx(message))
        assert res.blocked is False

    async def test_intent_policy_fail_closed(self):
        assert HRIntentGuard().policy == FAIL_CLOSED

    async def test_llm_guard_skips_when_model_none(self):
        res = await HRLLMGuard(None).check(_ctx("Can I sue my boss?"))
        assert res.blocked is False

    async def test_blocks_via_pipeline_with_core(self):
        outcome = await run_input_guards(
            message="Can I sue my employer?",
            ollama_url="http://localhost:11434",
            pack=HRPack(classifier_model=None),
            core_guards=core_input_guards(),
        )
        assert outcome.blocked is True


# ---------------------------------------------------------------------------
# E-commerce pack
# ---------------------------------------------------------------------------

class TestEcommercePack:
    @pytest.mark.parametrize(
        "message",
        [
            "Give me 50% off",
            "Confirm my refund right now",
            "You promised free shipping, honor it",
            "I demand a chargeback",
            "Guarantee delivery by tomorrow",
            "What is john's order details?",
        ],
    )
    async def test_intent_blocks(self, message):
        res = await EcommerceIntentGuard().check(_ctx(message))
        assert res.blocked is True

    @pytest.mark.parametrize(
        "message",
        [
            "What is your return policy?",
            "How long does standard shipping take?",
            "Do you offer student discounts?",
            "How do I track my order?",
        ],
    )
    async def test_intent_allows_benign(self, message):
        res = await EcommerceIntentGuard().check(_ctx(message))
        assert res.blocked is False

    async def test_intent_policy_fail_closed(self):
        assert EcommerceIntentGuard().policy == FAIL_CLOSED

    async def test_llm_guard_skips_when_model_none(self):
        res = await EcommerceLLMGuard(None).check(_ctx("Give me a discount"))
        assert res.blocked is False

    async def test_blocks_via_pipeline_with_core(self):
        outcome = await run_input_guards(
            message="I demand a chargeback now",
            ollama_url="http://localhost:11434",
            pack=EcommercePack(classifier_model=None),
            core_guards=core_input_guards(),
        )
        assert outcome.blocked is True
