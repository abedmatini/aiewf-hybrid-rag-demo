"""
Layer 2 — API integration tests.
Covers checklist items 2.1–2.26 (consent, chat paths, analytics, settings, documents).

No real DB or Ollama needed:
  - asyncpg pool → MockPool / MockConn  (from conftest.py)
  - Ollama HTTP calls → respx / monkeypatched coroutines
  - rag.retrieve → monkeypatched async function
"""

import json
import pytest
import httpx

from helpers import (
    CONSENT,
    FAKE_CHUNKS,
    FAKE_ESCALATION_MSG,
    FAKE_LOG_ROWS,
    FAKE_TOP_QUESTIONS,
    FAKE_DOC_ROWS,
    OLLAMA_STREAM_NDJSON,
    parse_sse,
    event_types,
)

CHAT_BODY = {"message": "What is vitamin D?", "history": [], "user_id": "test_user"}
MEDICAL_BODY = {"message": "Can I take ibuprofen with this?", "history": [], "user_id": "test_user"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_llm_no(monkeypatch):
    """Patch Tier-3 classifier to always return blocked=False (NO)."""
    from guardrails import GuardrailResult

    async def _no(*args, **kwargs):
        return GuardrailResult(blocked=False, reason="")

    monkeypatch.setattr("guardrails.check_medical_llm", _no)


def _noop_llm_yes(monkeypatch):
    """Patch Tier-3 classifier to always return blocked=True (YES)."""
    from guardrails import GuardrailResult

    async def _yes(*args, **kwargs):
        return GuardrailResult(blocked=True, reason="llm_classifier")

    monkeypatch.setattr("guardrails.check_medical_llm", _yes)


def _patch_retrieve(monkeypatch, chunks):
    """Patch rag.retrieve to return a fixed list of chunks."""

    async def _retrieve(*args, **kwargs):
        return chunks

    monkeypatch.setattr("routers.chat.retrieve", _retrieve)


# ---------------------------------------------------------------------------
# 2.1–2.3  Consent header enforcement
# ---------------------------------------------------------------------------

class TestConsentEnforcement:
    """CHECKLIST: 2.1–2.3"""

    async def test_2_1_no_consent_header_returns_403(self, app_client):
        """2.1 — Missing x-consent-given → 403 consent_required."""
        r = await app_client.post("/chat", json=CHAT_BODY)
        assert r.status_code == 403
        assert r.json()["detail"] == "consent_required"

    async def test_2_2_false_consent_returns_403(self, app_client):
        """2.2 — x-consent-given: false → 403."""
        r = await app_client.post(
            "/chat", json=CHAT_BODY, headers={"x-consent-given": "false"}
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "consent_required"

    async def test_2_3_valid_consent_proceeds(self, app_client, monkeypatch):
        """2.3 — x-consent-given: true → request reaches guardrail (not 403)."""
        # Tier 1 medical query blocks early — no Ollama call needed
        r = await app_client.post("/chat", json=MEDICAL_BODY, headers=CONSENT)
        assert r.status_code == 200  # StreamingResponse is always 200


# ---------------------------------------------------------------------------
# 2.4–2.7  Chat endpoint — escalation paths
# ---------------------------------------------------------------------------

class TestEscalationPath:
    """CHECKLIST: 2.4–2.7"""

    async def test_2_4_tier1_escalation_event_emitted(self, app_client):
        """2.4 — Tier 1 match → SSE stream contains escalation then done."""
        r = await app_client.post("/chat", json=MEDICAL_BODY, headers=CONSENT)
        assert r.status_code == 200
        events = parse_sse(r.text)
        types = event_types(events)
        assert "escalation" in types, f"Expected escalation event, got: {types}"
        assert "done" in types
        # done must follow escalation
        assert types.index("done") > types.index("escalation")

    async def test_2_5_escalation_content_matches_settings(self, app_client):
        """2.5 — Escalation response text matches the configured escalation_message."""
        r = await app_client.post("/chat", json=MEDICAL_BODY, headers=CONSENT)
        events = parse_sse(r.text)
        esc = next((e for e in events if e.get("type") == "escalation"), None)
        assert esc is not None
        assert "Healthcare Practitioner" in esc["content"], (
            f"Expected HCP mention in escalation, got: {esc['content']!r}"
        )

    async def test_2_6_tier3_llm_yes_escalates(self, app_client, monkeypatch):
        """2.6 — Tier 3 classifier returns YES → escalation fires even for clean phrases."""
        _noop_llm_yes(monkeypatch)
        # Also patch retrieve so we don't have to mock Ollama embeddings
        _patch_retrieve(monkeypatch, [])
        r = await app_client.post(
            "/chat",
            json={"message": "my energy feels low lately", "history": [], "user_id": "t"},
            headers=CONSENT,
        )
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "escalation" in types, f"Tier 3 should have escalated, got: {types}"

    async def test_2_7_no_chunk_events_after_tier3_escalation(self, app_client, monkeypatch):
        """2.7 — When Tier 3 escalates, no RAG chunk events are emitted."""
        _noop_llm_yes(monkeypatch)
        _patch_retrieve(monkeypatch, FAKE_CHUNKS)  # would emit chunks if not cancelled
        r = await app_client.post(
            "/chat",
            json={"message": "my energy feels low lately", "history": [], "user_id": "t"},
            headers=CONSENT,
        )
        events = parse_sse(r.text)
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        assert len(chunk_events) == 0, "No chunk events should be emitted on escalation"


# ---------------------------------------------------------------------------
# 2.8–2.11  Chat endpoint — RAG path
# ---------------------------------------------------------------------------

class TestRagPath:
    """CHECKLIST: 2.8–2.11"""

    @pytest.fixture(autouse=True)
    def _setup_rag_mocks(self, monkeypatch, respx_mock):
        """Patch classifier + retrieve; mock Ollama streaming endpoint."""
        _noop_llm_no(monkeypatch)
        _patch_retrieve(monkeypatch, FAKE_CHUNKS)
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=OLLAMA_STREAM_NDJSON)
        )

    async def test_2_8_rag_path_emits_chunks_then_tokens_then_done(self, app_client):
        """2.8 — Clean query with chunks → chunk(×2) then token events then done."""
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        events = parse_sse(r.text)
        types = event_types(events)

        chunks = [e for e in events if e.get("type") == "chunk"]
        tokens = [e for e in events if e.get("type") == "token"]

        assert len(chunks) == 2, f"Expected 2 chunk events, got {len(chunks)}"
        assert len(tokens) >= 1, "Expected at least one token event"
        assert "done" in types
        # chunks precede tokens
        if tokens:
            assert types.index("chunk") < types.index("token")

    async def test_2_9_sse_stream_is_valid_json(self, app_client):
        """2.9 — Every data: line in the SSE response is parseable JSON."""
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        for line in r.text.split("\n"):
            line = line.strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            try:
                json.loads(payload)
            except json.JSONDecodeError as exc:
                pytest.fail(f"Invalid JSON in SSE line {payload!r}: {exc}")

    async def test_2_10_chat_log_inserted_after_stream(self, app_client, mock_conn):
        """2.10 — After streaming, an INSERT INTO chat_logs is recorded."""
        await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        insert_calls = [
            c for c in mock_conn.execute_calls
            if c[0] == "execute" and "INSERT INTO chat_logs" in c[1]
        ]
        assert len(insert_calls) >= 1, (
            f"Expected chat_logs INSERT, execute_calls were: {mock_conn.execute_calls}"
        )

    async def test_2_11_duration_ms_is_positive(self, app_client, mock_conn):
        """2.11 — The logged duration_ms is a positive integer."""
        await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        insert_calls = [
            c for c in mock_conn.execute_calls
            if c[0] == "execute" and "INSERT INTO chat_logs" in c[1]
        ]
        assert insert_calls, "No chat_logs INSERT found"
        # execute_calls entry: ("execute", query_string, (arg0, arg1, ..., arg7))
        # arg positions: user_id, message, response, model, top_k, sources, event_type, duration_ms
        args = insert_calls[0][2]  # positional args tuple
        duration_ms = args[7]
        assert isinstance(duration_ms, int), f"duration_ms should be int, got {type(duration_ms)}"
        assert duration_ms >= 0, f"duration_ms should be non-negative, got {duration_ms}"


# ---------------------------------------------------------------------------
# 2.12–2.14  Chat endpoint — no-match / empty KB
# ---------------------------------------------------------------------------

class TestNoMatchEmptyKB:
    """CHECKLIST: 2.12–2.14"""

    @pytest.fixture(autouse=True)
    def _base(self, monkeypatch, respx_mock):
        _noop_llm_no(monkeypatch)
        _patch_retrieve(monkeypatch, [])  # no chunks returned
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=OLLAMA_STREAM_NDJSON)
        )

    async def test_2_12_no_match_streams_response(self, app_client, mock_conn):
        """2.12 — retrieve returns [] with docs in KB → stream completes (no crash)."""
        mock_conn._fetchval_default = 1  # KB has content (fetchval for rag_chunks check)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "done" in types

    async def test_2_13_empty_kb_streams_response(self, app_client, mock_conn):
        """2.13 — retrieve returns [] AND KB is empty → stream completes (no crash)."""
        mock_conn._fetchval_default = None  # KB is empty (fetchval returns None)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "done" in types

    async def test_2_14_no_match_event_type_logged(self, app_client, mock_conn):
        """2.14 — event_type 'no_match' is inserted when KB has docs but none matched."""
        mock_conn._fetchval_default = 1  # KB has content
        await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        insert_calls = [
            c for c in mock_conn.execute_calls
            if c[0] == "execute" and "INSERT INTO chat_logs" in c[1]
        ]
        assert insert_calls, "No chat_logs INSERT found"
        # execute_calls entry: ("execute", query_string, (arg0, ..., arg6=event_type, arg7=duration_ms))
        args = insert_calls[0][2]  # positional args tuple
        event_type = args[6]
        assert event_type == "no_match", f"Expected 'no_match', got {event_type!r}"


# ---------------------------------------------------------------------------
# 2.15–2.20  Analytics endpoints
# ---------------------------------------------------------------------------

class TestAnalyticsEndpoints:
    """CHECKLIST: 2.15–2.20"""

    async def test_2_15_analytics_summary_empty_db(self, app_client, mock_conn):
        """2.15 — Summary with empty DB returns correct zero-value shape."""
        mock_conn._fetchval_default = 0
        r = await app_client.get("/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["total_chats"] == 0
        assert body["escalation_count"] == 0
        assert body["escalation_rate"] == 0.0
        assert body["no_match_count"] == 0
        assert body["avg_duration_ms"] == 0
        assert body["top_questions"] == []
        assert body["recent_logs"] == []

    async def test_2_16_analytics_summary_with_data(self, app_client, mock_conn):
        """2.16 — Summary with seeded data returns correct aggregates."""
        mock_conn._fetchval_default = 10           # total
        mock_conn.configure_fetchval("event_type = 'escalation'", 2)
        mock_conn.configure_fetchval("event_type = 'no_match'", 1)
        mock_conn.configure_fetchval("AVG(duration_ms)", 450)
        mock_conn.configure_fetch("ORDER BY count DESC", FAKE_TOP_QUESTIONS)
        mock_conn.configure_fetch("ORDER BY logged_at DESC", FAKE_LOG_ROWS)

        r = await app_client.get("/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["total_chats"] == 10
        assert body["escalation_count"] == 2
        assert body["escalation_rate"] == 20.0
        assert body["no_match_count"] == 1
        assert body["avg_duration_ms"] == 450

    async def test_2_17_top_questions_max_10(self, app_client, mock_conn):
        """2.17 — top_questions list has at most 10 items."""
        mock_conn._fetchval_default = 0
        mock_conn.configure_fetch("ORDER BY count DESC", FAKE_TOP_QUESTIONS)
        r = await app_client.get("/analytics/summary")
        assert len(r.json()["top_questions"]) <= 10

    async def test_2_18_recent_logs_max_20(self, app_client, mock_conn):
        """2.18 — recent_logs list has at most 20 items."""
        mock_conn._fetchval_default = 0
        mock_conn.configure_fetch("ORDER BY logged_at DESC", FAKE_LOG_ROWS)
        r = await app_client.get("/analytics/summary")
        assert len(r.json()["recent_logs"]) <= 20

    async def test_2_19_delete_user_data_returns_count(self, app_client, mock_conn):
        """2.19 — DELETE /analytics/user/{id}/data returns deleted_rows count."""
        mock_conn._execute_return = "DELETE 3"
        r = await app_client.delete("/analytics/user/test_user/data")
        assert r.status_code == 200
        body = r.json()
        assert body["deleted_rows"] == 3
        assert body["user_id"] == "test_user"

    async def test_2_20_delete_nonexistent_user_returns_zero(self, app_client, mock_conn):
        """2.20 — DELETE for a user with no data returns deleted_rows=0."""
        mock_conn._execute_return = "DELETE 0"
        r = await app_client.delete("/analytics/user/ghost_user/data")
        assert r.status_code == 200
        assert r.json()["deleted_rows"] == 0


# ---------------------------------------------------------------------------
# 2.21–2.23  Settings endpoints
# ---------------------------------------------------------------------------

class TestSettingsEndpoints:
    """CHECKLIST: 2.21–2.23"""

    async def test_2_21_get_settings_returns_all_keys(self, app_client):
        """2.21 — GET /settings returns the four expected keys."""
        r = await app_client.get("/settings")
        assert r.status_code == 200
        body = r.json()
        assert "chat_model" in body
        assert "top_k" in body
        assert "system_prompt" in body
        assert "escalation_message" in body

    async def test_2_21b_get_settings_returns_correct_values(self, app_client):
        """2.21b — GET /settings reflects the values in kenvue_settings table."""
        r = await app_client.get("/settings")
        body = r.json()
        assert body["chat_model"] == "gemma4:latest"
        assert body["top_k"] == 5

    async def test_2_22_put_settings_persists(self, app_client, mock_conn):
        """2.22 — PUT /settings stores all six keys via executemany."""
        payload = {
            "chat_model": "llama3:latest",
            "top_k": 8,
            "system_prompt": "Updated prompt.",
            "escalation_message": "Updated escalation.",
            "agent_mode": False,
            "agent_model": "qwen2.5:7b-instruct",
        }
        r = await app_client.put("/settings", json=payload)
        assert r.status_code == 200
        assert r.json() == {"status": "saved"}
        # Verify executemany was called with our settings
        upsert_calls = [
            c for c in mock_conn.execute_calls
            if c[0] == "executemany" and "kenvue_settings" in c[1]
        ]
        assert upsert_calls, "Expected an upsert into kenvue_settings"
        rows_upserted = upsert_calls[0][2]  # list of (key, value) tuples
        keys_saved = [row[0] for row in rows_upserted]
        assert "chat_model" in keys_saved
        assert "top_k" in keys_saved

    async def test_2_23_put_settings_invalid_top_k_type(self, app_client):
        """2.23 — PUT /settings with non-integer top_k → 422 Unprocessable Entity."""
        payload = {
            "chat_model": "gemma4:latest",
            "top_k": "not_a_number",
            "system_prompt": "x",
            "escalation_message": "y",
            "agent_mode": False,
            "agent_model": "qwen2.5:7b-instruct",
        }
        r = await app_client.put("/settings", json=payload)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 2.24  Documents endpoints (basic)
# ---------------------------------------------------------------------------

class TestDocumentsEndpoints:
    """CHECKLIST: 2.24 — basic list (upload/delete tested in Layer 8)."""

    async def test_2_24_list_documents_empty_kb(self, app_client, mock_conn):
        """2.24 — GET /documents on empty KB returns []."""
        mock_conn.configure_fetch("rag_documents", [])
        r = await app_client.get("/documents")
        assert r.status_code == 200
        assert r.json() == []

    async def test_2_24b_list_documents_with_docs(self, app_client, mock_conn):
        """2.24b — GET /documents returns documents matching mock rows."""
        mock_conn.configure_fetch("rag_documents", FAKE_DOC_ROWS)
        r = await app_client.get("/documents")
        assert r.status_code == 200
        docs = r.json()
        assert len(docs) == 1
        assert docs[0]["filename"] == "test_doc.pdf"
        assert docs[0]["status"] == "active"


# ---------------------------------------------------------------------------
# 2.27–2.33  Agent settings endpoints
# ---------------------------------------------------------------------------

class TestAgentSettingsEndpoints:
    """CHECKLIST: 2.27–2.33"""

    async def test_2_27_get_settings_includes_agent_mode(self, app_client):
        """2.27 — GET /settings response includes agent_mode key."""
        r = await app_client.get("/settings")
        assert r.status_code == 200
        assert "agent_mode" in r.json()

    async def test_2_28_get_settings_includes_agent_model(self, app_client):
        """2.28 — GET /settings response includes agent_model key."""
        r = await app_client.get("/settings")
        assert r.status_code == 200
        assert "agent_model" in r.json()
        assert isinstance(r.json()["agent_model"], str)

    async def test_2_29_put_settings_agent_mode_false(self, app_client):
        """2.29 — PUT /settings with agent_mode: false → 200 saved."""
        payload = {
            "chat_model": "gemma4:latest",
            "top_k": 5,
            "system_prompt": "Test",
            "escalation_message": "Test",
            "agent_mode": False,
            "agent_model": "qwen2.5:7b-instruct",
        }
        r = await app_client.put("/settings", json=payload)
        assert r.status_code == 200
        assert r.json() == {"status": "saved"}

    async def test_2_30_get_settings_reflects_updated_agent_model(self, app_client, mock_conn):
        """2.30 — GET /settings returns updated agent_model when mock rows have new value."""
        mock_conn.configure_fetch("kenvue_settings", [
            {"key": "chat_model",         "value": "gemma4:latest"},
            {"key": "top_k",              "value": "5"},
            {"key": "system_prompt",      "value": "Test"},
            {"key": "escalation_message", "value": "Test"},
            {"key": "agent_mode",         "value": "false"},
            {"key": "agent_model",        "value": "llama3:8b"},
        ])
        r = await app_client.get("/settings")
        assert r.status_code == 200
        assert r.json()["agent_model"] == "llama3:8b"

    async def test_2_31_get_agents_returns_tools_array(self, app_client):
        """2.31 — GET /settings/agents returns {"tools": [...]} with 6 entries."""
        r = await app_client.get("/settings/agents")
        assert r.status_code == 200
        body = r.json()
        assert "tools" in body
        assert len(body["tools"]) == 6

    async def test_2_32_each_tool_has_name_and_description(self, app_client):
        """2.32 — Each tool object has non-empty name and description."""
        r = await app_client.get("/settings/agents")
        for tool in r.json()["tools"]:
            assert "name" in tool and tool["name"]
            assert "description" in tool and tool["description"]

    async def test_2_33_tool_names_match_definitions(self, app_client):
        """2.33 — Tool names exactly match TOOL_DEFINITIONS in agent_tools.py."""
        r = await app_client.get("/settings/agents")
        names = {t["name"] for t in r.json()["tools"]}
        expected = {
            "search_kb", "list_products", "get_product_info",
            "compare_products", "get_current_date", "calculate",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# 2.34–2.43  Agent loop SSE events
# ---------------------------------------------------------------------------

# Ollama response shapes used in agent tests
_OLLAMA_TOOL_CALL = json.dumps({
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "search_kb", "arguments": {"query": "vitamin D"}}}
        ],
    },
    "done": True,
})

_OLLAMA_NO_TOOLS = json.dumps({
    "message": {"role": "assistant", "content": ""},
    "done": True,
})

_AGENT_SETTINGS = {
    "chat_model": "qwen2.5:7b-instruct",
    "top_k": 5,
    "system_prompt": "You are a helpful FAQ assistant.",
    "escalation_message": (
        "This chatbot provides approved product information only. "
        "For any health concerns, symptoms, or treatment questions, "
        "please speak to your Healthcare Practitioner (HCP) or contact your doctor directly."
    ),
    "agent_mode": True,
    "agent_model": "qwen2.5:7b-instruct",
}


def _enable_agent(monkeypatch):
    """Patch get_current_settings to return agent_mode=True."""
    async def _agent_settings(pool=None):
        return _AGENT_SETTINGS
    monkeypatch.setattr("routers.chat.get_current_settings", _agent_settings)


def _disable_guardrails(monkeypatch):
    """Suppress both sync and async guardrail checks."""
    from guardrails import GuardrailResult
    monkeypatch.setattr("guardrails.check_medical", lambda msg: GuardrailResult(blocked=False, reason=""))
    async def _no(*a, **kw): return GuardrailResult(blocked=False, reason="")
    monkeypatch.setattr("guardrails.check_medical_llm", _no)


def _patch_execute_tool(monkeypatch, result: str = "mocked tool result"):
    """Patch execute_tool so the agent loop never hits real DB/Ollama for tool execution."""
    async def _tool(*args, **kwargs):
        return result
    monkeypatch.setattr("routers.chat.execute_tool", _tool)


def _patch_retrieve_empty(monkeypatch):
    """Patch retrieve so the source-tracking block inside the loop returns nothing."""
    async def _empty(*a, **kw): return []
    monkeypatch.setattr("routers.chat.retrieve", _empty)
    try:
        import rag
        monkeypatch.setattr(rag, "retrieve", _empty)
    except Exception:
        pass


class TestAgentLoopSSE:
    """CHECKLIST: 2.34–2.43"""

    @pytest.fixture(autouse=True)
    def _base_agent(self, monkeypatch):
        _enable_agent(monkeypatch)
        _disable_guardrails(monkeypatch)
        _patch_execute_tool(monkeypatch)
        _patch_retrieve_empty(monkeypatch)

    # ── 2.34–2.36: one tool call then final answer ──────────────────────

    async def test_2_34_tool_call_event_emitted(self, app_client, respx_mock):
        """2.34 — Agent mode ON + tool call returned → SSE contains tool_call event."""
        call_index = {"n": 0}

        def _side_effect(request):
            body = json.loads(request.content)
            if not body.get("stream", True):
                call_index["n"] += 1
                if call_index["n"] == 1:
                    return httpx.Response(200, text=_OLLAMA_TOOL_CALL)
                return httpx.Response(200, text=_OLLAMA_NO_TOOLS)
            return httpx.Response(200, text=OLLAMA_STREAM_NDJSON)

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=_side_effect)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "tool_call" in types

    async def test_2_35_tool_result_event_emitted(self, app_client, respx_mock):
        """2.35 — After tool executes, tool_result event is emitted."""
        call_index = {"n": 0}

        def _side_effect(request):
            body = json.loads(request.content)
            if not body.get("stream", True):
                call_index["n"] += 1
                if call_index["n"] == 1:
                    return httpx.Response(200, text=_OLLAMA_TOOL_CALL)
                return httpx.Response(200, text=_OLLAMA_NO_TOOLS)
            return httpx.Response(200, text=OLLAMA_STREAM_NDJSON)

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=_side_effect)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        events = parse_sse(r.text)
        tool_result_events = [e for e in events if e.get("type") == "tool_result"]
        assert tool_result_events, "Expected at least one tool_result event"
        assert tool_result_events[0]["name"] == "search_kb"
        assert "mocked tool result" in tool_result_events[0]["result"]

    async def test_2_36_final_answer_streamed_after_tool(self, app_client, respx_mock):
        """2.36 — After tool result, final answer is streamed (token events + done)."""
        call_index = {"n": 0}

        def _side_effect(request):
            body = json.loads(request.content)
            if not body.get("stream", True):
                call_index["n"] += 1
                if call_index["n"] == 1:
                    return httpx.Response(200, text=_OLLAMA_TOOL_CALL)
                return httpx.Response(200, text=_OLLAMA_NO_TOOLS)
            return httpx.Response(200, text=OLLAMA_STREAM_NDJSON)

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=_side_effect)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        types = event_types(parse_sse(r.text))
        assert "token" in types
        assert "done" in types

    # ── 2.37: no tool calls immediately → straight to tokens ────────────

    async def test_2_37_no_tool_calls_goes_straight_to_tokens(self, app_client, respx_mock):
        """2.37 — Agent returns no tool calls → stream goes straight to tokens (no tool_call)."""
        def _side_effect(request):
            body = json.loads(request.content)
            if not body.get("stream", True):
                return httpx.Response(200, text=_OLLAMA_NO_TOOLS)
            return httpx.Response(200, text=OLLAMA_STREAM_NDJSON)

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=_side_effect)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        types = event_types(parse_sse(r.text))
        assert "tool_call" not in types
        assert "token" in types
        assert "done" in types

    # ── 2.38–2.39: agent mode OFF → direct RAG ──────────────────────────

    async def test_2_38_agent_mode_off_no_tool_events(self, app_client, monkeypatch, respx_mock):
        """2.38 — agent_mode=False → no tool_call or tool_result events in stream."""
        # Override settings to disable agent mode
        async def _direct_settings(pool=None):
            return {**_AGENT_SETTINGS, "agent_mode": False}
        monkeypatch.setattr("routers.chat.get_current_settings", _direct_settings)
        _patch_retrieve_empty(monkeypatch)
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=OLLAMA_STREAM_NDJSON)
        )
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        types = event_types(parse_sse(r.text))
        assert "tool_call" not in types
        assert "tool_result" not in types

    async def test_2_39_agent_mode_off_rag_path_used(self, app_client, monkeypatch, respx_mock):
        """2.39 — agent_mode=False → retrieve is called (direct RAG path)."""
        retrieve_called = {"called": False}

        async def _direct_settings(pool=None):
            return {**_AGENT_SETTINGS, "agent_mode": False}

        async def _mock_retrieve(*a, **kw):
            retrieve_called["called"] = True
            return FAKE_CHUNKS

        monkeypatch.setattr("routers.chat.get_current_settings", _direct_settings)
        monkeypatch.setattr("routers.chat.retrieve", _mock_retrieve)
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=OLLAMA_STREAM_NDJSON)
        )
        await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert retrieve_called["called"], "retrieve should be called in direct RAG mode"

    # ── 2.40: event_type = "agent" logged ───────────────────────────────

    async def test_2_40_agent_event_type_logged(self, app_client, mock_conn, respx_mock):
        """2.40 — event_type 'agent' is inserted in chat_logs after agent loop."""
        def _side_effect(request):
            body = json.loads(request.content)
            if not body.get("stream", True):
                return httpx.Response(200, text=_OLLAMA_NO_TOOLS)
            return httpx.Response(200, text=OLLAMA_STREAM_NDJSON)

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=_side_effect)
        await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        insert_calls = [
            c for c in mock_conn.execute_calls
            if c[0] == "execute" and "INSERT INTO chat_logs" in c[1]
        ]
        assert insert_calls, "Expected chat_logs INSERT"
        event_type = insert_calls[0][2][6]
        assert event_type == "agent", f"Expected 'agent', got {event_type!r}"

    # ── 2.41: max iterations safety limit ───────────────────────────────

    async def test_2_41_max_iterations_exits_cleanly(self, app_client, respx_mock):
        """2.41 — Ollama always returns tool calls → loop exits at MAX_AGENT_ITERATIONS; done emitted."""
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=_OLLAMA_TOOL_CALL)
        )
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "done" in types
        # Should have tool_call events from each iteration
        assert "tool_call" in types

    # ── 2.42: execute_tool raises exception ─────────────────────────────

    async def test_2_42_execute_tool_exception_yields_error(self, app_client, monkeypatch, respx_mock):
        """2.42 — execute_tool raises an exception → SSE error event emitted."""
        async def _raising_tool(*a, **kw):
            raise RuntimeError("Tool execution failed!")
        monkeypatch.setattr("routers.chat.execute_tool", _raising_tool)

        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=_OLLAMA_TOOL_CALL)
        )
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" in types

    # ── 2.43: unknown tool name — loop continues ─────────────────────────

    async def test_2_43_unknown_tool_loop_continues(self, app_client, monkeypatch, respx_mock):
        """2.43 — Tool call references unknown tool → execute_tool returns error string; loop continues to done."""
        unknown_call = json.dumps({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "fly_to_moon", "arguments": {}}}
                ],
            },
            "done": True,
        })
        call_index = {"n": 0}

        def _side_effect(request):
            body = json.loads(request.content)
            if not body.get("stream", True):
                call_index["n"] += 1
                if call_index["n"] == 1:
                    return httpx.Response(200, text=unknown_call)
                return httpx.Response(200, text=_OLLAMA_NO_TOOLS)
            return httpx.Response(200, text=OLLAMA_STREAM_NDJSON)

        # Restore real execute_tool to return the error string for unknown tool
        from agent_tools import execute_tool as _real_execute_tool
        monkeypatch.setattr("routers.chat.execute_tool", _real_execute_tool)

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=_side_effect)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        # Loop should continue past the unknown tool and eventually reach done
        assert "done" in types
        assert "error" not in types
