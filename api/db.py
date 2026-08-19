"""
Database connection pool and schema for the Kenvue RAG API.

Only the RAG tables are created here (no Chainlit persistence tables).
Shares the same PostgreSQL instance as v3-chainlit for local development.
"""
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

_EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))

SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       TEXT NOT NULL,
    filename      TEXT NOT NULL,
    doc_hash      TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    is_persistent BOOLEAN NOT NULL DEFAULT TRUE,
    replaced_by   UUID REFERENCES rag_documents(id) ON DELETE SET NULL,
    chunk_count   INTEGER DEFAULT 0,
    uploaded_at   TIMESTAMPTZ DEFAULT NOW(),
    session_id    TEXT,
    strategy      TEXT NOT NULL DEFAULT 'heading'
);

CREATE INDEX IF NOT EXISTS idx_kv_docs_user   ON rag_documents(user_id);
CREATE INDEX IF NOT EXISTS idx_kv_docs_hash   ON rag_documents(user_id, doc_hash);
CREATE INDEX IF NOT EXISTS idx_kv_docs_status ON rag_documents(user_id, status);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    chunk_index     INTEGER NOT NULL,
    section_heading TEXT,
    content         TEXT NOT NULL,
    embedding       vector({_EMBED_DIM})
);

CREATE INDEX IF NOT EXISTS idx_kv_chunks_user ON rag_chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_kv_chunks_doc  ON rag_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_kv_chunks_fts
    ON rag_chunks USING gin (to_tsvector('english', content));

-- Admin-controlled LLM and retrieval settings
CREATE TABLE IF NOT EXISTS kenvue_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Interaction log — one row per chat turn
CREATE TABLE IF NOT EXISTS chat_logs (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    logged_at    TIMESTAMPTZ NOT NULL    DEFAULT NOW(),
    user_id      TEXT,
    message      TEXT        NOT NULL,
    response     TEXT,
    model        TEXT,
    top_k        INTEGER,
    sources      JSONB       NOT NULL    DEFAULT '[]',
    event_type   TEXT        NOT NULL    DEFAULT 'chat',
    duration_ms  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_chat_logs_time  ON chat_logs(logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_logs_event ON chat_logs(event_type);
"""

HNSW_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_kv_chunks_embedding
    ON rag_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""

# The shared namespace for all admin-uploaded knowledge base documents.
# All chat queries retrieve from this namespace.
KB_USER_ID = os.getenv("KB_USER_ID", "faq_kb")

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            os.environ["DATABASE_URL"],
            min_size=2,
            max_size=10,
        )
    return _pool


async def init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.execute(HNSW_INDEX_SQL)
        await conn.execute(
            """
            ALTER TABLE rag_documents
            ADD COLUMN IF NOT EXISTS strategy TEXT NOT NULL DEFAULT 'heading'
            """
        )
        # Seed default settings (no-op if already present)
        await conn.executemany(
            """
            INSERT INTO kenvue_settings (key, value)
            VALUES ($1, $2)
            ON CONFLICT (key) DO NOTHING
            """,
            [
                ("chat_model", os.getenv("CHAT_MODEL", "gemma4:latest")),
                ("top_k", "5"),
                (
                    "system_prompt",
                    "You are a helpful FAQ assistant. "
                    "Answer questions accurately and concisely using the provided document excerpts. "
                    "If the documents do not contain the answer, say so clearly. "
                    "Always cite the source document and section.",
                ),
                (
                    "escalation_message",
                    "I can only answer from our approved FAQ documents. "
                    "For account-specific, personal, or urgent matters, "
                    "please contact your support team directly.",
                ),
                ("agent_mode", "true"),
                ("agent_model", os.getenv("AGENT_MODEL", "qwen2.5:7b-instruct")),
                ("guard_model_enabled", "true" if os.getenv("GUARD_MODEL", "").strip() else "false"),
                ("guard_model", os.getenv("GUARD_MODEL", "").strip() or "llama-guard3:1b"),
                ("domain", os.getenv("DOMAIN", "health_faq")),
            ],
        )
