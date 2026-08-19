"""
conftest.py — shared fixtures and mock infrastructure for the Kenvue API test suite.

Provides:
  - MockConn / MockPool  — asyncpg drop-in mocks (no real DB required)
  - inject_mock_pool     — autouse fixture that swaps db._pool before each test
  - app_client           — async ASGI test client
  - Common constants / helpers used across multiple test files
"""

import sys
import os
from typing import AsyncGenerator

import pytest
from httpx import AsyncClient, ASGITransport

# Ensure the api package root and tests/ directory are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # kenvue/api/
sys.path.insert(0, os.path.dirname(__file__))                   # kenvue/api/tests/

import db  # noqa: E402 — must come after sys.path manipulation
from helpers import FAKE_SETTINGS_ROWS  # noqa: E402


# ---------------------------------------------------------------------------
# Mock asyncpg infrastructure
# ---------------------------------------------------------------------------

class MockConn:
    """
    Configurable asyncpg connection mock.

    Each method can be configured per-test via the `configure_*` helpers.
    All calls are recorded in `execute_calls` for assertion.
    """

    def __init__(self) -> None:
        self._fetch_map: dict[str, list] = {}       # query substring → row list
        self._fetchval_map: dict[str, object] = {}  # query substring → scalar
        self._fetchval_default: object = None
        self._execute_return: str | None = None
        self.execute_calls: list[tuple] = []

    # ── Configuration helpers ──────────────────────────────────────────────

    def configure_fetch(self, query_substr: str, rows: list) -> None:
        self._fetch_map[query_substr] = rows

    def configure_fetchval(self, query_substr: str, value: object) -> None:
        self._fetchval_map[query_substr] = value

    # ── asyncpg interface ──────────────────────────────────────────────────

    async def fetch(self, query: str, *args) -> list:
        for substr, rows in self._fetch_map.items():
            if substr in query:
                return rows
        return []

    async def fetchval(self, query: str, *args) -> object:
        for substr, val in self._fetchval_map.items():
            if substr in query:
                return val
        return self._fetchval_default

    async def execute(self, query: str, *args) -> str:
        self.execute_calls.append(("execute", query, args))
        return self._execute_return or "OK"

    async def executemany(self, query: str, args_list) -> None:
        self.execute_calls.append(("executemany", query, list(args_list)))

    def transaction(self):
        """Minimal transaction context manager (no-op). Must be sync — asyncpg's
        connection.transaction() is a regular method, not a coroutine."""
        return _FakeTransaction()


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockPool:
    """asyncpg Pool mock — supports `async with pool.acquire() as conn`."""

    def __init__(self, conn: MockConn) -> None:
        self._conn = conn

    def acquire(self) -> "MockPool":
        return self

    async def __aenter__(self) -> MockConn:
        return self._conn

    async def __aexit__(self, *args) -> None:
        pass

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_conn() -> MockConn:
    """
    Fresh MockConn pre-configured with default settings rows.
    Shared within a single test via pytest's function-scope deduplication.
    """
    conn = MockConn()
    conn.configure_fetch("kenvue_settings", FAKE_SETTINGS_ROWS)
    return conn


@pytest.fixture(autouse=True)
def inject_mock_pool(mock_conn: MockConn) -> MockConn:
    """
    Replace db._pool with a MockPool before every test; restore after.
    autouse=True means every test in this package benefits automatically.
    """
    original = db._pool
    db._pool = MockPool(mock_conn)
    yield mock_conn
    db._pool = original


@pytest.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """
    Async ASGI test client wrapping the full FastAPI app.

    The FastAPI lifespan runs against the mock pool (inject_mock_pool runs
    first, so db._pool is already a MockPool when lifespan starts).
    """
    from main import app  # lazy import — avoids side-effects at collection time
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client



