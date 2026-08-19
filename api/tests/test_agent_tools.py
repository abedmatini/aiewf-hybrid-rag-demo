"""
test_agent_tools.py — Unit tests for agent_tools.py

Tests A1.1–A1.28. Runs instantly — no network, no DB, no Ollama.
All async executor functions that touch the DB or rag module use unittest.mock.
"""

import sys
import os
import math
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # kenvue-agentic/api/

from agent_tools import (
    safe_calculate,
    execute_get_current_date,
    execute_calculate,
    execute_tool,
    execute_search_kb,
    execute_list_products,
    execute_compare_products,
)


# ── A1.1–A1.12: safe_calculate ───────────────────────────────────────────────

def test_A1_1_basic_addition():
    assert safe_calculate("2 + 2") == "4"


def test_A1_2_sqrt():
    assert safe_calculate("sqrt(144)") == "12.0"


def test_A1_3_round():
    assert safe_calculate("round(3.14159, 2)") == "3.14"


def test_A1_4_multiply_divide():
    assert safe_calculate("200 * 2 / 4") == "100.0"


def test_A1_5_division_by_zero():
    assert safe_calculate("10 / 0") == "Error: division by zero"


def test_A1_6_empty_expression():
    assert safe_calculate("") == "Error: empty expression"


def test_A1_7_dunder_import_blocked():
    result = safe_calculate("__import__('os').system('ls')")
    assert result == "Error: expression contains disallowed operations"


def test_A1_8_exec_blocked():
    result = safe_calculate("exec('import os')")
    assert result == "Error: expression contains disallowed operations"


def test_A1_9_open_blocked():
    result = safe_calculate("open('/etc/passwd').read()")
    assert result == "Error: expression contains disallowed operations"


def test_A1_10_globals_blocked():
    result = safe_calculate("globals()")
    assert result == "Error: expression contains disallowed operations"


def test_A1_11_eval_blocked():
    result = safe_calculate("eval('1+1')")
    assert result == "Error: expression contains disallowed operations"


def test_A1_12_pi_circle_area():
    result = safe_calculate("pi * 10 ** 2")
    # Should be approximately 314.159…
    value = float(result)
    assert abs(value - math.pi * 100) < 1e-6


# ── A1.13–A1.15: execute_get_current_date ────────────────────────────────────

@pytest.mark.asyncio
async def test_A1_13_date_contains_year():
    result = await execute_get_current_date({})
    from datetime import datetime
    year = str(datetime.now().year)
    assert year in result


@pytest.mark.asyncio
async def test_A1_14_date_non_empty():
    result = await execute_get_current_date({})
    assert len(result) > 10


@pytest.mark.asyncio
async def test_A1_15_date_prefix():
    result = await execute_get_current_date({})
    assert result.startswith("Current date:")


# ── A1.16–A1.17: execute_calculate ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_A1_16_calculate_dispatches():
    result = await execute_calculate({"expression": "5 * 5"})
    assert result == "25"


@pytest.mark.asyncio
async def test_A1_17_calculate_missing_expression():
    result = await execute_calculate({})
    assert result == "Error: no expression provided"


# ── A1.18: execute_tool — unknown tool ───────────────────────────────────────

@pytest.mark.asyncio
async def test_A1_18_unknown_tool():
    from unittest.mock import MagicMock
    # Pool and other args don't matter — should short-circuit before use
    mock_pool = MagicMock()
    result = await execute_tool(
        tool_name="nonexistent_tool",
        arguments={},
        pool=mock_pool,
        kb_user_id="user1",
        ollama_url="http://localhost:11434",
    )
    assert result == "Error: unknown tool 'nonexistent_tool'"


# ── A1.19–A1.22: execute_search_kb ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_A1_19_search_kb_missing_query():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    result = await execute_search_kb(
        pool=mock_pool,
        kb_user_id="user1",
        ollama_url="http://localhost:11434",
        top_k=5,
        arguments={},
    )
    assert result == "Error: no query provided"


@pytest.mark.asyncio
async def test_A1_20_search_kb_empty_results():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    with patch("rag.retrieve", new=AsyncMock(return_value=[])):
        result = await execute_search_kb(
            pool=mock_pool,
            kb_user_id="user1",
            ollama_url="http://localhost:11434",
            top_k=5,
            arguments={"query": "vitamin D"},
        )
    assert "No relevant product information found" in result


@pytest.mark.asyncio
async def test_A1_21_search_kb_two_chunks():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    chunks = [
        {"filename": "doc_a.pdf", "section_heading": "Overview", "content": "Content A"},
        {"filename": "doc_b.pdf", "section_heading": "Details", "content": "Content B"},
    ]
    with patch("rag.retrieve", new=AsyncMock(return_value=chunks)):
        result = await execute_search_kb(
            pool=mock_pool,
            kb_user_id="user1",
            ollama_url="http://localhost:11434",
            top_k=5,
            arguments={"query": "vitamin D"},
        )
    assert "[Result 1]" in result
    assert "[Result 2]" in result


@pytest.mark.asyncio
async def test_A1_22_search_kb_none_section_heading():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    chunks = [
        {"filename": "doc.pdf", "section_heading": None, "content": "Some content"},
    ]
    with patch("rag.retrieve", new=AsyncMock(return_value=chunks)):
        result = await execute_search_kb(
            pool=mock_pool,
            kb_user_id="user1",
            ollama_url="http://localhost:11434",
            top_k=5,
            arguments={"query": "anything"},
        )
    assert "General" in result


# ── A1.23–A1.24: execute_list_products ───────────────────────────────────────

@pytest.mark.asyncio
async def test_A1_23_list_products_empty():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    with patch("rag.list_documents", new=AsyncMock(return_value=[])):
        result = await execute_list_products(
            pool=mock_pool,
            kb_user_id="user1",
            arguments={},
        )
    assert "empty" in result.lower()


@pytest.mark.asyncio
async def test_A1_24_list_products_three_docs():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    docs = [
        {"filename": "tylenol.pdf", "status": "ready", "chunk_count": 10},
        {"filename": "advil.pdf", "status": "ready", "chunk_count": 8},
        {"filename": "vitamind.pdf", "status": "ready", "chunk_count": 5},
    ]
    with patch("rag.list_documents", new=AsyncMock(return_value=docs)):
        result = await execute_list_products(
            pool=mock_pool,
            kb_user_id="user1",
            arguments={},
        )
    assert "3 total" in result
    assert "tylenol.pdf" in result
    assert "advil.pdf" in result
    assert "vitamind.pdf" in result


# ── A1.25–A1.28: execute_compare_products ────────────────────────────────────

@pytest.mark.asyncio
async def test_A1_25_compare_missing_args():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    result = await execute_compare_products(
        pool=mock_pool,
        kb_user_id="user1",
        ollama_url="http://localhost:11434",
        top_k=5,
        arguments={"query_a": "Tylenol"},  # missing query_b
    )
    assert result == "Error: both query_a and query_b are required"


@pytest.mark.asyncio
async def test_A1_26_compare_both_results():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    chunks_a = [{"filename": "tylenol.pdf", "section_heading": "Overview", "content": "Tylenol info"}]
    chunks_b = [{"filename": "advil.pdf", "section_heading": "Overview", "content": "Advil info"}]

    async def mock_retrieve(**kwargs):
        if "Tylenol" in kwargs.get("query", ""):
            return chunks_a
        return chunks_b

    with patch("rag.retrieve", new=mock_retrieve):
        result = await execute_compare_products(
            pool=mock_pool,
            kb_user_id="user1",
            ollama_url="http://localhost:11434",
            top_k=5,
            arguments={"query_a": "Tylenol dosage", "query_b": "Advil dosage"},
        )
    assert "## Results for: Tylenol dosage" in result
    assert "## Results for: Advil dosage" in result


@pytest.mark.asyncio
async def test_A1_27_compare_one_empty():
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    chunks_a = [{"filename": "tylenol.pdf", "section_heading": "Overview", "content": "Tylenol info"}]

    async def mock_retrieve(**kwargs):
        if "Tylenol" in kwargs.get("query", ""):
            return chunks_a
        return []

    with patch("rag.retrieve", new=mock_retrieve):
        result = await execute_compare_products(
            pool=mock_pool,
            kb_user_id="user1",
            ollama_url="http://localhost:11434",
            top_k=5,
            arguments={"query_a": "Tylenol dosage", "query_b": "Unknown product"},
        )
    assert "No results found." in result


@pytest.mark.asyncio
async def test_A1_28_compare_calls_retrieve_concurrently():
    """Both retrieve calls must be made (asyncio.gather)."""
    from unittest.mock import MagicMock
    mock_pool = MagicMock()
    call_log: list[str] = []

    async def mock_retrieve(**kwargs):
        call_log.append(kwargs.get("query", ""))
        return []

    with patch("rag.retrieve", new=mock_retrieve):
        await execute_compare_products(
            pool=mock_pool,
            kb_user_id="user1",
            ollama_url="http://localhost:11434",
            top_k=5,
            arguments={"query_a": "alpha", "query_b": "beta"},
        )

    assert len(call_log) == 2
    assert "alpha" in call_log
    assert "beta" in call_log
