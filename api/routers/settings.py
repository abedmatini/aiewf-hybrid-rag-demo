"""
GET /settings  -> return current LLM settings from kenvue_settings table
PUT /settings  -> upsert all settings keys
GET /agents    -> return available agent tool definitions
"""
import os

from fastapi import APIRouter
from pydantic import BaseModel

from db import get_pool

router = APIRouter()

# Mirror of the defaults seeded in db.init_schema
_DEFAULTS = {
    "chat_model": "gemma4:latest",
    "top_k": "5",
    "system_prompt": (
        "You are a helpful FAQ assistant. "
        "Answer questions accurately and concisely using the provided document excerpts. "
        "If the documents do not contain the answer, say so clearly. "
        "Always cite the source document and section."
    ),
    "escalation_message": (
        "I can only answer from our approved FAQ documents. "
        "For account-specific, personal, or urgent matters, "
        "please contact your support team directly."
    ),
    "agent_mode": "false",
    "agent_model": "qwen2.5:7b-instruct",
    "guard_model_enabled": "false",
    "guard_model": os.getenv("GUARD_MODEL", "llama-guard3:1b") or "llama-guard3:1b",
    "domain": os.getenv("DOMAIN", "health_faq"),
}


class Settings(BaseModel):
    chat_model: str
    top_k: int
    system_prompt: str
    escalation_message: str
    agent_mode: bool
    agent_model: str
    guard_model_enabled: bool = False
    guard_model: str = "llama-guard3:1b"
    domain: str = "health_faq"


async def get_current_settings(pool=None) -> dict:
    """Helper used by other routers (e.g. chat) to read live settings."""
    if pool is None:
        pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM kenvue_settings")
    data = {r["key"]: r["value"] for r in rows}
    return {
        "chat_model": data.get("chat_model", _DEFAULTS["chat_model"]),
        "top_k": int(data.get("top_k", _DEFAULTS["top_k"])),
        "system_prompt": data.get("system_prompt", _DEFAULTS["system_prompt"]),
        "escalation_message": data.get("escalation_message", _DEFAULTS["escalation_message"]),
        "agent_mode": data.get("agent_mode", _DEFAULTS["agent_mode"]) == "true",
        "agent_model": data.get("agent_model", _DEFAULTS["agent_model"]),
        "guard_model_enabled": data.get("guard_model_enabled", _DEFAULTS["guard_model_enabled"]) == "true",
        "guard_model": data.get("guard_model", _DEFAULTS["guard_model"]),
        "domain": data.get("domain", _DEFAULTS["domain"]),
    }


@router.get("", response_model=Settings)
async def read_settings():
    s = await get_current_settings()
    return s


@router.put("", response_model=dict)
async def update_settings(body: Settings):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO kenvue_settings (key, value)
            VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            [
                ("chat_model", body.chat_model),
                ("top_k", str(body.top_k)),
                ("system_prompt", body.system_prompt),
                ("escalation_message", body.escalation_message),
                ("agent_mode", "true" if body.agent_mode else "false"),
                ("agent_model", body.agent_model),
                ("guard_model_enabled", "true" if body.guard_model_enabled else "false"),
                ("guard_model", body.guard_model),
                ("domain", body.domain),
            ],
        )
    return {"status": "saved"}


@router.get("/agents")
async def list_agents():
    """Return available agent tool definitions with name and description."""
    from agent_tools import TOOL_DEFINITIONS
    tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
        }
        for t in TOOL_DEFINITIONS
    ]
    return {"tools": tools}
