"""Opt-in PAID integration. No OSS/ASR network calls are mocked here."""
import os
from pathlib import Path

import pytest

from asr_live_support import run_live_check


@pytest.mark.skipif(os.getenv("ASR_RUN_LIVE_TESTS") != "1" or not os.getenv("DASHSCOPE_API_KEY")
                    or not os.getenv("ALIYUN_OSS_BUCKET") or not os.getenv("ASR_LIVE_AUDIO_PATH"),
                    reason="Real cloud ASR requires explicit opt-in, credentials and a short FLAC fixture")
def test_real_private_oss_and_paraformer(monkeypatch):
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
