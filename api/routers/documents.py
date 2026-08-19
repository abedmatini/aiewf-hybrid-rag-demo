"""
Documents router — upload, list, archive, restore, delete, view/edit chunks.

POST   /documents/upload                 multipart file upload → Docling → ingest
POST   /documents/screenshot/extract       image → vision OCR → preview text
POST   /documents/screenshot/confirm       index reviewed screenshot text
GET    /documents                          list all KB documents
GET    /documents/{id}/chunks              list all chunks for a document
PUT    /documents/{id}/chunks/{cid}        update chunk text + re-embed
PATCH  /documents/{id}/archive             set status=archived
PATCH  /documents/{id}/restore             set status=active
DELETE /documents/{id}                     permanently remove doc + chunks
"""
import hashlib
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from db import get_pool, KB_USER_ID
from rag import (
    STRATEGIES,
    archive_document,
    delete_document,
    embed_texts,
    ingest_document,
    list_documents,
    restore_document,
)
from vision import VISION_MODEL, image_to_text

router = APIRouter()

OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
UPLOADS_DIR  = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_SCREENSHOT_BYTES = 15 * 1024 * 1024


def _kb_upload_dir() -> Path:
    d = UPLOADS_DIR / KB_USER_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_stored_name(doc_hash: str, filename: str) -> str:
    return f"{doc_hash}_{Path(filename).name}"


def _stored_image_path(doc_hash: str, filename: str) -> Path:
    return _kb_upload_dir() / _safe_stored_name(doc_hash, filename)


def _validate_image_upload(filename: str | None, content_type: str | None) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
        raise HTTPException(400, f"Unsupported image type. Allowed: {allowed}")
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")


async def _chunk_count(pool, doc_id: str) -> int:
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT chunk_count FROM rag_documents WHERE id = $1",
            doc_id,
        )
    return int(count or 0)


async def _ingest_and_response(
    *,
    pool,
    filename: str,
    doc_hash: str,
    file_path: Path,
    markdown: str,
    strategy: str,
) -> dict:
    md_path = file_path.with_suffix(file_path.suffix + ".md")
    md_path.write_text(markdown, encoding="utf-8")

    doc_id, already_existed = await ingest_document(
        pool=pool,
        user_id=KB_USER_ID,
        filename=filename,
        doc_hash=doc_hash,
        file_path=str(file_path),
        markdown_text=markdown,
        is_persistent=True,
        ollama_url=OLLAMA_URL,
        strategy=strategy,
    )
    return {
        "doc_id": doc_id,
        "filename": filename,
        "strategy": strategy,
        "already_existed": already_existed,
        "chunk_count": await _chunk_count(pool, doc_id),
    }


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    strategy: str = Form("heading"),
):
    """Accept a file, parse to Markdown with Docling, ingest into KB namespace."""
    if strategy not in STRATEGIES:
        raise HTTPException(400, f"Unknown strategy. Choose: {', '.join(STRATEGIES)}")

    raw_bytes = await file.read()
    doc_hash  = hashlib.sha256(raw_bytes).hexdigest()[:16]

    file_path = _kb_upload_dir() / _safe_stored_name(doc_hash, file.filename or "upload")
    file_path.write_bytes(raw_bytes)

    try:
        suffix = Path(file.filename or "").suffix.lower()

        if suffix in (".md", ".txt"):
            # Plain text / markdown — read directly, no parser needed
            markdown = raw_bytes.decode("utf-8", errors="replace")

        elif suffix == ".pdf":
            # Lightweight PDF parser (no PyTorch dependency)
            try:
                from pypdf import PdfReader
                import io
                reader = PdfReader(io.BytesIO(raw_bytes))
                pages = [page.extract_text() or "" for page in reader.pages]
                markdown = "\n\n".join(p for p in pages if p.strip())
                if not markdown.strip():
                    raise HTTPException(422, "PDF appears to have no extractable text (scanned/image-only PDF).")
            except ImportError:
                raise HTTPException(422, "pypdf not installed — PDF upload not supported.")

        else:
            # Fallback: try docling for Word, PowerPoint, etc.
            try:
                from docling.document_converter import DocumentConverter
                converter = DocumentConverter()
                result    = converter.convert(str(file_path))
                markdown  = result.document.export_to_markdown()
            except ImportError:
                raise HTTPException(
                    422,
                    f"Unsupported file type '{suffix}'. Upload .md, .txt, or .pdf files.",
                )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Parse failed: {exc}")

    pool = await get_pool()
    return await _ingest_and_response(
        pool=pool,
        filename=file.filename or file_path.name,
        doc_hash=doc_hash,
        file_path=file_path,
        markdown=markdown,
        strategy=strategy,
    )


# ── Screenshot / image (vision OCR) ───────────────────────────────────────────

@router.post("/screenshot/extract")
async def screenshot_extract(file: UploadFile = File(...)):
    """
    Save an image and extract text with a local Ollama vision model.
    Returns preview text for admin review before indexing.
    """
    _validate_image_upload(file.filename, file.content_type)

    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(413, "Image too large (max 15 MB)")

    doc_hash  = hashlib.sha256(raw_bytes).hexdigest()[:16]
    filename  = Path(file.filename or "screenshot.png").name
    file_path = _kb_upload_dir() / _safe_stored_name(doc_hash, filename)
    file_path.write_bytes(raw_bytes)

    try:
        extracted = await image_to_text(raw_bytes, ollama_url=OLLAMA_URL)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Vision model error: {exc.response.text}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            502,
            f"Could not reach Ollama for vision OCR. Is {VISION_MODEL} pulled?",
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Vision OCR failed: {exc}") from exc

    return {
        "doc_hash": doc_hash,
        "filename": filename,
        "extracted_text": extracted,
        "strategy": "sentence",
        "vision_model": VISION_MODEL,
    }


class ScreenshotConfirm(BaseModel):
    doc_hash: str = Field(..., min_length=8, max_length=32)
    filename: str = Field(..., min_length=1, max_length=255)
    markdown_text: str = Field(..., min_length=1)
    strategy: str = "sentence"


@router.post("/screenshot/confirm")
async def screenshot_confirm(body: ScreenshotConfirm):
    """Index admin-reviewed screenshot text into the knowledge base."""
    if body.strategy not in STRATEGIES:
        raise HTTPException(400, f"Unknown strategy. Choose: {', '.join(STRATEGIES)}")

    file_path = _stored_image_path(body.doc_hash, body.filename)
    if not file_path.is_file():
        raise HTTPException(404, "Screenshot not found — extract again before indexing")

    pool = await get_pool()
    return await _ingest_and_response(
        pool=pool,
        filename=body.filename,
        doc_hash=body.doc_hash,
        file_path=file_path,
        markdown=body.markdown_text.strip(),
        strategy=body.strategy,
    )


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("")
async def list_docs():
    pool = await get_pool()
    return await list_documents(pool, KB_USER_ID)


# ── Archive / Restore / Delete ────────────────────────────────────────────────

@router.patch("/{doc_id}/archive")
async def archive(doc_id: str):
    pool = await get_pool()
    ok   = await archive_document(pool, KB_USER_ID, doc_id)
    if not ok:
        raise HTTPException(404, "Document not found or not active")
    return {"status": "archived"}


@router.patch("/{doc_id}/restore")
async def restore(doc_id: str):
    pool = await get_pool()
    ok   = await restore_document(pool, KB_USER_ID, doc_id)
    if not ok:
        raise HTTPException(404, "Document not found or not archived")
    return {"status": "active"}


@router.delete("/{doc_id}")
async def delete(doc_id: str):
    pool = await get_pool()
    ok   = await delete_document(pool, KB_USER_ID, doc_id)
    if not ok:
        raise HTTPException(404, "Document not found")
    return {"status": "deleted"}


# ── Chunks ─────────────────────────────────────────────────────

@router.get("/{doc_id}/chunks")
async def list_chunks(doc_id: str):
    """Return all chunks for a document (no embeddings)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, chunk_index, section_heading, content
            FROM   rag_chunks
            WHERE  doc_id  = $1
              AND  user_id = $2
            ORDER BY chunk_index
            """,
            doc_id,
            KB_USER_ID,
        )
    if not rows:
        # Verify the document itself exists before returning empty list
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM rag_documents WHERE id = $1 AND user_id = $2",
                doc_id, KB_USER_ID,
            )
        if not exists:
            raise HTTPException(404, "Document not found")
    return [
        {
            "id":              str(r["id"]),
            "chunk_index":     r["chunk_index"],
            "section_heading": r["section_heading"],
            "content":         r["content"],
        }
        for r in rows
    ]


class ChunkUpdate(BaseModel):
    content: str


@router.put("/{doc_id}/chunks/{chunk_id}")
async def update_chunk(doc_id: str, chunk_id: str, body: ChunkUpdate):
    """Update a chunk's text and regenerate its embedding."""
    if not body.content.strip():
        raise HTTPException(400, "Content cannot be empty")

    pool = await get_pool()

    # Verify ownership before updating
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM rag_chunks WHERE id = $1 AND doc_id = $2 AND user_id = $3",
            chunk_id, doc_id, KB_USER_ID,
        )
    if not row:
        raise HTTPException(404, "Chunk not found")

    # Re-embed the updated content
    try:
        embeddings = await embed_texts([body.content], OLLAMA_URL)
        embedding  = embeddings[0]
    except Exception as exc:
        raise HTTPException(502, f"Embedding failed: {exc}")

    # Persist the update
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE rag_chunks
            SET    content   = $1,
                   embedding = $2
            WHERE  id = $3
            """,
            body.content,
            embedding,
            chunk_id,
        )

    return {"status": "updated", "chunk_id": chunk_id}
