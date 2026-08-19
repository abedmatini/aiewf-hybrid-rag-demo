"""
Chat router — SSE streaming endpoint with agentic tool calling.

POST /chat
  Body: { "message": str, "history": [...], "user_id": str }
  Response: text/event-stream

SSE event types:
  data: {"type": "token",     "content": "..."}          — streamed LLM text
  data: {"type": "chunk",     "filename": "...", ...}    — RAG source chunk
  data: {"type": "tool_call", "name": "...", "args": {}} — agent called a tool
  data: {"type": "tool_result", "name": "...", "result": "..."} — tool output
  data: {"type": "done"}                                 — stream complete
  data: {"type": "error",    "detail": "..."}            — exception
  data: {"type": "escalation", "content": "..."}         — guardrail blocked
"""
import json
import asyncio
import os
import re
import time
from typing import AsyncGenerator

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import get_pool, KB_USER_ID
from rag import retrieve
from routers.settings import get_current_settings
from agent_tools import TOOL_DEFINITIONS, execute_tool
from harness.pipeline import run_input_guards, run_output_guards
from harness.registry import get_pack
from harness.core.guards import core_input_guards, core_output_guards

router = APIRouter()

OLLAMA_URL        = os.getenv("OLLAMA_URL", "http://localhost:11434")
# Dedicated small model for the Tier 3 YES/NO classifier.
CLASSIFIER_MODEL  = os.getenv("CLASSIFIER_MODEL", "qwen2.5:7b-instruct")
# Cosine distance gate (pgvector `<=>` operator, range 0-2).
CHITCHAT_DISTANCE_THRESHOLD = float(os.getenv("CHITCHAT_DISTANCE_THRESHOLD", "0.70"))
OLLAMA_NUM_CTX  = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
MAX_HISTORY     = int(os.getenv("MAX_HISTORY", "20"))
# Agent mode — model for tool calling (must support native function calling)
AGENT_MODEL     = os.getenv("AGENT_MODEL", "qwen2.5:7b-instruct")
MAX_AGENT_ITERATIONS = int(os.getenv("MAX_AGENT_ITERATIONS", "5"))

# ── Optional Langfuse tracing ─────────────────────────────────────────────────
# Active only when LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY are set.
# Import is lazy so a missing package doesn't break the app.
_lf_client = None

def _langfuse():
    global _lf_client
    if _lf_client is not None:
        return _lf_client
    try:
        from langfuse import Langfuse  # type: ignore
        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sk = os.getenv("LANGFUSE_SECRET_KEY", "")
        if pk and sk:
            _lf_client = Langfuse(
                public_key=pk,
                secret_key=sk,
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
    except Exception:
        pass
    return _lf_client

# Used when documents ARE retrieved — injects them into the admin system prompt.
SYSTEM_RAG = (
    "{system_prompt}\n\n"
    "## Retrieved Document Excerpts\n\n{context}"
)

# Used when KB has documents but none match this question.
SYSTEM_NO_MATCH = (
    "{system_prompt}\n\n"
    "IMPORTANT: No relevant documents were found in the knowledge base for this question. "
    "Do not answer from general knowledge. "
    "Politely tell the user this topic is not covered in the current knowledge base, "
    "and suggest they try rephrasing or ask about a topic the knowledge base covers."
)

# Used when the knowledge base is completely empty (no documents uploaded yet).
SYSTEM_EMPTY_KB = (
    "{system_prompt}\n\n"
    "IMPORTANT: The knowledge base is currently empty — no documents have been uploaded yet. "
    "Do not answer from general knowledge. "
    "Tell the user the knowledge base has no documents and they should ask an administrator "
    "to upload relevant content before using the chat."
)


# ── Tier 0 — chitchat bypass ──────────────────────────────────────────────────
# Messages that match are answered with a canned response, bypassing all
# guardrail LLM calls, RAG retrieval, and the main Ollama generation entirely.

_TIER0_CHITCHAT = re.compile(
    r"""^\s*(
      # ── Greetings (bare word + optional follow-up word + optional punctuation) ──
      (hi|hello|hey|hiya|howdy|greetings|salutations|yo|sup|heya|helo|ello|hiya)
        (\s+(there|everyone|all|guys|folks|friend|friends|team|partner|mate|buddy|world|again))?
        [!.,\s]*
      | (morning|afternoon|evening)[!.,\s]*
      | good\s+(morning|afternoon|evening|day|night)(\s+everyone|\s+all|\s+there)?[!.,\s]*

      # ── Combined greeting + how are you ────────────────────────────────
      | (hi|hello|hey|hiya|howdy)[,!\s]+how\s+are\s+(you|u)(\s+(doing|today|going))?[?!.,\s]*
      | (hi|hello|hey)[,!\s]+how('s|\s+is)\s+(it|it\s+going|everything|things)[?!.,\s]*
      | (hi|hello|hey)[,!\s]+what('s|\s+is)\s+up[?!.,\s]*

      # ── How are you (standalone) ────────────────────────────────────────
      | how\s+are\s+(you|u)(\s+(doing|today|going))?[?!.,\s]*
      | how\s+r\s+u[?!.,\s]*
      | how('s|\s+is)\s+(it|it\s+going|everything|life|things|your\s+day)[?!.,\s]*
      | how('s|\s+is)\s+your\s+day(\s+going)?[?!.,\s]*
      | (what('s|\s+is)\s+up|wassup|whats\s+up|wazzup|sup\s+man|sup\s+bro)[?!.,\s]*
      | how\s+do\s+you\s+do[?!.,\s]*
      | how\s+have\s+you\s+been[?!.,\s]*
      | (you\s+(ok|good|alright)|all\s+good)[?!.,\s]*
      | how\s+you\s+(doing|been)(\s+today)?[?!.,\s]*
      | you\s+doing\s+(ok|good|alright|well)[?!.,\s]*
      | hope\s+you('re|\s+are)\s+(well|doing\s+well|good)[?!.,\s]*

      # ── Identity / capability ───────────────────────────────────────────
      | (who|what)\s+are\s+you[?!.,\s]*
      | what\s+is\s+this(\s+chatbot|\s+assistant|\s+bot|\s+tool|\s+thing)?[?!.,\s]*
      | are\s+you\s+(a\s+)?(bot|ai|robot|chatbot|virtual\s+assistant|human|real|assistant|person|program)[?!.,\s]*
      | are\s+you\s+(real|alive|sentient|intelligent)[?!.,\s]*
      | (tell|describe)\s+(me\s+)?about\s+yourself[?!.,\s]*
      | what\s+can\s+you\s+do(\s+for\s+me)?[?!.,\s]*
      | what\s+do\s+you\s+do[?!.,\s]*
      | how\s+can\s+(you\s+help|i\s+use\s+you|this\s+work)(\s+me)?[?!.,\s]*
      | how\s+do\s+you\s+(work|help|function)[?!.,\s]*
      | (can|could)\s+you\s+help(\s+me)?[?!.,\s]*
      | what\s+(are\s+your\s+)?(capabilities|features|skills|functions)[?!.,\s]*
      | what\s+can\s+i\s+(ask|tell|say\s+to)\s+(you)?[?!.,\s]*
      | what\s+(topics?|questions?|things?|subjects?|areas?)\s+(can|do|will)\s+you\s+(help\s+with|answer|cover|handle|discuss)[?!.,\s]*
      | what\s+do\s+you\s+(know(\s+about)?|cover|handle|help\s+with|speciali[sz]e\s+in)[?!.,\s]*
      | what\s+are\s+you\s+(good|designed|built|trained|meant)\s+(at|for|to\s+do)[?!.,\s]*
      | how\s+does\s+(this\s+)?(chatbot|assistant|chat|bot|ai|thing)\s+work[?!.,\s]*
      | what\s+is\s+your\s+(purpose|goal|function|role|name|job)[?!.,\s]*
      | (what\s+should\s+i|what\s+can\s+i)\s+(ask|know|say)[?!.,\s]*
      | (help|help\s+me)[?!.,\s]*
      | can\s+you\s+(tell\s+me\s+)?what\s+you\s+(can\s+do|do|help\s+with)[?!.,\s]*

      # ── Acknowledgements ────────────────────────────────────────────────
      | (ok|okay|k|kk)[!.,\s]*
      | (ok|okay)\s*(,\s*)?(thanks?|thank\s+you|got\s+it)[!.,\s]*
      | (thanks?|thank\s+you|thx|ty|cheers|much\s+appreciated|appreciate\s+(it|that))[!.,\s]*
      | (thanks?\s+a\s+(lot|bunch|ton|million))[!.,\s]*
      | (cool|great|awesome|perfect|wonderful|nice|excellent|fantastic|brilliant|superb|splendid)[!.,\s]*
      | (cool|great|awesome|perfect|nice)\s+(thanks?|thank\s+you)[!.,\s]*
      | (noted|got\s+it|understood|makes?\s+sense|i\s+see|got\s+that|roger|copy\s+that)[!.,\s]*
      | got\s+it[,!\s]*(thanks?|thank\s+you)?[!.,\s]*
      | (alright|alrighty|sure|sure\s+thing|sounds?\s+good|sounds?\s+(great|perfect))[!.,\s]*
      | that('s|\s+is)\s+(great|helpful|perfect|good|fine|clear|useful|exactly\s+what\s+i\s+needed)[!.,\s]*
      | that\s+(helped|helped\s+a\s+(lot|lot))[!.,\s]*
      | (very|super|really|so)\s+(helpful|useful|clear)[!.,\s]*
      | (no\s+problem|no\s+worries|np|don't\s+worry|of\s+course)[!.,\s]*
      | (i\s+understand|i\s+get\s+it|i\s+see\s+now|makes\s+sense\s+now)[!.,\s]*
      | (clear|crystal\s+clear|loud\s+and\s+clear)[!.,\s]*

      # ── Farewells ────────────────────────────────────────────────────────
      | (bye|goodbye|farewell|ciao|tata|laters?|night)[!.,\s]*
      | see\s+(you|ya)(\s+(later|soon|around|tomorrow|next\s+time))?[!.,\s]*
      | (catch\s+you|talk\s+to\s+you|speak\s+to\s+you)\s+(later|soon)[!.,\s]*
      | talk\s+(soon|later|to\s+you\s+later)[!.,\s]*
      | (ttyl|ttys|bbl|brb)[!.,\s]*
      | take\s+care(\s+of\s+yourself)?[!.,\s]*
      | stay\s+(safe|well)[!.,\s]*
      | have\s+a\s+(good|nice|great|wonderful|lovely|fantastic|blessed)\s+(day|one|evening|night|weekend|rest\s+of\s+(your\s+day|the\s+day))[!.,\s]*
      | (good\s+night|good\s+evening|gn)[!.,\s]*
      | (peace|peace\s+out|later\s+man|later\s+mate)[!.,\s]*
      | until\s+(next\s+time|then|later)[!.,\s]*
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# Sub-patterns to pick the right canned response
_T0_FAREWELL    = re.compile(r"bye|goodbye|farewell|ciao|tata|see\s+(you|ya)|take\s+care|stay\s+safe|good\s+night|have\s+a\s+\w+\s+(day|evening|night|weekend)", re.I)
_T0_ACK         = re.compile(r"^(ok|okay|k|kk|thanks?|thank\s+you|thx|ty|cheers|noted|got\s+it|understood|makes?\s+sense|alright|no\s+problem|no\s+worries|np|sounds?\s+good|that('s|\s+is)\s+\w+)", re.I)
_T0_HOW_ARE_YOU = re.compile(r"how\s+are\s+(you|u)|how\s+r\s+u|how('s|\s+is)\s+(it|everything|things|life|your\s+day)|what('s|\s+is)\s+up|wassup|how\s+you\s+(doing|been)|hope\s+you.*well", re.I)
_T0_CAPABILITY  = re.compile(r"who\s+are\s+you|what\s+are\s+you|are\s+you\s+(a\s+)?(bot|ai|robot|chatbot|human|assistant)|tell.*about\s+yourself|what\s+can\s+you\s+do|what\s+do\s+you\s+do|how\s+(can|do)\s+you\s+(help|work)|capabilities|features|help\s+me|what\s+(topics|subjects|things|can\s+i\s+ask)|purpose|function|role|name", re.I)

_RESP_GREETING = (
    "Hi there! \U0001f44b I'm the FAQ assistant.\n\n"
    "I can help with questions answered in our uploaded FAQ documents \u2014 "
    "policies, procedures, product details, troubleshooting steps, and more.\n\n"
    "What would you like to know?"
)
_RESP_HOW_ARE_YOU = (
    "Doing great, thanks for asking! \U0001f60a "
    "I'm here and ready to help with any questions covered in our FAQ knowledge base.\n\n"
    "What would you like to know?"
)
_RESP_CAPABILITY = (
    "I'm the FAQ assistant. Here\u2019s what I can help with:\n\n"
    "\u2022 **Policy & procedure** \u2014 returns, shipping, account rules, eligibility\n"
    "\u2022 **How-to guidance** \u2014 setup steps, troubleshooting, configuration\n"
    "\u2022 **Product & service details** \u2014 features, specs, compatibility, pricing tiers\n"
    "\u2022 **Comparisons** \u2014 differences between plans, products, or options\n\n"
    "I answer only from approved FAQ documents. "
    "For account-specific or personal matters, please contact support directly.\n\n"
    "What would you like to know?"
)
_RESP_ACK = (
    "You\u2019re welcome! Let me know if you have any other FAQ questions. \U0001f60a"
)
_RESP_FAREWELL = (
    "Goodbye! \U0001f44b Have a great day. "
    "Feel free to come back anytime with more FAQ questions."
)


def _check_tier0(text: str) -> str | None:
    """Return a canned response for chitchat / greetings, or None to continue normal flow."""
    if not _TIER0_CHITCHAT.match(text.strip()):
        return None
    if _T0_FAREWELL.search(text):
        return _RESP_FAREWELL
    if _T0_ACK.match(text.strip()):
        return _RESP_ACK
    if _T0_HOW_ARE_YOU.search(text):
        return _RESP_HOW_ARE_YOU
    if _T0_CAPABILITY.search(text):
        return _RESP_CAPABILITY
    return _RESP_GREETING


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    user_id: str = "anonymous"
    agent_mode: bool = True  # Toggle agent mode from frontend


# ── Agent system prompt ───────────────────────────────────────────────────────

_AGENT_SYSTEM = (
    "{system_prompt}\n\n"
    "## Your Tools\n"
    "You have access to tools to search the FAQ knowledge base. "
    "IMPORTANT RULES:\n"
    "- Use search_kb to find answers — do NOT guess\n"
    "- You can search multiple times with different queries if the first search doesn't find what you need\n"
    "- Use compare_products when the user asks to compare two topics or documents\n"
    "- Always cite the document name and section in your answer\n"
    "- If no relevant information is found after searching, say so clearly\n"
    "- Only answer from knowledge base content — never from general knowledge\n"
    "- For account-specific or personal matters, direct the user to contact support\n"
    "- Use get_current_date when time/date information is relevant\n"
    "- Use calculate for any dosage math or conversions"
)


async def _stream_chat(request: ChatRequest) -> AsyncGenerator[str, None]:
    pool = await get_pool()

    # State collected for the interaction log
    start_time:     float      = time.monotonic()
    full_response:  str        = ""
    event_type:     str        = "chat"
    sources_logged: list[dict] = []
    chat_model:     str        = ""
    top_k:          int        = 5
    prompt_tokens:  int        = 0
    output_tokens:  int        = 0
    lf_trace                   = None
    lf_gen                     = None

    lf = _langfuse()
    if lf:
        try:
            lf_trace = lf.trace(
                name="faq-agentic-chat",
                input=request.message,
                user_id=request.user_id,
                metadata={
                    "agent_mode": request.agent_mode,
                    "history_turns": len(request.history) // 2,
                },
            )
        except Exception:
            pass

    try:
        # ── Tier 0: instant chitchat bypass ──────────────────────────────
        tier0_reply = _check_tier0(request.message)
        if tier0_reply:
            event_type    = "chitchat"
            full_response = tier0_reply
            yield f"data: {json.dumps({'type': 'token', 'content': tier0_reply})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Load live settings from DB
        settings = await get_current_settings(pool)
        chat_model         = settings["chat_model"]
        top_k              = settings["top_k"]
        system_prompt      = settings["system_prompt"]
        escalation_message = settings["escalation_message"]
        use_agent_mode     = settings.get("agent_mode", True)
        agent_model        = settings.get("agent_model", AGENT_MODEL)
        # Tier-3 guard model (Llama Guard 3) is admin-controlled: enabled flag +
        # model name. Empty string disables the guard-model layer entirely.
        guard_model = (
            settings.get("guard_model", "") if settings.get("guard_model_enabled") else ""
        )
        # Active domain pack — read live from DB so admin can switch without restart
        domain = settings.get("domain", os.getenv("DOMAIN", "health_faq"))

        # ── Input guards (Core + Domain Pack) ───────────────────────────────────
        # Core guards (crisis, prompt-injection, PII redaction) run on every
        # deployment, then the pack selected per-deployment via the DOMAIN env
        # var (default "health"). For health the pack runs Tier 1+2 (regex/
        # terms) then Tier 3 (LLM classifier) — identical to pre-harness code.
        pack = get_pack(domain=domain, classifier_model=CLASSIFIER_MODEL)
        outcome = await run_input_guards(
            message=request.message,
            ollama_url=OLLAMA_URL,
            pack=pack,
            core_guards=core_input_guards(guard_model),
            history=request.history,
        )
        if outcome.blocked:
            event_type    = "escalation"
            block_message = outcome.escalation_override or escalation_message
            full_response = block_message
            yield f"data: {json.dumps({'type': 'escalation', 'content': block_message})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Apply any PII redaction to the working message so the cleaned text is
        # what gets logged, retrieved on, and sent to the model.
        if outcome.message != request.message:
            request.message = outcome.message


        # ── Route: Agent mode or direct RAG (controlled by DB settings) ───────
        if use_agent_mode:
            async for event in _run_agent_loop(
                request=request,
                pool=pool,
                system_prompt=system_prompt,
                chat_model=chat_model,
                agent_model=agent_model,
                top_k=top_k,
                escalation_message=escalation_message,
                guard_model=guard_model,
                domain=domain,
                lf_trace=lf_trace,
            ):
                # Capture full_response and sources from events for logging
                try:
                    parsed = json.loads(event.replace("data: ", "").strip())
                    if parsed.get("type") == "token":
                        full_response += parsed.get("content", "")
                    elif parsed.get("type") == "chunk":
                        sources_logged.append({
                            "filename": parsed.get("filename"),
                            "section": parsed.get("section"),
                        })
                except Exception:
                    pass
                yield event
            event_type = "agent"
        else:
            # ── Direct RAG (agent mode off in settings) ───────────────────
            async for event in _run_direct_rag(
                request=request,
                pool=pool,
                system_prompt=system_prompt,
                chat_model=chat_model,
                top_k=top_k,
                escalation_message=escalation_message,
                guard_model=guard_model,
                domain=domain,
                lf_trace=lf_trace,
            ):
                try:
                    parsed = json.loads(event.replace("data: ", "").strip())
                    if parsed.get("type") == "token":
                        full_response += parsed.get("content", "")
                    elif parsed.get("type") == "chunk":
                        sources_logged.append({
                            "filename": parsed.get("filename"),
                            "section": parsed.get("section"),
                        })
                except Exception:
                    pass
                yield event
            if not sources_logged:
                event_type = "no_match"

    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    finally:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO chat_logs
                        (user_id, message, response, model, top_k, sources, event_type, duration_ms)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                    """,
                    request.user_id,
                    request.message,
                    full_response or None,
                    chat_model or AGENT_MODEL,
                    top_k,
                    json.dumps(sources_logged),
                    event_type,
                    duration_ms,
                )
        except Exception:
            pass
        if lf_trace:
            try:
                lf_trace.update(
                    output=full_response,
                    tags=[event_type, "agent" if request.agent_mode else "direct"],
                    metadata={
                        "event_type": event_type,
                        "agent_mode": request.agent_mode,
                        "model": chat_model or AGENT_MODEL,
                        "top_k": top_k,
                        "duration_ms": duration_ms,
                        "rag_chunks": len(sources_logged),
                        "sources": [s["filename"] for s in sources_logged],
                    },
                )
            except Exception:
                pass
        if lf:
            try:
                lf.flush()
            except Exception:
                pass


# ── Output guards (buffer-then-stream) ───────────────────────────────────────

async def _emit_guarded_answer(
    *,
    draft: str,
    message: str,
    sources: list[dict],
    system_prompt: str,
    escalation_message: str,
    history: list[dict],
    guard_model: str = "",
    domain: str = "",
) -> AsyncGenerator[str, None]:
    """
    Run Core + Pack output guards over the buffered draft answer, then emit it.

    On block → emit a safe replacement (guard override or the deployment's
    escalation message). On pass → emit the (possibly PII-redacted) answer.
    The vetted text is sent as a single token event so no unsafe token is ever
    streamed to the user before the checks complete.
    """
    pack = get_pack(domain=domain or os.getenv("DOMAIN", "health_faq"), classifier_model=CLASSIFIER_MODEL)
    outcome = await run_output_guards(
        message=message,
        draft_response=draft,
        ollama_url=OLLAMA_URL,
        pack=pack,
        core_guards=core_output_guards(guard_model),
        sources=sources,
        history=history,
        system_prompt=system_prompt,
    )
    if outcome.blocked:
        safe = outcome.escalation_override or escalation_message
        yield f"data: {json.dumps({'type': 'token', 'content': safe})}\n\n"
    elif outcome.response:
        yield f"data: {json.dumps({'type': 'token', 'content': outcome.response})}\n\n"


# ── Agent Loop ────────────────────────────────────────────────────────────────

async def _run_agent_loop(
    *,
    request: ChatRequest,
    pool,
    system_prompt: str,
    chat_model: str,
    agent_model: str,
    top_k: int,
    escalation_message: str,
    guard_model: str = "",
    domain: str = "",
    lf_trace,
) -> AsyncGenerator[str, None]:
    """ReAct-style agent loop with tool calling via Ollama."""

    system = _AGENT_SYSTEM.format(system_prompt=system_prompt)
    history = request.history[-MAX_HISTORY:]

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": request.message})

    collected_sources: list[dict] = []
    iteration = 0

    while iteration < MAX_AGENT_ITERATIONS:
        iteration += 1

        # Call Ollama with tools (non-streaming to get tool_calls)
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{OLLAMA_URL.rstrip('/')}/api/chat",
                    json={
                        "model": agent_model,
                        "messages": messages,
                        "tools": TOOL_DEFINITIONS,
                        "stream": False,
                        "options": {"num_ctx": OLLAMA_NUM_CTX},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': f'Agent error: {exc}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        response_message = data.get("message", {})
        tool_calls = response_message.get("tool_calls", [])

        # If no tool calls, the model is done — stream the final answer
        if not tool_calls:
            # Re-request with streaming, but BUFFER the answer so output guards
            # can vet the full text before any token reaches the user.
            buffer: list[str] = []
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL.rstrip('/')}/api/chat",
                    json={
                        "model": agent_model,
                        "messages": messages,
                        "stream": True,
                        "options": {"num_ctx": OLLAMA_NUM_CTX},
                    },
                ) as stream_resp:
                    stream_resp.raise_for_status()
                    async for line in stream_resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk_data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token = chunk_data.get("message", {}).get("content", "")
                        if token:
                            buffer.append(token)
                        if chunk_data.get("done"):
                            break

            # ── Output guards (buffer-then-stream) ─────────────────────────
            async for ev in _emit_guarded_answer(
                draft="".join(buffer),
                message=request.message,
                sources=collected_sources,
                system_prompt=system_prompt,
                escalation_message=escalation_message,
                history=request.history,
                guard_model=guard_model,                domain=domain,            ):
                yield ev

            # Emit collected sources as chunk events
            for c in collected_sources:
                yield f"data: {json.dumps({'type': 'chunk', 'filename': c['filename'], 'section': c.get('section_heading') or '', 'content': c['content']})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            # Langfuse span
            if lf_trace:
                try:
                    lf_trace.span(
                        name="agent_complete",
                        metadata={"iterations": iteration, "tools_used": iteration - 1},
                    )
                except Exception:
                    pass
            return

        # ── Execute tool calls ────────────────────────────────────────────
        messages.append(response_message)

        for tool_call in tool_calls:
            func = tool_call.get("function", {})
            tool_name = func.get("name", "unknown")
            tool_args = func.get("arguments", {})

            # Emit tool_call event to frontend
            yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'args': tool_args})}\n\n"

            # Execute the tool
            tool_result = await execute_tool(
                tool_name=tool_name,
                arguments=tool_args,
                pool=pool,
                kb_user_id=KB_USER_ID,
                ollama_url=OLLAMA_URL,
                top_k=top_k,
            )

            # Track sources from search_kb for citations
            if tool_name == "search_kb" and "No relevant" not in tool_result:
                try:
                    from rag import retrieve as _retrieve
                    query = tool_args.get("query", "")
                    if query:
                        chunks = await _retrieve(
                            pool=pool, user_id=KB_USER_ID,
                            query=query, ollama_url=OLLAMA_URL, top_k=top_k,
                        )
                        collected_sources.extend(chunks)
                except Exception:
                    pass

            # Emit tool_result event (truncated for UI)
            display_result = tool_result[:500] + "…" if len(tool_result) > 500 else tool_result
            yield f"data: {json.dumps({'type': 'tool_result', 'name': tool_name, 'result': display_result})}\n\n"

            # Langfuse span for tool
            if lf_trace:
                try:
                    lf_trace.span(
                        name=f"tool:{tool_name}",
                        input=tool_args,
                        output=tool_result[:500],
                        metadata={"iteration": iteration},
                    )
                except Exception:
                    pass

            # Feed result back to model
            messages.append({
                "role": "tool",
                "content": tool_result,
            })

    # Max iterations reached
    yield f"data: {json.dumps({'type': 'token', 'content': 'I reached the maximum number of search steps. Please try rephrasing your question.'})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ── Direct RAG (non-agent, same as original kenvue) ───────────────────────────

async def _run_direct_rag(
    *,
    request: ChatRequest,
    pool,
    system_prompt: str,
    chat_model: str,
    top_k: int,
    escalation_message: str,
    guard_model: str = "",
    domain: str = "",
    lf_trace,
) -> AsyncGenerator[str, None]:
    """Standard RAG flow: retrieve → build prompt → stream response."""

    rag_task = asyncio.create_task(
        retrieve(
            pool=pool,
            user_id=KB_USER_ID,
            query=request.message,
            ollama_url=OLLAMA_URL,
            top_k=top_k,
        )
    )

    chunks = await rag_task

    # Score gate: cosine distance threshold
    if chunks:
        best_dist = min((c.get("cosine_distance") or 1.0) for c in chunks)
        if best_dist > CHITCHAT_DISTANCE_THRESHOLD:
            chunks = []

    # Emit source chunks
    for chunk in chunks:
        yield f"data: {json.dumps({'type': 'chunk', 'filename': chunk['filename'], 'section': chunk['section_heading'] or '', 'content': chunk['content']})}\n\n"

    # Build system prompt
    if chunks:
        context = "\n\n---\n\n".join(
            f"[Source: {c['filename']} | Section: {c['section_heading'] or 'N/A'}]\n{c['content']}"
            for c in chunks
        )
        system = SYSTEM_RAG.format(system_prompt=system_prompt, context=context)
    else:
        async with pool.acquire() as conn:
            kb_has_content = await conn.fetchval(
                "SELECT 1 FROM rag_chunks WHERE user_id = $1 LIMIT 1",
                KB_USER_ID,
            )
        if kb_has_content:
            system = SYSTEM_NO_MATCH.format(system_prompt=system_prompt)
        else:
            system = SYSTEM_EMPTY_KB.format(system_prompt=system_prompt)

    history = request.history[-MAX_HISTORY:]
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": request.message})

    # Stream from Ollama, but BUFFER the answer so output guards can vet the
    # full text before any token reaches the user (buffer-then-stream).
    buffer: list[str] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_URL.rstrip('/')}/api/chat",
            json={
                "model": chat_model,
                "messages": messages,
                "stream": True,
                "options": {"num_ctx": OLLAMA_NUM_CTX},
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = data.get("message", {}).get("content", "")
                if token:
                    buffer.append(token)
                if data.get("done"):
                    break

    # ── Output guards (buffer-then-stream) ────────────────────────────────
    async for ev in _emit_guarded_answer(
        draft="".join(buffer),
        message=request.message,
        sources=chunks,
        system_prompt=system_prompt,
        escalation_message=escalation_message,
        history=request.history,        guard_model=guard_model,        domain=domain,    ):
        yield ev

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


@router.post("")
async def chat(http_req: Request, body: ChatRequest):
    if http_req.headers.get("x-consent-given") != "true":
        raise HTTPException(status_code=403, detail="consent_required")
    return StreamingResponse(
        _stream_chat(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
