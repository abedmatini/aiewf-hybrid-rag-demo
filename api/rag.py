"""
RAG pipeline for the Kenvue API.

Identical logic to v3-chainlit/rag.py with all Chainlit-specific
imports and callbacks removed. Functions return plain data structures;
streaming and UI concerns are handled in the routers.

To port a new feature from the playground:
  1. Copy the updated function(s) from v3-chainlit/rag.py
  2. Remove any cl.* calls or Chainlit imports
  3. Update the relevant router to expose it via HTTP
"""
import asyncio
import json
import logging
import os
import re
import uuid
from collections import OrderedDict
from functools import lru_cache
from typing import Any, Callable, Coroutine

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
EMBED_MODEL        = os.getenv("EMBED_MODEL", "bge-m3:latest")
EMBED_DIM          = int(os.getenv("EMBED_DIM", "1024"))
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

TOP_K      = 5
OVER_FETCH = 20
RRF_K      = 60
BATCH_SIZE = 20
MIN_CHUNK_CHARS = 80

_ZERO_VEC: tuple[float, ...] = tuple([0.0] * EMBED_DIM)

# ── Embedding cache (in-memory LRU) ──────────────────────────────────────────
_EMBED_CACHE: OrderedDict[str, list[float]] = OrderedDict()
_EMBED_CACHE_MAX = 512  # entries; ~2 MB at 1024 dims × 4 bytes per float

# ── Reranker (optional, lazy-loaded) ─────────────────────────────────────────
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "")


@lru_cache(maxsize=1)
def _get_reranker():
    """Lazy-load the cross-encoder. Returns None when RERANKER_MODEL is unset."""
    if not RERANKER_MODEL:
        return None
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        log.info("Loading reranker: %s", RERANKER_MODEL)
        return CrossEncoder(RERANKER_MODEL)
    except ImportError:
        log.warning("sentence-transformers not installed — RERANKER_MODEL ignored")
        return None


def _rerank_sync(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Score (query, chunk_text) pairs with cross-encoder. CPU-bound."""
    reranker = _get_reranker()
    if reranker is None or len(candidates) <= 1:
        return candidates[:top_k]
    texts = [c.get("content", "") for c in candidates]
    scores = reranker.predict([(query, t) for t in texts])
    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)
    return sorted(candidates, key=lambda x: x.get("rerank_score", 0.0), reverse=True)[:top_k]


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_by_headings(markdown: str) -> list[dict]:
    heading_re = re.compile(r"^#{1,4}\s+\S", re.MULTILINE)
    chunks: list[dict] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in markdown.split("\n"):
        if heading_re.match(line):
            content = "\n".join(current_lines).strip()
            if content:
                chunks.append({"section_heading": current_heading, "content": content})
            current_heading = re.sub(r"^#{1,4}\s+", "", line).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    content = "\n".join(current_lines).strip()
    if content:
        chunks.append({"section_heading": current_heading, "content": content})

    merged: list[dict] = []
    i = 0
    while i < len(chunks):
        chunk = dict(chunks[i])
        while len(chunk["content"]) < MIN_CHUNK_CHARS and i + 1 < len(chunks):
            i += 1
            chunk["content"] = chunk["content"] + "\n\n" + chunks[i]["content"]
        if len(chunk["content"]) >= MIN_CHUNK_CHARS:
            merged.append(chunk)
        i += 1
    return merged


def chunk_by_paragraph(markdown: str) -> list[dict]:
    heading_re = re.compile(r"^#{1,4}\s+(.+)$")
    current_heading = ""
    raw: list[dict] = []

    for para in re.split(r"\n\n+", markdown):
        para = para.strip()
        if not para:
            continue
        first_line = para.split("\n")[0].strip()
        m = heading_re.match(first_line)
        if m:
            current_heading = m.group(1).strip()
            rest = "\n".join(para.split("\n")[1:]).strip()
            if rest:
                raw.append({"section_heading": current_heading, "content": rest})
            continue
        raw.append({"section_heading": current_heading, "content": para})

    merged: list[dict] = []
    i = 0
    while i < len(raw):
        chunk = dict(raw[i])
        while len(chunk["content"]) < MIN_CHUNK_CHARS and i + 1 < len(raw):
            i += 1
            chunk["content"] += "\n\n" + raw[i]["content"]
        if len(chunk["content"]) >= MIN_CHUNK_CHARS:
            merged.append(chunk)
        i += 1
    return merged


def chunk_by_fixed(markdown: str, size: int = 512, overlap: int = 64) -> list[dict]:
    heading_re = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)
    checkpoints: list[tuple[int, str]] = [(0, "")]
    for m in heading_re.finditer(markdown):
        checkpoints.append((m.start(), m.group(1).strip()))

    def _heading_at(offset: int) -> str:
        h = ""
        for pos, heading in checkpoints:
            if pos <= offset:
                h = heading
            else:
                break
        return h

    chunks: list[dict] = []
    start = 0
    while start < len(markdown):
        end = min(start + size, len(markdown))
        content = markdown[start:end].strip()
        if len(content) >= MIN_CHUNK_CHARS:
            chunks.append({"section_heading": _heading_at(start), "content": content})
        start += size - overlap
    return chunks


def chunk_by_sentence(
    markdown: str, sentences_per_chunk: int = 5, overlap: int = 1
) -> list[dict]:
    heading_re = re.compile(r"^#{1,4}\s+(.+)$")
    sent_re    = re.compile(r"(?<=[.!?])\s+")
    current_heading = ""
    all_sentences: list[tuple[str, str]] = []

    for line in markdown.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        m = heading_re.match(stripped)
        if m:
            current_heading = m.group(1).strip()
            continue
        for sent in sent_re.split(stripped):
            sent = sent.strip()
            if sent:
                all_sentences.append((current_heading, sent))

    if not all_sentences:
        return []

    chunks: list[dict] = []
    step = max(1, sentences_per_chunk - overlap)
    i = 0
    while i < len(all_sentences):
        group   = all_sentences[i : i + sentences_per_chunk]
        heading = group[0][0]
        content = " ".join(s[1] for s in group)
        if len(content) >= MIN_CHUNK_CHARS:
            chunks.append({"section_heading": heading, "content": content})
        i += step
    return chunks


STRATEGIES: dict[str, Any] = {
    "heading":   chunk_by_headings,
    "paragraph": chunk_by_paragraph,
    "fixed":     chunk_by_fixed,
    "sentence":  chunk_by_sentence,
}

STRATEGY_LABELS: dict[str, str] = {
    "heading":   "Heading-based (default)",
    "paragraph": "Paragraph",
    "fixed":     "Fixed 512-char + 64-char overlap",
    "sentence":  "Sentence groups (5 per chunk)",
}


# ── Embedding ─────────────────────────────────────────────────────────────────

async def _embed_one(client: httpx.AsyncClient, text: str, url: str) -> list[float]:
    try:
        r = await client.post(
            f"{url.rstrip('/')}/api/embed",
            json={"model": EMBED_MODEL, "input": [text]},
        )
        if r.status_code == 500:
            log.warning("embed 500 (len=%d) — zero vector", len(text))
            return list(_ZERO_VEC)
        r.raise_for_status()
        return r.json()["embeddings"][0]
    except Exception as exc:
        log.warning("embed error (%s) — zero vector", exc)
        return list(_ZERO_VEC)


async def embed_texts(
    texts: list[str], ollama_url: str = DEFAULT_OLLAMA_URL
) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{ollama_url.rstrip('/')}/api/embed",
            json={"model": EMBED_MODEL, "input": texts, "keep_alive": 0},
        )
        if resp.status_code == 500 and len(texts) > 1:
            log.warning("batch embed 500 — falling back to per-text")
            return [await _embed_one(client, t, ollama_url) for t in texts]
        resp.raise_for_status()
        return resp.json()["embeddings"]


async def embed_query(query: str, ollama_url: str = DEFAULT_OLLAMA_URL) -> list[float]:
    """Embed a single query string (with in-memory LRU cache)."""
    cache_key = f"{EMBED_MODEL}:{query}"
    if cache_key in _EMBED_CACHE:
        _EMBED_CACHE.move_to_end(cache_key)
        return _EMBED_CACHE[cache_key]
    vec = (await embed_texts([query], ollama_url))[0]
    if len(_EMBED_CACHE) >= _EMBED_CACHE_MAX:
        _EMBED_CACHE.popitem(last=False)
    _EMBED_CACHE[cache_key] = vec
    return vec


# ── Ingest ────────────────────────────────────────────────────────────────────

async def ingest_document(
    *,
    pool: asyncpg.Pool,
    user_id: str,
    filename: str,
    doc_hash: str,
    file_path: str,
    markdown_text: str,
    is_persistent: bool = True,
    session_id: str | None = None,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    strategy: str = "heading",
) -> tuple[str, bool]:
    """Ingest a document. Returns (doc_id, already_existed)."""
    target_status = "session" if not is_persistent else "active"
    chunk_fn = STRATEGIES.get(strategy, chunk_by_headings)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, status FROM rag_documents
            WHERE user_id = $1 AND doc_hash = $2 AND strategy = $3
            ORDER BY uploaded_at DESC LIMIT 1
            """,
            user_id, doc_hash, strategy,
        )

        if row:
            existing_id = str(row["id"])
            existing_status = row["status"]

            if existing_status == "active":
                return existing_id, True

            if existing_status == "archived":
                await conn.execute(
                    "UPDATE rag_documents SET status = 'active' WHERE id = $1",
                    row["id"],
                )
                return existing_id, True

            count = await conn.fetchval(
                "SELECT COUNT(*) FROM rag_chunks WHERE doc_id = $1", row["id"]
            )
            if count and count > 0:
                await conn.execute(
                    "UPDATE rag_documents SET status = $1 WHERE id = $2",
                    target_status, row["id"],
                )
                return existing_id, True

            await conn.execute("DELETE FROM rag_documents WHERE id = $1", row["id"])

        doc_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO rag_documents
                (id, user_id, filename, doc_hash, file_path, status,
                 is_persistent, session_id, strategy)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            doc_id, user_id, filename, doc_hash, file_path,
            target_status, is_persistent, session_id, strategy,
        )

    chunks = chunk_fn(markdown_text)
    if not chunks:
        return doc_id, False

    all_embeddings: list[list[float]] = []
    for i in range(0, len(chunks), BATCH_SIZE):
        batch_texts = [c["content"] for c in chunks[i : i + BATCH_SIZE]]
        batch_vecs  = await embed_texts(batch_texts, ollama_url)
        all_embeddings.extend(batch_vecs)

    async with pool.acquire() as conn:
        rows = [
            (
                str(uuid.uuid4()), doc_id, user_id, idx,
                chunk["section_heading"], chunk["content"],
                json.dumps(emb),
            )
            for idx, (chunk, emb) in enumerate(zip(chunks, all_embeddings))
        ]
        await conn.executemany(
            """
            INSERT INTO rag_chunks
                (id, doc_id, user_id, chunk_index, section_heading, content, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
            """,
            rows,
        )
        await conn.execute(
            "UPDATE rag_documents SET chunk_count = $1 WHERE id = $2",
            len(chunks), doc_id,
        )

    return doc_id, False


# ── Retrieval ─────────────────────────────────────────────────────────────────

async def retrieve(
    *,
    pool: asyncpg.Pool,
    user_id: str,
    query: str,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    top_k: int = TOP_K,
) -> list[dict]:
    """Hybrid retrieval: vector cosine + BM25, merged with RRF."""
    query_vec = await embed_query(query, ollama_url)
    vec_str   = json.dumps(query_vec)

    async with pool.acquire() as conn:
        vec_rows = await conn.fetch(
            """
            SELECT c.id, c.doc_id, d.filename, c.section_heading, c.content,
                   (c.embedding <=> $2::vector) AS cosine_distance
            FROM rag_chunks c
            JOIN rag_documents d ON c.doc_id = d.id
            WHERE c.user_id = $1 AND d.status = 'active'
            ORDER BY cosine_distance
            LIMIT $3
            """,
            user_id, vec_str, OVER_FETCH,
        )
        bm25_rows = await conn.fetch(
            """
            SELECT c.id, c.doc_id, d.filename, c.section_heading, c.content
            FROM rag_chunks c
            JOIN rag_documents d ON c.doc_id = d.id
            WHERE c.user_id = $1 AND d.status = 'active'
              AND to_tsvector('english', c.content) @@ plainto_tsquery('english', $2)
            ORDER BY ts_rank(to_tsvector('english', c.content),
                             plainto_tsquery('english', $2)) DESC
            LIMIT $3
            """,
            user_id, query, OVER_FETCH,
        )

    scores: dict[str, float] = {}
    chunk_map: dict[str, dict] = {}

    for rank, row in enumerate(vec_rows):
        cid = str(row["id"])
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        chunk_map[cid] = dict(row)

    for rank, row in enumerate(bm25_rows):
        cid = str(row["id"])
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        chunk_map.setdefault(cid, dict(row))

    ranked = sorted(scores.items(), key=lambda x: -x[1])  # all candidates
    all_candidates = [
        {**chunk_map[cid], "rrf_score": score, "id": cid, "doc_id": str(chunk_map[cid]["doc_id"])}
        for cid, score in ranked
        if cid in chunk_map
    ]
    if _get_reranker() is not None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _rerank_sync, query, all_candidates, top_k)
    return all_candidates[:top_k]


# ── Library management ────────────────────────────────────────────────────────

async def list_documents(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, filename, status, is_persistent, chunk_count, uploaded_at, strategy
            FROM rag_documents
            WHERE user_id = $1
            ORDER BY uploaded_at DESC
            """,
            user_id,
        )
    return [
        {**dict(r), "id": str(r["id"]), "uploaded_at": r["uploaded_at"].isoformat()}
        for r in rows
    ]


async def archive_document(pool: asyncpg.Pool, user_id: str, doc_id: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE rag_documents SET status = 'archived'
            WHERE id = $1::uuid AND user_id = $2 AND status = 'active'
            """,
            doc_id, user_id,
        )
    return result != "UPDATE 0"


async def restore_document(pool: asyncpg.Pool, user_id: str, doc_id: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE rag_documents SET status = 'active'
            WHERE id = $1::uuid AND user_id = $2 AND status = 'archived'
            """,
            doc_id, user_id,
        )
    return result != "UPDATE 0"


async def delete_document(pool: asyncpg.Pool, user_id: str, doc_id: str) -> bool:
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Explicitly remove chunks first so nothing lingers in the HNSW index
            # even before the next VACUUM runs (belt-and-suspenders over CASCADE).
            await conn.execute(
                "DELETE FROM rag_chunks WHERE doc_id = $1::uuid AND user_id = $2",
                doc_id, user_id,
            )
            result = await conn.execute(
                "DELETE FROM rag_documents WHERE id = $1::uuid AND user_id = $2",
                doc_id, user_id,
            )
    return result != "DELETE 0"
