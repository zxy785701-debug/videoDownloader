import hashlib
import json
import logging
import math
import time
import uuid
from contextlib import ExitStack

from .. import subtitle_service
from ..analysis_errors import AnalysisError
from .audio import prepare_audio
from .config import ASRUser, get_config
from .network import result_json
from .providers import AliyunParaformer, RetryableQuery
from .storage import OSSStorage
from .store import ASRStore
from .subtitles import transcript
from .temporary import file_slot, sweep, workspace

logger = logging.getLogger(__name__)
FALLBACK_CODES = {"NO_CAPTIONS", "EMPTY_TRANSCRIPT", "CAPTIONS_ACCESS_REQUIRED",
                  "CAPTIONS_FETCH_FAILED", "SUBTITLE_FORMAT_UNSUPPORTED"}


class ASRService:
    def __init__(self, root):
        self.config = get_config(root)
        self.store_path = root / "asr.sqlite3"
        self._store = None
        self.provider = AliyunParaformer(self.config)
        self.storage = OSSStorage(self.config)
        self.audio = prepare_audio
        self.read_result = result_json
        if self.config.enabled:
            try:
                sweep(self.config.temp_root)
            except OSError:
                logger.warning("ASR temporary cleanup deferred")

    @property
    def store(self):
        if self._store is None:
            import sqlite3
            try:
                self._store = ASRStore(self.store_path)
            except (OSError, sqlite3.Error, RuntimeError) as error:
                raise AnalysisError("ASR_STORE_UNAVAILABLE", "转录任务数据库不可用，请管理员检查数据目录权限；原生字幕仍可使用。", 503) from error
        return self._store

    @store.setter
    def store(self, value):
        self._store = value

    def extract(self, url, language, metadata, user_key, check, stage):
        try:
            result = subtitle_service.extract_transcript(url, language, on_metadata=metadata)
            # Some extractors/tests can return a nominally successful empty body.
            if not result.get("cues") or not any(c.get("text", "").strip() for c in result["cues"]):
                raise AnalysisError("EMPTY_TRANSCRIPT", "原生字幕没有有效内容。")
            return result
        except AnalysisError as error:
            if error.code not in FALLBACK_CODES or not self.config.enabled:
                raise
            check()
            stage("原生字幕不可用，准备语音转录")
        return self.transcribe(url, language, user_key, check, stage)

    def _sleep(self, seconds, check):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            check()
            time.sleep(min(0.2, max(0, until - time.monotonic())))

    def transcribe(self, url, language, user_key, check, stage):
        self.config.require()
        user_key = user_key() if callable(user_key) else user_key
        member = isinstance(user_key, ASRUser) and user_key.member
        user_key = user_key.key if isinstance(user_key, ASRUser) else user_key
        deadline = time.monotonic() + self.config.job_timeout
        def bounded_check():
            check()
            if time.monotonic() >= deadline:
                raise AnalysisError("ASR_TIMEOUT", "云端语音转录等待超时；重试将先查询已保存任务，不会直接重复提交。")
        with ExitStack() as stack:
            # OS slots also bound media work in concurrent processes.
            while True:
                bounded_check()
                for slot in range(self.config.concurrency):
                    acquired = stack.enter_context(file_slot(self.config.temp_root / f"slot-{slot}.lock"))
                    if acquired:
                        break
                if acquired:
                    break
                stack.close()
                stage("等待语音转录处理名额")
                self._sleep(0.5, bounded_check)
            return self._transcribe(url, language, user_key, bounded_check, stage, member=member)

    def _existing(self, task, directory, metadata, language, check, stage):
        if task["state"] == "ready":
            stage("复用已缓存语音转录")
            return {**json.loads(task["result"]), **metadata}
        if task["task_id"]:
            stage("恢复查询原云端识别任务")
            return self._poll(task["cache_key"], task["task_id"], directory, metadata, language, check, stage)
        if task["state"] in {"submitting", "unknown"}:
            raise AnalysisError("ASR_SUBMISSION_UNKNOWN", "此前识别提交结果不明，已阻止重复计费；请管理员核查百炼任务。")
        if task["state"] == "failed":
            raise AnalysisError(task["error_code"] or "ASR_FAILED", "此前云端识别已失败，未自动提交新的付费任务。请管理员核查原任务。")
        return None

    def _transcribe(self, url, language, user_key, check, stage, *, member=False):
        video_key = hashlib.sha256((url + ":" + self.config.fingerprint(language)).encode()).hexdigest()
        key = None
        required_disk = self.config.max_download_bytes + self.config.max_audio_bytes + 64 * 1024 * 1024
        with workspace(self.config.temp_root, required_disk) as directory, ExitStack() as claims:
            try:
                self.cleanup_objects(check)
                prior = self.store.video_task(video_key)
                if prior and prior["state"] not in {"reserved", "preflight_failed", "rejected"}:
                    key = prior["cache_key"]
                    metadata = json.loads(prior["metadata"]) if prior["metadata"] else {"title": "语音转录", "source_id": "", "duration": prior["duration"]}
                    result = self._existing(prior, directory, metadata, language, check, stage)
                    if result:
                        return result
                # Validate storage before spending resources on a download.
                self.storage.connect()
                stage("提取音频并转换为单声道 FLAC")
                audio, metadata = self.audio(url, directory, self.config, check)
                duration = metadata["duration"]
                if not math.isfinite(duration) or duration <= 0 or duration > self.config.max_duration:
                    raise AnalysisError("ASR_VIDEO_TOO_LONG", "音频时长无效或超过语音转录上限。")
                if audio.stat().st_size > self.config.max_audio_bytes:
                    raise AnalysisError("ASR_FILE_TOO_LARGE", "音频文件超过上限。")
                digest = hashlib.sha256()
                with audio.open("rb") as stream:
                    while block := stream.read(64 * 1024):
                        check()
                        digest.update(block)
                key = hashlib.sha256((digest.hexdigest() + self.config.fingerprint(language)).encode()).hexdigest()
                # Different videos with identical audio can arrive in separate
                # slots. Hold a content lock through cache/save/cleanup.
                while not claims.enter_context(file_slot(self.config.temp_root / (key + ".lock"))):
                    claims.close()
                    self._sleep(0.5, check)
                prior = self.store.get_task(key)
                if prior:
                    self.store.alias(video_key, key, metadata)
                    result = self._existing(prior, directory, metadata, language, check, stage)
                    if result:
                        return result
                task = self.store.reserve(key, video_key, duration, user_key, self.config, member=member)
                self.store.alias(video_key, key, metadata)
                self.store.update_task(key, metadata=metadata)
                if task["state"] == "preflight_failed":
                    self.store.update_task(key, state="reserved", error_code=None)
                check()
                estimated = task["estimated_cny"]
                stage(f"上传临时音频；本次识别估算 ¥{estimated:.4f}")
                object_key = "asr/" + uuid.uuid4().hex + ".flac"
                self.store.update_task(key, object_key=object_key)
                signed_url = self.storage.upload(audio, object_key, check)
                check()
                # Crash window is intentionally treated as unknown on recovery.
                self.store.update_task(key, state="submitting", calls=task["calls"] + 1)
                task_id = self.provider.submit(signed_url, language)
                self.store.update_task(key, state="pending", task_id=task_id)
                return self._poll(key, task_id, directory, metadata, language, check, stage)
            except BaseException as error:
                if key:
                    task = self.store.get_task(key)
                    code = error.code if isinstance(error, AnalysisError) else "ASR_INTERRUPTED"
                    if task and task["state"] == "submitting":
                        unknown = code not in {"ASR_AUTH_FAILED", "ASR_RATE_LIMITED", "ASR_SUBMIT_FAILED"}
                        self.store.update_task(key, state="unknown" if unknown else "rejected", error_code=code,
                            **({} if unknown else {"reserved_cny": 0}))
                    elif task and task["state"] == "reserved":
                        # No paid submission yet: safe to retry preparation.
                        self.store.update_task(key, state="preflight_failed", error_code=code, reserved_cny=0)
                raise
            finally:
                if key:
                    self._cleanup_object(self.store.get_task(key))

    def _poll(self, key, task_id, directory, metadata, language, check, stage):
        failures = 0
        while True:
            check()
            try:
                response = self.provider.query(task_id)
                failures = 0
            except RetryableQuery:
                failures += 1
                if failures > self.config.retries:
                    raise
                self._sleep(min(2 ** failures, 10), check)
                continue
            output = response["output"]
            usage = (response.get("usage") or {}).get("duration")
            reported = usage if isinstance(usage, (int, float)) and not isinstance(usage, bool) and math.isfinite(usage) and usage >= 0 else None
            if reported is not None:
                self.store.update_task(key, reported_seconds=reported)
            status = output.get("task_status")
            if status in {"PENDING", "RUNNING"}:
                stage("云端识别排队中" if status == "PENDING" else "云端正在识别音频")
                self._sleep(self.config.poll_interval, check)
                continue
            if status != "SUCCEEDED":
                if status in {"FAILED", "CANCELED", "CANCELLED"}:
                    self.store.update_task(key, state="failed", error_code="ASR_FAILED")
                    raise AnalysisError("ASR_FAILED", "云端语音识别失败，未生成转录内容；未自动重复提交付费任务。")
                raise AnalysisError("ASR_STATUS_UNKNOWN", "云端返回未知状态；已保存原任务，未重复提交。")
            results = output.get("results") or []
            if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict) or results[0].get("subtask_status") != "SUCCEEDED":
                self.store.update_task(key, state="failed", error_code="ASR_FAILED")
                raise AnalysisError("ASR_FAILED", "云端音频子任务失败，无法生成有效字幕。")
            # Retrieval retries are free; submission is never repeated.
            for attempt in range(self.config.retries + 1):
                try:
                    result_url = results[0].get("transcription_url")
                    if not isinstance(result_url, str):
                        raise AnalysisError("ASR_RESULT_INVALID", "云端识别成功但未返回有效转录地址；未重新提交任务。")
                    data = self.read_result(result_url, directory, check)
                    break
                except (OSError, AnalysisError):
                    if attempt == self.config.retries:
                        raise
                    self._sleep(min(2 ** attempt, 10), check)
            result = transcript(data, metadata, language, self.config.provider)
            check()
            self.store.update_task(key, state="ready", result=result, reported_seconds=reported)
            return result

    def _cleanup_object(self, task):
        if not task or not task["object_key"]:
            return
        try:
            self.storage.delete(task["object_key"])
            self.store.update_task(task["cache_key"], object_key=None)
        except Exception as error:
            # Retain durable cleanup obligation; never log URL/credentials/body.
            logger.warning("ASR object cleanup deferred type=%s", type(error).__name__)

    def cleanup_objects(self, check=lambda: None):
        for task in self.store.artifacts():
            check()
            # Do not interfere with another slot's active uploads. Old artifacts
            # are reclaimed after URL expiry; failures/ready are safe immediately.
            if task["state"] in {"ready", "failed", "preflight_failed", "rejected"} or task["created"] < time.time() - self.config.url_ttl:
                self._cleanup_object(task)
