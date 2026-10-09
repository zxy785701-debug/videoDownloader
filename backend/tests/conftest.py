"""Prevent TestClient lifespans from recovering the developer's real database."""

import pytest

from app import ai_config
from app import membership_client
from app.analysis_jobs import close_engine


@pytest.fixture(autouse=True)
def isolated_learning_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_LEARNING_DB", str(tmp_path / "test-runtime.sqlite3"))
    monkeypatch.setattr(ai_config, "_LOCAL_CONFIG", {})
    monkeypatch.setenv("MEMBERSHIP_SERVICE_URL", "")
    monkeypatch.setattr(membership_client, "_client", None)
    close_engine()
    yield
    close_engine()
    membership_client.close_membership_client()
