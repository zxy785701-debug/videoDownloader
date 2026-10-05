import json
import threading
from dataclasses import replace
from http.cookiejar import CookieJar

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import ai_config, analysis_routes, chat_service, deepseek_client, main, subtitle_service, summary_service
from app.ai_config import get_config
from app.analysis_errors import AnalysisError
from app.analysis_jobs import AnalysisEngine
from app.analysis_store import AnalysisStore
from app.chat_service import validate_answer
from app.deepseek_client import DeepSeekClient


CUES = [{"id": "c000001", "start": 0.0, "end": 3.0, "text": "先理解概念，再结合例子练习。"},
        {"id": "c000002", "start": 70.0, "end": 75.0, "text": "最后用主动回忆检查学习效果。"}]


@pytest.fixture(autouse=True)
def isolated_local_settings(monkeypatch):
    # Unit tests must never use a developer's real key from project .env.
    monkeypatch.setattr(ai_config, "_LOCAL_CONFIG", {})


def content(cue_id="c000001"):
    return {"headline": "学习方法", "overview": "通过理解与主动回忆学习。",
            "chapters": [{"title": "理解概念", "overview": "结合练习。", "cue_ids": [cue_id],
                          "points": [{"text": "通过例子理解概念。", "cue_ids": [cue_id]}]}]}


def transcript_result():
    return {"title": "学习方法", "duration": 90, "source_id": "video:1", "language": "zh-Hans",
            "track_kind": "manual", "tracks": [{"language": "zh-Hans", "kind": "manual"}],
            "notes": [], "cues": CUES, "transcript_hash": "hash-1"}


def ready_record(store, record_id="record-1"):
    store.create(record_id, "https://www.youtube.com/watch?v=abcdefghijk", "YouTube", "auto")
    store.save_transcript(record_id, transcript_result())
    return store.get(record_id)


@pytest.fixture
def store(tmp_path):
    return AnalysisStore(tmp_path / "learning.sqlite3")


@pytest.fixture
def engine(store, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-unit-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    result = AnalysisEngine(store)
    yield result
    result.close()
    for future in list(result.futures.values()):
        try:
            future.result(timeout=5)
        except Exception:
            pass


@pytest.fixture
def api(engine, monkeypatch):
    monkeypatch.setattr(analysis_routes, "get_engine", lambda: engine)
    return TestClient(main.app, base_url="http://127.0.0.1:8000")


def finish(engine, job_id):
    for _ in range(200):
        job = engine.store.job(job_id)
        if not job or job["status"] not in {"queued", "processing"}:
            return job
        threading.Event().wait(0.01)
    raise AssertionError("Learning job did not finish")


@pytest.mark.parametrize("extension,body", [
    ("srt", "1\n00:00:01,200 --> 00:00:02,900\n<b>概念</b>\n\n2\n00:01:10,000 --> 00:01:15,000\n回忆"),
    ("vtt", "WEBVTT\n\nNOTE comment\nnot a cue\n\nfirst\n00:01.200 --> 00:02.900 align:start\n<c>概念</c>\n\n00:01:10.000 --> 00:01:15.000\n回忆"),
    ("bcc", json.dumps({"body": [{"from": 1.2, "to": 2.9, "content": "概念"}, {"from": 70, "to": 75, "content": "回忆"}]})),
    ("json3", json.dumps({"events": [{"tStartMs": 1200, "dDurationMs": 1700, "segs": [{"utf8": "概念"}]}, {"tStartMs": 70000, "dDurationMs": 5000, "segs": [{"utf8": "回忆"}]}]})),
    ("json", json.dumps({"utterances": [{"start_time": 1200, "end_time": 2900, "text": "概念"}, {"start_time": 70000, "end_time": 75000, "text": "回忆"}]})),
])
def test_caption_formats_keep_times_and_original_text(extension, body):
    cues, notes = subtitle_service.normalize_cues(subtitle_service.parse_captions(body, extension), 90, get_config())
    assert [(c["start"], c["end"], c["text"]) for c in cues] == [(1.2, 2.9, "概念"), (70, 75, "回忆")]
    assert [c["id"] for c in cues] == ["c000001", "c000002"]
    assert notes


def test_rolling_captions_and_invalid_times_are_normalized():
    raw = [{"start": 0, "end": 2, "text": "主动回忆"},
           {"start": 1, "end": 3, "text": "主动回忆效果好"},
           {"start": -1, "end": 1, "text": "错误"},
           {"start": 90, "end": 91, "text": "越界"},
           {"start": 3, "end": 4, "text": "主动回忆效果好"}]
    cues, notes = subtitle_service.normalize_cues(raw, 90, get_config())
    assert len(cues) == 2
    assert cues[0]["text"] == "主动回忆效果好"
    assert cues[0]["start"] == 0 and cues[0]["end"] == 3
    assert "2" in notes[0]


@pytest.mark.parametrize("raw,code", [
    ([], "EMPTY_TRANSCRIPT"),
    ([{"start": 1, "end": 1, "text": "空时间"}], "EMPTY_TRANSCRIPT"),
    ([{"start": 7200, "end": 7202, "text": "超限"}], "VIDEO_TOO_LONG"),
    ([{"start": 0, "end": 2, "text": "x" * 1001}], "TRANSCRIPT_TOO_LARGE"),
])
def test_empty_or_oversized_transcript_not_truncated_into_success(raw, code):
    with pytest.raises(AnalysisError) as failure:
        subtitle_service.normalize_cues(raw, None, replace(get_config(), max_characters=1000))
    assert failure.value.code == code


@pytest.mark.parametrize("extension,body", [("xml", "<i>弹幕</i>"), ("json", '{"unknown": []}'), ("json", "[1,2]"), ("json3", "{")])
def test_unknown_caption_structures_rejected(extension, body):
    with pytest.raises(AnalysisError) as failure:
        subtitle_service.parse_captions(body, extension)
    assert failure.value.code == "SUBTITLE_FORMAT_UNSUPPORTED"


def test_only_danmaku_is_not_a_transcript():
    assert subtitle_service.caption_tracks({"subtitles": {"danmaku": [{"ext": "xml", "url": "https://example.com/comments"}]}}) == []


def test_select_chinese_then_manual_and_preserve_auto_label():
    tracks = [
        {"language": "en", "kind": "manual"}, {"language": "zh-Hans", "kind": "automatic"},
        {"language": "zh-Hant", "kind": "manual"}]
    assert subtitle_service.choose_track(tracks, "auto")["language"] == "zh-Hant"
    assert subtitle_service.choose_track(tracks[:2], "auto")["kind"] == "automatic"
    assert subtitle_service.choose_track(tracks, "en")["language"] == "en"


def test_bilibili_ai_track_is_not_mislabeled_manual():
    tracks = subtitle_service.caption_tracks({"extractor_key": "BiliBili", "subtitles": {
        "ai-zh": [{"ext": "srt", "data": "test"}], "zh-Hans": [{"ext": "srt", "data": "test"}]}})
    assert {t["language"]: t["kind"] for t in tracks} == {"ai-zh": "automatic", "zh-Hans": "unknown"}


@pytest.mark.parametrize("url,platform,expected", [
    ("https://youtu.be/abcdefghijk?t=10", "YouTube", "https://www.youtube.com/watch?v=abcdefghijk"),
    ("https://www.youtube.com/shorts/abcdefghijk", "YouTube", "https://www.youtube.com/watch?v=abcdefghijk"),
    ("https://www.bilibili.com/video/BV1234567890/?p=2&share_source=copy", "Bilibili", "https://www.bilibili.com/video/BV1234567890/?p=2"),
    ("https://www.douyin.com/?modal_id=7691322577818201073", "Douyin", "https://www.douyin.com/video/7691322577818201073"),
])
def test_platform_identity_retains_part_not_tracking(monkeypatch, url, platform, expected):
    monkeypatch.setattr(subtitle_service, "validate_public_http_url", lambda url: url)
    assert subtitle_service.platform_url(url) == (platform, expected)


def test_host_suffix_attack_not_a_supported_platform():
    with pytest.raises(AnalysisError) as failure:
        subtitle_service.platform_url("https://youtube.com.evil.example/video")
    assert failure.value.code == "PLATFORM_UNSUPPORTED"


def test_resource_redirect_validates_private_target(monkeypatch):
    requested = []
    def validate(url):
        if "127.0.0.1" in url:
            raise HTTPException(400, "private host")
        return url
    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    original = httpx.Client
    monkeypatch.setattr(subtitle_service, "validate_public_http_url", validate)
    monkeypatch.setattr(subtitle_service.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    fake_ydl = type("YDL", (), {"cookiejar": CookieJar(), "params": {}})()
    with pytest.raises(AnalysisError):
        subtitle_service._resource_body({"url": "https://captions.example/test"}, {}, fake_ydl, "YouTube", get_config())
    assert requested == ["https://captions.example/test"]


def test_bounded_inline_resource():
    with pytest.raises(AnalysisError) as failure:
        subtitle_service._resource_body({"data": "文字" * 10}, {}, None, "Bilibili", replace(get_config(), max_resource_bytes=12))
    assert failure.value.code == "TRANSCRIPT_TOO_LARGE"


def test_subtitle_discovery_flags_and_no_cookie_expansion(monkeypatch):
    seen = {}
    class YDL:
        def __init__(self, options):
            seen.update(options)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            return {"id": "bv1", "extractor_key": "BiliBili", "title": "标题", "duration": 90,
                    "subtitles": {"zh-Hans": [{"ext": "srt", "data": "1\n00:00:01,000 --> 00:00:02,000\n知识"}]}}
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    monkeypatch.setattr(subtitle_service, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(subtitle_service, "YoutubeDL", YDL)
    result = subtitle_service.extract_transcript("https://www.bilibili.com/video/BV123/?p=2")
    assert seen["skip_download"] and seen["writesubtitles"] and seen["writeautomaticsub"]
    assert "cookiesfrombrowser" not in seen
    assert result["source_id"].endswith(":p2")
    assert result["cues"][0]["text"] == "知识"


@pytest.mark.parametrize("warning,code", [
    ("Subtitles are only available when logged in", "CAPTIONS_ACCESS_REQUIRED"),
    ("Unable to download subtitle info: 429", "CAPTIONS_FETCH_FAILED"),
    ("", "NO_CAPTIONS"),
])
def test_discovery_distinguishes_absent_and_blocked(monkeypatch, warning, code):
    class YDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            if warning:
                self.options["logger"].warning(warning)
            return {"id": "v", "subtitles": {"danmaku": [{"ext": "xml", "url": "https://example.com"}]}}
    monkeypatch.setattr(subtitle_service, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(subtitle_service, "YoutubeDL", YDL)
    with pytest.raises(AnalysisError) as failure:
        subtitle_service.extract_transcript("https://www.bilibili.com/video/BV123")
    assert failure.value.code == code


def test_store_persists_search_anchor_and_cascading_delete(store):
    ready_record(store)
    reopened = AnalysisStore(store.path)
    assert reopened.get("record-1")["subtitle_status"] == "ready"
    assert reopened.transcript("record-1", 0, 1, "", "c000002")["offset"] == 1
    assert reopened.transcript("record-1", 0, 100, "主动", None)["total"] == 1
    assert reopened.transcript("record-1", 0, 100, "%", None)["total"] == 0
    reopened.new_job("job", "record-1", "summary", "等待")
    reopened.record_usage("record-1", "job", "test-model", {"prompt_tokens": 12})
    reopened.save_chunk("record-1", "chunk", content())
    reopened.delete("record-1")
    reopened.save_transcript("record-1", transcript_result())
    reopened.save_chunk("record-1", "late-chunk", content())
    reopened.record_usage("record-1", "job", "test-model", {"prompt_tokens": 99})
    with reopened.connection() as db:
        for table in ["analyses", "cues", "jobs", "chunk_cache", "usage_events"]:
            assert db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


def test_restart_marks_in_progress_without_discarding_ready_result(store):
    ready_record(store)
    store.save_summary("record-1", "version", "fingerprint", content(), "model", "prompt")
    store.new_job("job", "record-1", "summary", "等待")
    store.update("record-1", summary_status="processing")
    store.recover()
    assert store.get("record-1")["summary_status"] == "interrupted"
    assert store.job("job")["status"] == "interrupted"
    assert store.summary("record-1")["content"] == content()


def test_unknown_cue_or_empty_supported_answer_rejected():
    with pytest.raises(AnalysisError):
        summary_service.validate_summary(content("made-up"), {"c000001"})
    with pytest.raises(AnalysisError):
        validate_answer({"answer": "内容", "evidence": "supported", "cue_ids": []}, {"c000001"})
    assert validate_answer({"answer": "字幕没有足够信息。", "evidence": "insufficient", "cue_ids": []}, set())["evidence"] == "insufficient"


def test_long_video_all_chunks_including_last_are_processed_and_cached(store):
    record = ready_record(store)
    cues = [{"id": f"c{i:06}", "start": i * 10, "end": i * 10 + 5, "text": "知识" * 400} for i in range(1, 11)]
    cues[-1]["text"] = "后半段独有知识" * 120
    seen = []
    class Fake:
        def complete(self, messages, max_tokens, deadline):
            user = json.loads(messages[1]["content"])
            if "cues" in user:
                seen.extend(c["id"] for c in user["cues"])
                return content(user["cues"][-1]["id"])
            data = content()
            data["chapters"] = [chapter for note in user["notes"] for chapter in note["chapters"]]
            return data
    config = replace(get_config(), chunk_characters=1500)
    result = summary_service.generate_summary(record, cues, Fake(), config, store, lambda _: None, lambda: None)
    assert set(seen) == {c["id"] for c in cues}
    assert "c000010" in summary_service.summary_ids(result)
    calls = len(seen)
    summary_service.generate_summary(record, cues, Fake(), config, store, lambda _: None, lambda: None)
    assert len(seen) == calls


def test_failed_later_chunk_does_not_mark_partial_summary_complete(engine, monkeypatch):
    ready_record(engine.store)
    monkeypatch.setattr(summary_service, "generate_summary", lambda *args: (_ for _ in ()).throw(AnalysisError("AI_TIMEOUT", "超时")))
    result = engine.start_summary("record-1")
    assert finish(engine, result["job_id"])["status"] == "failed"
    assert engine.store.get("record-1")["summary_status"] == "failed"
    assert engine.store.summary("record-1") is None


def test_model_repair_is_bounded_and_rejects_wrong_cues():
    calls = []
    class Fake:
        def complete(self, messages, max_tokens, deadline):
            calls.append(messages[:])
            return content("made-up")
    with pytest.raises(AnalysisError):
        summary_service.validated_call(Fake(), "json", {}, lambda d: summary_service.validate_summary(d, {"c000001"}), 4096, 9999999999)
    assert len(calls) == 2


@pytest.mark.parametrize("status,code", [(400, "AI_REQUEST_INVALID"), (401, "AI_KEY_INVALID"), (402, "AI_BALANCE_INSUFFICIENT"), (422, "AI_REQUEST_INVALID")])
def test_deepseek_auth_and_parameter_failures_not_retried(monkeypatch, status, code):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-unit-test-key")
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="upstream-secret-should-not-be-exposed")
    client = DeepSeekClient(get_config(), lambda: None, lambda _: None, httpx.MockTransport(respond))
    with pytest.raises(AnalysisError) as failure:
        client.complete([{"role": "user", "content": "json"}], 10, 9999999999)
    assert failure.value.code == code
    assert len(calls) == 1 and "upstream-secret" not in str(failure.value)


def test_deepseek_request_config_and_real_usage(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-unit-test-key")
    recorded = []
    def respond(request):
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash" and payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content())}}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "prompt_cache_hit_tokens": 5}})
    client = DeepSeekClient(get_config(), lambda: None, recorded.append, httpx.MockTransport(respond))
    assert client.complete([{"role": "user", "content": "json"}], 100, 9999999999) == content()
    assert recorded[0]["prompt_tokens"] == 10


def test_no_key_or_context_over_budget_makes_no_http_request(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(AnalysisError) as failure:
        DeepSeekClient(get_config(), lambda: None, lambda _: None).complete([], 1, 9999999999)
    assert failure.value.code == "AI_NOT_CONFIGURED"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-unit-test-key")
    with pytest.raises(AnalysisError) as failure:
        DeepSeekClient(replace(get_config(), max_request_bytes=20), lambda: None, lambda _: None).complete([], 1, 9999999999)
    assert failure.value.code == "AI_CONTEXT_TOO_LARGE"


def test_local_origin_and_host_checks(api):
    assert api.get("/api/v1/ai/config", headers={"Origin": "https://evil.example"}).status_code == 403
    assert api.get("/api/v1/ai/config", headers={"Host": "evil.example"}).status_code == 403
    assert api.get("/api/v1/ai/config", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200
    assert "fake-unit-test-key" not in api.get("/api/v1/ai/config").text


def test_no_subtitle_blocks_all_ai_work(api, engine):
    engine.store.create("no-subs", "https://www.youtube.com/watch?v=abcdefghijk", "YouTube", "auto")
    engine.store.update("no-subs", subtitle_status="unavailable")
    assert api.post("/api/v1/analyses/no-subs/summary", json={}).status_code == 409
    assert api.post("/api/v1/analyses/no-subs/chat", json={"question": "内容？", "request_id": "request-1"}).status_code == 409
    assert engine.store.usage("no-subs")["calls"] == 0


def test_transcript_api_create_restore_and_delete(api, engine, monkeypatch):
    monkeypatch.setattr(subtitle_service, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(subtitle_service, "extract_transcript", lambda *args, **kwargs: transcript_result())
    created = api.post("/api/v1/analyses", json={"url": "https://youtu.be/abcdefghijk"})
    assert created.status_code == 202
    result = created.json()
    assert finish(engine, result["job_id"])["status"] == "ready"
    assert api.get("/api/v1/analyses/" + result["id"]) .json()["subtitle_status"] == "ready"
    assert api.get(f"/api/v1/analyses/{result['id']}/transcript?q=主动").json()["total"] == 1
    cached = api.post("/api/v1/analyses", json={"url": "https://youtu.be/abcdefghijk"}).json()
    assert cached["id"] == result["id"] and cached["cached"]
    exported = api.get(f"/api/v1/analyses/{result['id']}/export?format=srt")
    assert "00:01:10,000" in exported.text
    assert api.delete("/api/v1/analyses/" + result["id"]).status_code == 204
    assert api.get("/api/v1/analyses/" + result["id"]).status_code == 404


def test_duplicate_summary_and_chat_are_not_rebilled(api, engine):
    ready_record(engine.store)
    calls = []
    class Fake:
        def __init__(self, *args):
            pass
        def complete(self, messages, max_tokens, deadline):
            calls.append(messages)
            if "previous_conversation" in messages[1]["content"]:
                return {"answer": "通过主动回忆检查。", "evidence": "supported", "cue_ids": ["c000002"]}
            return content()
    engine.client_factory = Fake
    summary = api.post("/api/v1/analyses/record-1/summary", json={}).json()
    assert finish(engine, summary["job_id"])["status"] == "ready"
    assert api.post("/api/v1/analyses/record-1/summary", json={}).json()["cached"]
    assert len(calls) == 1
    response = api.get("/api/v1/analyses/record-1/summary").json()["summary"]
    assert response["content"]["chapters"][0]["references"][0]["start"] == 0
    assert response["mindmap"]["children"][0]["children"][0]["text"] == content()["chapters"][0]["points"][0]["text"]
    body = {"question": "如何检查效果？", "request_id": "request-1"}
    chat = api.post("/api/v1/analyses/record-1/chat", json=body).json()
    assert finish(engine, chat["job_id"])["status"] == "ready"
    assert api.post("/api/v1/analyses/record-1/chat", json=body).json()["cached"]
    assert len(calls) == 2
    items = api.get("/api/v1/analyses/record-1/messages").json()["items"]
    assert items[0]["answer"]["references"][0]["start"] == 70
    assert api.delete("/api/v1/analyses/record-1/messages").status_code == 204
    assert api.get("/api/v1/analyses/record-1/messages").json()["items"] == []


def test_delete_during_model_call_does_not_resurrect_record(engine):
    ready_record(engine.store)
    class Fake:
        def __init__(self, *args):
            pass
        def complete(self, *args):
            engine.delete("record-1")
            return content()
    engine.client_factory = Fake
    result = engine.start_summary("record-1")
    finish(engine, result["job_id"])
    with pytest.raises(AnalysisError):
        engine.store.get("record-1")
    with engine.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 0


def test_clear_during_chat_does_not_restore_old_answer(engine):
    ready_record(engine.store)
    class Fake:
        def __init__(self, *args):
            pass
        def complete(self, *args):
            engine.clear_messages("record-1")
            return {"answer": "回答", "evidence": "supported", "cue_ids": ["c000001"]}
    engine.client_factory = Fake
    result = engine.start_chat("record-1", "问题", "request-1")
    assert finish(engine, result["job_id"])["status"] == "cancelled"
    assert engine.store.messages("record-1") == []


@pytest.mark.parametrize("status,code", [(429, "AI_RATE_LIMITED"), (500, "AI_UPSTREAM_FAILED"), (503, "AI_UPSTREAM_FAILED")])
def test_transient_model_failures_have_bounded_retries(monkeypatch, status, code):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-unit-test-key")
    delays, calls = [], []
    monkeypatch.setattr(deepseek_client.time, "sleep", delays.append)
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="private upstream detail")
    client = DeepSeekClient(get_config(), lambda: None, lambda _: None, httpx.MockTransport(respond))
    with pytest.raises(AnalysisError) as failure:
        client.complete([], 10, 9999999999)
    assert failure.value.code == code and len(calls) == 3
    assert delays == [1, 2] and "private upstream" not in str(failure.value)


@pytest.mark.parametrize("output,finish_reason", [("", "stop"), ("{}", "length"), ("[]", "stop"), ("not json", "stop")])
def test_invalid_model_response_is_never_success(monkeypatch, output, finish_reason):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-unit-test-key")
    usage = []
    def respond(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": finish_reason, "message": {"content": output}}], "usage": {"prompt_tokens": 9}})
    client = DeepSeekClient(get_config(), lambda: None, usage.append, httpx.MockTransport(respond))
    with pytest.raises(AnalysisError) as failure:
        client.complete([], 10, 9999999999)
    assert failure.value.code == "AI_OUTPUT_INVALID"
    assert usage == [{"prompt_tokens": 9}]


def test_ambiguous_network_timeout_is_not_automatically_rebilled(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-unit-test-key")
    calls = []
    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("private diagnostic")
    client = DeepSeekClient(get_config(), lambda: None, lambda _: None, httpx.MockTransport(respond))
    with pytest.raises(AnalysisError) as failure:
        client.complete([], 10, 9999999999)
    assert failure.value.code == "AI_TIMEOUT" and len(calls) == 1


def test_ai_database_failure_does_not_disable_download_api(monkeypatch):
    def unavailable():
        raise AnalysisError("STORE_UNAVAILABLE", "测试数据库不可用", 503)
    monkeypatch.setattr(main, "get_engine", unavailable)
    monkeypatch.setattr(analysis_routes, "get_engine", unavailable)
    monkeypatch.setattr(main, "close_engine", lambda: None)
    monkeypatch.setattr(main.video_service, "parse_video", lambda url: {
        "title": "原下载解析", "extractor": "test", "duration": 1, "thumbnail": None,
        "formats": [{"format_id": "best", "label": "自动", "ext": None, "resolution": None, "filesize": None, "fps": None}],
    })
    with TestClient(main.app, base_url="http://127.0.0.1:8000") as api:
        assert api.get("/api/v1/health").status_code == 200
        assert api.post("/api/v1/parse", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"}).status_code == 200
        assert api.get("/api/v1/analyses").status_code == 503


def test_summary_error_remains_available_after_many_chat_jobs(store):
    ready_record(store)
    store.new_job("summary", "record-1", "summary", "等待")
    store.set_job("summary", "failed", "失败", "余额不足", "AI_BALANCE_INSUFFICIENT")
    for index in range(8):
        store.new_job(f"chat-{index}", "record-1", "chat", "完成")
        store.set_job(f"chat-{index}", "ready", "完成")
    latest = store.latest_jobs("record-1")
    assert {j["id"] for j in latest} == {"summary", "chat-7"}
    assert next(j for j in latest if j["kind"] == "summary")["error_code"] == "AI_BALANCE_INSUFFICIENT"


def test_queue_capacity_and_duplicate_active_summary(engine, monkeypatch):
    release = threading.Event()
    def blocked(*args):
        assert release.wait(10)
        return content()
    monkeypatch.setattr(summary_service, "generate_summary", blocked)
    results = []
    try:
        for index in range(13):
            ready_record(engine.store, f"record-{index}")
        for index in range(12):
            results.append(engine.start_summary(f"record-{index}"))
        assert engine.start_summary("record-0")["job_id"] == results[0]["job_id"]
        with pytest.raises(AnalysisError) as failure:
            engine.start_summary("record-12")
        assert failure.value.code == "QUEUE_FULL"
        assert engine.store.get("record-12")["summary_status"] == "idle"
    finally:
        release.set()
        for item in results:
            finish(engine, item["job_id"])


def test_full_transcript_and_only_last_five_ready_turns_are_sent():
    captured = []
    class Fake:
        def complete(self, messages, *args):
            captured.append(json.loads(messages[1]["content"]))
            return {"answer": "主动回忆。", "cue_ids": ["c000002"], "evidence": "supported"}
    history = [{"status": "ready", "question": str(i), "answer": {"answer": "历史回答"}} for i in range(8)]
    history.append({"status": "failed", "question": "失败问题", "answer": None})
    result = chat_service.generate_answer({"title": "标题"}, CUES, "如何检查？", history, Fake(), get_config())
    assert captured[0]["cues"] == CUES
    assert [m["question"] for m in captured[0]["previous_conversation"]] == ["3", "4", "5", "6", "7"]
    assert result["references"][0]["start"] == 70


def test_explicit_firefox_caption_session_is_scoped_to_learning(monkeypatch):
    configurations = []
    class YDL:
        def __init__(self, options):
            configurations.append(options)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            return {"id": "video", "duration": 90, "subtitles": {"zh": [{"ext": "srt", "data": "1\n00:00:01,000 --> 00:00:02,000\n知识"}]}}
    monkeypatch.setattr(subtitle_service, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(subtitle_service, "YoutubeDL", YDL)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge:Default")
    monkeypatch.delenv("VIDEO_LEARNING_FIREFOX_SESSION", raising=False)
    subtitle_service.extract_transcript("https://www.bilibili.com/video/BV123/")
    assert "cookiesfrombrowser" not in configurations[-1]
    monkeypatch.setenv("VIDEO_LEARNING_FIREFOX_SESSION", "1")
    for url in ["https://www.bilibili.com/video/BV123/", "https://www.douyin.com/video/123456789"]:
        subtitle_service.extract_transcript(url)
        assert configurations[-1]["cookiesfrombrowser"][0] == "firefox"
    subtitle_service.extract_transcript("https://www.youtube.com/watch?v=abcdefghijk")
    assert configurations[-1]["cookiesfrombrowser"][0] == "edge"
    assert "fake-unit-test-key" not in repr(get_config())
    assert "firefox_subtitle_profile" not in get_config().public()


def test_original_auto_captions_precede_other_language_translations():
    tracks = [{"language": "af", "kind": "automatic"}, {"language": "en", "kind": "manual"},
              {"language": "ko-orig", "kind": "automatic"}]
    assert subtitle_service.choose_track(tracks, "auto")["language"] == "ko-orig"
    tracks.append({"language": "zh-Hans", "kind": "manual"})
    assert subtitle_service.choose_track(tracks, "auto", "ko")["language"] == "zh-Hans"


def test_ninety_minute_fixture_covers_middle_and_final_cues(store):
    record = ready_record(store)
    raw = [{"start": i * 15, "end": i * 15 + 10, "text": f"第{i}段的独有知识：" + "理解概念结合例子检验" * 20} for i in range(360)]
    cues, _ = subtitle_service.normalize_cues(raw, 5400, get_config())
    seen, stages = set(), []
    class Fake:
        def complete(self, messages, *args):
            user = json.loads(messages[1]["content"])
            if "cues" in user:
                seen.update(c["id"] for c in user["cues"])
                return content(user["cues"][-1]["id"])
            data = content()
            data["chapters"] = [chapter for note in user["notes"] for chapter in note["chapters"]]
            return data
    result = summary_service.generate_summary(record, cues, Fake(), get_config(), store, stages.append, lambda: None)
    assert len(seen) == 360 and "c000360" in summary_service.summary_ids(result)
    assert any(stage.startswith("汇总") for stage in stages)
    assert cues[-1]["end"] == 5395


def test_dotenv_only_loads_learning_settings_and_keeps_values_literal(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text('DEEPSEEK_API_KEY="fake-${UNSET_VALUE}"\nDEEPSEEK_MODEL=deepseek-flash\nYTDLP_COOKIES_FROM_BROWSER=edge\nVITE_API_KEY=must-not-load\n', encoding="utf-8")
    values = ai_config.read_local_settings(path)
    assert values == {"DEEPSEEK_API_KEY": "fake-${UNSET_VALUE}", "DEEPSEEK_MODEL": "deepseek-flash"}
    monkeypatch.setattr(ai_config, "_LOCAL_CONFIG", values)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert ai_config.get_config().api_key == "fake-${UNSET_VALUE}"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-process-key")
    assert ai_config.get_config().api_key == "fake-process-key"
    assert "fake-process-key" not in repr(ai_config.get_config())
    assert "fake-process-key" not in json.dumps(ai_config.get_config().public())
