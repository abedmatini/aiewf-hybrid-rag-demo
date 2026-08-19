"""
helpers.py — shared constants and utility functions for the Kenvue API test suite.
Imported by both conftest.py and test_*.py modules.
"""

import json
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# HTTP header helpers
# ---------------------------------------------------------------------------

CONSENT = {"x-consent-given": "true"}
NO_CONSENT: dict = {}


# ---------------------------------------------------------------------------
# Fake data constants
# ---------------------------------------------------------------------------

FAKE_ESCALATION_MSG = (
    "This chatbot provides approved product information only. "
    "For any health concerns, symptoms, or treatment questions, "
    "please speak to your Healthcare Practitioner (HCP) or contact your doctor directly."
)

FAKE_SETTINGS = {
    "chat_model": "gemma4:latest",
    "top_k": 5,
    "system_prompt": "You are a helpful FAQ assistant.",
    "escalation_message": FAKE_ESCALATION_MSG,
    "agent_mode": False,
    "agent_model": "qwen2.5:7b-instruct",
}

FAKE_SETTINGS_ROWS = [
    {"key": "chat_model",         "value": "gemma4:latest"},
    {"key": "top_k",              "value": "5"},
    {"key": "system_prompt",      "value": FAKE_SETTINGS["system_prompt"]},
    {"key": "escalation_message", "value": FAKE_SETTINGS["escalation_message"]},
    {"key": "agent_mode",         "value": "false"},
    {"key": "agent_model",        "value": "qwen2.5:7b-instruct"},
]

FAKE_CHUNKS = [
    {
        "filename": "test_doc.pdf",
        "section_heading": "Overview",
        "content": "Vitamin D is a fat-soluble vitamin essential for bone health.",
        "cosine_distance": 0.3,
    },
    {
        "filename": "test_doc.pdf",
        "section_heading": "Benefits",
        "content": "Vitamin D helps regulate calcium absorption in the body.",
        "cosine_distance": 0.35,
    },
]

# Valid NDJSON that Ollama returns for a streaming chat request
OLLAMA_STREAM_NDJSON = "\n".join([
    json.dumps({"message": {"role": "assistant", "content": "Vitamin D is"}, "done": False}),
    json.dumps({"message": {"role": "assistant", "content": " important for health."}, "done": False}),
    json.dumps({"done": True}),
])

FAKE_LOG_ROWS = [
    {
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "logged_at": datetime(2026, 5, 26, 10, 0, 0, tzinfo=timezone.utc),
        "user_id": "test_user",
        "message": "What is vitamin D?",
        "event_type": "chat",
        "duration_ms": 350,
    }
]

FAKE_TOP_QUESTIONS = [
    {"message": "What is vitamin D?", "count": 5},
    {"message": "How does ibuprofen work?", "count": 3},
]

FAKE_DOC_ROWS = [
    {
        "id": "bbbbbbbb-0000-0000-0000-000000000001",
        "filename": "test_doc.pdf",
        "status": "active",
        "is_persistent": True,
        "chunk_count": 5,
        "uploaded_at": datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc),
        "strategy": "heading",
    }
]


# ---------------------------------------------------------------------------
# SSE parsing helpers
# ---------------------------------------------------------------------------

def parse_sse(body: str) -> list[dict]:
    """Parse an SSE response body string into a list of JSON event dicts."""
    events: list[dict] = []
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def event_types(events: list[dict]) -> list[str]:
    """Extract the 'type' field from each SSE event dict."""
    return [e.get("type") for e in events]
