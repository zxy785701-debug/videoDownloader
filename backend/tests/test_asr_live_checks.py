"""MOCK-only regression checks for the real-cloud test's safety/observations."""
import json
import shutil

import httpx
import pytest

import asr_live_support as live
from app.analysis_errors import AnalysisError
from app.asr.providers import AliyunParaformer
from app.asr.storage import OSSStorage


SECRET_SENTINEL = "never-emit-this-fake-credential"
SIGNED_URL = ("https://fixture.oss-cn-beijing.aliyuncs.com/asr/test.flac"
              "?x-oss-signature-version=OSS4-HMAC-SHA256&x-oss-expires=7200"
              "&x-oss-signature=" + SECRET_SENTINEL)


def audio_file(path, rate=16000, channels=1, seconds=20):
    header = bytearray(42)
    header[:8] = b"fLaC\x80\x00\x00\x22"
    packed = (rate << 44) | ((channels - 1) << 41) | (15 << 36) | int(seconds * rate)
    header[18:26] = packed.to_bytes(8, "big")
    path.write_bytes(header + b"fixture")
    return path


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    """All network calls are mocked. Never consume the operator's real credentials."""
    root = tmp_path / "live"
    monkeypatch.setenv("ASR_ENABLED", "true")
    monkeypatch.setenv("ASR_TEMP_DIR", str(root / "asr-tmp"))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-test-key")
    monkeypatch.setenv("ALIYUN_OSS_BUCKET", "fixture")
    monkeypatch.setenv("ALIYUN_OSS_ENDPOINT", "https://oss-cn-beijing.aliyuncs.com")
    monkeypatch.setenv("ASR_API_BASE", "https://dashscope.aliyuncs.com/api/v1")
    source = audio_file(tmp_path / "fixture.flac")

    class Bucket:
        uploaded = False
        objects = {}

        def put_object_from_file(self, key, path, **kwargs):
            self.uploaded = True
            self.objects[key] = True

        def sign_url(self, *args, **kwargs):
            return SIGNED_URL

        def delete_object(self, key):
            self.objects.pop(key, None)

        def object_exists(self, key):
            return key in self.objects

    bucket = Bucket()
    monkeypatch.setattr(OSSStorage, "connect", lambda _: bucket)
    monkeypatch.setattr(live, "unsigned_status", lambda _: 403)
    monkeypatch.setattr(live, "download", lambda url, target, limit, check: shutil.copyfile(source, target))
    submissions = []

    def request(self, method, path, **kwargs):
        if path == "/services/audio/asr/transcription":
            submissions.append(kwargs)
            return httpx.Response(200, json={"output": {"task_id": "test-task-id", "task_status": "PENDING"}})
        return httpx.Response(200, json={"message": SECRET_SENTINEL, "usage": {"duration": 20},
            "output": {"task_status": "SUCCEEDED", "results": [{"subtask_status": "SUCCEEDED",
                "file_url": SIGNED_URL, "transcription_url": "https://fixture.oss-cn-beijing.aliyuncs.com/result"}]}})

    monkeypatch.setattr(AliyunParaformer, "_request", request)
    monkeypatch.setattr("app.asr.service.result_json", lambda *args: {"transcripts": [{"channel_id": 0,
        "sentences": [{"begin_time": 0, "end_time": 2000, "text": "测试转录。"}]}]})
    return source, root, bucket, submissions


def test_mocked_live_observations_and_durable_cache(cloud, capsys):
    source, root, bucket, submissions = cloud
    report = live.run_live_check(source, root)
    assert report["status"] == "PASSED"
    assert all(report["checks"].values())
    assert report["unsigned_http_status"] == 403
    assert not bucket.objects
    assert report["usage"][0]["actual_billed_cny"] is None
    assert report["asr_submit_requests"] == len(submissions) == 1
    cached = live.run_live_check(source, root)
    assert cached["status"] == "CACHED_VERIFIED"
    assert cached["asr_submit_requests"] == cached["asr_query_requests"] == 0
    assert len(submissions) == 1
    assert "signed_audio_matches" in cached["historical_checks"]
    output = capsys.readouterr().out + (root / "report.json").read_text(encoding="utf-8")
    assert SECRET_SENTINEL not in output and SIGNED_URL not in output


def test_public_object_blocks_paid_submission(cloud, monkeypatch):
    source, root, bucket, submissions = cloud
    monkeypatch.setattr(live, "unsigned_status", lambda _: 200)
    report = live.run_live_check(source, root)
    assert report["error_code"] == "LIVE_OSS_PRIVACY_FAILED"
    assert not report["checks"]["unsigned_access_denied"]
    assert not submissions and not bucket.objects


def test_upload_permission_error_is_sanitized(cloud, monkeypatch, capsys):
    source, root, bucket, submissions = cloud

    class Denied(Exception):
        code, status, request_id = "AccessDenied", 403, "0123456789ABCDEF01234567"

    def denied(*args, **kwargs):
        raise Denied(SECRET_SENTINEL + SIGNED_URL)

    monkeypatch.setattr(bucket, "put_object_from_file", denied)
    report = live.run_live_check(source, root)
    assert report["error_code"] == "ASR_OSS_UPLOAD_FAILED"
    assert report["failure_diagnostics"][-1]["cloud_code"] == "AccessDenied"
    assert not submissions and report["checks"]["local_tmp_cleaned"]
    assert SECRET_SENTINEL not in capsys.readouterr().out


def test_delete_permission_failure_is_not_reported_as_success(cloud, monkeypatch):
    source, root, bucket, _ = cloud

    def denied(*args):
        raise RuntimeError(SECRET_SENTINEL)

    monkeypatch.setattr(bucket, "delete_object", denied)
    report = live.run_live_check(source, root)
    assert report["status"] == "FAILED" and report["error_code"] == "LIVE_CHECK_INCOMPLETE"
    assert report["checks"]["object_deleted"] is False
    assert report["pending_object_cleanup"] == 1
    assert bucket.objects


def test_unknown_submit_is_not_resubmitted(cloud, monkeypatch):
    source, root, _, _ = cloud
    attempts = []

    def unknown(*args, **kwargs):
        attempts.append(1)
        raise httpx.ReadTimeout(SECRET_SENTINEL)

    monkeypatch.setattr(AliyunParaformer, "_request", unknown)
    first = live.run_live_check(source, root)
    second = live.run_live_check(source, root)
    assert first["error_code"] == second["error_code"] == "ASR_SUBMISSION_UNKNOWN"
    assert second["tasks"][0]["state"] == "unknown"
    assert second["asr_submit_requests"] == 0 and len(attempts) == 1


@pytest.mark.parametrize("params", [{"rate": 8000}, {"channels": 2}, {"seconds": 31}, {"seconds": 0}])
def test_fixture_limits_before_any_paid_call(tmp_path, params):
    with pytest.raises(AnalysisError, match="30 秒"):
        live.inspect_audio(audio_file(tmp_path / "bad.flac", **params))


def test_safe_fields_never_emit_raw_cloud_messages():
    assert live.safe_cloud_fields({"code": SECRET_SENTINEL, "message": SIGNED_URL,
                                   "request_id": SECRET_SENTINEL}) == {"cloud_code": "OTHER"}
