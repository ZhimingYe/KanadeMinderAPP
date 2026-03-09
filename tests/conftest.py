"""Shared test fixtures."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kanademinder.db import init_db, open_db


@pytest.fixture()
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    """Return an initialized in-memory-like SQLite connection backed by a temp file."""
    conn = open_db(tmp_path / "tasks.db")
    yield conn
    conn.close()


@pytest.fixture()
def mock_llm_response():
    """Factory: patches LLMClient.chat to return the given dict as JSON string."""

    def _factory(response_dict: dict):
        import json

        mock = MagicMock(return_value=json.dumps(response_dict))
        patcher = patch("kanademinder.llm.client.LLMClient.chat", mock)
        patcher.start()
        return mock, patcher

    yield _factory
