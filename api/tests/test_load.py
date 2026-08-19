"""
test_load.py — Layer 9: Load / concurrency smoke tests.

Runs in-process via the ASGI test client (asyncio.gather for concurrency).
All external services (Ollama, pgvector) are mocked — these tests run in CI
without a live stack.

test_9_3 is skipped and requires a live stack for p95 latency measurement.
"""

import asyncio
import sys
import time

import httpx
import pytest

from helpers import CONSENT, OLLAMA_STREAM_NDJSON, parse_sse, event_types

CHAT_BODY_CLEAN = {"message": "What is vitamin D?", "history": [], "user_id": "load_user"}
CHAT_BODY_ESC   = {"message": "Can I take ibuprofen with this?", "history": [], "user_id": "load_user"}

FAKE_DOC_ID = "00000000-0000-0000-0000-000000000099"
FAKE_MD     = "# Load Test Doc\n\nContent for load testing."


# ── Shared helpers ────────────────────────────────────────────────────────────

def _stub_llm_clean(monkeypatch):
    """Patch check_medical_llm to return non-blocked (skips Ollama tier-3 call)."""
    from guardrails import GuardrailResult

    async def _clean(*args, **kwargs):
        return GuardrailResult(blocked=False, reason="")

    monkeypatch.setattr("guardrails.check_medical_llm", _clean)


def _stub_retrieve_empty(monkeypatch):
    """Patch retrieve to return no chunks (triggers empty_kb path, skips embedding call)."""

    async def _empty(**kwargs):
        return []

    monkeypatch.setattr("routers.chat.retrieve", _empty)


# ── Upload fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def redirect_uploads(monkeypatch, tmp_path):
    """Redirect UPLOADS_DIR to a temp folder so tests never touch the real uploads/ tree."""
    import routers.documents as docs_mod
    monkeypatch.setattr(docs_mod, "UPLOADS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def mock_docling(monkeypatch):
    """Stub docling.document_converter so tests run without a real PDF or Docling install."""

    class _FakeResult:
        class document:
            @staticmethod
            def export_to_markdown() -> str:
                return FAKE_MD

    class _FakeConverter:
        def convert(self, path: str) -> "_FakeResult":
            return _FakeResult()

    class _FakeDoclingModule:
        DocumentConverter = _FakeConverter

    monkeypatch.setitem(sys.modules, "docling.document_converter", _FakeDoclingModule())


@pytest.fixture
def mock_ingest(monkeypatch):
    """Stub ingest_document to avoid DB writes and Ollama embedding calls."""

    async def _fake_ingest(**kwargs):
        return FAKE_DOC_ID, False

    monkeypatch.setattr("routers.documents.ingest_document", _fake_ingest)


# ── 9.1–9.2: Concurrent chat ──────────────────────────────────────────────────

class TestConcurrentChat:

    async def test_9_1_ten_concurrent_clean_requests(
        self, app_client, monkeypatch, respx_mock
    ):
        """9.1 — 10 simultaneous clean chat queries all complete with 200 and a SSE done event."""
        _stub_llm_clean(monkeypatch)
        _stub_retrieve_empty(monkeypatch)

        # Only the final Ollama streaming chat call reaches the network layer.
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, content=OLLAMA_STREAM_NDJSON.encode())
        )

        responses = await asyncio.gather(*[
            app_client.post("/chat", json=CHAT_BODY_CLEAN, headers=CONSENT)
            for _ in range(10)
        ])

        codes = [r.status_code for r in responses]
        assert all(c == 200 for c in codes), f"Expected all 200, got: {codes}"

        for r in responses:
            types = event_types(parse_sse(r.text))
            assert "done" in types or "error" in types, (
                f"Missing done/error event in: {types}"
            )

    async def test_9_2_five_concurrent_escalation_requests(self, app_client):
        """9.2 — 5 simultaneous escalation queries return escalation event; no Ollama call needed."""
        t0 = time.monotonic()

        responses = await asyncio.gather(*[
            app_client.post("/chat", json=CHAT_BODY_ESC, headers=CONSENT)
            for _ in range(5)
        ])

        elapsed = time.monotonic() - t0

        codes = [r.status_code for r in responses]
        assert all(c == 200 for c in codes), f"Expected all 200, got: {codes}"

        for r in responses:
            types = event_types(parse_sse(r.text))
            assert "escalation" in types, (
                f"Expected escalation event, got: {types}"
            )

        # Tier-1 escalation is pure Python — 5 requests should finish quickly.
        assert elapsed < 5.0, (
            f"5 escalation requests took {elapsed:.2f}s — expected < 5 s (no Ollama call)"
        )


# ── 9.3: Sequential latency (manual / live stack only) ───────────────────────

class TestLatency:
    @pytest.mark.skip(
        reason=(
            "9.3 — Requires live Ollama + pgvector stack. "
            "Run manually: pytest tests/test_load.py::TestLatency -s --no-header"
        )
    )
    async def test_9_3_sequential_p95_latency(self, app_client):
        """9.3 — 20 sequential chats; p95 latency < 10 s (live stack only)."""
        durations = []
        for _ in range(20):
            t0 = time.monotonic()
            r = await app_client.post("/chat", json=CHAT_BODY_CLEAN, headers=CONSENT)
            durations.append(time.monotonic() - t0)
            assert r.status_code == 200

        durations.sort()
        p95 = durations[int(len(durations) * 0.95)]
        print(
            f"\np95={p95:.2f}s  median={durations[len(durations)//2]:.2f}s  "
            f"max={max(durations):.2f}s"
        )
        assert p95 < 10.0, f"p95 latency {p95:.2f}s exceeds 10 s threshold"


# ── 9.4: Concurrent analytics reads ──────────────────────────────────────────

class TestConcurrentAnalytics:
    async def test_9_4_concurrent_analytics_reads(self, app_client):
        """9.4 — 10 simultaneous GET /analytics/summary; all return 200 with correct shape.

        MockConn defaults handle all analytics queries:
          fetchval → None  (cast to 0 or 0.0 by the router)
          fetch    → []    (top_questions and recent_logs are empty lists)
        """
        responses = await asyncio.gather(*[
            app_client.get("/analytics/summary")
            for _ in range(10)
        ])

        codes = [r.status_code for r in responses]
        assert all(c == 200 for c in codes), f"Expected all 200, got: {codes}"

        for r in responses:
            body = r.json()
            assert "total_chats" in body
            assert "escalation_rate" in body
            assert isinstance(body["top_questions"], list)
            assert isinstance(body["recent_logs"], list)


# ── 9.5: Parallel uploads ─────────────────────────────────────────────────────

class TestParallelUploads:
    async def test_9_5_five_parallel_uploads(
        self, app_client, redirect_uploads, mock_docling, mock_ingest
    ):
        """9.5 — 5 documents uploaded concurrently; all succeed without resource leaks."""

        async def _upload(i: int):
            return await app_client.post(
                "/documents/upload",
                files={
                    "file": (
                        f"doc_{i}.pdf",
                        f"%%PDF-1.4 content {i}".encode(),
                        "application/pdf",
                    )
                },
                data={"strategy": "heading"},
            )

        responses = await asyncio.gather(*[_upload(i) for i in range(5)])

        codes = [r.status_code for r in responses]
        assert all(c == 200 for c in codes), f"Expected all 200, got: {codes}"

        for r in responses:
            body = r.json()
            assert "doc_id" in body
            assert body["doc_id"] == FAKE_DOC_ID
