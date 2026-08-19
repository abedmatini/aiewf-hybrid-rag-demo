"""
FAQ chatbot — FastAPI application entry point.

Starts the RAG API on port 8002.
Run with: uvicorn main:app --port 8002 --reload
"""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from db import get_pool, init_schema
from routers import chat, documents, settings, models, settings, models
from routers.analytics    import router as analytics_router
from routers.suggestions  import router as suggestions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise DB pool and schema on startup; close pool on shutdown."""
    pool = await get_pool()
    await init_schema(pool)
    yield
    await pool.close()


app = FastAPI(
    title="FAQ RAG API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
_default_origins = "http://localhost:5174,http://localhost:5175,http://localhost:5173"
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(chat.router,      prefix="/chat",      tags=["chat"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(settings.router,  prefix="/settings",  tags=["settings"])
app.include_router(models.router,    prefix="/models",    tags=["models"])
app.include_router(analytics_router,   prefix="/analytics",   tags=["analytics"])
app.include_router(suggestions_router, prefix="/suggestions", tags=["suggestions"])


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "faq-rag-api"}
