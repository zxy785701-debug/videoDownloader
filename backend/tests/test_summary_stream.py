import asyncio
import importlib
import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
import httpx
from fastapi.testclient import TestClient

from app import analysis_routes, main, summary_service
from app.ai_config import get_config
from app.analysis_errors import AnalysisError, OutputLimitError
from app.analysis_jobs import AnalysisEngine
from app.deepseek_client import DeepSeekClient
from app.streaming_json import partial_json, summary_prefix
from app.summary_events import summary_events
from tests.test_chat_stream import Bytes, engine, finished, isolated, model_frames


def content(ids=None, title='理解 "概念" 😀'):
    ids = ids or ["c000001"]
    return {"headline": title, "overview": "通过练习学习。\n保留原文信息。",
            "chapters": [{"title": "理解与回忆", "overview": "使用例子检验。", "cue_ids": ids,
                          "points": [{"text": "先回忆，再练习。", "cue_ids": ids}]}]}


class Request:
    async def is_disconnected(self): return False


def test_summary_model_metadata_does_not_trigger_whole_stage_repair(engine):
    expected = content()
    output = content()
    output["type"] = "json_object"
    output["chapters"][0]["metadata"] = {"source": "captions"}
    output["chapters"][0]["points"][0]["type"] = "point"
    calls, retries = [], []
    class Fake:
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            calls.append(messages)
            on_content(json.dumps(output, ensure_ascii=False))
            return output
    result = summary_service.generate_summary(engine.store.get("stream-record"), engine.store.cues("stream-record"), Fake(),
        get_config(), engine.store, lambda _: None, lambda: None,
        on_preview=lambda *_: None, on_retry=lambda *args: retries.append(args))
    assert result == expected and len(calls) == 1 and retries == []
    assert summary_prefix(json.dumps(output)) == summary_prefix(json.dumps(result))
    assert output["type"] == "json_object"  # Do not mutate the model response.


@pytest.mark.parametrize("invalid", ["missing_text", "unknown_cue", "missing_chapters", "bad_chapter", "empty_points"])
def test_summary_metadata_projection_keeps_content_and_reference_validation(invalid):
    output = content()
    output["type"] = "json_object"
    if invalid == "missing_text": del output["chapters"][0]["points"][0]["text"]
    if invalid == "unknown_cue": output["chapters"][0]["points"][0]["cue_ids"] = ["unknown"]
    if invalid == "missing_chapters": del output["chapters"]
    if invalid == "bad_chapter": output["chapters"][0] = "invalid"
    if invalid == "empty_points": output["chapters"][0]["points"] = []
    with pytest.raises(AnalysisError, match="摘要结构或字幕引用无效"):
        summary_service.validate_summary(output, {"c000001"})


@pytest.mark.parametrize("ascii_only", [True, False])
def test_summary_preview_decodes_incomplete_nested_json_without_citation_fields(ascii_only):
    raw = json.dumps(content(), ensure_ascii=ascii_only)
    text = summary_prefix(raw)
    for end in range(len(raw) + 1):
        preview = summary_prefix(raw[:end])
        preview.encode("utf-8")
        assert "cue_ids" not in preview and "c000001" not in preview
        for line in preview.split("\n\n"):
            assert any(full.startswith(line) for full in text.split("\n\n"))
    assert text == '理解 "概念" 😀\n\n通过练习学习。\n保留原文信息。\n\n章节 1：理解与回忆\n\n使用例子检验。\n\n• 先回忆，再练习。'
    assert partial_json(raw) == content()
    assert summary_prefix('[{"headline":"不展示"}]') == ""
    assert summary_prefix('{"headline":123,"chapters":["invalid"]}') == ""
    assert summary_prefix('{"headline":"合法\\ud800') == "合法"
    assert len(summary_prefix(json.dumps(content(title="长" * 20000)))) <= 16000
    assert summary_prefix('{"metadata":{"headline":"不展示"},"overview":"合法') == "合法"


def test_streaming_summary_reconnect_is_observation_and_final_result_is_validated(engine):
    reached, release, calls = threading.Event(), threading.Event(), []
    class Fake:
        def __init__(self, config, check, usage): self.usage = usage
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            calls.append(messages)
            on_content('{"headline":"正在生成的概览')
            reached.set(); release.wait(5)
            self.usage({"prompt_tokens": 10, "completion_tokens": 20})
            return content()
    engine.client_factory = Fake
    result = engine.start_summary("stream-record", streaming=True)
    try:
        assert reached.wait(2)
        assert engine.store.summary("stream-record") is None
        async def observe():
            for _ in range(2):
                observer = summary_events(engine, "stream-record", result["job_id"], Request())
                assert (await anext(observer)).startswith(": connected")
                snapshot = await anext(observer)
                assert "正在生成的概览" in snapshot and "references" not in snapshot
                assert "总结第 1/1 段" in snapshot
                await observer.aclose()
        asyncio.run(observe())
        same = engine.start_summary("stream-record", force=True, streaming=True)
        assert same["job_id"] == result["job_id"] and len(calls) == 1
    finally:
        release.set()
    assert finished(engine, result["job_id"])["status"] == "ready"
    assert engine.store.summary("stream-record")["content"] == content()
    assert engine.summary_preview(result["job_id"]) == {}
    api = TestClient(main.app, base_url="http://127.0.0.1:8000")
    response = api.get(f"/api/v1/analyses/stream-record/summary/{result['job_id']}/stream")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: complete" in response.text and '"start": 2.0' in response.text
    assert '"mindmap"' in response.text and len(calls) == 1
    assert engine.store.usage("stream-record")["calls"] == 1
    assert engine.start_summary("stream-record", streaming=True)["cached"]
    assert len(calls) == 1


def test_long_summary_streams_all_chunks_and_hierarchy_with_cache_reuse(engine):
    record = engine.store.get("stream-record")
    cues = [{"id": f"c{i:06}", "start": i, "end": i + 1, "text": "长字幕" * 200} for i in range(1, 6)]
    config, calls, states = replace(get_config(), chunk_characters=1000), [], []
    class Fake:
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            user = json.loads(messages[1]["content"])
            ids = [cue["id"] for cue in user["cues"]] if "cues" in user else sorted(set().union(*(summary_service.summary_ids(note) for note in user["notes"])))
            calls.append((max_tokens, ids))
            output = content(ids, title="分段或汇总" + str(len(calls)))
            raw = json.dumps(output, ensure_ascii=False)
            on_content(raw[:len(raw) // 2]); on_content(raw)
            return output
    client = Fake()
    result = summary_service.generate_summary(record, cues, client, config, engine.store, lambda _: None, lambda: None,
        on_preview=lambda text, stage, phase: states.append((text, stage, phase)))
    assert summary_service.summary_ids(result) == {cue["id"] for cue in cues}
    assert len(calls) == 7 and [tokens for tokens, _ in calls[:5]] == [4096] * 5
    assert all(tokens == 4096 for tokens, _ in calls[5:])
    assert {stage for _, stage, _ in states} == {f"总结第 {i}/5 段" for i in range(1, 6)} | {"汇总第 1 层（1/2）", "汇总第 2 层（1/1）"}
    assert len([state for state in states if state[0] == "" and state[2] == "generating"]) >= 7
    states.clear()
    again = summary_service.generate_summary(record, cues, client, config, engine.store, lambda _: None, lambda: None,
        on_preview=lambda text, stage, phase: states.append((text, stage, phase)))
    assert again == result and len(calls) == 7
    assert len([state for state in states if state[2] == "cached"]) == 7


def test_summary_stream_repair_starts_new_attempt_and_saves_only_valid_result(engine):
    calls, states = [], []
    class Fake:
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            calls.append(messages)
            output = content(["wrong"] if len(calls) == 1 else ["c000001"], "第一版" if len(calls) == 1 else "修复版")
            on_content(json.dumps(output, ensure_ascii=False))
            return output
    result = summary_service.generate_summary(engine.store.get("stream-record"), engine.store.cues("stream-record"), Fake(), get_config(),
        engine.store, lambda _: None, lambda: None, on_preview=lambda text, stage, phase: states.append((text, stage, phase)))
    assert result["headline"] == "修复版" and len(calls) == 2
    first = next(i for i, state in enumerate(states) if "第一版" in state[0])
    second = next(i for i, state in enumerate(states) if "修复版" in state[0])
    assert any(state[0] == "" for state in states[first:second])
    with engine.store.connection() as db:
        saved = json.loads(db.execute("SELECT content FROM chunk_cache WHERE analysis_id='stream-record'").fetchone()[0])
        assert saved["headline"] == "修复版"


def test_retry_reuses_validated_early_chunks_after_later_stream_failure(engine):
    cues = [{"id": f"c{i:06}", "start": i, "end": i + 1, "text": "分段知识" * 150} for i in range(1, 4)]
    config, calls, states = replace(get_config(), chunk_characters=1000), [], []
    class Fake:
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            user = json.loads(messages[1]["content"])
            ids = [cue["id"] for cue in user["cues"]] if "cues" in user else sorted(set().union(*(summary_service.summary_ids(note) for note in user["notes"])))
            calls.append(ids)
            on_content('{"headline":"当前分段草稿')
            if len(calls) == 2: raise AnalysisError("AI_NETWORK_FAILED", "模拟断流")
            return content(ids)
    client = Fake()
    args = (engine.store.get("stream-record"), cues, client, config, engine.store, lambda _: None, lambda: None)
    with pytest.raises(AnalysisError):
        summary_service.generate_summary(*args, on_preview=lambda text, stage, phase: states.append((text, stage, phase)))
    assert engine.store.summary("stream-record") is None
    result = summary_service.generate_summary(*args, on_preview=lambda text, stage, phase: states.append((text, stage, phase)))
    assert calls.count(["c000001"]) == 1 and calls.count(["c000002"]) == 2
    assert summary_service.summary_ids(result) == {cue["id"] for cue in cues}
    assert any(stage == "总结第 1/3 段" and phase == "cached" for _, stage, phase in states)


@pytest.mark.parametrize("failure", ["AI_NETWORK_FAILED", "AI_OUTPUT_INVALID"])
def test_failed_regeneration_keeps_previous_summary_and_does_not_save_partial(engine, failure):
    engine.store.save_summary("stream-record", "previous", "old", content(), "model", "prompt")
    calls = []
    class Fake:
        def __init__(self, *_): pass
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            calls.append(messages)
            on_content('{"headline":"新版本未完成')
            if failure == "AI_NETWORK_FAILED": raise AnalysisError(failure, "模型连接中断")
            return content(["wrong"])
    engine.client_factory = Fake
    result = engine.start_summary("stream-record", force=True, streaming=True)
    assert finished(engine, result["job_id"])["status"] == "failed"
    assert len(calls) == (1 if failure == "AI_NETWORK_FAILED" else 2)
    assert engine.store.summary("stream-record")["id"] == "previous"
    assert engine.store.get("stream-record")["summary_status"] == "failed"
    assert engine.summary_preview(result["job_id"]) == {}
    api = TestClient(main.app, base_url="http://127.0.0.1:8000")
    response = api.get(f"/api/v1/analyses/stream-record/summary/{result['job_id']}/stream")
    assert "event: failed" in response.text and failure in response.text


def test_deleting_active_summary_blocks_late_cache_and_final_save(engine):
    class Fake:
        def __init__(self, *_): pass
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            on_content('{"headline":"旧草稿')
            engine.delete("stream-record")
            return content()
    engine.client_factory = Fake
    result = engine.start_summary("stream-record", streaming=True)
    finished(engine, result["job_id"])
    assert engine.summary_preview(result["job_id"]) == {}
    with engine.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM summaries WHERE analysis_id='stream-record'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM chunk_cache WHERE analysis_id='stream-record'").fetchone()[0] == 0


def test_summary_stream_access_is_local_and_matches_record_and_job_kind(engine):
    engine.store.new_job("summary-job", "stream-record", "summary", "结束")
    engine.store.set_job("summary-job", "failed", "失败", "测试失败", "AI_TIMEOUT")
    engine.store.new_job("chat-job", "stream-record", "chat", "等待")
    api = TestClient(main.app, base_url="http://127.0.0.1:8000")
    endpoint = "/api/v1/analyses/stream-record/summary/summary-job/stream"
    assert api.get(endpoint, headers={"Origin": "https://evil.example"}).status_code == 403
    assert api.get(endpoint.replace("stream-record", "other-record")).status_code == 404
    assert api.get(endpoint.replace("summary-job", "chat-job")).status_code == 404
    assert api.get(endpoint.replace("summary-job", "missing")).status_code == 404
    assert api.get(endpoint).status_code == 200


def test_summary_restart_returns_interrupted_with_previous_version(engine):
    engine.store.save_summary("stream-record", "previous", "old", content(), "model", "prompt")
    engine.store.new_job("restart-summary", "stream-record", "summary", "等待")
    engine.store.update("stream-record", summary_status="processing")
    restarted = AnalysisEngine(engine.store)
    try:
        assert restarted.store.get("stream-record")["summary_status"] == "interrupted"
        async def observe():
            observer = summary_events(restarted, "stream-record", "restart-summary", Request())
            await anext(observer)
            failed = await anext(observer)
            assert "event: failed" in failed and "INTERRUPTED" in failed
            await observer.aclose()
        asyncio.run(observe())
        assert restarted.store.summary("stream-record")["id"] == "previous"
        assert restarted.summary_streams == {} and restarted.futures == {}
    finally:
        restarted.close()


def test_summary_subscription_heartbeat_and_removal(engine, monkeypatch):
    engine.store.new_job("idle-summary", "stream-record", "summary", "等待")
    module = importlib.import_module("app.summary_events")
    readings = iter([0, 16, 16])
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(readings)))
    async def observe():
        observer = summary_events(engine, "stream-record", "idle-summary", Request())
        await anext(observer)
        assert "event: snapshot" in await anext(observer)
        assert await anext(observer) == ": heartbeat\n\n"
        engine.delete("stream-record")
        assert "event: removed" in await anext(observer)
        await observer.aclose()
    asyncio.run(observe())


def test_truncated_summary_retries_once_with_larger_budget(engine):
    payloads, states, usage = [], [], []
    def respond(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        raw = json.dumps(content(), ensure_ascii=False)
        body = model_frames(raw[:len(raw) // 2], finish="length") if len(payloads) == 1 else model_frames(raw)
        return httpx.Response(200, stream=Bytes([body]))
    client = DeepSeekClient(get_config(), lambda: None, usage.append, httpx.MockTransport(respond))
    result = summary_service.generate_summary(engine.store.get("stream-record"), engine.store.cues("stream-record"), client, get_config(),
        engine.store, lambda _: None, lambda: None, on_preview=lambda text, stage, phase: states.append((text, stage, phase)))
    assert result == content()
    assert [payload["max_tokens"] for payload in payloads] == [4096, 8192]
    assert len(usage) == 2 and all(payload["stream"] for payload in payloads)
    assert any(phase == "retrying" for _, _, phase in states)


def test_summary_output_limit_is_bounded_and_qa_budget_is_unchanged():
    class Limited:
        def __init__(self): self.budgets = []
        def complete(self, messages, max_tokens, deadline):
            self.budgets.append(max_tokens)
            raise OutputLimitError()
    client = Limited()
    with pytest.raises(OutputLimitError):
        summary_service.validated_call(client, "json", {}, lambda value: value, 4096, time.monotonic() + 30, truncation_limit=8192)
    assert client.budgets == [4096, 8192]
    client = Limited()
    with pytest.raises(OutputLimitError):
        summary_service.validated_call(client, "json", {}, lambda value: value, 2048, time.monotonic() + 30)
    assert client.budgets == [2048, 2048]


def test_summary_parts_keep_previous_stage_and_attempt_in_reconnect_snapshot(engine):
    job_id = "history-summary"
    engine.store.new_job(job_id, "stream-record", "summary", "等待")
    engine.summary_streams[job_id] = {"record_id": "stream-record", "text": "", "stage": "等待", "phase": "waiting", "parts": []}
    engine._summary_preview(job_id, "", "第 1 段", "starting")
    engine._summary_preview(job_id, "已经展示的第一版", "第 1 段", "generating")
    before = engine.summary_preview(job_id)
    engine._summary_preview(job_id, "", "第 1 段", "retrying")
    during = engine.summary_preview(job_id)
    assert during["parts"][0]["text"] == "已经展示的第一版" and during["parts"][0]["phase"] == "superseded"
    assert before["parts"][0]["phase"] == "generating"  # Snapshots must not share mutable part objects.
    engine._summary_preview(job_id, "已经修正的第一段", "第 1 段", "generating")
    engine._summary_preview(job_id, "已经修正的第一段", "第 1 段", "validated")
    engine._summary_preview(job_id, "", "第 2 段", "starting")
    after = engine.summary_preview(job_id)
    assert [part["text"] for part in after["parts"]] == ["已经展示的第一版", "已经修正的第一段", ""]
    assert [part["id"] for part in after["parts"]] == [1, 2, 3]
    assert [part["attempt"] for part in after["parts"]] == [1, 2, 1]
    async def observe():
        observer = summary_events(engine, "stream-record", job_id, Request())
        await anext(observer)
        snapshot = await anext(observer)
        assert "已经展示的第一版" in snapshot and "已经修正的第一段" in snapshot
        await observer.aclose()
    asyncio.run(observe())


def test_streaming_repair_snapshot_reports_backend_reason_not_inferred_text_change(engine):
    reached, release, calls = threading.Event(), threading.Event(), []
    class Fake:
        def __init__(self, *_): pass
        def complete_stream(self, messages, max_tokens, deadline, on_content):
            calls.append(messages)
            if len(calls) == 1:
                on_content(json.dumps(content(["wrong"]), ensure_ascii=False))
                return content(["wrong"])
            on_content('{"headline":"实际修复中')
            reached.set(); release.wait(5)
            return content()
    engine.client_factory = Fake
    submitted = engine.start_summary("stream-record", streaming=True)
    try:
        assert reached.wait(2)
        state = engine.summary_preview(submitted["job_id"])
        assert len(state["parts"]) == 2
        assert state["parts"][0]["phase"] == "superseded"
        assert state["parts"][1]["attempt"] == 2
        assert state["parts"][1]["retry_reason"] == "摘要结构或字幕引用无效，未保存为成功结果。"
    finally:
        release.set()
    assert finished(engine, submitted["job_id"])["status"] == "ready"
    assert len(calls) == 2


def test_summary_runtime_protocol_is_public_without_credentials(engine):
    client = TestClient(main.app, base_url="http://127.0.0.1:8000")
    config = client.get("/api/v1/ai/config").json()
    assert config["summary_stream_version"] == 2
    assert "api_key" not in config
