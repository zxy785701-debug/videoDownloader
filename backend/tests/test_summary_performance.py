"""Streaming throughput and safety regressions; no external model calls."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest

from app import deepseek_client
from app.ai_config import get_config
from app.analysis_errors import AnalysisError, JobStopped
from app.deepseek_client import DeepSeekClient, DeepSeekHTTPPool
from test_chat_stream import engine, finished, frame
from test_learning import content


def response_content(value):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}}


def test_shared_model_pool_isolates_auth_cookies_timeouts_and_closes(monkeypatch):
    constructed, requests = [], []
    original = httpx.Client
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=response_content(content()), headers={"Set-Cookie": "private=other-task; Path=/"})
    def factory(**options):
        constructed.append(dict(options))
        options.pop("transport", None)
        return original(transport=httpx.MockTransport(respond), **options)
    monkeypatch.setattr(deepseek_client.httpx, "Client", factory)
    pool = DeepSeekHTTPPool()
    configs = [replace(get_config(), api_key="fake-key-a", request_timeout=10),
               replace(get_config(), api_key="fake-key-b", request_timeout=25)]
    clients = [DeepSeekClient(config, lambda: None, lambda _: None, pool=pool) for config in configs]
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda client: client.complete([], 4096, 9999999999), clients))
        assert results == [content(), content()]
        clients[0].close()  # A job does not own the shared pool.
        assert clients[1].complete([], 4096, 9999999999) == content()
        assert len(constructed) == 1
        assert constructed[0]["verify"] is True
        assert constructed[0]["trust_env"] is False and constructed[0]["follow_redirects"] is False
        assert {r.headers["Authorization"] for r in requests} == {"Bearer fake-key-a", "Bearer fake-key-b"}
        assert all("cookie" not in r.headers for r in requests)
        for request in requests:
            maximum = 10 if request.headers["Authorization"].endswith("a") else 25
            assert 0 < request.extensions["timeout"]["read"] <= maximum
            assert request.extensions["timeout"]["connect"] <= 10
    finally:
        pool.close()
    assert pool.http.is_closed
    with pytest.raises(AnalysisError) as failure:
        clients[1].complete([], 4096, 9999999999)
    assert failure.value.code == "SERVICE_STOPPING" and len(constructed) == 1


def test_tls_initialization_is_in_deadline_and_does_not_send_late_request(monkeypatch):
    clock, requests = [0.0], []
    monkeypatch.setattr(deepseek_client, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    original = httpx.Client
    def construct(**options):
        clock[0] += 11
        options.pop("transport", None)
        return original(transport=httpx.MockTransport(lambda request: requests.append(request)), **options)
    monkeypatch.setattr(deepseek_client.httpx, "Client", construct)
    client = DeepSeekClient(replace(get_config(), api_key="fake-key", request_timeout=10), lambda: None, lambda _: None)
    try:
        with pytest.raises(AnalysisError) as failure:
            client.complete([], 4096, 100)
        assert failure.value.code == "AI_TIMEOUT" and requests == []
    finally:
        client.close()


def test_fast_stream_checks_at_bounded_intervals_and_keeps_every_prefix(monkeypatch):
    clock, checked, previews, usages = [0.0], [], [], []
    monkeypatch.setattr(deepseek_client, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    raw = json.dumps({"headline": "完整内容" * 200}, ensure_ascii=False)
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for character in raw:
                clock[0] += 0.001
                yield frame({"choices": [{"delta": {"content": character}, "finish_reason": None}]})
            yield frame({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"completion_tokens": 20}})
            yield b"data: [DONE]\n\n"
    client = DeepSeekClient(replace(get_config(), api_key="fake-key"), lambda: checked.append(clock[0]), usages.append,
                            httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())))
    try:
        assert client.complete_stream([], 4096, 100, previews.append) == json.loads(raw)
        assert len(previews) == len(raw) and previews[-1] == raw
        assert 5 < len(checked) < 20
        assert usages == [{"completion_tokens": 20}]
    finally:
        client.close()


@pytest.mark.parametrize("stop", [JobStopped(), AnalysisError("QUOTA_RESERVATION_EXPIRED", "expired", 409)])
def test_last_check_rejects_stop_or_expiry_inside_stream_check_interval(monkeypatch, stop):
    clock, cancelled = [0.0], [False]
    monkeypatch.setattr(deepseek_client, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def check():
        if cancelled[0]:
            raise stop
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield frame({"choices": [{"delta": {"content": json.dumps(content())}, "finish_reason": None}]})
            cancelled[0] = True
            clock[0] = 0.05
            yield frame({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            yield b"data: [DONE]\n\n"
    client = DeepSeekClient(replace(get_config(), api_key="fake-key"), check, lambda _: None,
                            httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())))
    try:
        with pytest.raises(type(stop)):
            client.complete_stream([], 4096, 100, lambda _: None)
    finally:
        client.close()


def test_summary_preview_uses_memory_and_cannot_revive_deleted_task(engine, monkeypatch):
    engine.store.new_job("draft-job", "stream-record", "summary", "等待")
    engine.summary_streams["draft-job"] = {"record_id": "stream-record", "text": "", "stage": "生成", "phase": "starting", "parts": []}
    monkeypatch.setattr(engine, "check", lambda _: pytest.fail("Preview must not read databases per token"))
    for i in range(1000):
        engine._summary_preview("draft-job", "文字" * i, "生成", "generating")
    assert engine.summary_preview("draft-job")["text"] == "文字" * 999
    engine.delete("stream-record")
    engine._summary_preview("draft-job", "迟到文字", "生成", "generating")
    assert engine.summary_preview("draft-job") == {}


def test_summary_model_client_is_closed_even_after_failure(engine, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-offline-key")
    closed = []
    class Failed:
        def __init__(self, *_): pass
        def complete_stream(self, *args):
            raise AnalysisError("AI_NETWORK_FAILED", "offline")
        def close(self):
            closed.append(True)
    engine.client_factory = Failed
    result = engine.start_summary("stream-record", streaming=True)
    assert finished(engine, result["job_id"])["status"] == "failed"
    assert closed == [True]
