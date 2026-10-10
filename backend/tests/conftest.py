"""Prevent TestClient lifespans from recovering the developer's real database."""

import pytest

from app import ai_config
from app import membership_client
from app.analysis_jobs import close_engine


@pytest.fixture(autouse=True)
def isolated_learning_runtime(tmp_path, monkeypatch):
    from app.access_policy import load_access_policy
    from app.main import app
    monkeypatch.setattr(app.state, "access_policy", load_access_policy({}, tmp_path / "no-settings.env"))
    monkeypatch.setenv("VIDEO_LEARNING_DB", str(tmp_path / "test-runtime.sqlite3"))
    monkeypatch.setattr(ai_config, "_LOCAL_CONFIG", {})
    monkeypatch.setenv("MEMBERSHIP_SERVICE_URL", "")
    # Existing regression tests remain caption-only; ASR tests explicitly opt in.
    monkeypatch.setenv("ASR_ENABLED", "false")
    monkeypatch.delenv("BILIBILI_METADATA_SOURCE", raising=False)
    monkeypatch.setattr(membership_client, "_client", None)
    close_engine()
    yield
    close_engine()
    membership_client.close_membership_client()
