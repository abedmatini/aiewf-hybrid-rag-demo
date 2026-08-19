"""
Generic YES/NO LLM safety classifier (Tier 3) shared by Domain Packs.

Mirrors the health pack's `guardrails.check_medical_llm` but takes the policy
prompt as a parameter so any pack can run a domain-specific classifier on the
same local Ollama endpoint. Fails open: any error returns ``False`` (allow), so
a classification outage never blocks a legitimate user.
"""
from __future__ import annotations

import httpx


async def classify_yes_no(
    message: str,
    ollama_url: str,
    model: str,
    *,
    system_prompt: str,
    timeout: float = 8.0,
) -> bool:
    """Return True iff the model answers YES for ``message`` under ``system_prompt``."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{ollama_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 5},
                },
            )
            resp.raise_for_status()
            answer = resp.json().get("message", {}).get("content", "").strip().upper()
            return answer.startswith("YES")
    except Exception:
        return False  # fail open — never block on classification error
