"""
Layer 3B — RAGAS RAG quality metrics.

Prerequisites (already in venv):
  pip install ragas langchain-ollama   # already done

Run against a live stack:
  RAGAS_LIVE=1 pytest tests/test_ragas.py -v -s
  RAGAS_LIVE=1 KENVUE_API_URL=http://localhost:8002 pytest tests/test_ragas.py -v -s

Ground truths in ragas_dataset.json are illustrative placeholders.
Update them to match your actual loaded KB documents for meaningful
context_recall scores.

Thresholds (from checklist 3B.S3):
  faithfulness        >= 0.80
  answer_relevancy    >= 0.75
  context_recall      >= 0.70
  context_precision   >= 0.70
"""

# ── Vertex AI stub (ragas 0.4.3 / langchain-community 0.4.x compatibility) ──
# ragas.llms.base imports ChatVertexAI from langchain_community.chat_models.vertexai,
# which was removed in langchain-community 0.4.x (moved to langchain-google-vertexai).
# This stub lets ragas import cleanly without installing google-cloud SDKs.
import sys
from types import ModuleType as _ModuleType

if "langchain_community.chat_models.vertexai" not in sys.modules:
    _stub = _ModuleType("langchain_community.chat_models.vertexai")
    _stub.ChatVertexAI = None  # type: ignore[attr-defined]
    sys.modules["langchain_community.chat_models.vertexai"] = _stub

# ── Standard imports ──────────────────────────────────────────────────────────
import json
import os
import warnings
from pathlib import Path

import httpx
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")

# ── Configuration ──────────────────────────────────────────────────────────────
RAGAS_LIVE   = bool(os.environ.get("RAGAS_LIVE"))
API_URL      = os.environ.get("KENVUE_API_URL",    "http://localhost:8002")
OLLAMA_URL   = os.environ.get("OLLAMA_URL",         "http://localhost:11434")
CHAT_MODEL   = os.environ.get("OLLAMA_CHAT_MODEL",  "gemma4:latest")
EMBED_MODEL  = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3:latest")

DATASET_PATH = Path(__file__).parent / "ragas_dataset.json"

THRESHOLDS = {
    "faithfulness":     0.80,
    "answer_relevancy": 0.75,
    "context_recall":   0.70,
    "context_precision": 0.70,
}


# ── SSE stream collector ───────────────────────────────────────────────────────

def _call_chat(question: str) -> tuple[str, list[str]]:
    """POST to /chat, return (assembled answer, [retrieved chunk texts])."""
    r = httpx.post(
        f"{API_URL}/chat",
        json={"message": question, "history": [], "user_id": "ragas_eval"},
        headers={"x-consent-given": "true"},
        timeout=120.0,
    )
    r.raise_for_status()

    tokens: list[str] = []
    contexts: list[str] = []

    for line in r.text.split("\n"):
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except json.JSONDecodeError:
            continue

        ev_type = ev.get("type", "")
        if ev_type == "chunk":
            text = ev.get("content", "").strip()
            if text:
                contexts.append(text)
        elif ev_type == "token":
            tokens.append(ev.get("content", ""))

    return "".join(tokens), contexts


# ── Module-scoped evaluation fixture ──────────────────────────────────────────

@pytest.fixture(scope="module")
def ragas_results():
    """
    Run the full RAGAS evaluation once and return an EvaluationResult.
    Skips unless RAGAS_LIVE=1 is set.
    """
    if not RAGAS_LIVE:
        pytest.skip("Set RAGAS_LIVE=1 to run the RAGAS evaluation against a live stack.")

    from datasets import Dataset
    from ragas import evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )
    from langchain_ollama import ChatOllama, OllamaEmbeddings

    # Wrap Ollama models in the ragas adapter layer
    llm = LangchainLLMWrapper(ChatOllama(model=CHAT_MODEL, base_url=OLLAMA_URL))
    embeddings = LangchainEmbeddingsWrapper(
        OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
    )

    # Load question/ground_truth pairs
    dataset_raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    questions:     list[str]       = []
    answers:       list[str]       = []
    all_contexts:  list[list[str]] = []
    ground_truths: list[str]       = []

    print(f"\nCollecting responses from {API_URL} for {len(dataset_raw)} questions...")
    for item in dataset_raw:
        answer, contexts = _call_chat(item["question"])
        if not answer.strip() or not contexts:
            # Escalation path or empty-KB response — skip for RAGAS scoring
            print(f"  SKIP (no answer/contexts): {item['question'][:60]}")
            continue
        questions.append(item["question"])
        answers.append(answer)
        all_contexts.append(contexts)
        ground_truths.append(item["ground_truth"])
        print(f"  OK: {item['question'][:60]}")

    if not questions:
        pytest.skip(
            "No valid RAG responses collected. "
            "Ensure the KB has documents loaded (POST /documents/upload)."
        )

    # Build HuggingFace Dataset (compatible with old-style MetricWithLLM metrics)
    ds = Dataset.from_dict(
        {
            "question":     questions,
            "answer":       answers,
            "contexts":     all_contexts,
            "ground_truth": ground_truths,
        }
    )

    print(f"\nRunning RAGAS evaluation on {len(questions)} samples...")
    result = evaluate(
        dataset=ds,
        metrics=[faithfulness, answer_relevancy, context_recall, context_precision],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False,
        show_progress=True,
    )
    print(f"\nRAGAS scores: {result}")
    return result


# ── 3B.1–3B.4  Threshold tests ────────────────────────────────────────────────

@pytest.mark.skipif(not RAGAS_LIVE, reason="Requires RAGAS_LIVE=1 and a live stack")
class TestRagasMetrics:

    def test_3b_1_faithfulness(self, ragas_results):
        """3B.1 — Faithfulness ≥ 0.80 (answer is grounded in retrieved context, not hallucinated)."""
        score = float(ragas_results["faithfulness"])
        print(f"\nFaithfulness:     {score:.3f}  (threshold ≥ {THRESHOLDS['faithfulness']})")
        assert score >= THRESHOLDS["faithfulness"], (
            f"Faithfulness {score:.3f} < threshold {THRESHOLDS['faithfulness']} — "
            "model may be hallucinating content not present in retrieved chunks"
        )

    def test_3b_2_answer_relevancy(self, ragas_results):
        """3B.2 — Answer relevancy ≥ 0.75 (answer directly addresses the question asked)."""
        score = float(ragas_results["answer_relevancy"])
        print(f"\nAnswer Relevancy: {score:.3f}  (threshold ≥ {THRESHOLDS['answer_relevancy']})")
        assert score >= THRESHOLDS["answer_relevancy"], (
            f"Answer Relevancy {score:.3f} < threshold {THRESHOLDS['answer_relevancy']} — "
            "answers may be off-topic or too generic"
        )

    def test_3b_3_context_recall(self, ragas_results):
        """3B.3 — Context recall ≥ 0.70 (retrieved chunks cover the ground truth answer)."""
        score = float(ragas_results["context_recall"])
        print(f"\nContext Recall:   {score:.3f}  (threshold ≥ {THRESHOLDS['context_recall']})")
        assert score >= THRESHOLDS["context_recall"], (
            f"Context Recall {score:.3f} < threshold {THRESHOLDS['context_recall']} — "
            "retriever is missing relevant chunks; consider increasing top_k or improving embeddings"
        )

    def test_3b_4_context_precision(self, ragas_results):
        """3B.4 — Context precision ≥ 0.70 (retrieved chunks are mostly relevant, low noise)."""
        score = float(ragas_results["context_precision"])
        print(f"\nContext Precision: {score:.3f}  (threshold ≥ {THRESHOLDS['context_precision']})")
        assert score >= THRESHOLDS["context_precision"], (
            f"Context Precision {score:.3f} < threshold {THRESHOLDS['context_precision']} — "
            "retriever is returning noisy/irrelevant chunks; consider reducing top_k"
        )


# ── 3B.5–3B.8  Regression reminders (skipped, run manually before config changes) ──

@pytest.mark.skip(reason=(
    "3B.5 — Re-run with RAGAS_LIVE=1 after changing the top_k setting. "
    "Fewer chunks may drop context_recall below 0.70."
))
def test_3b_5_top_k_regression():
    """3B.5 — Changing top_k must not drop context_recall below threshold."""


@pytest.mark.skip(reason=(
    "3B.6 — Re-run with RAGAS_LIVE=1 after swapping the embedding model. "
    "New embedding space may shift precision/recall."
))
def test_3b_6_embedding_model_regression():
    """3B.6 — Embedding model swap must not shift precision or recall below thresholds."""


@pytest.mark.skip(reason=(
    "3B.7 — Re-run with RAGAS_LIVE=1 after editing the system_prompt in settings. "
    "Prompt change may reduce faithfulness."
))
def test_3b_7_system_prompt_regression():
    """3B.7 — system_prompt change must not reduce faithfulness below 0.80."""


@pytest.mark.skip(reason=(
    "3B.8 — Re-run with RAGAS_LIVE=1 after adding large new documents to the KB. "
    "New documents must not cause context_precision to drop below 0.70."
))
def test_3b_8_new_document_regression():
    """3B.8 — Adding KB documents must not cause context_precision to drop below 0.70."""
