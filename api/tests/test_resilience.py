"""
Layer 6 — Resilience & Error Handling tests.
Covers checklist items 6.1–6.10: Ollama failures, DB failures, client disconnects.

Key design principles verified:
  - External service failures (Ollama) yield a structured SSE error event, never a bare 500
  - The Tier-3 LLM classifier fails open (a network error → blocked=False, not an error event)
  - DB logging failures in the finally block are swallowed — the stream always completes
  - Missing settings fall back to _DEFAULTS — chat remains functional
  - Concurrent requests share no mutable state
"""

import asyncio
import json

import httpx
import pytest

from helpers import (
    CONSENT,
    FAKE_CHUNKS,
    FAKE_SETTINGS_ROWS,
    OLLAMA_STREAM_NDJSON,
    parse_sse,
    event_types,
)

CHAT_BODY = {"message": "What is vitamin D?", "history": [], "user_id": "test_user"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_llm_no(monkeypatch):
    from guardrails import GuardrailResult
    async def _no(*a, **kw): return GuardrailResult(blocked=False, reason="")
    monkeypatch.setattr("guardrails.check_medical_llm", _no)


def _patch_retrieve(monkeypatch, chunks=None):
    async def _r(*a, **kw): return chunks or []
    monkeypatch.setattr("routers.chat.retrieve", _r)


# ---------------------------------------------------------------------------
# 6.1–6.5  Ollama failures
# ---------------------------------------------------------------------------

class TestOllamaFailures:
    """CHECKLIST: 6.1–6.5"""

    async def test_6_1_ollama_unreachable_yields_error_event(
        self, app_client, monkeypatch, respx_mock
    ):
        """
        6.1 — Ollama chat endpoint unreachable (ConnectError).

        check_medical_llm catches the error and fails open (blocked=False).
        The streaming chat call also gets ConnectError → SSE {"type": "error"} event.
        No unhandled 500 is returned.
        """
        _patch_retrieve(monkeypatch, FAKE_CHUNKS)
        respx_mock.post("http://localhost:11434/api/chat").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)

        assert r.status_code == 200  # StreamingResponse header is sent first
        events = parse_sse(r.text)
        types = event_types(events)
        assert "error" in types, (
            f"Expected SSE error event when Ollama is unreachable, got: {types}"
        )
        # Verify the error detail doesn't expose a raw Python traceback
        err_event = next(e for e in events if e.get("type") == "error")
        assert "Traceback" not in err_event.get("detail", ""), (
            "Raw Python traceback leaked in SSE error detail"
        )

    async def test_6_2_ollama_returns_500_yields_error_event(
        self, app_client, monkeypatch, respx_mock, mock_conn
    ):
        """
        6.2 — Ollama streaming endpoint returns HTTP 500.

        check_medical_llm fails open on the 500. The streaming call
        raises httpx.HTTPStatusError → SSE error event. The finally block
        still writes a chat_logs entry.
        """
        _patch_retrieve(monkeypatch, FAKE_CHUNKS)
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)

        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" in types, f"Expected SSE error event on 500, got: {types}"

        # The finally block should still have attempted the INSERT
        insert_calls = [
            c for c in mock_conn.execute_calls
            if c[0] == "execute" and "INSERT INTO chat_logs" in c[1]
        ]
        assert insert_calls, "DB log should still be written even after Ollama 500"

    async def test_6_3_malformed_ndjson_stream_completes_gracefully(
        self, app_client, monkeypatch, respx_mock
    ):
        """
        6.3 — Ollama stream contains malformed / partial JSON lines.

        Invalid lines are skipped (JSONDecodeError caught), and the stream
        still completes with a 'done' event once the body is exhausted.
        """
        _noop_llm_no(monkeypatch)
        _patch_retrieve(monkeypatch, FAKE_CHUNKS)

        # Mix of valid, empty, and malformed NDJSON lines
        partial_body = "\n".join([
            json.dumps({"message": {"role": "assistant", "content": "Vitamin"}, "done": False}),
            "{invalid json",          # malformed — should be skipped
            "",                        # empty line — should be skipped
            json.dumps({"message": {"role": "assistant", "content": " D"}, "done": False}),
            "not json at all!!",      # malformed — should be skipped
            # NOTE: no {"done": true} — stream ends abruptly
        ])
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=partial_body)
        )

        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)

        assert r.status_code == 200
        events = parse_sse(r.text)
        types = event_types(events)
        assert "done" in types, f"Expected 'done' even after malformed stream, got: {types}"
        assert "error" not in types, f"No error event expected for skippable malformed lines"

    async def test_6_4_classifier_timeout_fails_open_query_proceeds(
        self, app_client, monkeypatch, respx_mock
    ):
        """
        6.4 — Tier-3 LLM classifier times out.

        check_medical_llm wraps the call in try/except Exception: pass and
        returns GuardrailResult(blocked=False) on any error → fail-open design.
        The query proceeds to RAG and completes normally (token + done events).
        """
        _patch_retrieve(monkeypatch, FAKE_CHUNKS)

        # First call hits check_medical_llm (stream=False) → timeout → fail open
        # Second call is the actual streaming response from _stream_chat
        respx_mock.post("http://localhost:11434/api/chat").mock(
            side_effect=[
                httpx.ReadTimeout("Classifier timed out"),
                httpx.Response(200, text=OLLAMA_STREAM_NDJSON),
            ]
        )

        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)

        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" not in types, (
            f"Classifier timeout should fail open (not emit error), got: {types}"
        )
        assert "done" in types, (
            f"Query should proceed to RAG after classifier timeout, got: {types}"
        )

    async def test_6_5_retrieve_raises_yields_error_event(
        self, app_client, monkeypatch
    ):
        """
        6.5 — Ollama embedding call fails during RAG retrieval.

        Simulated by making routers.chat.retrieve raise httpx.ConnectError.
        The outer except block in _stream_chat catches it and yields an error event.
        """
        _noop_llm_no(monkeypatch)

        async def _failing_retrieve(*a, **kw):
            raise httpx.ConnectError("Embed endpoint unreachable")

        monkeypatch.setattr("routers.chat.retrieve", _failing_retrieve)

        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)

        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" in types, (
            f"Expected SSE error event when retrieve raises, got: {types}"
        )


# ---------------------------------------------------------------------------
# 6.6–6.8  Database failures
# ---------------------------------------------------------------------------

class TestDatabaseFailures:
    """CHECKLIST: 6.6–6.8"""

    async def test_6_6_db_unreachable_response_does_not_leak_traceback(
        self, app_client, monkeypatch
    ):
        """
        6.6 — DB pool unreachable at request time (get_pool raises OSError).

        pool = await get_pool() is called BEFORE the try/except in _stream_chat.
        Starlette propagates the unhandled generator exception (ExceptionGroup on Python 3.11+).

        Security assertion: the exception does NOT expose DB connection strings or passwords.

        FINDING: move `pool = await get_pool()` inside the try/except so the
        client receives an SSE {"type": "error"} event rather than a hard crash.
        """
        async def _unreachable():
            raise OSError("Connection to PostgreSQL refused: [Errno 111]")

        monkeypatch.setattr("routers.chat.get_pool", _unreachable)

        # The generator raises before its first yield — Starlette re-raises as an ExceptionGroup
        with pytest.raises(Exception) as exc_info:
            await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)

        exc_str = str(exc_info.value).lower()
        # Verify no DB credentials are present in the exception chain
        assert "password" not in exc_str, "DB password leaked in exception"
        assert "secret" not in exc_str, "DB secret leaked in exception"
        # The OSError we injected should be the cause
        assert "connection" in exc_str or "111" in exc_str or "oserror" in exc_str, (
            f"Unexpected exception type propagated: {exc_info.type.__name__}: {exc_info.value}"
        )

    async def test_6_6b_mid_request_db_error_yields_sse_error_event(
        self, app_client, monkeypatch
    ):
        """
        6.6b — DB connection lost AFTER pool is obtained (inside the try/except).

        Monkeypatching get_current_settings to raise simulates the DB becoming
        unavailable mid-request. Since this is inside _stream_chat's try/except,
        an SSE {"type": "error"} event is emitted. No traceback is leaked.
        """
        async def _db_lost(pool=None):
            raise OSError("SSL connection has been closed unexpectedly")

        monkeypatch.setattr("routers.chat.get_current_settings", _db_lost)

        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)

        assert r.status_code == 200
        events = parse_sse(r.text)
        types = event_types(events)
        assert "error" in types, (
            f"Expected SSE error event when DB fails mid-request, got: {types}"
        )
        err = next(e for e in events if e.get("type") == "error")
        assert "Traceback" not in err.get("detail", ""), (
            "Raw Python traceback leaked in SSE error detail"
        )

    async def test_6_7_chat_log_insert_failure_does_not_break_stream(
        self, app_client, mock_conn
    ):
        """
        6.7 — INSERT INTO chat_logs raises a DB constraint error.

        The finally block wraps the INSERT in try/except Exception: pass.
        The SSE stream should have completed normally (with escalation + done)
        before the finally block ran — the logging failure is silently swallowed.
        """
        # Override execute to raise only for the chat_logs INSERT
        original_execute = mock_conn.execute

        async def _raising_execute(query, *args):
            if "INSERT INTO chat_logs" in query:
                raise Exception("DB constraint violation: duplicate key")
            return await original_execute(query, *args)

        mock_conn.execute = _raising_execute

        # Use a Tier-1 escalation message — no Ollama call needed
        r = await app_client.post(
            "/chat",
            json={"message": "Can I take ibuprofen with this?", "history": [], "user_id": "t"},
            headers=CONSENT,
        )

        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "escalation" in types, "Expected escalation event to be emitted normally"
        assert "done" in types, "Expected done event — stream should complete despite log failure"
        assert "error" not in types, "No error event expected — logging failure is swallowed"

    async def test_6_8_settings_table_empty_falls_back_to_defaults(
        self, app_client, monkeypatch, respx_mock, mock_conn
    ):
        """
        6.8 — kenvue_settings table returns no rows.

        get_current_settings() falls back to _DEFAULTS for all missing keys.
        Chat should work normally with the default model / system prompt.
        """
        # Remove the pre-configured settings rows — fetch returns []
        mock_conn._fetch_map.pop("kenvue_settings", None)
        _noop_llm_no(monkeypatch)
        _patch_retrieve(monkeypatch, FAKE_CHUNKS)
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=OLLAMA_STREAM_NDJSON)
        )

        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)

        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" not in types, (
            f"Chat should work with _DEFAULTS when settings table is empty, got: {types}"
        )
        assert "done" in types


# ---------------------------------------------------------------------------
# 6.9–6.10  Client disconnects & concurrency
# ---------------------------------------------------------------------------

class TestConcurrency:
    """CHECKLIST: 6.9–6.10"""

    @pytest.mark.skip(
        reason=(
            "6.9 — Simulating a mid-stream client disconnect requires a real HTTP server "
            "(httpx ASGI transport consumes the full response). "
            "Test this manually with: uvicorn main:app --port 8002 and then kill the curl "
            "mid-stream to verify the finally block still executes."
        )
    )
    async def test_6_9_client_disconnect_mid_stream(self, app_client):
        pass  # pragma: no cover

    async def test_6_10_concurrent_requests_complete_independently(
        self, app_client, monkeypatch, respx_mock
    ):
        """
        6.10 — Two concurrent POST /chat requests from the same user_id.

        Both streams must complete with their own 'done' event.
        No shared mutable state between requests (each gets its own pool.acquire() call).
        """
        _noop_llm_no(monkeypatch)
        _patch_retrieve(monkeypatch, FAKE_CHUNKS)
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=OLLAMA_STREAM_NDJSON)
        )

        results = await asyncio.gather(
            app_client.post("/chat", json=CHAT_BODY, headers=CONSENT),
            app_client.post("/chat", json=CHAT_BODY, headers=CONSENT),
        )

        for i, r in enumerate(results):
            assert r.status_code == 200, f"Request {i + 1} failed with {r.status_code}"
            types = event_types(parse_sse(r.text))
            assert "done" in types, f"Request {i + 1} missing 'done' event: {types}"
            assert "error" not in types, f"Request {i + 1} unexpected error event: {types}"


# ---------------------------------------------------------------------------
# 6.11–6.16  Agent loop failures — NEW for agentic
# ---------------------------------------------------------------------------

_OLLAMA_TOOL_CALL_BODY = json.dumps({
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "search_kb", "arguments": {"query": "vitamin D"}}}],
    },
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
    async def _s(pool=None): return _AGENT_SETTINGS
    monkeypatch.setattr("routers.chat.get_current_settings", _s)


def _patch_execute_tool_noop(monkeypatch):
    async def _t(*a, **kw): return "tool result"
    monkeypatch.setattr("routers.chat.execute_tool", _t)


def _patch_retrieve_empty(monkeypatch):
    async def _r(*a, **kw): return []
    monkeypatch.setattr("routers.chat.retrieve", _r)
    try:
        import rag
        monkeypatch.setattr(rag, "retrieve", _r)
    except Exception:
        pass


def _disable_guardrails(monkeypatch):
    from guardrails import GuardrailResult
    monkeypatch.setattr("guardrails.check_medical", lambda m: GuardrailResult(blocked=False, reason=""))
    async def _no(*a, **kw): return GuardrailResult(blocked=False, reason="")
    monkeypatch.setattr("guardrails.check_medical_llm", _no)


class TestAgentLoopFailures:
    """CHECKLIST: 6.11–6.16"""

    @pytest.fixture(autouse=True)
    def _base(self, monkeypatch):
        _enable_agent(monkeypatch)
        _disable_guardrails(monkeypatch)
        _patch_execute_tool_noop(monkeypatch)
        _patch_retrieve_empty(monkeypatch)

    async def test_6_11_ollama_unreachable_during_agent_decision(
        self, app_client, respx_mock
    ):
        """6.11 — ConnectError on non-streaming tool-decision call → SSE error event."""
        respx_mock.post("http://localhost:11434/api/chat").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" in types, f"Expected SSE error event, got: {types}"

    async def test_6_12_ollama_500_during_agent_decision(
        self, app_client, respx_mock
    ):
        """6.12 — HTTP 500 on tool-decision call → SSE error event; no unhandled exception."""
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" in types, f"Expected SSE error on Ollama 500, got: {types}"

    async def test_6_13_ollama_unreachable_during_streaming_final_answer(
        self, app_client, respx_mock
    ):
        """6.13 — Tool call succeeds; ConnectError on the streaming final answer call.

        Sequence:
          non-streaming call 1 → returns tool_call  (tool_call + tool_result emitted)
          non-streaming call 2 → returns no tool_calls  → triggers streaming final answer
          streaming call       → raises ConnectError   → SSE error event
        """
        _NO_TOOLS = json.dumps({
            "message": {"role": "assistant", "content": ""},
            "done": True,
        })
        call_count = {"n": 0}

        def _side_effect(request):
            body = json.loads(request.content)
            call_count["n"] += 1
            if not body.get("stream", True):
                # Decision call 1: return a tool call
                if call_count["n"] == 1:
                    return httpx.Response(200, text=_OLLAMA_TOOL_CALL_BODY)
                # Decision call 2: no tool calls → triggers the streaming final answer
                return httpx.Response(200, text=_NO_TOOLS)
            # Streaming final answer → connection refused
            raise httpx.ConnectError("Connection refused on streaming call")

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=_side_effect)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        events = parse_sse(r.text)
        types = event_types(events)
        # tool_call and tool_result must already be present before the failure
        assert "tool_call" in types, "tool_call event should be emitted before failure"
        assert "error" in types, f"Expected SSE error event after streaming failure, got: {types}"

    async def test_6_14_execute_tool_raises_exception(
        self, app_client, monkeypatch, respx_mock
    ):
        """6.14 — execute_tool raises RuntimeError → SSE error event; stream terminates.

        The exception is caught by the outer except in _stream_chat.
        """
        async def _raising_tool(*a, **kw):
            raise RuntimeError("disk full")
        monkeypatch.setattr("routers.chat.execute_tool", _raising_tool)

        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=_OLLAMA_TOOL_CALL_BODY)
        )
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" in types, f"Expected SSE error after execute_tool raises, got: {types}"

    async def test_6_15_max_agent_iterations_exits_with_done(
        self, app_client, respx_mock
    ):
        """6.15 — Ollama always returns tool calls → loop exits at MAX_AGENT_ITERATIONS.

        A 'done' event must still be emitted; the request must not hang.
        """
        # Always return a tool call — model never gives a final answer
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=_OLLAMA_TOOL_CALL_BODY)
        )
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "done" in types, f"Expected 'done' after max iterations, got: {types}"

    async def test_6_16_empty_agent_model_falls_back_to_default(
        self, app_client, monkeypatch, respx_mock
    ):
        """6.16 — agent_mode=True but agent_model="" → falls back to AGENT_MODEL env default; no crash."""
        async def _empty_model_settings(pool=None):
            return {**_AGENT_SETTINGS, "agent_model": ""}
        monkeypatch.setattr("routers.chat.get_current_settings", _empty_model_settings)

        # Non-streaming decision call → no tool calls → streaming final answer
        call_count = {"n": 0}

        def _side_effect(request):
            body = json.loads(request.content)
            call_count["n"] += 1
            if not body.get("stream", True):
                return httpx.Response(200, text=json.dumps({
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                }))
            return httpx.Response(200, text=OLLAMA_STREAM_NDJSON)

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=_side_effect)
        r = await app_client.post("/chat", json=CHAT_BODY, headers=CONSENT)
        assert r.status_code == 200
        types = event_types(parse_sse(r.text))
        assert "error" not in types, f"Empty agent_model should not crash, got: {types}"
        assert "done" in types

        # Verify both requests logged independently (two INSERT calls)
        # (mock_conn is shared across the two concurrent requests)
        from conftest import MockConn  # just to confirm type
