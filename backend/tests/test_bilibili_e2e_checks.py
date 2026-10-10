"""MOCK/local-only tests; these never contact Bilibili, OSS or model APIs."""
import json
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from app.analysis_errors import AnalysisError
from tests.e2e_metrics import Metrics
from tests.run_bilibili_e2e import api, trace_llm_pool, validate_cues


def test_memory_metrics_sample_local_process_without_command_lines(tmp_path):
    metrics = Metrics()
    metrics.start()
    with metrics.phase("local_wait"):
        time.sleep(0.3)
    result = metrics.finish(tmp_path)
    assert result["samples"] >= 1
    assert result["peak_backend_rss_mib"] > 0
    assert result["phases"][0]["status"] == "passed"
    assert "command" not in (tmp_path / "memory.csv").read_text()


@pytest.mark.parametrize("source", ["asr", "native_subtitle"])
def test_timeline_accepts_real_sources_and_seconds(source):
    validate_cues([{"source": source, "text": "字幕", "start": 0.0, "end": 2.5}], source, 109)


@pytest.mark.parametrize("change,code", [
    ({"source": "native_subtitle"}, "E2E_WRONG_SUBTITLE_SOURCE"),
    ({"text": " "}, "E2E_WRONG_SUBTITLE_SOURCE"),
    ({"end": float("nan")}, "E2E_INVALID_TIMELINE"),
    ({"start": -1}, "E2E_INVALID_TIMELINE"),
    ({"end": 120}, "E2E_INVALID_TIMELINE"),
])
def test_wrong_source_or_invalid_timestamp_cannot_pass(change, code):
    with pytest.raises(AnalysisError) as caught:
        validate_cues([{"source": "asr", "text": "字幕", "start": 0, "end": 2, **change}], "asr", 109)
    assert caught.value.code == code


def test_local_api_error_does_not_echo_raw_upstream_body():
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(403,
        json={"detail": {"code": "ASR_AUTH_FAILED", "message": "fake-secret-never-log"}})), base_url="http://localhost")
    with pytest.raises(AnalysisError) as caught:
        api(client, "GET", "/test")
    assert caught.value.code == "ASR_AUTH_FAILED"
    assert "fake-secret" not in str(caught.value)


def test_unknown_model_request_is_blocked_after_restart(tmp_path):
    attempts = []

    @contextmanager
    def original(*args):
        attempts.append(1)
        raise httpx.ReadTimeout("fake-secret")
        yield

    def engine():
        return SimpleNamespace(model_http=SimpleNamespace(stream=original))

    for run in range(2):
        instance = engine()
        report = {"llm_requests": []}
        trace_llm_pool(instance, report, Metrics(), tmp_path / "ledger.json", lambda: None)
        with pytest.raises((httpx.ReadTimeout, AnalysisError)):
            with instance.model_http.stream(b"payload", "fake-secret", 0, lambda: None):
                pass
    assert len(attempts) == 1
    assert "fake-secret" not in (tmp_path / "ledger.json").read_text()


def test_received_response_is_not_blindly_billed_again(tmp_path):
    @contextmanager
    def original(*args):
        yield httpx.Response(200)

    instance = SimpleNamespace(model_http=SimpleNamespace(stream=original))
    report = {"llm_requests": []}
    trace_llm_pool(instance, report, Metrics(), tmp_path / "ledger.json", lambda: None)
    with instance.model_http.stream(b"payload", "fake-secret", 0, lambda: None):
        pass
    with pytest.raises(AnalysisError) as caught:
        with instance.model_http.stream(b"payload", "fake-secret", 0, lambda: None):
            pass
    assert caught.value.code == "E2E_LLM_SUBMISSION_UNKNOWN"
    assert len(report["llm_requests"]) == 1


def test_clear_model_rejections_have_a_finite_retry_limit(tmp_path):
    @contextmanager
    def original(*args):
        yield httpx.Response(429)

    instance = SimpleNamespace(model_http=SimpleNamespace(stream=original))
    report = {"llm_requests": []}
    trace_llm_pool(instance, report, Metrics(), tmp_path / "ledger.json", lambda: None)
    for _ in range(3):
        with instance.model_http.stream(b"payload", "fake-secret", 0, lambda: None):
            pass
    with pytest.raises(AnalysisError) as caught:
        with instance.model_http.stream(b"payload", "fake-secret", 0, lambda: None):
            pass
    assert caught.value.code == "E2E_LLM_RETRY_LIMIT"
    assert len(report["llm_requests"]) == 3
