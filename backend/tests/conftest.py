"""Prevent TestClient lifespans from recovering the developer's real database."""

import pytest

from app import ai_config
from app.analysis_jobs import close_engine


@pytest.fixture(autouse=True)
def isolated_learning_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_LEARNING_DB", str(tmp_path / "test-runtime.sqlite3"))
    monkeypatch.setattr(ai_config, "_LOCAL_CONFIG", {})
    close_engine()
    yield
    close_engine()
