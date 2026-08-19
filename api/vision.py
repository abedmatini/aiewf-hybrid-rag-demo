"""
Local vision OCR via Ollama — convert screenshot/image bytes to Markdown text.

Used for admin-only ingest when the source is a photo or screenshot (email alert,
Slack message, etc.) rather than a structured document file.
"""
import base64
import os

import httpx

VISION_MODEL = os.getenv("VISION_MODEL", "qwen2.5vl")
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
VISION_TIMEOUT = float(os.getenv("VISION_TIMEOUT", "180"))

SCREENSHOT_PROMPT = """Extract all visible text from this image faithfully.

Rules:
- Preserve dates, times, subject lines, and maintenance windows exactly as shown.
- Output plain Markdown: use a # heading for the subject or title if visible, then the body.
- Transcribe the message content — do not summarize.
- Omit decorative UI chrome (toolbars, window frames) when it is clearly not part of the message.
- If no readable text is present, respond with exactly: NO_TEXT_FOUND"""


async def image_to_text(
    image_bytes: bytes,
    *,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = VISION_MODEL,
) -> str:
    """Send an image to a local Ollama vision model and return extracted Markdown text."""
    if not image_bytes:
        raise ValueError("Empty image")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": SCREENSHOT_PROMPT,
                "images": [b64],
            }
        ],
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=VISION_TIMEOUT) as client:
        resp = await client.post(f"{ollama_url.rstrip('/')}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

    text = (data.get("message") or {}).get("content") or ""
    text = text.strip()
    if not text or text == "NO_TEXT_FOUND":
        raise ValueError("No readable text found in image")
    return text
