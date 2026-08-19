"""
Suggestions endpoint — returns 4 dynamic sample questions built from
ingested document content via the LLM (classifier model).
Results are cached per user_id for 30 minutes.
"""
import json
import logging
import os
import time

import httpx
from fastapi import APIRouter

from db import get_pool, KB_USER_ID

log    = logging.getLogger(__name__)
router = APIRouter()

_OLLAMA_URL       = os.getenv("OLLAMA_URL", "http://localhost:11434")
# Use dedicated classifier model if set; fall back to chat model for suggestions
_classifier_env   = os.getenv("CLASSIFIER_MODEL", "")
_SUGGESTION_MODEL = (
    _classifier_env
    if _classifier_env and _classifier_env.lower() != "none"
    else os.getenv("CHAT_MODEL", "qwen2.5:7b-instruct")
)
_CACHE_TTL        = 1800  # 30 minutes

# key: user_id → (suggestions, monotonic_timestamp)
_cache: dict[str, tuple[list[str], float]] = {}

# Empty fallback — if there are no documents, don't suggest unanswerable questions
_FALLBACK: list[str] = []


def _parse_suggestions(raw: str) -> list[str] | None:
    """Extract a list[str] from the raw LLM response text."""
    raw = raw.strip()
    parsed = None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fallback: extract the first [...] block from surrounding text
    if parsed is None:
        start = raw.find("[")
        end   = raw.rfind("]")
        if start != -1 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass

    if parsed is None:
        return None

    if isinstance(parsed, list):
        items = [str(s).strip() for s in parsed if str(s).strip()]
        return items[:4] if items else None

    if isinstance(parsed, dict):
        # Standard wrapper keys: {"questions": [...]}
        for key in ("questions", "suggestions", "items", "results"):
            val = parsed.get(key)
            if isinstance(val, list):
                items = [str(s).strip() for s in val if str(s).strip()]
                return items[:4] if items else None
        # Model used questions as dict keys: {"Q1": "", "Q2": "", ...}
        items = [k.strip() for k in parsed.keys() if len(k.strip()) > 10]
        return items[:4] if items else None

    return None


async def _generate(user_id: str) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT section_heading, content
            FROM   rag_chunks
            WHERE  user_id = $1
              AND  LENGTH(content) > 80
            ORDER  BY RANDOM()
            LIMIT  4
            """,
            KB_USER_ID,  # documents are always stored under the shared KB user
        )

    if not rows:
        return _FALLBACK[:]

    # Build labelled excerpts — include heading when present, otherwise content alone
    chunks_text = "\n\n".join(
        f"[{i + 1}]{(' ' + r['section_heading']) if r['section_heading'] else ''}:\n{r['content'][:400]}"
        for i, r in enumerate(rows)
    )
    prompt = (
        "You are creating example questions for a health product information chatbot.\n\n"
        "For each numbered excerpt below, write ONE question whose answer is CLEARLY "
        "PRESENT in that excerpt — do not ask about anything the text does not cover.\n\n"
        "Rules:\n"
        "- Stick to product facts visible in the text: what the product is, active ingredients, "
        "how to use it, dosage, or directions\n"
        "- Do NOT ask about drug interactions, medical diagnoses, or questions that need a doctor\n"
        "- Write naturally, as a real user would type\n"
        "- Return ONLY a valid JSON array of strings, one per excerpt\n\n"
        f"{chunks_text}\n\n"
        'Return format: ["question for excerpt 1", "question for excerpt 2", ...]'
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{_OLLAMA_URL}/api/generate",
                json={
                    "model":   _SUGGESTION_MODEL,
                    "prompt":  prompt,
                    "stream":  False,
                    "options": {"temperature": 0.4, "num_predict": 256},
                },
            )
        raw   = resp.json().get("response", "")
        items = _parse_suggestions(raw)
        if items and len(items) >= 1:
            return items
    except Exception as exc:
        log.warning("Suggestions LLM call failed: %s", exc)

    return _FALLBACK[:]


@router.get("")
async def get_suggestions(user_id: str = "anonymous"):
    now   = time.monotonic()
    entry = _cache.get(user_id)
    if entry and (now - entry[1]) < _CACHE_TTL:
        return {"suggestions": entry[0]}
    suggestions        = await _generate(user_id)
    _cache[user_id]    = (suggestions, now)
    return {"suggestions": suggestions}
