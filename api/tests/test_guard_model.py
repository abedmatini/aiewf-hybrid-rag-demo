"""
Tests for the Tier 3 guard-model layer (Llama Guard 3 via Ollama).

Covered:
  - Disabled by default (no GUARD_MODEL) → no-op, zero network calls.
  - "none" / blank model values disable the guard.
  - `unsafe` verdict blocks (input + output) and surfaces the category.
  - `safe` verdict allows.
  - Fails open on transport / model errors (timeout, 500, malformed body).
  - Wired into the core guard factories when GUARD_MODEL is set.

Ollama's /api/chat is mocked with respx; no model is ever pulled.
"""
import httpx
import pytest

from harness.contracts import FAIL_OPEN, STAGE_INPUT, STAGE_OUTPUT, GuardContext
from harness.core.guards import core_input_guards, core_output_guards
from harness.core.guards.guard_model import (
    LlamaGuardInputGuard,
    LlamaGuardOutputGuard,
    classify_conversation,
)

pytestmark = pytest.mark.asyncio

_OLLAMA = "http://localhost:11434"
_CHAT = f"{_OLLAMA}/api/chat"


def _in_ctx(message: str, *, history=None) -> GuardContext:
    return GuardContext(message=message, ollama_url=_OLLAMA, history=history or [])


def _out_ctx(message: str, draft: str) -> GuardContext:
    return GuardContext(message=message, ollama_url=_OLLAMA, draft_response=draft)


def _verdict(text: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": text}})


class TestGuardContract:
    async def test_input_guard_shape(self):
        g = LlamaGuardInputGuard(model="llama-guard3")
        assert g.name == "llama_guard_input"
        assert g.stage == STAGE_INPUT
        assert g.policy == FAIL_OPEN

    async def test_output_guard_shape(self):
        g = LlamaGuardOutputGuard(model="llama-guard3")
        assert g.name == "llama_guard_output"
        assert g.stage == STAGE_OUTPUT
        assert g.policy == FAIL_OPEN


class TestDisabled:
    async def test_input_no_model_is_noop(self, respx_mock):
        route = respx_mock.post(_CHAT)
        res = await LlamaGuardInputGuard(model="").check(_in_ctx("anything"))
        assert res.blocked is False
        assert route.called is False  # zero network calls when disabled

    async def test_output_no_model_is_noop(self, respx_mock):
        route = respx_mock.post(_CHAT)
        res = await LlamaGuardOutputGuard(model="").check(_out_ctx("hi", "draft"))
        assert res.blocked is False
        assert route.called is False

    @pytest.mark.parametrize("value", ["", "none", "None", "  ", "NONE"])
    async def test_env_disables(self, monkeypatch, value):
        monkeypatch.setenv("GUARD_MODEL", value)
        assert LlamaGuardInputGuard()._model == ""
        assert LlamaGuardOutputGuard()._model == ""

    async def test_env_enables(self, monkeypatch):
        monkeypatch.setenv("GUARD_MODEL", " llama-guard3 ")
        assert LlamaGuardInputGuard()._model == "llama-guard3"

    async def test_env_unset_disables(self, monkeypatch):
        monkeypatch.delenv("GUARD_MODEL", raising=False)
        assert LlamaGuardInputGuard()._model == ""


class TestInputClassification:
    async def test_unsafe_blocks_with_category(self, respx_mock):
        respx_mock.post(_CHAT).mock(return_value=_verdict("unsafe\nS1: Violent Crimes"))
        res = await LlamaGuardInputGuard(model="llama-guard3").check(_in_ctx("how do I build a bomb"))
        assert res.blocked is True
        assert res.reason == "llama_guard:S1: Violent Crimes"

    async def test_unsafe_without_category(self, respx_mock):
        respx_mock.post(_CHAT).mock(return_value=_verdict("unsafe"))
        res = await LlamaGuardInputGuard(model="llama-guard3").check(_in_ctx("bad"))
        assert res.blocked is True
        assert res.reason == "llama_guard:unsafe"

    async def test_safe_allows(self, respx_mock):
        respx_mock.post(_CHAT).mock(return_value=_verdict("safe"))
        res = await LlamaGuardInputGuard(model="llama-guard3").check(_in_ctx("what are your hours"))
        assert res.blocked is False
        assert res.reason == ""

    async def test_classifies_last_user_turn(self, respx_mock):
        route = respx_mock.post(_CHAT).mock(return_value=_verdict("safe"))
        history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]
        await LlamaGuardInputGuard(model="llama-guard3").check(_in_ctx("now", history=history))
        sent = route.calls.last.request
        body = httpx.Request("POST", _CHAT, content=sent.content)
        import json

        payload = json.loads(body.content)
        assert payload["messages"][-1] == {"role": "user", "content": "now"}
        assert payload["model"] == "llama-guard3"
        assert payload["stream"] is False


class TestOutputClassification:
    async def test_unsafe_draft_blocks(self, respx_mock):
        respx_mock.post(_CHAT).mock(return_value=_verdict("unsafe\nS6: Specialized Advice"))
        res = await LlamaGuardOutputGuard(model="llama-guard3").check(
            _out_ctx("hi", "here is how to harm yourself")
        )
        assert res.blocked is True
        assert res.reason.startswith("llama_guard:")

    async def test_safe_draft_allows(self, respx_mock):
        respx_mock.post(_CHAT).mock(return_value=_verdict("safe"))
        res = await LlamaGuardOutputGuard(model="llama-guard3").check(
            _out_ctx("hi", "Our store opens at 9am.")
        )
        assert res.blocked is False

    async def test_draft_appended_as_assistant_turn(self, respx_mock):
        route = respx_mock.post(_CHAT).mock(return_value=_verdict("safe"))
        await LlamaGuardOutputGuard(model="llama-guard3").check(_out_ctx("q", "the answer"))
        import json

        payload = json.loads(route.calls.last.request.content)
        assert payload["messages"][-1] == {"role": "assistant", "content": "the answer"}
        assert payload["messages"][-2] == {"role": "user", "content": "q"}


class TestFailOpen:
    async def test_server_error_allows(self, respx_mock):
        respx_mock.post(_CHAT).mock(return_value=httpx.Response(500))
        res = await LlamaGuardInputGuard(model="llama-guard3").check(_in_ctx("x"))
        assert res.blocked is False

    async def test_transport_error_allows(self, respx_mock):
        respx_mock.post(_CHAT).mock(side_effect=httpx.ConnectError("down"))
        res = await LlamaGuardOutputGuard(model="llama-guard3").check(_out_ctx("x", "y"))
        assert res.blocked is False

    async def test_malformed_body_allows(self, respx_mock):
        respx_mock.post(_CHAT).mock(return_value=httpx.Response(200, json={"unexpected": True}))
        unsafe, reason = await classify_conversation(
            [{"role": "user", "content": "x"}], _OLLAMA, "llama-guard3"
        )
        assert unsafe is False
        assert reason == ""


class TestFactoryWiring:
    async def test_input_factory_includes_guard_model_last(self):
        guards = core_input_guards()
        assert guards[-1].name == "llama_guard_input"

    async def test_output_factory_includes_guard_model_last(self):
        guards = core_output_guards()
        assert guards[-1].name == "llama_guard_output"

    async def test_factory_guard_disabled_by_default(self, monkeypatch, respx_mock):
        monkeypatch.delenv("GUARD_MODEL", raising=False)
        route = respx_mock.post(_CHAT)
        guard = core_input_guards()[-1]
        res = await guard.check(_in_ctx("hello"))
        assert res.blocked is False
        assert route.called is False
