import asyncio
import importlib
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ai_config, analysis_routes, chat_service, main
from app.ai_config import get_config
from app.analysis_errors import AnalysisError
from app.analysis_jobs import AnalysisEngine
from app.analysis_store import AnalysisStore
from app.chat_events import chat_events
from app.deepseek_client import DeepSeekClient
from app.streaming_json import answer_prefix

ANSWER = {"answer": '通过主动回忆检查。\n引用 "原文" 😀', "evidence": "supported", "cue_ids": ["c000001"]}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(ai_config, "_LOCAL_CONFIG", {})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-stream-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = AnalysisEngine(AnalysisStore(tmp_path / "stream.sqlite3"))
    for record_id in ["stream-record", "other-record"]:
        engine.store.create(record_id, "https://youtu.be/abcdefghijk", "YouTube", "auto")
        engine.store.save_transcript(record_id, {"title": "测试视频", "duration": 10, "source_id": "test", "language": "zh-Hans",
            "track_kind": "manual", "tracks": [], "notes": [], "transcript_hash": "test-hash",
            "cues": [{"id": "c000001", "start": 2, "end": 5, "text": "通过主动回忆检查学习效果。"}]})
    monkeypatch.setattr(analysis_routes, "get_engine", lambda: engine)
    yield engine
    engine.close()


def finished(engine, job_id):
    for _ in range(300):
        job = engine.store.job(job_id)
        if not job or job["status"] not in {"queued", "processing"}:
            return job
        time.sleep(.01)
    raise AssertionError("Job did not complete")


class Bytes(httpx.SyncByteStream):
    def __init__(self, parts):
        self.parts = parts
    def __iter__(self):
        yield from self.parts


def frame(data):
    return ("data: " + json.dumps(data, ensure_ascii=False) + "\r\n\r\n").encode("utf-8")


def model_frames(content, finish="stop", done=True, legacy=False):
    result = b": keepalive\r\n\r\n"
    for offset in range(0, len(content), 3):
        result += frame({"choices": [{"index": 0, "delta": {"content": content[offset:offset + 3]}, "finish_reason": None}]})
    usage = {"prompt_tokens": 10, "completion_tokens": 20, "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": -1, "other": 99}
    result += frame({"choices": [{"delta": {}, "finish_reason": finish}], "usage": None if legacy else usage})
    if legacy:
        result += frame({"choices": [], "usage": usage})
    if done:
        result += b"data: [DONE]\r\n\r\n"
    return result


@pytest.mark.parametrize("legacy", [False, True])
def test_deepseek_stream_decodes_split_utf8_and_records_usage_once(legacy):
    payloads, previews, usages = [], [], []
    body = model_frames(json.dumps(ANSWER, ensure_ascii=False), legacy=legacy)
    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Bytes([body[i:i + 1] for i in range(len(body))]))
    client = DeepSeekClient(get_config(), lambda: None, usages.append, httpx.MockTransport(respond))
    result = client.complete_stream([], 2048, time.monotonic() + 30, previews.append)
    assert result == ANSWER and len(previews) > 5
    assert usages == [{"prompt_tokens": 10, "completion_tokens": 20, "prompt_cache_hit_tokens": 4}]
    assert payloads[0]["stream"] is True and payloads[0]["stream_options"] == {"include_usage": True}
    assert all(json.dumps(ANSWER, ensure_ascii=False).startswith(part) for part in previews)


@pytest.mark.parametrize("content,finish,done,code", [
    (json.dumps(ANSWER), "stop", False, "AI_NETWORK_FAILED"),
    (json.dumps(ANSWER), "length", True, "AI_OUTPUT_INVALID"),
    (json.dumps(ANSWER), None, True, "AI_OUTPUT_INVALID"),
    ("not json", "stop", True, "AI_OUTPUT_INVALID"),
    ("", "stop", True, "AI_OUTPUT_INVALID"),
    ('{"answer":"\\ud800"}', "stop", True, "AI_OUTPUT_INVALID"),
])
def test_incomplete_or_invalid_stream_is_not_a_success(content, finish, done, code):
    calls, usages = [], []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, stream=Bytes([model_frames(content, finish, done)]))
    client = DeepSeekClient(get_config(), lambda: None, usages.append, httpx.MockTransport(respond))
    with pytest.raises(AnalysisError) as failure:
        client.complete_stream([], 2048, time.monotonic() + 30, lambda _: None)
    assert failure.value.code == code and len(calls) == 1 and len(usages) == 1


def test_stream_timeout_after_partial_text_does_not_retry_model():
    calls, previews = [], []
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield frame({"choices": [{"delta": {"content": '{"answer":"部分内容'}, "finish_reason": None}]})
            raise httpx.ReadTimeout("private upstream information")
    def respond(request):
        calls.append(request)
        return httpx.Response(200, stream=Broken())
    client = DeepSeekClient(get_config(), lambda: None, lambda _: None, httpx.MockTransport(respond))
    with pytest.raises(AnalysisError) as failure:
        client.complete_stream([], 2048, time.monotonic() + 30, previews.append)
    assert failure.value.code == "AI_TIMEOUT" and len(calls) == 1 and previews
    assert "private" not in str(failure.value)


@pytest.mark.parametrize("text", ['中文，换行\n引用 "原文" 和 \\ 路径 😀', '结束于 emoji 😀', '\t表格\r\n第二行'])
def test_partial_answer_preserves_json_escapes_and_surrogate_boundaries(text):
    for ascii_only in [False, True]:
        content = json.dumps({"evidence": "supported", "cue_ids": ["c000001"], "answer": text}, ensure_ascii=ascii_only)
        for end in range(len(content) + 1):
            preview = answer_prefix(content[:end])
            assert text.startswith(preview)
            preview.encode("utf-8")
        assert answer_prefix(content) == text
    assert answer_prefix('{"metadata":{"answer":"不能展示"},"answer":"正确答案') == '正确答案'
    assert answer_prefix('{"answer":123}') == ""
    assert answer_prefix('[{"answer":"不能展示"}]') == ""


def test_stream_observation_and_reconnect_never_start_or_cancel_a_model_job(engine):
    reached, release, calls = threading.Event(), threading.Event(), []
    class Fake:
        def __init__(self, *_): pass
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            calls.append(messages)
            on_content('{"answer":"正在生成的草稿')
            reached.set(); release.wait(5)
            return ANSWER
    engine.client_factory = Fake
    result = engine.start_chat("stream-record", "测试问题", "same-request", True)
    try:
        assert reached.wait(2)
        message = engine.store.message("stream-record", result["message_id"])
        assert message["answer"] is None and message["status"] == "processing"
        class Request:
            async def is_disconnected(self): return False
        async def observe():
            for _ in range(2):
                observer = chat_events(engine, "stream-record", result["message_id"], Request())
                assert (await anext(observer)).startswith(": connected")
                snapshot = await anext(observer)
                assert "正在生成的草稿" in snapshot and "references" not in snapshot
                await observer.aclose()
        asyncio.run(observe())
        same = engine.start_chat("stream-record", "测试问题", "same-request", True)
        assert same["message_id"] == result["message_id"] and same["cached"]
        assert len(calls) == 1 and engine.store.message("stream-record", result["message_id"])["status"] == "processing"
    finally:
        release.set()
    assert finished(engine, result["job_id"])["status"] == "ready"
    saved = engine.store.message("stream-record", result["message_id"])
    assert saved["answer"]["references"][0]["start"] == 2
    api = TestClient(main.app, base_url="http://127.0.0.1:8000")
    stream = api.get(f"/api/v1/analyses/stream-record/messages/{result['message_id']}/stream")
    assert stream.status_code == 200 and stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["x-accel-buffering"] == "no" and "event: complete" in stream.text
    assert len(calls) == 1


def test_invalid_citations_clear_first_draft_before_bounded_repair(engine):
    calls, states = [], []
    class Fake:
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            calls.append(messages)
            output = {**ANSWER, "answer": "第一版错误引用" if len(calls) == 1 else "修复后的回答", "cue_ids": ["invalid"] if len(calls) == 1 else ["c000001"]}
            on_content(json.dumps(output, ensure_ascii=False))
            return output
    record = engine.store.get("stream-record")
    answer = chat_service.generate_answer(record, engine.store.cues("stream-record"), "问题", [], Fake(), get_config(), lambda text, stage: states.append((text, stage)))
    assert len(calls) == 2 and states.count(("", "generating")) == 2
    assert answer["answer"] == "修复后的回答" and answer["references"][0]["cue_id"] == "c000001"
    assert not any("第一版" in text and "修复后" in text for text, _ in states)


@pytest.mark.parametrize("action", ["clear", "delete"])
def test_clear_or_delete_during_stream_prevents_late_save_and_drops_cache(engine, action):
    class Fake:
        def __init__(self, *_): pass
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            on_content('{"answer":"旧草稿')
            if action == "clear": engine.clear_messages("stream-record")
            else: engine.delete("stream-record")
            return ANSWER
    engine.client_factory = Fake
    result = engine.start_chat("stream-record", "问题", "delete-request", True)
    finished(engine, result["job_id"])
    assert engine.chat_preview(result["message_id"]) == {}
    with engine.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM messages WHERE analysis_id='stream-record'").fetchone()[0] == 0


def test_stream_access_requires_current_record_and_local_origin(engine):
    class Fake:
        def __init__(self, *_): pass
        def complete_stream(self, messages, max_tokens, deadline, on_content): return ANSWER
    engine.client_factory = Fake
    result = engine.start_chat("stream-record", "问题", "access-request", True)
    finished(engine, result["job_id"])
    api = TestClient(main.app, base_url="http://127.0.0.1:8000")
    endpoint = f"/api/v1/analyses/stream-record/messages/{result['message_id']}/stream"
    assert api.get(endpoint, headers={"Origin": "https://evil.example"}).status_code == 403
    assert api.get(endpoint.replace("stream-record", "other-record")).status_code == 404
    assert api.get(endpoint.replace(result["message_id"], "missing-message")).status_code == 404
    assert api.get(endpoint).status_code == 200


def test_restart_reports_interrupted_without_resubmitting_model(engine, monkeypatch):
    engine.store.new_job("restart-job", "stream-record", "chat", "等待回答")
    engine.store.new_message("restart-message", "stream-record", "restart-job", "restart-request", "重启问题")
    engine.store.set_message("restart-message", "processing")
    restarted = AnalysisEngine(engine.store)
    try:
        restarted.client_factory = lambda *_: pytest.fail("Restart must never submit a model call")
        monkeypatch.setattr(analysis_routes, "get_engine", lambda: restarted)
        same = restarted.start_chat("stream-record", "重启问题", "restart-request", True)
        assert same["cached"] and same["message_id"] == "restart-message"
        api = TestClient(main.app, base_url="http://127.0.0.1:8000")
        response = api.get("/api/v1/analyses/stream-record/messages/restart-message/stream")
        assert "event: failed" in response.text and '"status": "interrupted"' in response.text
        assert '"answer": null' in response.text and '"error_code": "INTERRUPTED"' in response.text
        assert restarted.chat_streams == {}
    finally:
        restarted.close()


@pytest.mark.parametrize("action", ["clear", "delete"])
def test_active_subscription_reports_removed_after_deletion(engine, action):
    engine.store.new_job("remove-job", "stream-record", "chat", "等待回答")
    engine.store.new_message("remove-message", "stream-record", "remove-job", "remove-request", "删除问题")
    class Request:
        async def is_disconnected(self): return False
    async def observe():
        observer = chat_events(engine, "stream-record", "remove-message", Request())
        await anext(observer)
        assert "event: snapshot" in await anext(observer)
        if action == "clear": engine.clear_messages("stream-record")
        else: engine.delete("stream-record")
        assert "event: removed" in await anext(observer)
        with pytest.raises(StopAsyncIteration):
            await anext(observer)
    asyncio.run(observe())


def test_idle_stream_sends_heartbeat_without_starting_model(engine, monkeypatch):
    engine.store.new_job("idle-job", "stream-record", "chat", "等待回答")
    engine.store.new_message("idle-message", "stream-record", "idle-job", "idle-request", "排队问题")
    module = importlib.import_module("app.chat_events")
    readings = iter([0, 16])
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(readings)))
    class Request:
        async def is_disconnected(self): return False
    async def observe():
        observer = chat_events(engine, "stream-record", "idle-message", Request())
        assert (await anext(observer)).startswith(": connected")
        assert "event: snapshot" in await anext(observer)
        assert await anext(observer) == ": heartbeat\n\n"
        await observer.aclose()
    asyncio.run(observe())
    assert engine.store.message("stream-record", "idle-message")["status"] == "queued"
