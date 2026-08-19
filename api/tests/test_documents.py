"""
test_documents.py — Layer 8: document upload edge-case tests.

All tests run in-process via the ASGI test client (no real DB or Ollama).
The inject_mock_pool autouse fixture (conftest.py) supplies a MockPool/MockConn
for every test; upload tests additionally stub out Docling and ingest_document.
"""

import sys
import uuid
from datetime import datetime, timezone

import pytest

from helpers import CONSENT

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_DOC_ID = str(uuid.uuid4())
FAKE_MD = "# Vitamin D\n\nVitamin D is a fat-soluble vitamin essential for bone health."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def redirect_uploads(monkeypatch, tmp_path):
    """Redirect UPLOADS_DIR to a temp folder so tests never write to the real uploads/ tree."""
    import routers.documents as docs_mod
    monkeypatch.setattr(docs_mod, "UPLOADS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def mock_docling(monkeypatch):
    """
    Stub docling.document_converter.DocumentConverter so upload tests run
    without a real PDF and without the Docling heavy-weight dependency.
    Returns FAKE_MD from export_to_markdown().
    """
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
    """
    Stub routers.documents.ingest_document so no DB writes or Ollama embedding
    calls happen during upload tests.  Returns (FAKE_DOC_ID, False) by default.
    """
    async def _fake_ingest(**kwargs):
        return FAKE_DOC_ID, False

    monkeypatch.setattr("routers.documents.ingest_document", _fake_ingest)


@pytest.fixture
def upload_fixtures(redirect_uploads, mock_docling, mock_ingest):
    """Convenience fixture — activates all three upload stubs for happy-path tests."""
    pass  # return value unused; side effects come from the sub-fixtures


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pdf_upload(filename: str = "test.pdf", content: bytes = b"%%PDF-1.4 fake content"):
    """Return a files dict suitable for httpx multipart POST."""
    return {"file": (filename, content, "application/pdf")}


# ---------------------------------------------------------------------------
# Layer 8 — Upload
# ---------------------------------------------------------------------------

class TestUpload:

    async def test_8_1_valid_pdf_upload_returns_doc_id(
        self, app_client, upload_fixtures
    ):
        """8.1 — Minimal valid PDF → 200 with doc_id and correct filename."""
        r = await app_client.post(
            "/documents/upload",
            files=_pdf_upload(),
            data={"strategy": "heading"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["doc_id"] == FAKE_DOC_ID
        assert body["filename"] == "test.pdf"
        assert body["strategy"] == "heading"
        assert body["already_existed"] is False

    async def test_8_2_large_pdf_upload_succeeds(
        self, app_client, upload_fixtures
    ):
        """8.2 — Large file (1 MB) uploads and parses without error."""
        large_content = b"%%PDF-1.4 " + b"A" * (1024 * 1024)
        r = await app_client.post(
            "/documents/upload",
            files=_pdf_upload(content=large_content),
        )
        assert r.status_code == 200
        assert r.json()["doc_id"] == FAKE_DOC_ID

    async def test_8_3_docx_upload_succeeds(
        self, app_client, upload_fixtures
    ):
        """8.3 — .docx files are accepted (Docling handles them)."""
        r = await app_client.post(
            "/documents/upload",
            files={
                "file": (
                    "report.docx",
                    b"PK\x03\x04fake-docx-content",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert r.status_code == 200
        assert r.json()["filename"] == "report.docx"

    async def test_8_4_txt_upload_succeeds(
        self, app_client, upload_fixtures
    ):
        """8.4 — Plain-text files are accepted (Docling can parse them)."""
        r = await app_client.post(
            "/documents/upload",
            files={"file": ("notes.txt", b"Vitamin D overview.", "text/plain")},
        )
        assert r.status_code == 200
        assert r.json()["filename"] == "notes.txt"

    @pytest.mark.xfail(
        reason=(
            "FINDING 8.5: No MIME-type validation — a ZIP file with .pdf extension "
            "passes to Docling unchecked. Fix: add python-magic sniffing before parsing."
        )
    )
    async def test_8_5_mime_mismatch_rejected(
        self, app_client, redirect_uploads, mock_ingest, monkeypatch
    ):
        """
        8.5 — File with .pdf extension but ZIP magic bytes should be rejected at the
        gateway with 400 before Docling is invoked.

        Current behaviour: the file is passed straight to Docling, which either
        parses it (200) or returns a Docling-level error (422).  Neither is a
        deliberate content-type rejection.
        """
        # Do NOT mock Docling — we want it to attempt to parse the fake ZIP
        zip_bytes = b"PK\x03\x04" + b"\x00" * 100

        r = await app_client.post(
            "/documents/upload",
            files={"file": ("fake.pdf", zip_bytes, "application/pdf")},
        )
        assert r.status_code == 400, (
            f"Expected 400 MIME validation error, got {r.status_code}. "
            "Add MIME sniffing (e.g. python-magic) to reject non-PDF content."
        )

    @pytest.mark.xfail(
        reason=(
            "FINDING 8.6: No upload size limit — files larger than 50 MB are accepted "
            "without a 413 response. Fix: add "
            "`if len(raw_bytes) > MAX_UPLOAD_BYTES: raise HTTPException(413)` "
            "before the Docling call."
        )
    )
    async def test_8_6_oversized_file_rejected(
        self, app_client, upload_fixtures
    ):
        """8.6 — File > 50 MB should return 413 (Request Entity Too Large)."""
        big_content = b"%%PDF-1.4 " + b"X" * (51 * 1024 * 1024)  # 51 MB
        r = await app_client.post(
            "/documents/upload",
            files=_pdf_upload(content=big_content),
        )
        assert r.status_code == 413, (
            f"Expected 413 for oversized upload, got {r.status_code}."
        )

    async def test_8_7_zero_byte_file_yields_422(
        self, app_client, redirect_uploads, monkeypatch
    ):
        """8.7 — Empty file triggers Docling failure → 422 with 'Docling parse failed'."""
        class _FailConverter:
            def convert(self, path: str):
                raise ValueError("Cannot parse empty file: no content found")

        class _FailModule:
            DocumentConverter = _FailConverter

        monkeypatch.setitem(sys.modules, "docling.document_converter", _FailModule())

        r = await app_client.post(
            "/documents/upload",
            files=_pdf_upload(content=b""),
        )
        assert r.status_code == 422
        assert "Docling parse failed" in r.json()["detail"]

    async def test_8_8_duplicate_upload_returns_already_existed(
        self, app_client, redirect_uploads, mock_docling, monkeypatch
    ):
        """8.8 — Uploading the same file twice returns already_existed = True."""
        async def _already_exists(**kwargs):
            return FAKE_DOC_ID, True

        monkeypatch.setattr("routers.documents.ingest_document", _already_exists)

        r = await app_client.post(
            "/documents/upload",
            files=_pdf_upload(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["already_existed"] is True
        assert body["doc_id"] == FAKE_DOC_ID

    @pytest.mark.xfail(
        reason=(
            "FINDING 8.9: Filename not sanitised — path-traversal sequences "
            "(`../../etc/passwd.pdf`) are stored verbatim in safe_name. "
            "Fix: `safe_name = f\"{doc_hash}_{Path(file.filename).name}\"`"
        )
    )
    async def test_8_9_path_traversal_filename_sanitised(
        self, app_client, upload_fixtures, tmp_path
    ):
        """
        8.9 — A filename containing path-traversal sequences must be stripped to just
        the basename before being written to disk.  All saved files must stay within
        the uploads tree.
        """
        import routers.documents as docs_mod

        r = await app_client.post(
            "/documents/upload",
            files={"file": ("../../etc/passwd.pdf", b"%%PDF-1.4 content", "application/pdf")},
        )
        assert r.status_code == 200

        # Every file created during this test must be under UPLOADS_DIR
        uploads_root = docs_mod.UPLOADS_DIR
        for f in uploads_root.rglob("*"):
            if f.is_file():
                assert uploads_root in f.parents, (
                    f"File escaped uploads tree: {f}"
                )

    async def test_8_10_unicode_filename_handled(
        self, app_client, upload_fixtures
    ):
        """8.10 — Unicode characters and spaces in filenames are stored and returned correctly."""
        unicode_name = "Vitamin D Übersicht.pdf"
        r = await app_client.post(
            "/documents/upload",
            files={"file": (unicode_name, b"%%PDF-1.4 content", "application/pdf")},
        )
        assert r.status_code == 200
        assert r.json()["filename"] == unicode_name


# ---------------------------------------------------------------------------
# Layer 8 — CRUD (list, delete, get chunks)
# ---------------------------------------------------------------------------

class TestDocumentCRUD:

    async def test_8_11_delete_removes_doc_and_chunks(
        self, app_client, mock_conn
    ):
        """
        8.11 — DELETE /documents/{doc_id} issues DELETE statements for both
        rag_chunks and rag_documents and returns {"status": "deleted"}.
        """
        doc_id = str(uuid.uuid4())
        mock_conn._execute_return = "DELETE 1"

        r = await app_client.delete(f"/documents/{doc_id}")

        assert r.status_code == 200
        assert r.json() == {"status": "deleted"}

        queries = [call[1].lower() for call in mock_conn.execute_calls if call[0] == "execute"]
        assert any("rag_chunks" in q for q in queries), (
            "Expected DELETE FROM rag_chunks in execute_calls"
        )
        assert any("rag_documents" in q for q in queries), (
            "Expected DELETE FROM rag_documents in execute_calls"
        )

    async def test_8_12_delete_nonexistent_doc_returns_404(
        self, app_client, mock_conn
    ):
        """8.12 — DELETE on a non-existent doc_id returns 404."""
        doc_id = str(uuid.uuid4())
        mock_conn._execute_return = "DELETE 0"

        r = await app_client.delete(f"/documents/{doc_id}")

        assert r.status_code == 404

    async def test_8_13_get_chunks_returns_stored_chunks(
        self, app_client, mock_conn
    ):
        """8.13 — GET /documents/{doc_id}/chunks returns the stored chunk array."""
        doc_id = str(uuid.uuid4())
        chunk_id = str(uuid.uuid4())

        mock_conn.configure_fetch(
            "rag_chunks",
            [
                {
                    "id": chunk_id,
                    "chunk_index": 0,
                    "section_heading": "Overview",
                    "content": "Vitamin D is essential for bone health.",
                }
            ],
        )

        r = await app_client.get(f"/documents/{doc_id}/chunks")

        assert r.status_code == 200
        chunks = r.json()
        assert len(chunks) == 1
        assert chunks[0]["id"] == chunk_id
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["section_heading"] == "Overview"
        assert chunks[0]["content"] == "Vitamin D is essential for bone health."


# ---------------------------------------------------------------------------
# Screenshot / vision OCR upload
# ---------------------------------------------------------------------------

FAKE_SCREENSHOT_MD = (
    "# Scheduled maintenance\n\n"
    "Database downtime **Saturday 6pm – Sunday 6am UTC** this weekend."
)


@pytest.fixture
def mock_vision(monkeypatch):
    async def _fake(image_bytes, **kwargs):
        return FAKE_SCREENSHOT_MD

    monkeypatch.setattr("routers.documents.image_to_text", _fake)


@pytest.fixture
def screenshot_fixtures(redirect_uploads, mock_vision, mock_ingest):
    pass


def _png_upload(filename: str = "maintenance.png", content: bytes = b"\x89PNG\r\n\x1a\nfake"):
    return {"file": (filename, content, "image/png")}


class TestScreenshotUpload:

    async def test_screenshot_extract_returns_preview(
        self, app_client, screenshot_fixtures
    ):
        r = await app_client.post(
            "/documents/screenshot/extract",
            files=_png_upload(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["extracted_text"] == FAKE_SCREENSHOT_MD
        assert body["strategy"] == "sentence"
        assert body["filename"] == "maintenance.png"
        assert "doc_hash" in body

    async def test_screenshot_extract_rejects_non_image(
        self, app_client, redirect_uploads
    ):
        r = await app_client.post(
            "/documents/screenshot/extract",
            files=_pdf_upload("not-a-screenshot.pdf"),
        )
        assert r.status_code == 400

    async def test_screenshot_confirm_indexes_text(
        self, app_client, screenshot_fixtures, mock_conn
    ):
        mock_conn.configure_fetchval("chunk_count", 2)

        extract = await app_client.post(
            "/documents/screenshot/extract",
            files=_png_upload(),
        )
        assert extract.status_code == 200
        meta = extract.json()

        r = await app_client.post(
            "/documents/screenshot/confirm",
            json={
                "doc_hash": meta["doc_hash"],
                "filename": meta["filename"],
                "markdown_text": meta["extracted_text"],
                "strategy": "sentence",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["doc_id"] == FAKE_DOC_ID
        assert body["strategy"] == "sentence"
        assert body["chunk_count"] == 2

    async def test_screenshot_confirm_missing_file_404(
        self, app_client, redirect_uploads, mock_ingest
    ):
        r = await app_client.post(
            "/documents/screenshot/confirm",
            json={
                "doc_hash": "abc123deadbeef",
                "filename": "missing.png",
                "markdown_text": "Some text",
                "strategy": "sentence",
            },
        )
        assert r.status_code == 404

