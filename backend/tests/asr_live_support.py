"""Real-cloud observations; persist only explicitly selected safe fields.

OSS and Paraformer use production implementations. Only audio acquisition uses
the local fixture. Keep the ledger across retries to protect unknown submissions.
"""
import hashlib
import json
import logging
import math
import os
import re
import shutil
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from app.analysis_errors import AnalysisError
from app.asr.network import PinnedHTTPS, download
from app.asr.providers import AliyunParaformer
from app.asr.service import ASRService
from app.asr.temporary import file_slot


CHECKS = (
    "private_bucket", "uploaded", "unsigned_access_denied", "signed_https",
    "short_lived_signature", "signed_audio_matches", "task_id_saved",
    "provider_succeeded", "subtitle_valid", "object_deleted", "local_tmp_cleaned",
    "repeat_cache_hit",
)
CLOUD_CODES = {
    "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "NoSuchBucket",
    "NoSuchKey", "RequestTimeTooSkewed", "SecurityTokenExpired", "InvalidSecurityToken",
    "InvalidArgument", "InvalidApiKey", "InvalidParameter", "InvalidParameter.Model",
    "InvalidFile.DownloadFailed", "InvalidFile.Format", "InvalidFile.UnsupportedFormat",
    "InvalidFile.Empty", "InvalidFile.TooLarge", "UnsupportedOperation", "ModelNotFound",
    "Throttling", "Throttling.RateQuota", "Throttling.AllocationQuota", "ServiceUnavailable",
    "InternalError", "BadRequest", "Unauthorized", "Forbidden", "AllocationQuota.FreeTierOnly",
}


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(64 * 1024):
            digest.update(block)
    return digest.hexdigest()


def inspect_audio(path):
    if not path.is_file() or not 0 < path.stat().st_size < 2 * 1024 * 1024:
        raise AnalysisError("LIVE_AUDIO_INVALID", "测试音频必须存在且小于 2 MiB。")
    with path.open("rb") as stream:
        header = stream.read(42)
    if (len(header) < 42 or header[:4] != b"fLaC" or header[4] & 0x7f != 0
            or int.from_bytes(header[5:8], "big") != 34):
        raise AnalysisError("LIVE_AUDIO_INVALID", "测试音频必须是有效 FLAC。")
    packed = int.from_bytes(header[18:26], "big")
    rate = packed >> 44
    channels = ((packed >> 41) & 7) + 1
    samples = packed & ((1 << 36) - 1)
    if rate != 16000 or channels != 1 or not 0 < samples / rate <= 30:
        raise AnalysisError("LIVE_AUDIO_INVALID", "测试仅允许 30 秒以内的 16kHz 单声道 FLAC。")
    return {"bytes": path.stat().st_size, "sample_rate": rate, "channels": channels,
            "duration_seconds": samples / rate, "sha256": file_hash(path)}


def safe_cloud_fields(value):
    """Never copy upstream message/body/headers/URL, even for failures."""
    result = {}
    code = value.get("code") if isinstance(value, dict) else getattr(value, "code", None)
    if isinstance(code, str):
        result["cloud_code"] = code if code in CLOUD_CODES else "OTHER"
    status = getattr(value, "status", None)
    if type(status) is int and 100 <= status <= 599:
        result["http_status"] = status
    request_id = value.get("request_id") if isinstance(value, dict) else getattr(value, "request_id", None)
    if isinstance(request_id, str) and re.fullmatch(r"[0-9a-fA-F-]{16,64}", request_id):
        result["request_id"] = request_id
    return result


def unsigned_status(url):
    parsed = urlsplit(url)
    connection = PinnedHTTPS(parsed.hostname, timeout=20)
    try:
        connection.request("GET", parsed.path)  # deliberately omit the signature
        return connection.getresponse().status
    finally:
        connection.close()


class ObservedStorage:
    def __init__(self, storage, report, save, verification_limit=2 * 1024 * 1024):
        self.inner, self.report, self.save = storage, report, save
        self.verification_limit = verification_limit

    def connect(self):
        self.report["last_operation"] = "oss_bucket_acl"
        bucket = self.inner.connect()  # production implementation enforces private
        self.report["checks"]["private_bucket"] = True
        self.save()
        return bucket

    def upload(self, path, key, check):
        self.report["last_operation"] = "oss_upload"
        self.save()
        url = self.inner.upload(path, key, check)
        checks = self.report["checks"]
        checks["uploaded"] = True
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        checks["signed_https"] = parsed.scheme == "https" and bool(parsed.query)
        checks["short_lived_signature"] = (
            params.get("x-oss-signature-version") == ["OSS4-HMAC-SHA256"]
            and params.get("x-oss-expires") == [str(self.inner.config.url_ttl)]
            and self.inner.config.url_ttl <= 86400
        )
        self.report["last_operation"] = "oss_unsigned_get"
        self.save()
        status = unsigned_status(url)
        self.report["unsigned_http_status"] = status
        checks["unsigned_access_denied"] = status == 403
        if not all(checks[name] for name in (
                "signed_https", "short_lived_signature", "unsigned_access_denied")):
            raise AnalysisError("LIVE_OSS_PRIVACY_FAILED", "签名或私有对象访问校验失败，未提交付费任务。")
        self.report["last_operation"] = "oss_signed_get"
        target = path.parent / "signed-check.flac"
        download(url, target, self.verification_limit, check)
        checks["signed_audio_matches"] = file_hash(target) == file_hash(path)
        self.save()
        if not checks["signed_audio_matches"]:
            raise AnalysisError("LIVE_AUDIO_MISMATCH", "签名链接读回的音频不一致，未提交付费任务。")
        return url

    def delete(self, key):
        self.report["cleanup_operation"] = "oss_delete_and_head"
        try:
            self.inner.delete(key)
            self.report["checks"]["object_deleted"] = not self.inner.connect().object_exists(key)
            if not self.report["checks"]["object_deleted"]:
                raise AnalysisError("LIVE_OSS_DELETE_FAILED", "删除后对象仍然存在。")
        except Exception as error:
            self.report["checks"]["object_deleted"] = False
            self.report["cleanup_error"] = safe_cloud_fields(error)
            raise
        finally:
            self.save()


class ObservedParaformer(AliyunParaformer):
    def __init__(self, config, report, save):
        super().__init__(config)
        self.report, self.save = report, save

    def _request(self, method, path, **kwargs):
        operation = "asr_submit" if path == "/services/audio/asr/transcription" else "asr_query"
        self.report["last_operation"] = operation
        self.report[operation + "_requests"] += 1
        self.save()
        response = super()._request(method, path, **kwargs)
        evidence = {"operation": operation, "http_status": response.status_code}
        try:
            data = response.json()
            evidence.update(safe_cloud_fields(data))
            output = data.get("output") or {}
            if isinstance(output, dict):
                status = output.get("task_status")
                if status in {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED", "CANCELLED"}:
                    evidence["task_status"] = status
                results = output.get("results") or []
                if isinstance(results, list) and results and isinstance(results[0], dict):
                    evidence["subtask"] = safe_cloud_fields(results[0])
                    substatus = results[0].get("subtask_status")
                    if substatus in {"SUCCEEDED", "FAILED"}:
                        evidence["subtask"]["status"] = substatus
                    self.report["checks"]["provider_succeeded"] = (
                        status == "SUCCEEDED" and substatus == "SUCCEEDED")
        except (ValueError, TypeError, AttributeError):
            evidence["response_json_invalid"] = True
        self.report["cloud_responses"].append(evidence)
        self.report["cloud_responses"] = self.report["cloud_responses"][-20:]
        self.save()
        return response


def run_live_check(source, root):
    root.mkdir(parents=True, exist_ok=True)
    with file_slot(root / "live-check.lock") as acquired:
        if not acquired:
            return {"status": "FAILED", "error_code": "LIVE_CHECK_ALREADY_RUNNING"}
        return _run_live_check(source, root)


def _run_live_check(source, root):
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "report.json"
    report = {"status": "RUNNING", "started_utc": datetime.now(timezone.utc).isoformat(),
              "model": "paraformer-v2", "checks": dict.fromkeys(CHECKS),
              "asr_submit_requests": 0, "asr_query_requests": 0, "cloud_responses": []}
    service = None

    def save():
        pending = root / "report.pending"
        pending.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.replace(report_path)

    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)  # SDK diagnostics may contain secret arguments
    try:
        report["audio"] = inspect_audio(source)
        service = ASRService(root)
        report["recognition_fingerprint"] = service.config.fingerprint("auto")
        report["target"] = {"bucket": os.getenv("ALIYUN_OSS_BUCKET", "").strip(),
                            "endpoint": os.getenv("ALIYUN_OSS_ENDPOINT", "https://oss-cn-beijing.aliyuncs.com").rstrip("/"),
                            "api_base": service.config.base_url}
        try:
            previous = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
        if (previous.get("audio", {}).get("sha256") == report["audio"]["sha256"]
                and previous.get("recognition_fingerprint") == report["recognition_fingerprint"]
                and previous.get("target") == report["target"]):
            report["checks"] = {k: previous.get("checks", {}).get(k) is True for k in CHECKS}
            report["historical_checks"] = [k for k, v in report["checks"].items() if v]
            report["historical_evidence_utc"] = previous.get("started_utc")
        service.storage = ObservedStorage(service.storage, report, save)
        service.provider = ObservedParaformer(service.config, report, save)

        def audio(url, directory, config, check):
            check()
            target = directory / "audio.flac"
            shutil.copyfile(source, target)
            return target, {"duration": report["audio"]["duration_seconds"],
                            "title": "真实云端集成测试", "source_id": "integration"}

        service.audio = audio
        save()
        url = "https://www.bilibili.com/video/BV1integration/" + report["audio"]["sha256"]
        result = service.transcribe(url, "auto", "integration", lambda: None, lambda _: None)
        cues = result.get("cues") or []
        report["checks"]["subtitle_valid"] = bool(cues) and result.get("track_kind") == "asr" and all(
            isinstance(c.get("text"), str) and c["text"].strip()
            and c.get("source") == "asr" and c.get("provider") == "aliyun_paraformer"
            and type(c.get("start")) in {int, float} and type(c.get("end")) in {int, float}
            and math.isfinite(c["start"]) and math.isfinite(c["end"])
            and 0 <= c["start"] < c["end"] <= report["audio"]["duration_seconds"] + 1
            for c in cues)
        report["subtitle_count"] = len(cues)
        # Audio text stays in the local transcript artifact, not diagnostic output.
        (root / "transcript.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        requests = (report["asr_submit_requests"], report["asr_query_requests"])
        stages = []
        cached = service.transcribe(url, "auto", "integration", lambda: None, stages.append)
        report["checks"]["repeat_cache_hit"] = (
            "复用已缓存语音转录" in stages and cached == result
            and requests == (report["asr_submit_requests"], report["asr_query_requests"])
            and report["asr_submit_requests"] <= 1)
        report["status"] = "CHECKING"
    except BaseException as error:
        report["status"] = "FAILED"
        report["error_code"] = error.code if isinstance(error, AnalysisError) else "LIVE_CHECK_INTERRUPTED"
        causes = []
        current = error
        for _ in range(5):
            fields = safe_cloud_fields(current)
            if fields:
                causes.append(fields)
            current = current.__cause__
            if current is None:
                break
        report["failure_diagnostics"] = causes
    finally:
        try:
            if service is not None:
                report["usage"] = service.store.usage_report()
                with service.store.connection() as db:
                    report["tasks"] = [dict(row) for row in db.execute(
                        "SELECT task_id,state,calls FROM asr_tasks ORDER BY created")]
                report["checks"]["task_id_saved"] = any(t["task_id"] for t in report["tasks"])
                report["pending_object_cleanup"] = len(service.store.artifacts())
                report["checks"]["local_tmp_cleaned"] = not any(
                    p.is_dir() for p in service.config.temp_root.iterdir())
                if report["status"] == "CHECKING":
                    if all(report["checks"].values()) and not report["pending_object_cleanup"]:
                        report["status"] = ("PASSED" if report["asr_submit_requests"] else
                                            "RESUMED_VERIFIED" if report["asr_query_requests"] else "CACHED_VERIFIED")
                    else:
                        report["status"], report["error_code"] = "FAILED", "LIVE_CHECK_INCOMPLETE"
        except Exception:
            report["status"], report["error_code"] = "FAILED", "LIVE_REPORT_FAILED"
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        logging.disable(previous_logging)
    print("ASR_LIVE_RESULT=" + json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    return report
