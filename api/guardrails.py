"""
Medical intent guardrails.

Three-tier detection:
  Tier 1 — intent patterns : regex phrases that signal advice-seeking
                              (diagnose, my symptoms, should I take, …)
  Tier 2 — clinical terms  : high-confidence standalone medical terms
                              unlikely in a legitimate product query.
  Tier 3 — LLM classifier  : async YES/NO call to Ollama for paraphrases
                              that slip through Tiers 1 & 2.  Runs in
                              parallel with RAG so it adds zero latency
                              on clean queries.
"""

import re
from typing import NamedTuple

import httpx


class GuardrailResult(NamedTuple):
    blocked: bool
    reason: str  # logged server-side; never sent to the user


# ---------------------------------------------------------------------------
# Tier 1 — intent patterns (advice-seeking language)
# ---------------------------------------------------------------------------
_INTENT_PATTERNS: list[re.Pattern] = [
    # Diagnosis intent
    re.compile(r"\b(diagnose|diagnosis|diagnoses|diagnose\s+me)\b", re.I),
    re.compile(r"\bdo\s+i\s+have\b", re.I),
    re.compile(r"\bcould\s+i\s+(?:have|be)\b", re.I),
    re.compile(r"\bmight\s+i\s+(?:have|be)\b", re.I),
    re.compile(r"\bi\s+(?:think|believe|suspect)\s+i\s+(?:have|might|could)\b", re.I),
    re.compile(r"\bwhat(?:'s|\s+is)\s+wrong\s+with\s+(me|my)\b", re.I),
    re.compile(r"\bwhat(?:'s|\s+is)\s+causing\s+my\b", re.I),
    re.compile(r"\bsuffer(?:ing)?\s+from\b", re.I),
    # My symptoms / condition
    re.compile(r"\bmy\s+(symptom|symptoms|condition|illness|disease|pain|infection|rash|fever|cough|headache|nausea)\b", re.I),
    re.compile(
        r"\bi\s+(have|feel|am\s+feeling|am\s+experiencing|am\s+suffering|am\s+having)"
        r".*?\b(pain|fever|cough|nausea|rash|swelling|infection|illness|headache|dizziness|bleeding)\b",
        re.I | re.S,
    ),
    # Prescribing / treatment
    re.compile(r"\bprescri(be|bed|bing|ption|ptions)\b", re.I),
    re.compile(r"\bshould\s+i\s+(take|use|apply|stop|avoid)\b", re.I),
    re.compile(r"\bcan\s+i\s+take\b", re.I),
    re.compile(r"\bwhat\s+should\s+i\s+take\s+for\b", re.I),
    re.compile(r"\bhow\s+(?:do|should|can)\s+i\s+treat\b", re.I),
    re.compile(r"\btreat(?:ment|ing|ed)?\s+for\s+my\b", re.I),
    re.compile(r"\bnatural\s+remedy\b", re.I),
    re.compile(r"\bhome\s+remedy\b", re.I),
    re.compile(r"\bcure\s+for\b", re.I),
    # Safety for me
    re.compile(r"\bis\s+it\s+safe\s+for\s+(me|my|a)\b", re.I),
    re.compile(r"\bis\s+it\s+normal\s+to\b", re.I),
    re.compile(r"\bam\s+i\s+(sick|ill|infected|allergic|at\s+risk)\b", re.I),
    re.compile(r"\bam\s+i\s+(?:deficient|low\s+in|lacking|getting\s+enough|missing)\b", re.I),
    # Dose / interaction / overdose
    re.compile(r"\bwhat\s+(?:dose|dosage)\s+should\s+i\b", re.I),
    re.compile(r"\bhow\s+much\s+(?:should\s+i\s+take|can\s+i\s+take)\b", re.I),
    re.compile(r"\boverdo(?:se|sed|sing)\b", re.I),
    re.compile(r"\bdrug\s+interaction\b", re.I),
    re.compile(r"\bside[\s-]?effect[s]?\s+(?:for\s+me|i\s+(?:am|have))\b", re.I),
    # General medical advice
    re.compile(r"\bmedical\s+advice\b", re.I),
    re.compile(r"\bdo\s+i\s+need\b", re.I),       # "Do I need vitamin D?"
    re.compile(r"\bhelp\s+(?:with\s+)?my\s+(?:symptom|condition|pain|illness)\b", re.I),
]

# ---------------------------------------------------------------------------
# Tier 2 — standalone clinical terms (substring match, lowercased)
# Single occurrence is sufficient to trigger escalation.
# ---------------------------------------------------------------------------
_CLINICAL_TERMS: frozenset[str] = frozenset({
    "anaphylaxis",
    "anaphylactic",
    "arrhythmia",
    "tachycardia",
    "bradycardia",
    "myocardial infarction",
    "heart attack",
    "haemorrhage",
    "hemorrhage",
    "thrombosis",
    "embolism",
    "sepsis",
    "carcinoma",
    "malignant tumor",
    "malignant tumour",
    "metastasis",
    "chemotherapy",
    "radiotherapy",
    "immunotherapy",
    "biopsy",
    "contraindication",
    "adverse reaction",
    "lethal dose",
    "ld50",
    "toxic dose",
    "vitamin deficiency",
    "nutrient deficiency",
    "mineral deficiency",
    "iron deficiency",
    # Note: "anaemia"/"anemia" removed from Tier 2 — they are common conditions
    # that appear in legitimate product queries (e.g. dietary info, iron supplements).
    # First-person forms are caught by Tier 1 patterns; ambiguous third-person forms
    # are correctly handled by the Tier 3 LLM classifier.
})

# ---------------------------------------------------------------------------
# Tier 3 — LLM classifier prompt
# ---------------------------------------------------------------------------
_LLM_SYSTEM = """You are a safety classifier for a consumer health product chatbot.
Determine if the user message is seeking personal medical advice, a health
diagnosis, treatment recommendation, nutritional guidance, or similar health
guidance FOR THEMSELVES.

Respond with ONLY the word YES or NO — nothing else.

YES examples:
  "Do I need vitamin D supplements?"
  "What's causing my tiredness?"
  "Am I getting enough iron?"
  "Could I be vitamin deficient?"
  "Is it normal to feel dizzy?"
  "Do I need to see a doctor?"

NO examples:
  What are the ingredients in Tylenol?
  How does SPF 50 work?
  What studies back this product?
  What documents are in the knowledge base?"""


def check_medical(text: str) -> GuardrailResult:
    """
    Synchronous check (Tiers 1 + 2 only).  Runs purely in-process, < 1 ms.
    Call this first; only escalate to check_medical_llm when this returns False.
    """
    lower = text.lower()

    for pattern in _INTENT_PATTERNS:
        if pattern.search(text):
            return GuardrailResult(blocked=True, reason=f"intent_pattern:{pattern.pattern}")

    for term in _CLINICAL_TERMS:
        if term in lower:
            return GuardrailResult(blocked=True, reason=f"clinical_term:{term}")

    return GuardrailResult(blocked=False, reason="")


async def check_medical_llm(text: str, ollama_url: str, model: str) -> GuardrailResult:
    """
    Tier 3 — async LLM-based classification.

    Sends a minimal YES/NO prompt to Ollama.  Called only when Tiers 1 & 2
    did NOT block, meaning this handles paraphrases regex cannot catch.

    Fails open on any error (network, timeout) — never blocks a legitimate
    user due to a classification service failure.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{ollama_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _LLM_SYSTEM},
                        {"role": "user", "content": text},
                    ],
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 5},
                },
            )
            resp.raise_for_status()
            answer = resp.json().get("message", {}).get("content", "").strip().upper()
            if answer.startswith("YES"):
                return GuardrailResult(blocked=True, reason="llm_classifier")
    except Exception:
        pass  # fail open — never block on classification error

    return GuardrailResult(blocked=False, reason="")
