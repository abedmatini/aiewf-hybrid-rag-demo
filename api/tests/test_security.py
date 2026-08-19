"""
Layer 5 — Security tests.
Covers checklist items 5.1–5.16: injection, file upload security, CORS, auth/consent bypass.

All tests run in-process against the FastAPI ASGI app (no real server needed).
The autouse `inject_mock_pool` fixture from conftest ensures every test uses the mock DB.

FINDINGS are marked with @pytest.mark.xfail(strict=False) — they document a known gap
that should be addressed before go-live but do not block the CI pipeline.
"""

import io
import sys
from pathlib import Path

import httpx
import pytest

from helpers import CONSENT, FAKE_SETTINGS_ROWS, OLLAMA_STREAM_NDJSON, parse_sse, event_types

CHAT_BODY_TMPL = {"message": "What is vitamin D?", "history": [], "user_id": "test_user"}
SMALL_PDF_BYTES = b"%PDF-1.4 malformed pdf content for testing"
MULTIPART_CT = "multipart/form-data"


# ---------------------------------------------------------------------------
# Shared monkeypatch helpers (same as test_api.py)
# ---------------------------------------------------------------------------

def _noop_llm_no(monkeypatch):
    from guardrails import GuardrailResult
    async def _no(*a, **kw): return GuardrailResult(blocked=False, reason="")
    monkeypatch.setattr("guardrails.check_medical_llm", _no)


def _patch_retrieve(monkeypatch, chunks=None):
    async def _retrieve(*a, **kw): return chunks or []
    monkeypatch.setattr("routers.chat.retrieve", _retrieve)


# ---------------------------------------------------------------------------
# Upload support fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def redirect_uploads(monkeypatch, tmp_path):
    """Redirect UPLOADS_DIR to a pytest tmp_path so no files pollute the repo."""
    monkeypatch.setattr("routers.documents.UPLOADS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def mock_docling(monkeypatch):
    """Patch DocumentConverter so it succeeds without loading an ML model."""
    import sys

    class _MockResult:
        class document:
            @staticmethod
            def export_to_markdown():
                return "# Mocked\n\nContent."

    class _MockConverter:
        def convert(self, path):
            return _MockResult()

    dc = sys.modules.get("docling.document_converter")
    if dc is not None:
        monkeypatch.setattr(dc, "DocumentConverter", _MockConverter)


@pytest.fixture
def mock_ingest(monkeypatch):
    """Stub routers.documents.ingest_document to return a fake doc_id."""
    import uuid
    captured = {}

    async def _ingest(*, pool, user_id, filename, doc_hash,
                      file_path, markdown_text, is_persistent, ollama_url, strategy):
        captured.update({"file_path": Path(file_path), "filename": filename})
        return (str(uuid.uuid4()), False)

    monkeypatch.setattr("routers.documents.ingest_document", _ingest)
    return captured


# ---------------------------------------------------------------------------
# 5.1–5.5  Injection
# ---------------------------------------------------------------------------

class TestInjection:
    """CHECKLIST: 5.1–5.5"""

    @pytest.fixture(autouse=True)
    def _setup_chat_mocks(self, monkeypatch, respx_mock, mock_conn):
        """Common mocks for injection chat tests: no-op LLM, empty retrieve, Ollama mock."""
        _noop_llm_no(monkeypatch)
        _patch_retrieve(monkeypatch, [])
        mock_conn._fetchval_default = None  # empty KB path
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=OLLAMA_STREAM_NDJSON)
        )

    async def test_5_1_sql_injection_in_message_does_not_crash(
        self, app_client, mock_conn
    ):
        """5.1 — SQL injection string in message → server responds (no crash, no DB error)."""
        body = {**CHAT_BODY_TMPL, "message": "'; DROP TABLE chat_logs; --"}
        r = await app_client.post("/chat", json=body, headers=CONSENT)
        assert r.status_code == 200
        events = parse_sse(r.text)
        assert "done" in event_types(events)

    async def test_5_1b_sql_injection_message_is_parameterized(
        self, app_client, mock_conn
    ):
        """5.1b — The injected message is stored as a parameterized $2 value, not interpolated."""
        injection = "'; DROP TABLE chat_logs; --"
        await app_client.post(
            "/chat", json={**CHAT_BODY_TMPL, "message": injection}, headers=CONSENT
        )
        inserts = [
            c for c in mock_conn.execute_calls
            if c[0] == "execute" and "INSERT INTO chat_logs" in c[1]
        ]
        assert inserts, "Expected an INSERT INTO chat_logs"
        # The injection string should appear in the positional args, NOT in the query template
        query_str = inserts[0][1]
        args = inserts[0][2]
        assert injection not in query_str, "SQL injection leaked into the query template"
        assert injection in args, "Injected value should appear in parameterized args"

    async def test_5_2_xss_in_message_not_reflected_as_html(self, app_client):
        """5.2 — XSS payload in message → response is SSE/JSON, no raw HTML echoed back."""
        body = {**CHAT_BODY_TMPL, "message": "<script>alert(1)</script>"}
        r = await app_client.post("/chat", json=body, headers=CONSENT)
        assert r.status_code == 200
        # The content-type is text/event-stream (not text/html)
        assert "html" not in r.headers.get("content-type", "").lower()
        # The raw script tag should not appear as unescaped HTML in a JSON field
        # (it would only appear inside a valid JSON string, properly escaped)
        for event in parse_sse(r.text):
            content = event.get("content", "")
            assert "<script>" not in content, (
                "XSS payload echoed back in SSE content — potential reflected XSS"
            )

    async def test_5_3_sql_injection_in_user_id_is_parameterized(
        self, app_client, mock_conn
    ):
        """5.3 — SQL injection in user_id → treated as a literal string, not executed."""
        malicious_id = "admin' OR '1'='1"
        await app_client.post(
            "/chat",
            json={**CHAT_BODY_TMPL, "user_id": malicious_id},
            headers=CONSENT,
        )
        inserts = [
            c for c in mock_conn.execute_calls
            if c[0] == "execute" and "INSERT INTO chat_logs" in c[1]
        ]
        assert inserts
        query_str = inserts[0][1]
        args = inserts[0][2]
        assert malicious_id not in query_str, "user_id leaked into the query template"
        assert malicious_id in args, "user_id should appear only in parameterized args"

    async def test_5_4_path_traversal_in_user_id_is_literal(
        self, app_client, mock_conn
    ):
        """5.4 — Path-traversal string in user_id → stored as-is, no file I/O attempted."""
        traversal_id = "../../../etc/passwd"
        r = await app_client.post(
            "/chat",
            json={**CHAT_BODY_TMPL, "user_id": traversal_id},
            headers=CONSENT,
        )
        assert r.status_code == 200
        inserts = [
            c for c in mock_conn.execute_calls
            if c[0] == "execute" and "INSERT INTO chat_logs" in c[1]
        ]
        assert inserts
        # user_id is $1 — verify it's in the positional args as a literal string
        args = inserts[0][2]
        assert traversal_id in args, "user_id must be stored as a parameterized literal"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "FINDING 5.5: No max_length validation on ChatRequest.message. "
            "100 000-char inputs are processed without error. "
            "Add: message: str = Field(..., max_length=10_000) in ChatRequest."
        ),
    )
    async def test_5_5_very_large_message_rejected(self, app_client):
        """5.5 — 100 000-char message should be rejected with 422 (currently processed as 200)."""
        body = {**CHAT_BODY_TMPL, "message": "A" * 100_000}
        r = await app_client.post("/chat", json=body, headers=CONSENT)
        assert r.status_code == 422, (
            f"Expected 422 for oversized message, got {r.status_code}. "
            "Implement Field(max_length=...) on ChatRequest.message."
        )


# ---------------------------------------------------------------------------
# 5.6–5.10  File upload security
# ---------------------------------------------------------------------------

class TestFileUploadSecurity:
    """CHECKLIST: 5.6–5.10"""

    async def test_5_6_exe_upload_rejected(self, app_client, redirect_uploads, mock_ingest):
        """5.6 — .exe upload → rejected (Docling cannot parse binary, returns 422)."""
        exe_bytes = b"MZ\x90\x00\x03\x00fake-pe-header"  # PE header magic bytes
        r = await app_client.post(
            "/documents/upload",
            files={"file": ("malware.exe", io.BytesIO(exe_bytes), "application/octet-stream")},
            data={"strategy": "heading"},
        )
        assert r.status_code in (400, 422), (
            f"Expected 400/422 for .exe upload, got {r.status_code}. "
            "FINDING: no explicit extension allowlist; relies on Docling failure."
        )

    async def test_5_7_pdf_extension_html_content_rejected(
        self, app_client, redirect_uploads, mock_ingest
    ):
        """5.7 — .pdf extension with HTML content → rejected via Docling failure (422)."""
        html_bytes = b"<html><body><h1>Not a PDF</h1></body></html>"
        r = await app_client.post(
            "/documents/upload",
            files={"file": ("document.pdf", io.BytesIO(html_bytes), "application/pdf")},
            data={"strategy": "heading"},
        )
        # Docling will fail on non-PDF bytes → 422
        # FINDING: validation is implicit (Docling-dependent), no explicit MIME check
        assert r.status_code in (400, 422), (
            f"Expected 400/422 for MIME mismatch upload, got {r.status_code}. "
            "FINDING: no explicit MIME validation before Docling is invoked."
        )

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "FINDING 5.8: No upload size limit enforced. "
            "A large file is processed (or causes OOM) rather than being rejected with 413. "
            "Add a FastAPI body size limit or validate len(raw_bytes) before processing."
        ),
    )
    async def test_5_8_large_file_rejected_413(
        self, app_client, redirect_uploads, mock_docling, mock_ingest
    ):
        """5.8 — File larger than allowed limit should return 413 (currently processed)."""
        # 11 MB — exceeds a reasonable 10 MB limit
        large_bytes = b"%PDF-1.4 " + b"A" * (11 * 1024 * 1024)
        r = await app_client.post(
            "/documents/upload",
            files={"file": ("big.pdf", io.BytesIO(large_bytes), "application/pdf")},
            data={"strategy": "heading"},
        )
        assert r.status_code == 413, (
            f"Expected 413 for oversized upload, got {r.status_code}. "
            "Implement a size check: if len(raw_bytes) > MAX_UPLOAD_BYTES: raise HTTPException(413)."
        )

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "FINDING 5.9: Filename is not sanitised before constructing the save path. "
            "A path-traversal filename (e.g. ../../etc/passwd.pdf) causes the server "
            "to crash with a FileNotFoundError (500) because the intermediate "
            "directory does not exist. Fix: use Path(file.filename).name to strip "
            "all directory components before building safe_name."
        ),
    )
    async def test_5_9_path_traversal_filename_rejected(
        self, app_client, redirect_uploads, mock_docling, mock_ingest
    ):
        """5.9 — Path-traversal filename → server should reject with 400 (currently 500)."""
        r = await app_client.post(
            "/documents/upload",
            files={
                "file": (
                    "../../etc/passwd.pdf",
                    io.BytesIO(b"%PDF-1.4 traversal test"),
                    "application/pdf",
                )
            },
            data={"strategy": "heading"},
        )
        assert r.status_code == 400, (
            f"Expected 400 for path-traversal filename, got {r.status_code}. "
            "Fix: sanitise filename with Path(file.filename).name before use."
        )

    async def test_5_9b_path_traversal_stays_within_uploads(self, tmp_path):
        """5.9b — Even without sanitisation, the resolved path stays within uploads tree."""
        from pathlib import Path as P
        uploads_dir = tmp_path / "uploads" / "faq_kb"
        uploads_dir.mkdir(parents=True)

        # Simulate what documents.py does
        doc_hash = "abc123def456789a"
        filename = "../../etc/passwd.pdf"
        safe_name = f"{doc_hash}_{filename}"
        file_path = uploads_dir / safe_name

        # Lexical resolve — path stays within uploads_dir's parent tree
        # (hash prefix prevents escaping above uploads/ root)
        uploads_root = (tmp_path / "uploads").resolve()
        # The worst-case resolved path: hash_.. goes back to faq_kb, .. goes to uploads/
        # → still within uploads_root
        resolved = Path(str(file_path)).resolve()
        assert str(resolved).startswith(str(uploads_root)), (
            f"Path traversal escaped uploads_root!\n"
            f"  file_path:     {file_path}\n"
            f"  resolved:      {resolved}\n"
            f"  uploads_root:  {uploads_root}"
        )

    async def test_5_10_zero_byte_file_rejected(
        self, app_client, redirect_uploads, mock_ingest
    ):
        """5.10 — Zero-byte file upload → rejected (Docling fails on empty input, 422)."""
        r = await app_client.post(
            "/documents/upload",
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
            data={"strategy": "heading"},
        )
        assert r.status_code in (400, 422), (
            f"Expected 400/422 for zero-byte upload, got {r.status_code}."
        )


# ---------------------------------------------------------------------------
# 5.11–5.13  CORS & security headers
# ---------------------------------------------------------------------------

class TestCorsAndHeaders:
    """CHECKLIST: 5.11–5.13"""

    async def test_5_11_disallowed_origin_no_acao_header(self, app_client):
        """5.11 — OPTIONS from a disallowed origin → no Access-Control-Allow-Origin header."""
        r = await app_client.options(
            "/chat",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-consent-given",
            },
        )
        acao = r.headers.get("access-control-allow-origin", "")
        assert "evil.com" not in acao, (
            f"Disallowed origin 'evil.com' reflected in ACAO header: {acao!r}"
        )

    async def test_5_12_allowed_origin_gets_acao_header(self, app_client):
        """5.12 — OPTIONS from http://localhost:5173 → ACAO header is present and correct."""
        r = await app_client.options(
            "/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-consent-given",
            },
        )
        acao = r.headers.get("access-control-allow-origin", "")
        assert "localhost:5173" in acao, (
            f"Expected ACAO to contain 'localhost:5173', got: {acao!r}"
        )

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "FINDING 5.13: FastAPI does not add X-Content-Type-Options: nosniff by default. "
            "Add a SecurityHeadersMiddleware or custom response middleware to include "
            "this and other OWASP-recommended security headers."
        ),
    )
    async def test_5_13_x_content_type_options_nosniff(self, app_client):
        """5.13 — API responses should include X-Content-Type-Options: nosniff."""
        r = await app_client.get("/health")
        xcto = r.headers.get("x-content-type-options", "")
        assert xcto.lower() == "nosniff", (
            f"Missing/wrong X-Content-Type-Options header. Got: {xcto!r}. "
            "Add a middleware that sets this header on every response."
        )


# ---------------------------------------------------------------------------
# 5.14–5.16  Authentication & consent bypass
# ---------------------------------------------------------------------------

class TestAuthAndConsentBypass:
    """CHECKLIST: 5.14–5.16"""

    async def test_5_14_analytics_delete_unauthenticated(self, app_client, mock_conn):
        """
        5.14 — DELETE /analytics/user/{id}/data requires NO authentication.
        DESIGN DECISION (documented): This endpoint is intentionally public in the
        current MVP. Add bearer-token auth before production deployment.
        """
        mock_conn._execute_return = "DELETE 0"
        r = await app_client.delete("/analytics/user/any_user/data")
        # We are asserting the CURRENT behavior (200) — not that this is secure.
        # This test documents the gap so it can be tracked.
        assert r.status_code == 200, (
            "Expected 200 (currently no auth). "
            "NOTE: Add authentication to this endpoint before go-live."
        )

    async def test_5_15_settings_put_unauthenticated(self, app_client):
        """
        5.15 — PUT /settings requires NO authentication.
        DESIGN DECISION (documented): Intentionally public in the current MVP.
        Add bearer-token auth before production deployment.
        """
        payload = {
            "chat_model": "gemma4:latest",
            "top_k": 5,
            "system_prompt": "Updated.",
            "escalation_message": "Updated.",
            "agent_mode": False,
            "agent_model": "qwen2.5:7b-instruct",
        }
        r = await app_client.put("/settings", json=payload)
        assert r.status_code == 200, (
            "Expected 200 (currently no auth). "
            "NOTE: Add authentication to this endpoint before go-live."
        )

    async def test_5_16_consent_header_case_sensitive(self, app_client):
        """5.16 — x-consent-given: TRUE (uppercase) → 403 (header check is case-sensitive)."""
        r = await app_client.post(
            "/chat",
            json={**CHAT_BODY_TMPL, "message": "What is vitamin D?"},
            headers={"x-consent-given": "TRUE"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "consent_required"

    async def test_5_16b_consent_header_mixed_case_rejected(self, app_client):
        """5.16b — x-consent-given: True (title case) → 403."""
        r = await app_client.post(
            "/chat",
            json={**CHAT_BODY_TMPL, "message": "What is vitamin D?"},
            headers={"x-consent-given": "True"},
        )
        assert r.status_code == 403

    async def test_5_16c_consent_header_with_whitespace_rejected(self, app_client):
        """5.16c — x-consent-given: ' true' (leading space) → 403."""
        r = await app_client.post(
            "/chat",
            json={**CHAT_BODY_TMPL, "message": "What is vitamin D?"},
            headers={"x-consent-given": " true"},
        )
        assert r.status_code == 403
