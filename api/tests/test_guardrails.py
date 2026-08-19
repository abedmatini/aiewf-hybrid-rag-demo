"""
Layer 1 — Guardrail unit tests.
Covers all 33 test items from TESTING_CHECKLIST.md Layer 1.

No network calls, no DB — pure in-process regex/substring matching.
Run with: pytest tests/test_guardrails.py -v
"""

import pytest
from guardrails import check_medical


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def blocked(text: str) -> bool:
    return check_medical(text).blocked


def reason(text: str) -> str:
    return check_medical(text).reason


# ---------------------------------------------------------------------------
# Tier 1 — Intent patterns (1.1 – 1.15): must be blocked
# ---------------------------------------------------------------------------

class TestTier1IntentPatterns:
    """CHECKLIST: 1.1–1.15 — Tier 1 regex intent patterns."""

    def test_1_1_can_i_take(self):
        """1.1 — can i take"""
        assert blocked("Can I take ibuprofen with this?")

    def test_1_2_do_i_have(self):
        """1.2 — do i have"""
        assert blocked("Do I have a vitamin deficiency?")

    def test_1_3_should_i_use(self):
        """1.3 — should I use"""
        assert blocked("Should I use this product twice a day?")

    def test_1_4_my_symptoms(self):
        """1.4 — my symptoms"""
        assert blocked("My symptoms include headache and nausea")

    def test_1_5_i_think_i_might_have(self):
        """1.5 — i think i might have"""
        assert blocked("I think I might have an allergy")

    def test_1_6_whats_causing_my(self):
        """1.6 — what's causing my"""
        assert blocked("What's causing my dizziness?")

    def test_1_7_how_should_i_treat(self):
        """1.7 — how should i treat"""
        assert blocked("How should I treat my rash?")

    def test_1_8_is_it_safe_for_me(self):
        """1.8 — is it safe for me"""
        assert blocked("Is it safe for me to take this while pregnant?")

    def test_1_9_am_i_getting_enough(self):
        """1.9 — am i getting enough"""
        assert blocked("Am I getting enough iron?")

    def test_1_10_what_dose_should_i(self):
        """1.10 — what dose should i"""
        assert blocked("What dose should I take?")

    def test_1_11_do_i_need(self):
        """1.11 — do i need"""
        assert blocked("Do I need to see a doctor?")

    def test_1_12_is_it_normal_to(self):
        """1.12 — is it normal to"""
        assert blocked("Is it normal to feel dizzy after taking this?")

    def test_1_13_i_have_fever_and_cough(self):
        """1.13 — i have fever cough"""
        assert blocked("I have a fever and a cough")

    def test_1_14_home_remedy(self):
        """1.14 — home remedy"""
        assert blocked("What home remedy can I use?")

    def test_1_15_diagnose_me(self):
        """1.15 — diagnose me"""
        assert blocked("Can you diagnose me?")

    # Verify reason string marks tier1 for a sample
    def test_tier1_reason_prefix(self):
        """Reason string contains 'intent_pattern' for a tier-1 block."""
        r = reason("Can I take ibuprofen with this?")
        assert r.startswith("intent_pattern:"), f"Unexpected reason: {r}"


# ---------------------------------------------------------------------------
# Tier 2 — Clinical terms (1.16 – 1.22): must be blocked
# ---------------------------------------------------------------------------

class TestTier2ClinicalTerms:
    """CHECKLIST: 1.16–1.22 — Tier 2 clinical term substring matches."""

    def test_1_16_anaphylaxis(self):
        """1.16 — anaphylaxis"""
        assert blocked("Tell me about anaphylaxis")

    def test_1_17_sepsis(self):
        """1.17 — sepsis"""
        assert blocked("What is sepsis?")

    def test_1_18_vitamin_deficiency(self):
        """1.18 — vitamin deficiency"""
        assert blocked("Information about vitamin deficiency")

    def test_1_19_iron_deficiency(self):
        """1.19 — iron deficiency"""
        assert blocked("iron deficiency symptoms")

    def test_1_20_drug_interaction(self):
        """1.20 — drug interaction"""
        assert blocked("drug interaction between paracetamol")

    def test_1_21_heart_attack(self):
        """1.21 — heart attack"""
        assert blocked("heart attack warning signs")

    def test_1_22_adverse_reaction(self):
        """1.22 — adverse reaction"""
        assert blocked("adverse reaction to ibuprofen")

    # Verify reason string marks tier2 for a sample
    def test_tier2_reason_prefix(self):
        """Reason string contains 'clinical_term' for a tier-2 block."""
        r = reason("Tell me about anaphylaxis")
        assert r.startswith("clinical_term:"), f"Unexpected reason: {r}"


# ---------------------------------------------------------------------------
# Clean queries (1.23 – 1.29): must NOT be blocked by tiers 1+2
# ---------------------------------------------------------------------------

class TestCleanPassThrough:
    """CHECKLIST: 1.23–1.29 — Legitimate product queries must pass through."""

    def test_1_23_what_is_vitamin_d(self):
        """1.23 — What is vitamin D?"""
        assert not blocked("What is vitamin D?")

    def test_1_24_how_does_ibuprofen_work(self):
        """1.24 — How does ibuprofen work?"""
        assert not blocked("How does ibuprofen work?")

    def test_1_25_ingredients_in_tylenol(self):
        """1.25 — ingredients in Tylenol"""
        assert not blocked("What are the ingredients in Tylenol?")

    def test_1_26_third_person_anaemia(self):
        """1.26 — third-person anaemia question should pass (only first-person escalates)"""
        assert not blocked("What should a person with anaemia eat?")

    def test_1_27_company_hq(self):
        """1.27 — general company question"""
        assert not blocked("Where is Acme Cloud headquartered?")

    def test_1_28_upload_document(self):
        """1.28 — admin workflow question"""
        assert not blocked("How do I upload a document?")

    def test_1_29_faq_topics(self):
        """1.29 — general FAQ topic question"""
        assert not blocked("What topics are covered in the FAQ?")


# ---------------------------------------------------------------------------
# Edge cases (1.30 – 1.33)
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """CHECKLIST: 1.30–1.33 — Edge cases: empty input, long input, casing, unicode."""

    def test_1_30_empty_string(self):
        """1.30 — empty string must not crash and must not block"""
        result = check_medical("")
        assert result.blocked is False

    def test_1_31_very_long_input(self):
        """1.31 — 5 000-char input must not raise an exception"""
        long_text = "What is vitamin D? " * 263  # ~5 000 chars, clean content
        result = check_medical(long_text)
        # Content is clean (no medical intent in this phrase) — just must not crash
        assert isinstance(result.blocked, bool)

    def test_1_31b_long_input_with_medical_phrase(self):
        """1.31b — 5 000-char input containing a medical phrase must still block"""
        padding = "What is vitamin D? " * 260
        text = padding + "Can I take ibuprofen with this?"
        assert blocked(text)

    def test_1_32_uppercase_can_i_take(self):
        """1.32 — case-insensitive: CAN I TAKE must still block"""
        assert blocked("CAN I TAKE ibuprofen")

    def test_1_32b_uppercase_clinical_term(self):
        """1.32b — case-insensitive: ANAPHYLAXIS must still block"""
        assert blocked("Tell me about ANAPHYLAXIS")

    def test_1_33_unicode_input(self):
        """1.33 — unicode accented chars must not raise an exception"""
        result = check_medical("Can I tàke this?")
        assert isinstance(result.blocked, bool)

    def test_1_33b_unicode_clean(self):
        """1.33b — fully non-Latin unicode must not crash"""
        result = check_medical("製品について教えてください")
        assert isinstance(result.blocked, bool)

    def test_whitespace_only(self):
        """Whitespace-only string must not crash"""
        result = check_medical("   \n\t  ")
        assert result.blocked is False

    def test_none_is_not_accepted(self):
        """Passing None should raise TypeError (function expects str)"""
        with pytest.raises((TypeError, AttributeError)):
            check_medical(None)  # type: ignore[arg-type]
