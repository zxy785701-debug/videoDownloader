"""Opt-in PAID integration. No OSS/ASR network calls are mocked here."""
import os
from pathlib import Path

import pytest

from asr_live_support import run_live_check
from app.asr.settings import setting


@pytest.mark.skipif(os.getenv("ASR_RUN_LIVE_TESTS") != "1" or not setting("DASHSCOPE_API_KEY")
                    or not setting("ALIYUN_OSS_BUCKET") or not os.getenv("ASR_LIVE_AUDIO_PATH"),
                    reason="Real cloud ASR requires explicit opt-in, credentials and a short FLAC fixture")
def test_real_private_oss_and_paraformer(monkeypatch):
    # The global Mock-test fixture clears file settings. Restore them only for
    # this explicitly authorized PAID test; ordinary tests never use real keys.
    from app.asr import settings
    monkeypatch.setattr(settings, "_LOCAL_CONFIG", settings.read_local_settings(
        Path(__file__).resolve().parents[2] / ".env"))
    root = Path(os.getenv("ASR_LIVE_WORK_DIR", str(
        Path(__file__).resolve().parents[2] / ".local" / "asr-live-first"))).resolve()
    monkeypatch.setenv("ASR_ENABLED", "true")
    monkeypatch.setenv("ASR_TEMP_DIR", str(root / "asr-tmp"))
    monkeypatch.setenv("ASR_JOB_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("ASR_SIGNED_URL_TTL_SECONDS", "900")
    report = run_live_check(Path(os.environ["ASR_LIVE_AUDIO_PATH"]), root)
    if report["status"] not in {"PASSED", "RESUMED_VERIFIED", "CACHED_VERIFIED"}:
        # Never render cloud exception bodies, URLs or request locals in pytest.
        pytest.fail("Real ASR check failed: " + report["error_code"]
                    + "; see .local/asr-live-first/report.json (sanitized)", pytrace=False)
