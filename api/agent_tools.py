"""
Agent tools for kenvue-agentic.

Defines tool schemas (OpenAI-compatible) and executor functions for
the agentic chat loop. Tools operate within the approved knowledge base
boundary — no web search or external data access.

Tools:
  search_kb           — RAG retrieval with a model-chosen query
  list_products       — List indexed KB documents
  get_product_info    — First N chunks of a specific product document
  compare_products    — Parallel retrieval for two topics, returns both
  get_current_date    — Today's date/time
  calculate           — Safe math expression evaluator
"""
import json
import math
import re
from datetime import datetime
from typing import Any

import asyncpg

# ── Tool Definitions (sent to Ollama `tools` parameter) ──────────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": (
                "Search the FAQ knowledge base using a semantic query. "
                "Returns the most relevant text chunks from approved FAQ documents. "
                "You can reformulate the user's question into a better search query. "
                "Call this multiple times with different queries if needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant product information. Can be a reformulated version of the user's question.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_products",
            "description": (
                "List all product documents available in the knowledge base with their "
                "chunk counts. Use this to understand what products are documented before searching."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_info",
            "description": (
                "Get detailed information from a specific product document by retrieving "
                "its first sections. Use when the user asks about a particular product "
                "or you need an overview of what a document contains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The exact filename or partial match of the product document.",
                    },
                    "max_chunks": {
                        "type": "integer",
                        "description": "Maximum number of sections to retrieve (default 5, max 10).",
                    },
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_products",
            "description": (
                "Compare two products or topics by searching the knowledge base for each one "
                "separately and returning both result sets. Use when the user asks to compare "
                "products, ingredients, or features between two items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_a": {
                        "type": "string",
                        "description": "Search query for the first product/topic.",
                    },
                    "query_b": {
                        "type": "string",
                        "description": "Search query for the second product/topic.",
                    },
                },
                "required": ["query_a", "query_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": (
                "Get the current date and time. Use when the user's question involves "
                "dates, expiry, seasons, or time-sensitive product information."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a mathematical expression. Supports arithmetic, common math "
                "functions (sqrt, log, round, etc.), and unit conversions. "
                "Use for dosage calculations, unit conversions, or any math the user needs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression to evaluate, e.g. '200 * 2 / 4' or 'sqrt(144)'.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
]


# ── Safe math evaluator ───────────────────────────────────────────────────────

_SAFE_MATH_NAMES: dict[str, Any] = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sum": sum, "int": int, "float": float,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "log2": math.log2,
    "ceil": math.ceil, "floor": math.floor, "pow": math.pow, "exp": math.exp,
    "pi": math.pi, "e": math.e,
}

_UNSAFE_PATTERNS = re.compile(
    r"(__|\bimport\b|\bexec\b|\beval\b|\bopen\b|\bos\b|\bsys\b"
    r"|\bgetattr\b|\bsetattr\b|\bglobals\b|\blocals\b|\bcompile\b)",
    re.IGNORECASE,
)


def safe_calculate(expression: str) -> str:
    """Evaluate a math expression safely."""
    expression = expression.strip()
    if not expression:
        return "Error: empty expression"
    if _UNSAFE_PATTERNS.search(expression):
        return "Error: expression contains disallowed operations"
    try:
        result = eval(expression, {"__builtins__": {}}, _SAFE_MATH_NAMES)
        return str(result)
    except ZeroDivisionError:
        return "Error: division by zero"
    except Exception as exc:
        return f"Error: {exc}"


# ── Tool Executors ────────────────────────────────────────────────────────────

async def execute_search_kb(
    pool: asyncpg.Pool,
    kb_user_id: str,
    ollama_url: str,
    top_k: int,
    arguments: dict,
) -> str:
    """Execute the search_kb tool."""
    from rag import retrieve

    query = arguments.get("query", "")
    if not query:
        return "Error: no query provided"

    chunks = await retrieve(
        pool=pool,
        user_id=kb_user_id,
        query=query,
        ollama_url=ollama_url,
        top_k=top_k,
    )

    if not chunks:
        return "No relevant product information found for this query."

    results = []
    for i, c in enumerate(chunks, 1):
        results.append(
            f"[Result {i}] Source: {c['filename']} | Section: {c['section_heading'] or 'General'}\n"
            f"{c['content']}"
        )
    return "\n\n---\n\n".join(results)


async def execute_list_products(
    pool: asyncpg.Pool,
    kb_user_id: str,
    arguments: dict,
) -> str:
    """Execute the list_products tool."""
    from rag import list_documents

    docs = await list_documents(pool, kb_user_id)
    if not docs:
        return "The knowledge base is empty. No product documents have been uploaded."

    lines = []
    for d in docs:
        lines.append(
            f"- {d['filename']} | Status: {d['status']} | Chunks: {d['chunk_count']}"
        )
    return f"Product documents in knowledge base ({len(docs)} total):\n" + "\n".join(lines)


async def execute_get_product_info(
    pool: asyncpg.Pool,
    kb_user_id: str,
    arguments: dict,
) -> str:
    """Execute the get_product_info tool."""
    from rag import list_documents

    filename_query = arguments.get("filename", "")
    max_chunks = min(arguments.get("max_chunks", 5), 10)

    if not filename_query:
        return "Error: no filename provided"

    docs = await list_documents(pool, kb_user_id)
    matches = [d for d in docs if filename_query.lower() in d["filename"].lower()]

    if not matches:
        available = ", ".join(d["filename"] for d in docs[:5])
        return f"No document matching '{filename_query}' found. Available: {available}"

    doc = matches[0]
    doc_id = str(doc["id"])

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT chunk_index, section_heading, content
            FROM rag_chunks
            WHERE doc_id = $1::uuid
            ORDER BY chunk_index
            LIMIT $2
            """,
            doc_id,
            max_chunks,
        )

    if not rows:
        return f"Document '{doc['filename']}' has no indexed content."

    parts = []
    for r in rows:
        heading = r["section_heading"] or "(no heading)"
        parts.append(f"[Section: {heading}]\n{r['content']}")

    total = doc["chunk_count"]
    return f"Document: {doc['filename']} ({total} total sections, showing first {len(rows)}):\n\n" + "\n\n---\n\n".join(parts)


async def execute_compare_products(
    pool: asyncpg.Pool,
    kb_user_id: str,
    ollama_url: str,
    top_k: int,
    arguments: dict,
) -> str:
    """Execute the compare_products tool — parallel retrieval for two queries."""
    import asyncio
    from rag import retrieve

    query_a = arguments.get("query_a", "")
    query_b = arguments.get("query_b", "")
    if not query_a or not query_b:
        return "Error: both query_a and query_b are required"

    results_a, results_b = await asyncio.gather(
        retrieve(pool=pool, user_id=kb_user_id, query=query_a, ollama_url=ollama_url, top_k=top_k),
        retrieve(pool=pool, user_id=kb_user_id, query=query_b, ollama_url=ollama_url, top_k=top_k),
    )

    output_parts = []

    output_parts.append(f"## Results for: {query_a}")
    if results_a:
        for i, c in enumerate(results_a, 1):
            output_parts.append(f"[{i}] {c['filename']} | {c['section_heading'] or 'General'}\n{c['content']}")
    else:
        output_parts.append("No results found.")

    output_parts.append(f"\n## Results for: {query_b}")
    if results_b:
        for i, c in enumerate(results_b, 1):
            output_parts.append(f"[{i}] {c['filename']} | {c['section_heading'] or 'General'}\n{c['content']}")
    else:
        output_parts.append("No results found.")

    return "\n\n".join(output_parts)


async def execute_get_current_date(arguments: dict) -> str:
    """Execute the get_current_date tool."""
    now = datetime.now()
    return f"Current date: {now.strftime('%A, %B %d, %Y at %H:%M:%S')}"


async def execute_calculate(arguments: dict) -> str:
    """Execute the calculate tool."""
    expression = arguments.get("expression", "")
    if not expression:
        return "Error: no expression provided"
    return safe_calculate(expression)


# ── Main Dispatcher ───────────────────────────────────────────────────────────

async def execute_tool(
    tool_name: str,
    arguments: dict,
    pool: asyncpg.Pool,
    kb_user_id: str,
    ollama_url: str,
    top_k: int = 5,
) -> str:
    """Dispatch a tool call to the appropriate executor."""
    if tool_name == "search_kb":
        return await execute_search_kb(pool, kb_user_id, ollama_url, top_k, arguments)
    elif tool_name == "list_products":
        return await execute_list_products(pool, kb_user_id, arguments)
    elif tool_name == "get_product_info":
        return await execute_get_product_info(pool, kb_user_id, arguments)
    elif tool_name == "compare_products":
        return await execute_compare_products(pool, kb_user_id, ollama_url, top_k, arguments)
    elif tool_name == "get_current_date":
        return await execute_get_current_date(arguments)
    elif tool_name == "calculate":
        return await execute_calculate(arguments)
    else:
        return f"Error: unknown tool '{tool_name}'"
