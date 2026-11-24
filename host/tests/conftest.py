"""Shared test fixtures."""

import pytest

import agent_pets_daemon.session_store as session_store


@pytest.fixture(autouse=True)
def _isolate_sessions(tmp_path, monkeypatch):
    """Redirect session persistence to a temp dir for all tests.

    Prevents tests from reading/writing the real ~/.agent-pets/sessions.json.
    """
    monkeypatch.setattr(session_store, "SESSIONS_PATH", tmp_path / "sessions.json")
