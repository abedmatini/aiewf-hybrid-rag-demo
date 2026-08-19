# AIEWF Hybrid RAG Demo

> Reference implementation for **"Bypassing the Multimodal Tax: Framework-Free Hybrid RAG, Raw SQL RRF, and Live UI Telemetry"** — AI Engineer World's Fair 2026, Online Track. Every architectural claim in the talk maps to a file in this repo.

**Talk recording:** https://www.youtube.com/watch?v=Akm1sqvWG4A
**Companion article:** https://abedmatini.hashnode.dev/bypassing-the-multimodal-tax-framework-free-hybrid-rag-raw-sql-rrf-and-live-ui-telemetry
**Author:** https://abedmatini.com/

A production-grade **FastAPI + React** chatbot: local Docling ingest, hybrid retrieval (pgvector cosine + Postgres full-text, merged with Reciprocal Rank Fusion in plain Python — no vector DB, no LangChain), Ollama for local embeddings/chat, and agentic tool calling — the LLM autonomously decides which tools to invoke (search, compare, calculate) using a ReAct-style loop, with a layered guardrail pipeline in front of it.

---

## What this is

Instead of a fixed "retrieve → generate" pipeline, the model receives tool definitions and decides autonomously when and how to search, compare topics, or calculate. Guardrails still fire **before** the agent loop, so unsafe/off-topic questions are always intercepted.

```
api/    ← FastAPI backend: rag.py (hybrid RRF retrieval), agent_tools.py, harness/ + packs/ (guardrails)
ui/     ← Vite + React frontend (chat, admin panel, tool step cards, embeddable widget)
```

## Agent Tools

| Tool | Description |
|------|-------------|
| `search_kb` | Semantic RAG retrieval with model-chosen query |
| `list_products` | List all indexed KB documents with chunk counts |
| `get_product_info` | Get first N sections of a specific product doc |
| `compare_products` | Parallel retrieval for two topics, returns both |
| `get_current_date` | Today's date/time for time-sensitive questions |
| `calculate` | Safe math evaluator for dosage/unit calculations |

## SSE Events

The chat endpoint streams these event types:

```
tool_call    → { "type": "tool_call", "name": "search_kb", "args": {...} }
tool_result  → { "type": "tool_result", "name": "search_kb", "result": "..." }
token        → { "type": "token", "content": "..." }
chunk        → { "type": "chunk", "filename": "...", "section": "...", "content": "..." }
escalation   → { "type": "escalation", "content": "..." }
done         → { "type": "done" }
error        → { "type": "error", "detail": "..." }
```

---

## How the Agent Works

### What "tool calling" actually means

Each tool is two things that never touch each other directly:

**1. A JSON description** (in `TOOL_DEFINITIONS`) sent to Ollama alongside the user's message. This tells the model what tools exist, what they do, and what arguments they accept:

```python
{
    "type": "function",
    "function": {
        "name": "search_kb",
        "description": "Search the Kenvue product knowledge base...",
        "parameters": {
            "type": "object",
            "properties": {
                "query": { "type": "string", "description": "..." }
            },
            "required": ["query"]
        }
    }
}
```

**2. A Python async function** (`execute_search_kb`, `execute_calculate`, etc.) that actually runs when the model picks that tool.

The model never calls Python directly. It reads the JSON descriptions, decides which tool it wants to use, and responds with a structured JSON object: *"I want to call `search_kb` with `query='Tylenol dosage for children'`"*. Your code reads that, dispatches to the right Python function, gets a string result back, appends it to the conversation, and sends everything back to the model. The model is the decision-maker; Python is the executor.

### The ReAct loop

```
User question
      │
      ▼
① Send message + tool definitions to Ollama (non-streaming, to get tool decision)
      │
      ├── Model responds with tool_call ──► Execute Python function
      │                                     Append result to messages
      │                                     ◄── Loop back to ①
      │                                         (up to MAX_AGENT_ITERATIONS=5)
      │
      └── Model responds with no tool_call ──► Re-call Ollama with streaming=True
                                               Stream tokens to frontend
                                               Emit collected source chunks
                                               done
```

Every tool call costs one extra round-trip to Ollama (~1–3s each). A question that triggers two tool calls before answering takes 3 Ollama calls total: decision call 1, decision call 2, final streaming call.

### How `agent_tools.py` is structured

```
TOOL_DEFINITIONS          ← list of JSON schemas sent to Ollama
safe_calculate()          ← sandboxed math evaluator (no eval with builtins)
execute_search_kb()       ← calls rag.retrieve(), formats chunks as text
execute_list_products()   ← calls rag.list_documents(), returns formatted list
execute_get_product_info()← queries rag_chunks table directly for a named doc
execute_compare_products()← asyncio.gather() two retrieve() calls in parallel
execute_get_current_date()← datetime.now(), formatted string
execute_calculate()       ← delegates to safe_calculate()
execute_tool()            ← dispatcher: tool name → correct executor function
```

`execute_tool()` is the only function called by `chat.py` — it's a name-based switch that routes to the right executor. Adding a new tool means: add a dict to `TOOL_DEFINITIONS`, write an `async def execute_<name>()`, add one `elif` in `execute_tool()`.

---

## Alternative Agent Approaches

The current implementation uses raw Python functions with Ollama's native function-calling API directly. Here's how that compares to the three main alternatives:

### Option A — Current: Raw Python functions + Ollama API directly ✅ (chosen)

Every tool is a plain `async def`. The dispatch loop is ~50 lines in `chat.py`. Ollama receives the tool definitions as JSON and returns structured tool call decisions.

**Pros:**
- Full visibility into every message sent to and received from Ollama — nothing is hidden behind a framework
- Zero framework dependency; the entire agent logic is readable in two files (`chat.py` + `agent_tools.py`)
- Easy to debug: add a `print()` anywhere in the loop and see exactly what the model decided
- Adding a tool is three steps: one dict, one function, one `elif`
- No risk of a framework update breaking the Ollama integration

**Cons:**
- The dispatch loop is manual — parallel tool execution, retry logic, and tool chaining with conditional branching all require custom code
- As the number of tools grows (15+), managing TOOL_DEFINITIONS and the dispatcher by hand gets repetitive
- No built-in memory management, streaming parsers, or multi-agent coordination

**Best for:** 1–10 tools, a linear loop, and a team that wants to understand every line of the agent logic. This is the right choice for this project at its current scale.

---

### Option B — LangChain / LangGraph

Tools are defined with a `@tool` decorator. LangChain manages message formatting, the loop, memory, and retries. LangGraph adds stateful directed graphs — different tools can have different next steps depending on their output.

```python
# LangChain equivalent of search_kb
from langchain.tools import tool

@tool
def search_kb(query: str) -> str:
    """Search the Kenvue product knowledge base."""
    return retrieve(query)

agent = create_react_agent(llm, [search_kb, list_products, calculate])
```

**Pros:**
- The loop, message formatting, and error handling are handled for you
- LangGraph enables complex conditional flows (if tool A fails → try tool B)
- Large ecosystem of pre-built tools (web search, SQL, calculator, etc.)
- Good for multi-agent pipelines (Agent A hands off to Agent B)

**Cons:**
- Heavy dependency (~150 MB, many transitive packages)
- Adds abstraction between your code and the Ollama API — debugging means reading LangChain internals, not your own code
- Ollama compatibility requires `langchain-ollama` and version pinning; updates often break things
- Framework makes assumptions about message format that don't always match Ollama's actual API behaviour
- Overkill for a linear loop with 6 tools

**Best for:** Complex multi-agent pipelines, 15+ tools with conditional branching, or teams already invested in the LangChain ecosystem.

---

### Option C — LlamaIndex AgentRunner

Similar to LangChain but more RAG-focused. Tools are wrapped query engines. The `AgentRunner` manages the step-based execution.

```python
from llama_index.core.agent import ReActAgent
from llama_index.core.tools import FunctionTool

search_tool = FunctionTool.from_defaults(fn=search_kb, name="search_kb")
agent = ReActAgent.from_tools([search_tool], llm=ollama_llm)
```

**Pros:**
- Designed around retrieval — native integration with vector stores, retrievers, and query pipelines
- `SubQuestionQueryEngine` can decompose a question into sub-queries automatically
- Good abstractions for document-centric tools

**Cons:**
- Same abstraction cost as LangChain — harder to debug, heavier install
- The RAG pipeline is already written manually in `rag.py` and works well; wrapping it in LlamaIndex abstractions would obscure it without adding value
- Less flexible for custom SSE streaming — the current implementation streams tokens as they arrive, which LlamaIndex's agent runner doesn't expose directly

**Best for:** Projects building on LlamaIndex's retrieval primitives from the start, or when you want auto-decomposition of complex multi-hop questions.

---

### Option D — MCP (Model Context Protocol)

A newer standard where tools are exposed as a separate server over a standardised JSON-RPC protocol. The LLM client connects to the MCP server; tools don't have to be in the same process or even language.

```
Chat server (Python)  ──MCP──►  Tool server (Node.js, Python, Go, etc.)
                                   search_kb tool
                                   calculate tool
                                   list_products tool
```

**Pros:**
- Tools can run anywhere — separate process, separate machine, different language
- A single MCP tool server can be shared across multiple chat applications
- Hot-swappable: add or remove tools from the MCP server without restarting the chat API
- Emerging standard — growing IDE and framework support

**Cons:**
- More infrastructure: you now run and maintain two separate services instead of one
- Adds network latency for every tool call (local loopback is fast; remote adds real overhead)
- MCP spec is still evolving — breaking changes are more likely than with a stable Python library
- Complete overkill for a single-app deployment where tools and chat logic share the same codebase

**Best for:** Platform products where the same tools need to be accessible from multiple applications (chatbot + IDE assistant + API + CLI), or when tool implementations need to be in a different language or managed by a different team.

---

### Decision summary

| Criterion | Raw Python | LangChain/LangGraph | LlamaIndex | MCP |
|---|---|---|---|---|
| Debuggability | ✅ Full visibility | ❌ Framework abstracts internals | ❌ Framework abstracts internals | ⚠️ Two services to debug |
| Dependency weight | ✅ Zero extra | ❌ ~150 MB | ❌ ~100 MB | ⚠️ Separate server |
| Ollama compatibility | ✅ Native | ⚠️ Needs langchain-ollama | ⚠️ Needs llama-index-llms-ollama | ✅ Protocol-level |
| Custom SSE streaming | ✅ Full control | ❌ Hard to expose | ❌ Hard to expose | ✅ Possible |
| Adding a tool | ✅ 3 steps | ✅ 1 decorator | ✅ 1 wrapper | ⚠️ Register in 2 places |
| Complex tool graphs | ⚠️ Manual code | ✅ LangGraph | ⚠️ Limited | ✅ Composable |
| Good for 1–10 tools | ✅ Ideal | ⚠️ Overkill | ⚠️ Overkill | ❌ Overkill |
| Good for 15+ tools | ⚠️ Gets verbose | ✅ Ideal | ✅ Good | ✅ Good |

**Chosen: raw Python.** The project has 6 tools, a linear loop, and a custom SSE streaming implementation that needs full control over the Ollama API. LangChain would add 150 MB of dependencies and hide the exact messages going to Ollama — the opposite of what's needed for a system that needs to be debuggable and transparent. If the tool count grew to 15+ with conditional branching between them, LangGraph would become the right call.

### Backend

| Endpoint | What it does |
|---|---|
| `POST /chat` | SSE streaming chat. Reads `chat_model`, `top_k`, `system_prompt` from DB on every request. Retrieves from `kenvue_kb` namespace. Includes Tier 0 instant chitchat bypass (regex, no DB), three-tier HCP medical guardrail, and cosine distance score gate (rejects answers when best chunk distance > threshold). |
| `POST /documents/upload` | Docling parse → markdown → chunk → embed → store. Strategy chosen at upload time. |
| `GET /documents` | Lists all KB documents with status, chunk count, strategy, date. |
| `GET /documents/{id}/chunks` | Returns every chunk for a document (index, heading, content — no vectors). |
| `PUT /documents/{id}/chunks/{chunk_id}` | Saves edited chunk text and regenerates its embedding in place. |
| `PATCH /documents/{id}/archive` | Excludes document from retrieval without deleting it. |
| `PATCH /documents/{id}/restore` | Re-activates an archived document. |
| `DELETE /documents/{id}` | Permanently removes document and all its chunks. |
| `GET /settings` | Returns current `chat_model`, `top_k`, `system_prompt`, `agent_mode`, `agent_model`, `escalation_message` from `kenvue_settings` table. |
| `PUT /settings` | Upserts all settings keys. Changes apply to the next chat request — no restart needed. |
| `GET /settings/agents` | Returns all 6 agent tool definitions (name + description). Used by the admin Settings tab to render the tool list. |
| `GET /models` | Queries the live Ollama instance and returns available model names. |
| `GET /suggestions` | Returns 4 LLM-generated sample questions grounded in actual KB chunk content. Cached 30 min per user. Falls back to empty if no documents are indexed. |
| `GET /health` | Simple liveness check. |

**Key architectural decisions:**
- All admin documents live under `KB_USER_ID = kenvue_kb` — one shared knowledge base, no per-user namespacing
- Settings stored in a DB table (`kenvue_settings`), not in `.env`, so the admin can change the model and prompt at runtime
- **Agent mode and agent model are DB-controlled** — toggle on/off and swap models from the admin Settings panel without restarting the API
- Re-embedding on chunk edit uses the same `bge-m3:latest` model as ingest
- Two separate Ollama models to avoid VRAM eviction: `medgemma:latest` (chat, 3.3 GB GPU) and `qwen2.5:7b-instruct` (Tier 3 classifier + agent tool calling + suggestions, 4.7 GB GPU)
- Tier 0 chitchat bypass fires before any DB or LLM call — covers greetings, how-are-you, capability questions, acknowledgements, and farewells via compiled regex
- Cosine distance score gate: if the best-matching chunk has distance > `CHITCHAT_DISTANCE_THRESHOLD` (default 0.70) the query is answered as "no match" instead of hallucinating

### Frontend

| Page / Component | What it does |
|---|---|
| `/` — ChatPage | Clean end-user chat. No upload button, no settings, no sidebar. Full-width streaming chat with inline source citation chips and a sources drawer. Shows dynamic suggestion chips on first load. **Agent mode badge** (pulsing green dot + model name) shown under the header when agent mode is on — users see at a glance that tool calling is active. |
| `/admin` — AdminPage | Kenvue-branded admin header, "← Back to Chat" link, Documents / Settings tab navigation. |
| Documents tab | Upload card (file picker + strategy dropdown). Document table with Archive / Restore / Delete actions. **Chunks button** opens the chunk inspector. |
| Chunk inspector (slide-in panel) | Shows every chunk with its index and section heading. Content readable inline (scrollable per card). Click **Edit** to rewrite a chunk → Save re-embeds it server-side. |
| Settings tab | Live model dropdown (from `/models`), Top-K number input, System prompt textarea, Medical escalation message textarea. **Agent mode** ON/OFF toggle. **Agent model** dropdown (separate from chat model — picks the function-calling model). **Available tools** grid showing all 6 tools with icons and descriptions. Save persists all settings to DB. |
| Tool step cards | While the agent is working, expandable cards appear above the streamed answer — one per tool call. Each card shows tool name, query used, and (on expand) the raw result returned. Running tools show a spinning icon; completed tools show ✓. |
| Inline source citation chips | Numbered chips (`[1]`, `[2]`, …) appear below each assistant answer. Click a chip to open a popover showing filename, section heading, and a preview with Show more / Show less. Left-anchored to avoid clipping. |
| Suggestion chips (empty state) | On page load, after consent, 4 clickable question chips fetched from `/suggestions` appear above the input. Questions are grounded in actual KB content so they always have answers. Shimmer skeleton while loading. Disappear on first message. |
| `/widget-embed` — Widget test page | Mock host-site (Acme Health) with a dev banner (API URL + "Reset consent" button). Used to test the Shadow DOM widget in a realistic embedding scenario. |
| `<kenvue-chat>` Web Component | Embeddable chat widget — no iframe. Registers a custom element backed by a Shadow DOM so host-page CSS never leaks in. Ships as a single self-contained IIFE (`chatbot-widget.iife.js`, ~150 KB gzipped). Full consent gate, streaming chat, citation chips, suggestion chips, **agent mode badge**, and **tool step cards**. Embed with one `<script>` tag. |

---

## Two roles

| Role | What they see | URL |
|---|---|---|
| **Admin** | Document upload, chunking strategy, chunk inspection and editing, LLM settings, **agent mode toggle + available tools list** | `http://localhost:5174/admin` |
| **End user** | Chat only — agent mode badge visible when active; tool step cards appear during agent reasoning | `http://localhost:5174` |

All users query the **same shared knowledge base** (`kenvue_kb` namespace). End users cannot add or remove documents.

> **Auth**: not implemented yet — access `/admin` by navigating to the URL directly. Add a password gate before any staging deploy.

---

## Architecture

```
End user              Admin
    │                     │
React /           React /admin
    │                     │
    └──────────┬──────────┘
               │
    FastAPI API (port 8003)
    /chat  /documents  /settings  /settings/agents  /models  /suggestions  /health
               │ asyncpg
    PostgreSQL + pgvector (port 5435)
      ┌─────────────────────────────────────────┐
      │ rag_documents                           │  ← one row per uploaded file
      │ rag_chunks + HNSW idx                   │  ← one row per chunk, embedding vector
      │ kenvue_settings                         │  ← chat_model, top_k, system_prompt,
      │                                         │    agent_mode, agent_model,
      │                                         │    escalation_message
      └─────────────────────────────────────────┘
               │
    Ollama (port 11434)
      bge-m3:latest          ← embeddings (GPU)
      qwen2.5:7b-instruct   ← agent tool calling + Tier 3 classifier (GPU)
```

---

## Ports

| Service | Port |
|---|---|
| **Kenvue Agentic API** | **8003** |
| **Kenvue Agentic UI** | **http://localhost:5174** |
| **Admin Panel** | **http://localhost:5174/admin** |
| PostgreSQL | 5435 |
| Ollama | 11434 |

---

## Running locally

```powershell
# From the project root
.\start.ps1

# Or individually:

# API
cd api
uvicorn main:app --port 8003 --reload

# UI (separate terminal)
cd ui
$env:VITE_API_URL="http://localhost:8003"
npm run dev -- --port 5174
```

### First Time Setup

```bash
# 1. Start database
docker compose up -d

# 2. Install API dependencies
cd api
python -m venv .venv
.venv/Scripts/activate    # Windows (use source .venv/bin/activate on Linux)
pip install -r requirements.txt

# 3. Install UI dependencies
cd ../ui
npm install

# 4. Pull models
ollama pull qwen2.5:7b-instruct
ollama pull bge-m3
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `AGENT_MODEL` | `qwen2.5:7b-instruct` | Model for tool calling |
| `CLASSIFIER_MODEL` | `qwen2.5:7b-instruct` | Model for Tier 3 guardrail |
| `MAX_AGENT_ITERATIONS` | `5` | Max tool-calling loops |
| `OLLAMA_NUM_CTX` | `4096` | Context window size |
| `CHITCHAT_DISTANCE_THRESHOLD` | `0.70` | Cosine distance gate |
| `DOMAIN` | `health_faq` | Guardrail pack: `health_faq`, `health`, `hr`, or `ecommerce` (see `HARNESS_ARCHITECTURE.md`). **The default (`health_faq`) blocks first-person phrasing like "do I have..."** even on non-health content — set `DOMAIN=ecommerce` in `api/.env` if you're testing with non-health KB docs. |

### GitHub Codespaces

```bash
ollama pull qwen2.5:7b-instruct && ollama pull bge-m3
docker compose up -d
cd api && pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8003 --reload &
cd ../ui && npm install && VITE_API_URL=http://localhost:8003 npm run dev -- --port 5174
```

Or let `.devcontainer/setup.sh` do all of this automatically on Codespace creation (smaller CPU-friendly models — see that file).

---

## Status

Feature-complete demo: hybrid RRF retrieval, Docling ingest with 4 chunking strategies, agentic tool-calling loop (6 tools, DB-controlled on/off), a layered Core + Domain Pack guardrail harness (`HARNESS_ARCHITECTURE.md`), an admin panel for documents/chunks/settings, and an embeddable Shadow DOM chat widget. Extracted from a larger private monorepo as a standalone reference for the AIEWF talk — no auth/HTTPS hardening included (see `docker-compose.staging.yml` for a fuller containerized deploy example).

---

## Testing guide

### Happy path — end to end

1. Start API (`uvicorn`) and UI (`npm run dev`)
2. Open `http://localhost:5174/admin` → **Documents tab**
3. Select a strategy (e.g. "Heading-based"), pick a PDF or DOCX, click **Choose file**
4. Wait for "✓ Indexed: filename.pdf (N chunks)"
5. Click **Chunks (N)** on the new row → verify chunks are readable, headings are labelled
6. Edit one chunk: change some text, click **Save** → confirm "Saved & re-embedded"
7. Open `http://localhost:5174` → verify the **Agent mode** badge shows under the header
8. Ask a question about content in that chunk → confirm tool step cards appear during reasoning
9. Confirm the answer cites the correct document and the edited chunk content is reflected

### Agent mode toggle

1. Go to `/admin` → **Settings tab** → scroll to **Agent mode** section
2. Toggle agent mode **OFF** → Save settings
3. Go to chat → confirm the agent badge is gone → ask a question → confirm no tool step cards appear (direct RAG)
4. Toggle agent mode back **ON** → Save → confirm badge returns and tools fire again

### Agent model swap

1. In Settings tab, change **Agent model** to a different model (e.g. `qwen2.5-coder:7b`)
2. Save → ask a question → confirm the badge shows the new model name
3. Swap back to `qwen2.5:7b-instruct` for best tool-calling reliability

### Settings round-trip

1. Go to **Settings tab** in admin
2. Change the system prompt to "Only answer in bullet points."
3. Click Save → go to chat → ask any question → confirm answer is in bullets
4. Change Top-K to 1 → ask a multi-document question → confirm only 1 source appears in the drawer

### Archive / restore

1. Upload two documents covering different topics
2. Archive one → ask a question that only that document can answer → confirm the answer says it doesn't know
3. Restore the document → ask again → confirm it answers correctly

### Edge cases to check

| Scenario | Expected behaviour |
|---|---|
| Upload the same file twice | "Already indexed" message, no duplicate in table |
| Upload an empty or corrupt file | Docling parse error shown in upload feedback |
| Edit a chunk to empty text | API returns 400; no save happens |
| `/models` when Ollama is down | Settings tab shows current model but dropdown may be empty; 503 logged |
| Long chunks | Chunk card content scrolls within its 220 px window; edit textarea expands |

---

## Talk resources

- 🎥 Recording: https://www.youtube.com/watch?v=Akm1sqvWG4A
- ✍️ Companion article: https://abedmatini.hashnode.dev/bypassing-the-multimodal-tax-framework-free-hybrid-rag-raw-sql-rrf-and-live-ui-telemetry
- 🌐 Author: https://abedmatini.com/

## License

MIT — built as a public reference for the AI Engineer World's Fair 2026 talk. Use it, fork it, adapt it.

