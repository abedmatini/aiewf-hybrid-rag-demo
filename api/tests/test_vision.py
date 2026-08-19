"""Unit tests for vision.py — Ollama screenshot OCR."""
import base64
import json

import httpx
import pytest
import respx

from vision import image_to_text


@respx.mock
@pytest.mark.asyncio
async def test_image_to_text_returns_model_content():
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={"message": {"content": "# Alert\n\nMaintenance tonight."}},
        )
    )

    raw = b"\x89PNG fake image bytes"
    text = await image_to_text(raw, ollama_url="http://localhost:11434")
    assert "Maintenance tonight" in text

    body = json.loads(respx.calls.last.request.content)
    assert body["messages"][0]["images"]
    assert base64.b64decode(body["messages"][0]["images"][0]) == raw


@pytest.mark.asyncio
async def test_image_to_text_empty_image_raises():
    with pytest.raises(ValueError, match="Empty"):
        await image_to_text(b"")


@respx.mock
@pytest.mark.asyncio
async def test_image_to_text_no_text_raises():
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "NO_TEXT_FOUND"}})
    )
    with pytest.raises(ValueError, match="No readable text"):
        await image_to_text(b"\x89PNG fake", ollama_url="http://localhost:11434")
