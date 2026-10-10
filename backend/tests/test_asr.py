"""ASR contract/security tests. All cloud/media calls are mocked unless named local."""
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app import subtitle_service
from app.analysis_errors import AnalysisError, JobStopped
from app.asr import audio_worker, network, providers
from app.asr.config import get_config
from app.asr.service import ASRService
from app.asr.storage import OSSStorage
from app.asr.store import ASRStore
from app.asr.temporary import sweep, workspace
from test_learning import api, content, engine, finish, store, transcript_result

URL = "https://www.bilibili.com/video/BV1234567890"
DATA = {"transcripts": [{"channel_id": 0, "sentences": [
    {"begin_time": 0, "end_time": 3000, "text": "学习知识。"},
    {"begin_time": 70000, "end_time": 75000, "text": "复习巩固。"}]}]}
SUCCESS = {"output": {"task_status": "SUCCEEDED", "results": [
    {"subtask_status": "SUCCEEDED", "transcription_url": "https://result.oss-cn-beijing.aliyuncs.com/test"}]}, "usage": {"duration": 80}}


class FakeStorage:
    def __init__(self):
        self.uploads, self.deletes = [], []

    def connect(self):
        return self

    def upload(self, path, key, check):
        check()
        self.uploads.append(key)
        assert path.is_file()
        return "https://private.oss-cn-beijing.aliyuncs.com/audio?Signature=secret"

    def delete(self, key):
        self.deletes.append(key)


class FakeProvider:
    def __init__(self):
        self.submits, self.queries = [], []

    def submit(self, url, language):
        self.submits.append((url, language))
        return "task-123"

    def query(self, task_id):
        self.queries.append(task_id)
        return SUCCESS


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_ENABLED", "true")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "mock-unit-key")
    for name in ["ASR_TEMP_DIR", "ASR_MONTHLY_BUDGET_CNY", "ASR_MAX_CONCURRENT_JOBS", "ASR_API_BASE"]:
        monkeypatch.delenv(name, raising=False)
    result = ASRService(tmp_path)
    result.storage = FakeStorage()
    result.provider = FakeProvider()
    result.read_result = lambda *args: DATA
    result.audio_calls = []
    def audio(url, directory, config, check):
        result.audio_calls.append(url)
        check()
        path = directory / "audio.flac"
        path.write_bytes(b"same-normalized-audio")
        return path, {"title": "学习方法", "source_id": "BV1234567890:p1", "duration": 90}
    result.audio = audio
    result._sleep = lambda seconds, check: check()
    return result


def run(service, url=URL, language="auto", check=lambda: None):
    return service.transcribe(url, language, "user-hash", check, lambda stage: None)


def assert_clean(service):
    assert not [p for p in service.config.temp_root.iterdir() if p.is_dir()]
    assert service.storage.deletes == service.storage.uploads


def test_native_bilibili_does_not_invoke_asr(service, monkeypatch):
    monkeypatch.setattr(subtitle_service, "extract_transcript", lambda *a, **kw: transcript_result())
    result = service.extract(URL, "auto", lambda _: None, "user", lambda: None, lambda _: None)
    assert result["track_kind"] == "manual"
    assert service.audio_calls == service.provider.submits == []


@pytest.mark.parametrize("code", ["CAPTIONS_ACCESS_REQUIRED", "NO_CAPTIONS", "EMPTY_TRANSCRIPT", "SUBTITLE_FORMAT_UNSUPPORTED", "CAPTIONS_FETCH_FAILED"])
def test_native_failure_falls_back(service, monkeypatch, code):
    def fail(*args, **kwargs):
        raise AnalysisError(code, "原生字幕不可用")
    monkeypatch.setattr(subtitle_service, "extract_transcript", fail)
    result = service.extract(URL, "auto", lambda _: None, "user", lambda: None, lambda _: None)
    assert result["cues"][1]["start"] == 70
    assert all(c["source"] == "asr" and c["provider"] == "aliyun_paraformer" for c in result["cues"])
    assert len(service.provider.submits) == 1
    assert_clean(service)


def test_nominally_successful_empty_native_falls_back(service, monkeypatch):
    monkeypatch.setattr(subtitle_service, "extract_transcript", lambda *a, **kw: {"cues": []})
    assert service.extract(URL, "auto", None, "user", lambda: None, lambda _: None)["track_kind"] == "asr"


def test_invalid_input_does_not_trigger_paid_fallback(service, monkeypatch):
    def fail(*args, **kwargs):
        raise AnalysisError("SINGLE_VIDEO_REQUIRED", "单个视频")
    monkeypatch.setattr(subtitle_service, "extract_transcript", fail)
    with pytest.raises(AnalysisError, match="单个"):
        service.extract(URL, "auto", None, "user", lambda: None, lambda _: None)
    assert service.provider.submits == []


def test_missing_key_is_clear_and_performs_no_download(service, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_NOT_CONFIGURED"
    assert service.audio_calls == []


def test_upload_failure_cleans_and_can_retry_without_double_submission(service):
    original = service.storage.upload
    def fail(path, key, check):
        service.storage.uploads.append(key)
        raise AnalysisError("ASR_OSS_UPLOAD_FAILED", "上传失败")
    service.storage.upload = fail
    with pytest.raises(AnalysisError):
        run(service)
    assert service.provider.submits == []
    assert_clean(service)
    service.storage.upload = original
    assert run(service)["cues"]
    assert len(service.provider.submits) == 1


def test_timeout_preserves_task_id_and_retry_queries_original(service):
    def pending(task_id):
        service.provider.queries.append(task_id)
        raise AnalysisError("ASR_TIMEOUT", "等待超时")
    original = service.provider.query
    service.provider.query = pending
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_TIMEOUT"
    service.provider.query = original
    assert run(service)["cues"]
    assert len(service.provider.submits) == len(service.audio_calls) == 1
    assert_clean(service)


def test_polling_deadline_has_explicit_timeout(service, monkeypatch):
    now = [0]
    def pending(_):
        now[0] = 999999
        return {"output": {"task_status": "RUNNING"}}
    service.provider.query = pending
    monkeypatch.setattr("app.asr.service.time.monotonic", lambda: now[0])
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_TIMEOUT"
    assert len(service.provider.submits) == 1
    assert_clean(service)


def test_query_retries_are_bounded_and_never_resubmit(service):
    def fail(task_id):
        service.provider.queries.append(task_id)
        raise providers.RetryableQuery()
    service.provider.query = fail
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_QUERY_FAILED"
    assert len(service.provider.queries) == service.config.retries + 1
    assert len(service.provider.submits) == 1
    assert_clean(service)


def test_unknown_submission_never_resubmits_even_after_restart(service):
    def unknown(*args):
        service.provider.submits.append(args)
        raise AnalysisError("ASR_SUBMISSION_UNKNOWN", "提交结果不明")
    service.provider.submit = unknown
    with pytest.raises(AnalysisError):
        run(service)
    # Reopen the durable store; aliases survive UI record deletion and restart.
    service.store = ASRStore(service.store.path)
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_SUBMISSION_UNKNOWN"
    assert len(service.provider.submits) == 1
    assert service.store.usage_report()[0]["actual_billed_cny"] is None


def test_cache_same_video_and_same_audio_across_videos(service):
    first = run(service)
    assert run(service) == first
    assert len(service.audio_calls) == 1
    assert run(service, URL + "?p=2") == first
    assert len(service.audio_calls) == 2 and len(service.provider.submits) == 1
    assert service.store.usage_report()[0]["accepted_tasks"] == 1
    assert service.store.usage_report()[0]["reported_seconds"] == 80
    assert_clean(service)


def test_recognition_parameters_are_part_of_cache_identity(service):
    run(service)
    run(service, language="en")
    assert len(service.provider.submits) == 2


def test_audio_cache_preserves_each_video_metadata(service):
    first = run(service)
    original = service.audio
    def renamed(*args):
        path, meta = original(*args)
        return path, {**meta, "title": "另一个视频", "source_id": "BV-other:p2"}
    service.audio = renamed
    second = run(service, URL + "?p=2")
    assert first["title"] == "学习方法" and second["title"] == "另一个视频"
    assert run(service, URL + "?p=2")["source_id"] == "BV-other:p2"
    assert len(service.provider.submits) == 1


def test_known_rejected_submission_can_retry_but_has_a_limit(service):
    def rejected(*args):
        service.provider.submits.append(args)
        raise AnalysisError("ASR_RATE_LIMITED", "云端限流")
    service.provider.submit = rejected
    for _ in range(service.config.retries + 1):
        with pytest.raises(AnalysisError) as error:
            run(service)
        assert error.value.code == "ASR_RATE_LIMITED"
        assert service.store.usage_report()[0]["budget_reserved_cny"] == 0
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_RETRY_EXHAUSTED"
    assert len(service.provider.submits) == service.config.retries + 1


def test_cleanup_failure_is_retried_from_durable_record(service):
    original = service.storage.delete
    service.storage.delete = lambda _: (_ for _ in ()).throw(OSError("mock unavailable"))
    assert run(service)["cues"]
    assert len(service.store.artifacts()) == 1
    service.storage.delete = original
    service.store = ASRStore(service.store.path)
    service.cleanup_objects()
    assert service.store.artifacts() == []


def test_two_configured_slots_still_deduplicate_same_audio(service):
    service.config = replace(service.config, concurrency=2)
    service._sleep = ASRService._sleep.__get__(service)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda index: run(service, URL + f"?p={index + 1}"), range(2)))
    assert results[0]["cues"] == results[1]["cues"] and len(service.provider.submits) == 1


def test_original_cloud_failure_does_not_create_new_charge(service):
    service.provider.query = lambda _: {"output": {"task_status": "FAILED"}}
    for _ in range(2):
        with pytest.raises(AnalysisError) as error:
            run(service)
        assert error.value.code == "ASR_FAILED"
    assert len(service.provider.submits) == 1


def test_empty_cloud_transcript_never_generates_fabricated_text(service):
    service.read_result = lambda *a: {"transcripts": []}
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "EMPTY_TRANSCRIPT"
    assert service.store.usage_report()[0]["reported_seconds"] == 80
    assert_clean(service)


def test_restart_recovers_pending_task_without_audio_or_upload(service):
    original = service.provider.query
    service.provider.query = lambda _: (_ for _ in ()).throw(JobStopped())
    with pytest.raises(JobStopped):
        run(service)
    reopened = ASRService(service.store.path.parent)
    reopened.provider = service.provider
    reopened.provider.query = original
    reopened.storage = service.storage
    reopened.read_result = service.read_result
    reopened.audio = lambda *args: pytest.fail("Restart must query saved task before downloading")
    assert run(reopened)["cues"]
    assert len(service.provider.submits) == 1


def test_native_survives_unavailable_asr_storage(service, monkeypatch):
    monkeypatch.setattr(subtitle_service, "extract_transcript", lambda *a, **kw: transcript_result())
    service.store_path = Path("Z:/missing-volume/asr.sqlite3")
    assert service.extract(URL, "auto", None, "user", lambda: None, lambda _: None)["track_kind"] == "manual"


def test_budget_blocks_before_upload(service):
    service.config = replace(service.config, budget=0)
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_BUDGET_EXCEEDED"
    assert service.storage.uploads == service.provider.submits == []
    assert_clean(service)


def test_per_user_frequency_is_durable_and_cache_does_not_count(service):
    service.config = replace(service.config, per_user_hour=1)
    run(service)
    run(service)
    with pytest.raises(AnalysisError) as error:
        run(service, language="en")
    assert error.value.code == "ASR_USER_RATE_LIMIT"
    assert len(service.provider.submits) == 1


def test_long_video_stops_without_upload(service):
    original = service.audio
    def long_audio(*args):
        audio, meta = original(*args)
        return audio, {**meta, "duration": 3601}
    service.audio = long_audio
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_VIDEO_TOO_LONG"
    assert service.storage.uploads == []
    assert_clean(service)


def test_cancel_during_poll_cleans_resources_and_keeps_task(service):
    def cancelled(_):
        raise JobStopped()
    service.provider.query = cancelled
    with pytest.raises(JobStopped):
        run(service)
    assert service.store.usage_report()[0]["accepted_tasks"] == 1
    assert_clean(service)


def test_cloud_subtask_failure_is_not_success(service):
    service.provider.query = lambda _: {"output": {"task_status": "SUCCEEDED", "results": [{"subtask_status": "FAILED"}]}}
    with pytest.raises(AnalysisError) as error:
        run(service)
    assert error.value.code == "ASR_FAILED"
    assert len(service.provider.submits) == 1
    assert_clean(service)


def test_concurrent_jobs_only_one_audio_process_and_one_charge(service):
    service._sleep = ASRService._sleep.__get__(service)
    original = service.audio
    active, maximum = 0, 0
    lock = threading.Lock()
    def slow(*args):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.05)
            return original(*args)
        finally:
            with lock:
                active -= 1
    service.audio = slow
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: run(service), range(4)))
    assert all(result == results[0] for result in results)
    assert maximum == 1 and len(service.provider.submits) == 1


@pytest.mark.parametrize("response,code", [(401, "ASR_AUTH_FAILED"), (429, "ASR_RATE_LIMITED"), (500, "ASR_SUBMISSION_UNKNOWN")])
def test_real_provider_http_errors_no_submit_retries(service, monkeypatch, response, code):
    calls = []
    def request(*args, **kwargs):
        calls.append(args)
        return httpx.Response(response, text="sensitive upstream body")
    provider = providers.AliyunParaformer(service.config)
    monkeypatch.setattr(provider, "_request", request)
    with pytest.raises(AnalysisError) as error:
        provider.submit("https://oss.example/audio?Signature=private", "auto")
    assert error.value.code == code and len(calls) == 1
    assert "sensitive" not in str(error.value) and "Signature" not in str(error.value)


def test_provider_contract_matches_official_file_api(service, monkeypatch):
    seen = []
    def request(method, path, **kwargs):
        seen.append((method, path, kwargs))
        return httpx.Response(200, json={"output": {"task_id": "task-1", "task_status": "PENDING"}})
    provider = providers.AliyunParaformer(service.config)
    monkeypatch.setattr(provider, "_request", request)
    assert provider.submit("https://oss.example/audio", "zh-Hans") == "task-1"
    provider.query("task-1")
    assert seen[0][2]["json"] == {"model": "paraformer-v2", "input": {"file_urls": ["https://oss.example/audio"]},
                                   "parameters": {"channel_id": [0], "language_hints": ["zh"]}}
    assert seen[1][:2] == ("POST", "/tasks/task-1")


def test_provider_transport_timeout_is_never_retried(service, monkeypatch):
    provider = providers.AliyunParaformer(service.config)
    calls = []
    def timeout(*a, **kw):
        calls.append(a)
        raise httpx.ReadTimeout("sensitive URL")
    monkeypatch.setattr(provider, "_request", timeout)
    with pytest.raises(AnalysisError) as error:
        provider.submit("https://oss.example/audio", "auto")
    assert error.value.code == "ASR_SUBMISSION_UNKNOWN" and len(calls) == 1


@pytest.mark.parametrize("acl", ["public-read", "public-read-write"])
def test_real_oss_sdk_rejects_public_bucket(service, monkeypatch, acl):
    oss2 = pytest.importorskip("oss2")
    from types import SimpleNamespace
    monkeypatch.setenv("ALIYUN_OSS_BUCKET", "unit-asr-bucket")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_ID", "mock-ak")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "mock-sk")
    monkeypatch.setattr(oss2.Bucket, "get_bucket_acl", lambda _: SimpleNamespace(acl=acl))
    with pytest.raises(AnalysisError) as error:
        OSSStorage(service.config).connect()
    assert error.value.code == "ASR_OSS_NOT_PRIVATE"


def test_real_oss_sdk_private_upload_and_expiring_https_url(service, monkeypatch, tmp_path):
    oss2 = pytest.importorskip("oss2")
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit
    monkeypatch.setenv("ALIYUN_OSS_BUCKET", "unit-asr-bucket")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_ID", "mock-ak")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "mock-sk")
    monkeypatch.setenv("ALIYUN_OSS_ENDPOINT", "https://oss-cn-beijing.aliyuncs.com")
    monkeypatch.setattr(oss2.Bucket, "get_bucket_acl", lambda _: SimpleNamespace(acl="private"))
    seen = []
    monkeypatch.setattr(oss2.Bucket, "put_object_from_file", lambda self, *a, **kw: seen.append(kw))
    path = tmp_path / "audio.flac"
    path.write_bytes(b"fixture")
    url = OSSStorage(service.config).upload(path, "asr/" + "a" * 32 + ".flac", lambda: None)
    assert seen[0]["headers"]["x-oss-object-acl"] == "private"
    assert urlsplit(url).scheme == "https"
    assert parse_qs(urlsplit(url).query)["x-oss-expires"] == [str(service.config.url_ttl)]


def test_instance_credential_chain_is_used_when_fixed_keys_absent(service, monkeypatch):
    oss2 = pytest.importorskip("oss2")
    from types import SimpleNamespace
    from alibabacloud_credentials.client import Client
    monkeypatch.setenv("ALIYUN_OSS_BUCKET", "unit-asr-bucket")
    monkeypatch.delenv("ALIYUN_OSS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIYUN_OSS_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.setattr(oss2.Bucket, "get_bucket_acl", lambda _: SimpleNamespace(acl="private"))
    monkeypatch.setattr(Client, "__init__", lambda self: None)
    monkeypatch.setattr(Client, "get_credential", lambda _: SimpleNamespace(access_key_id="mock-role-ak", access_key_secret="mock-role-sk", security_token="mock-sts"))
    bucket = OSSStorage(service.config).connect()
    assert "x-oss-security-token" in bucket.sign_url("GET", "asr/" + "a" * 32 + ".flac", 60)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://169.254.169.254/latest", "https://user:pass@example.com/a", "https://example.com:444/a"])
def test_media_urls_reject_local_and_unsafe_protocols(tmp_path, url):
    with pytest.raises(AnalysisError) as error:
        network.download(url, tmp_path / "audio", 1024)
    assert error.value.code == "ASR_URL_UNSAFE"


def test_dns_mixed_public_private_is_rejected(monkeypatch):
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(AnalysisError):
        network.public_addresses("test", 443)


def test_redirect_revalidates_and_does_not_forward_secrets(tmp_path, monkeypatch):
    seen = []
    class Response:
        status = 302
        def getheader(self, *args):
            return "https://127.0.0.1/secret"
    class Connection:
        def __init__(self, host, **kw):
            if host == "127.0.0.1":
                raise AnalysisError("ASR_URL_UNSAFE", "内网地址")
        def request(self, method, path, headers):
            seen.append(headers)
        def getresponse(self):
            return Response()
        def close(self):
            pass
    monkeypatch.setattr(network, "PinnedHTTPS", Connection)
    with pytest.raises(AnalysisError):
        network.download("https://example.com/audio", tmp_path / "a", 1024, headers={"Cookie": "secret", "Authorization": "key"})
    assert not any("Cookie" in h or "Authorization" in h for h in seen)


def test_temp_sweeper_only_removes_old_owned_directories(tmp_path):
    old = tmp_path / ("a" * 32)
    old.mkdir()
    os.utime(old, (0, 0))
    unrelated = tmp_path / "keep-me"
    unrelated.mkdir()
    sweep(tmp_path)
    assert not old.exists() and unrelated.is_dir()


def test_audio_worker_prefers_audio_only_and_rejects_manifests():
    audio = {"url": "https://cdn.example/audio.m4a", "protocol": "https", "vcodec": "none", "acodec": "aac", "abr": 64}
    video = {"url": "https://cdn.example/video.mp4", "protocol": "https", "vcodec": "h264", "acodec": "aac", "tbr": 32}
    assert audio_worker.select_media({"formats": [video, audio]}) == audio
    with pytest.raises(AnalysisError) as error:
        audio_worker.select_media({"formats": [{"url": "https://cdn.example/index.m3u8", "protocol": "m3u8_native"}]})
    assert error.value.code == "ASR_AUDIO_UNAVAILABLE"


def test_audio_supervisor_kills_child_on_cancellation(tmp_path, service, monkeypatch):
    from app.asr import audio
    class Process:
        pid = 12345
        def poll(self):
            return None
    killed = []
    monkeypatch.setattr(audio.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(audio, "stop_process", lambda p: killed.append(p.pid))
    def cancel():
        raise JobStopped()
    with pytest.raises(JobStopped):
        audio.prepare_audio(URL, tmp_path, service.config, cancel)
    assert killed == [12345]


def test_asr_generated_transcript_uses_existing_summary_api(service, api, engine, monkeypatch):
    monkeypatch.setattr(subtitle_service, "platform_url", lambda url: ("Bilibili", url))
    def no_captions(*a, **kw):
        raise AnalysisError("CAPTIONS_ACCESS_REQUIRED", "需要登录字幕")
    monkeypatch.setattr(subtitle_service, "extract_transcript", no_captions)
    engine.asr = service
    class Model:
        def __init__(self, *a, **kw):
            pass
        def complete(self, *a, **kw):
            return content()
        def complete_stream(self, *a, **kw):
            return content()
    engine.client_factory = Model
    result = api.post("/api/v1/analyses", json={"url": URL, "auto_summary": True}).json()
    assert finish(engine, result["job_id"])["status"] == "ready"
    for _ in range(200):
        if engine.store.get(result["id"])["summary_status"] == "ready":
            break
        time.sleep(0.01)
    response = api.get(f"/api/v1/analyses/{result['id']}/summary").json()
    assert response["status"] == "ready" and response["summary"]["content"]["headline"] == "学习方法"
    cues = api.get(f"/api/v1/analyses/{result['id']}/transcript").json()["items"]
    assert cues[0]["source"] == "asr" and cues[0]["provider"] == "aliyun_paraformer"


def test_local_ffmpeg_produces_bounded_flac_with_one_thread(tmp_path, monkeypatch):
    """Real local conversion only. No platform/OSS/paid cloud request."""
    from app import video_service
    ffmpeg = video_service._ffmpeg_location()
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    media = tmp_path / "fixture.wav"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-threads", "1", str(media)], check=True, capture_output=True)
    monkeypatch.setattr(audio_worker, "platform_url", lambda _: ("Douyin", URL))
    from app.douyin import DouyinVideo
    monkeypatch.setattr(audio_worker.douyin, "resolve_video", lambda _: DouyinVideo("1234567890", "本地测试", ("https://example.com/a",), None, 2, 1, 1))
    def copy(url, target, *args):
        import shutil
        shutil.copyfile(media, target)
    monkeypatch.setattr(audio_worker, "download", copy)
    result = audio_worker.prepare({"url": URL, "audio_timeout": 30, "max_duration": 3, "max_download_bytes": 1024 * 1024,
                                   "max_audio_bytes": 1024 * 1024, "threads": 1}, tmp_path)
    assert result["duration"] == 2
    assert (tmp_path / "audio.flac").stat().st_size < 1024 * 1024
    assert not (tmp_path / "source.media").exists()
