"""Douyin native/ASR learning regressions. Cloud and platform calls are MOCKED."""
import json
import time
from dataclasses import replace

import httpx
import pytest
from fastapi import HTTPException

from app import douyin, subtitle_service
from app.analysis_errors import AnalysisError
from app.asr import audio_worker
from app.ai_config import get_config
from test_asr import assert_clean, service
from test_douyin import VIDEO_ID, VIDEO_URL, item, mock_upstream, offline_public_dns, share_html
from test_learning import api, content, engine, finish, store


@pytest.fixture(autouse=True)
def anonymous_captions(monkeypatch):
    monkeypatch.setenv("VIDEO_LEARNING_FIREFOX_SESSION", "0")


def public_video(subtitles=None, media_urls=None, duration=90):
    return douyin.DouyinVideo(VIDEO_ID, "抖音学习", tuple(media_urls or ["https://media.example/audio.mp4"]),
                              None, duration, 720, 1280, subtitles or {})


def test_public_douyin_native_caption_avoids_ytdlp_and_asr(service, monkeypatch):
    subtitles = {"zh-Hans": [{"ext": "srt", "data": "1\n00:00:01,000 --> 00:00:03,000\n讲解内容"}]}
    monkeypatch.setattr(douyin, "resolve_video", lambda _: public_video(subtitles))
    monkeypatch.setattr(subtitle_service, "YoutubeDL", lambda *a: pytest.fail("unexpected fresh-cookie API"))
    metadata = []
    result = service.extract(VIDEO_URL, "auto", metadata.append, "user", lambda: None, lambda _: None)
    assert result["source_id"] == VIDEO_ID
    assert result["cues"][0]["source"] == "native_subtitle"
    assert result["cues"][0]["provider"] == "douyin"
    assert metadata[0]["duration"] == 90
    assert service.provider.submits == service.audio_calls == []


@pytest.mark.parametrize("url", [VIDEO_URL, "https://www.douyin.com/jingxuan?modal_id=" + VIDEO_ID,
                                  "https://v.douyin.com/short/"])
def test_no_public_captions_automatically_uses_asr(service, monkeypatch, url):
    resolved = []
    def resolve(target):
        resolved.append(target)
        return public_video()
    monkeypatch.setattr(douyin, "resolve_video", resolve)
    monkeypatch.setattr(subtitle_service, "YoutubeDL", lambda *a: pytest.fail("anonymous Douyin must reuse adapter"))
    result = service.extract(url, "auto", None, "user", lambda: None, lambda _: None)
    assert len(resolved) == 1
    assert result["track_kind"] == "asr"
    assert all(c["source"] == "asr" for c in result["cues"])
    assert len(service.provider.submits) == 1
    assert_clean(service)


def test_real_share_schema_native_resources_use_existing_caption_parser(service, mock_upstream, monkeypatch):
    video_item = item()
    video_item["video"]["subtitleInfos"] = [{"LanguageCodeName": "zh-Hans", "Format": "webvtt",
                                              "Url": "https://captions.example/captions.vtt?secret=private"}]
    mock_upstream(lambda request: httpx.Response(200, text=share_html([video_item])))
    # Only the caption resource transport is mocked; share parsing remains real.
    original = httpx.Client
    def caption_client(**kwargs):
        return original(transport=httpx.MockTransport(lambda request: httpx.Response(200,
            text="WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n有效字幕")), **kwargs)
    monkeypatch.setattr(subtitle_service.httpx, "Client", caption_client)
    result = service.extract(VIDEO_URL, "auto", None, "user", lambda: None, lambda _: None)
    assert result["cues"][0]["text"] == "有效字幕"
    assert result["duration"] == 12.5
    assert not service.provider.submits


@pytest.mark.parametrize("bad_body", ["WEBVTT\n\n", "not a subtitle"])
def test_empty_public_native_caption_falls_back(service, monkeypatch, bad_body):
    monkeypatch.setattr(douyin, "resolve_video", lambda _: public_video({"zh": [{"ext": "vtt", "data": bad_body}]}))
    result = service.extract(VIDEO_URL, "auto", None, "user", lambda: None, lambda _: None)
    assert result["track_kind"] == "asr" and len(service.provider.submits) == 1


def test_asr_disabled_reports_need_for_transcription_without_paid_call(service, monkeypatch):
    service.config = replace(service.config, enabled=False)
    monkeypatch.setattr(douyin, "resolve_video", lambda _: public_video())
    with pytest.raises(AnalysisError) as error:
        service.extract(VIDEO_URL, "auto", None, "user", lambda: None, lambda _: None)
    assert error.value.code == "NO_CAPTIONS" and "语音转录" in error.value.message
    assert not service.provider.submits


def test_image_post_does_not_trigger_paid_fallback(service, monkeypatch):
    def image(_):
        raise douyin.DouyinError("图集只支持下载", "DOUYIN_IMAGE_POST")
    monkeypatch.setattr(douyin, "resolve_video", image)
    with pytest.raises(AnalysisError) as error:
        service.extract(VIDEO_URL, "auto", None, "user", lambda: None, lambda _: None)
    assert error.value.code == "SINGLE_VIDEO_REQUIRED"
    assert not service.provider.submits


def test_share_page_private_redirect_does_not_trigger_asr(service, monkeypatch):
    def unsafe(_):
        raise HTTPException(400, "private-cookie-do-not-log")
    monkeypatch.setattr(douyin, "resolve_video", unsafe)
    with pytest.raises(AnalysisError) as error:
        service.extract(VIDEO_URL, "auto", None, "user", lambda: None, lambda _: None)
    assert error.value.code == "URL_INVALID"
    assert "cookie" not in error.value.message and not service.provider.submits


@pytest.mark.parametrize("schema", ["web", "feed", "sticker"])
def test_explicit_native_subtitle_schemas(schema):
    video_item = item()
    if schema == "web":
        video_item["video"]["subtitleInfos"] = [{"LanguageCodeName": "zh", "Format": "srt", "Url": "https://caption.example/a"}]
    elif schema == "feed":
        video_item["video"]["cla_info"] = {"caption_infos": [{"lang": "zh", "Format": "srt", "url": "https://caption.example/a"}]}
    else:
        video_item["interaction_stickers"] = [{"auto_video_caption_info": {"auto_captions": [
            {"language": "zh", "url": {"url_list": ["https://caption.example/a"]}}]}}]
    result = douyin._video_from_item(video_item, VIDEO_ID)
    assert result.subtitles == {"zh": [{"url": "https://caption.example/a", "ext": "json" if schema == "sticker" else "srt"}]}


def test_malformed_optional_caption_metadata_cannot_break_download():
    video_item = item(title="标题不能当作字幕")
    video_item["video"].update(subtitleInfos=[None, {"Format": {}, "Url": "https://example/a"}], cla_info="invalid")
    video_item["interaction_stickers"] = 123
    video = douyin._video_from_item(video_item, VIDEO_ID)
    assert video.media_urls and video.subtitles == {}


def test_douyin_media_uses_bounded_https_backups_before_conversion(tmp_path, monkeypatch):
    primary = "https://media.example/a?token=primary"
    backup = "https://backup.example/a?token=backup"
    monkeypatch.setattr(audio_worker, "platform_url", lambda _: ("Douyin", VIDEO_URL))
    monkeypatch.setattr(douyin, "resolve_video", lambda _: public_video(media_urls=[primary, backup]))
    calls = []
    def download(url, destination, limit, check, headers):
        calls.append(url)
        assert headers == douyin.MOBILE_HEADERS
        if url == primary:
            destination.write_bytes(b"partial")
            raise AnalysisError("ASR_RESOURCE_FAILED", "403")
        assert not destination.exists()
        raise AnalysisError("ASR_AUDIO_INVALID", "stop before fake conversion")
    monkeypatch.setattr(audio_worker, "download", download)
    with pytest.raises(AnalysisError) as error:
        audio_worker.prepare({"url": VIDEO_URL, "audio_timeout": 30, "max_duration": 3600,
                              "max_download_bytes": 1024}, tmp_path)
    assert error.value.code == "ASR_AUDIO_INVALID" and calls == [primary, backup]


def test_overlong_douyin_is_rejected_before_download(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_worker, "platform_url", lambda _: ("Douyin", VIDEO_URL))
    monkeypatch.setattr(douyin, "resolve_video", lambda _: public_video(duration=3601))
    monkeypatch.setattr(audio_worker, "download", lambda *a: pytest.fail("overlong video downloaded"))
    with pytest.raises(AnalysisError) as error:
        audio_worker.prepare({"url": VIDEO_URL, "audio_timeout": 30, "max_duration": 3600}, tmp_path)
    assert error.value.code == "ASR_VIDEO_TOO_LONG"


def test_platform_denial_remains_actionable_in_audio_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_worker, "platform_url", lambda _: ("Douyin", VIDEO_URL))
    def denied(_):
        raise douyin.DouyinError("抖音暂时拒绝访问或请求过于频繁，请稍后重试。")
    monkeypatch.setattr(douyin, "resolve_video", denied)
    with pytest.raises(AnalysisError) as error:
        audio_worker.prepare({"url": VIDEO_URL, "audio_timeout": 30}, tmp_path)
    assert error.value.code == "ASR_AUDIO_UNAVAILABLE" and "频繁" in error.value.message


def test_douyin_asr_summary_mindmap_chat_exports_and_repeat_cache(service, api, engine, monkeypatch):
    monkeypatch.setattr(douyin, "resolve_video", lambda _: public_video())
    engine.asr = service
    class Model:
        def __init__(self, *a, **kw):
            pass
        def complete(self, messages, *args, **kw):
            if "question" in json.loads(messages[-1]["content"]):
                return {"answer": "先学习知识。", "evidence": "supported", "cue_ids": ["c000001"]}
            return content()
        complete_stream = complete
    engine.client_factory = Model
    first = api.post("/api/v1/analyses", json={"url": "https://www.douyin.com/jingxuan?modal_id=" + VIDEO_ID,
                                                          "auto_summary": True}).json()
    assert finish(engine, first["job_id"])["status"] == "ready"
    for _ in range(200):
        if engine.store.get(first["id"])["summary_status"] in {"ready", "failed"}:
            break
        time.sleep(0.01)
    base = "/api/v1/analyses/" + first["id"]
    summary = api.get(base + "/summary").json()
    assert summary["status"] == "ready"
    assert summary["summary"]["content"]["headline"] == "学习方法"
    assert summary["summary"]["mindmap"]["children"]
    for format in ("srt", "txt", "markdown"):
        response = api.get(base + "/export?format=" + format)
        assert response.status_code == 200
        assert ("学习方法" if format == "markdown" else "学习知识。") in response.text
    chat = api.post(base + "/chat", json={"question": "怎样学习？", "request_id": "douyin-test"}).json()
    assert finish(engine, chat["job_id"])["status"] == "ready"
    message = api.get(base + "/messages").json()["items"][0]
    assert message["answer"]["references"][0]["start"] == 0
    repeat = api.post("/api/v1/analyses", json={"url": VIDEO_URL, "auto_summary": True}).json()
    assert repeat["cached"] and repeat["id"] == first["id"]
    assert len(service.provider.submits) == len(service.storage.uploads) == 1
    assert_clean(service)
