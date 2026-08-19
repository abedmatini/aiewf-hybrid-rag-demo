"""
GET /models  -> list models available in the local Ollama instance
"""

import os

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


@router.get("")
async def list_models():
    url = f"{OLLAMA_URL.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Cannot reach Ollama: {exc}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama error: {exc}")

    model_names = [m["name"] for m in data.get("models", [])]
    return {"models": model_names}
