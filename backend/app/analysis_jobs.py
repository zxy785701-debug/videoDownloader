import logging
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import chat_service, subtitle_service, summary_service
from .ai_config import get_config, setting
from .analysis_errors import AnalysisError, JobStopped
from .analysis_store import AnalysisStore
from .deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)


def identifier() -> str:
    return secrets.token_urlsafe(18)


class AnalysisEngine:
    def __init__(self, store: AnalysisStore, workers: int = 2):
        self.store = store
        self.store.recover()
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(workers + 10)
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="video-learning")
        self.futures = {}
        self.closed = False
        self.client_factory = DeepSeekClient
        self.chat_streams = {}
        self.summary_streams = {}

    def _reserve(self):
        if self.closed:
            raise AnalysisError("SERVICE_STOPPING", "服务正在停止，请稍后重试。", 503)
        if not self.slots.acquire(blocking=False):
            raise AnalysisError("QUEUE_FULL", "学习任务队列已满，请等待现有任务结束后再试。", 429)

    def _schedule(self, job_id, record_id, kind, action, message_id=None):
        try:
            future = self.executor.submit(self._run, job_id, record_id, kind, action, message_id)
            self.futures[job_id] = future
            def finished(_):
                with self.lock:
                    self.futures.pop(job_id, None)
                    self.slots.release()
                    if kind == "subtitle":
                        self._continue_auto_summary(record_id)
            future.add_done_callback(finished)
        except Exception:
            self.slots.release()
            raise

    def check(self, job_id):
        job = self.store.job(job_id)
        if self.closed or not job or job["status"] not in {"queued", "processing"}:
            raise JobStopped()

    def _run(self, job_id, record_id, kind, action, message_id):
        try:
            self.check(job_id)
            self.store.set_job(job_id, "processing", "获取字幕" if kind == "subtitle" else "正在处理")
            if kind == "subtitle":
                self.store.update(record_id, subtitle_status="fetching", subtitle_error=None, subtitle_error_code=None)
            elif kind == "summary":
                self.store.update(record_id, summary_status="processing")
            else:
                self.store.set_message(message_id, "processing")
            action()
            self.check(job_id)
            self.store.set_job(job_id, "ready", "处理完成")
        except JobStopped:
            return
        except Exception as error:
            current = self.store.job(job_id)
            if self.closed or not current or current["status"] not in {"queued", "processing"}:
                return
            failure = error if isinstance(error, AnalysisError) else AnalysisError("PROCESSING_FAILED", "处理失败，请稍后重试。")
            logger.warning("Learning job failed kind=%s code=%s type=%s", kind, failure.code, type(error).__name__)
            if kind == "subtitle":
                unavailable = failure.code in {"NO_CAPTIONS", "EMPTY_TRANSCRIPT", "SUBTITLE_FORMAT_UNSUPPORTED"}
                self.store.update(record_id, subtitle_status="unavailable" if unavailable else "failed",
                                  subtitle_error=failure.message, subtitle_error_code=failure.code)
            elif kind == "summary":
                self.store.update(record_id, summary_status="failed")
            else:
                self.store.set_message(message_id, "failed", error=failure.message, code=failure.code)
            # Consumers may stop polling a terminal job: publish it after its result state.
            self.store.set_job(job_id, "failed", "处理未完成", failure.message, failure.code)
        finally:
            with self.lock:
                self.summary_streams.pop(job_id, None)
                if message_id:
                    self.chat_streams.pop(message_id, None)

    def start_transcript(self, url: str, language: str, auto_summary: bool = False) -> dict:
        platform, safe_url = subtitle_service.platform_url(url)
        with self.lock:
            record = self.store.find(safe_url, language)
            if record:
                active = self.store.active_job(record["id"], "subtitle")
                # Opening/reparsing a failed automatic flow is not permission to
                # retry a paid request. Explicit subtitle/summary retries remain available.
                if auto_summary and record["subtitle_status"] in {"failed", "unavailable"}:
                    return {"id": record["id"], "job_id": None, "cached": True}
                if active or record["subtitle_status"] == "ready":
                    if auto_summary:
                        self._request_auto_summary(record["id"])
                    return {"id": record["id"], "job_id": active["id"] if active else None, "cached": not bool(active)}
            self._reserve()
            try:
                record_id = record["id"] if record else identifier()
                if not record:
                    self.store.create(record_id, safe_url, platform, language)
                job_id = identifier()
                self.store.new_job(job_id, record_id, "subtitle", "等待获取字幕")
                self.store.update(record_id, subtitle_status="pending", subtitle_error=None, subtitle_error_code=None)
                if auto_summary:
                    self._request_auto_summary(record_id)
            except Exception:
                self.slots.release()
                raise
            def action():
                result = subtitle_service.extract_transcript(
                    safe_url, language,
                    on_metadata=lambda meta: self._metadata(job_id, record_id, meta),
                )
                self.check(job_id)
                self.store.save_transcript(record_id, result)
            self._schedule(job_id, record_id, "subtitle", action)
            return {"id": record_id, "job_id": job_id, "cached": False}

    def _request_auto_summary(self, record_id: str):
        """Persist one opt-in continuation using the existing job schema."""
        record = self.store.get(record_id)
        if self.store.summary(record_id) or record["summary_status"] != "idle":
            return
        prior = next((job for job in self.store.latest_jobs(record_id) if job["kind"] == "auto_summary"), None)
        if not prior:
            self.store.new_job(identifier(), record_id, "auto_summary", "字幕获取成功后自动总结")
        elif prior["status"] not in {"queued", "processing"}:
            return
        if record["subtitle_status"] == "ready":
            self._continue_auto_summary(record_id)

    def _continue_auto_summary(self, record_id: str):
        # Called under the engine lock after the subtitle slot is released.
        # No worker waits for another worker, including with workers=1.
        if self.closed:
            return
        pending = self.store.active_job(record_id, "auto_summary")
        if not pending:
            return
        try:
            record = self.store.get(record_id)
            if record["subtitle_status"] in {"pending", "fetching"}:
                return
            if record["subtitle_status"] != "ready":
                self.store.set_job(pending["id"], "failed", "未启动自动总结",
                                   record["subtitle_error"] or "没有有效字幕，未调用模型。",
                                   record["subtitle_error_code"] or "TRANSCRIPT_NOT_READY")
                return
            # A manual action may have completed while the subtitle callback
            # waited for the lock. Reuse it even if model settings have changed.
            if self.store.summary(record_id):
                self.store.set_job(pending["id"], "ready", "已复用保存的摘要")
                return
            if record["summary_status"] in {"failed", "interrupted"}:
                self.store.set_job(pending["id"], "cancelled", "请手动重试总结")
                return
            self.start_summary(record_id, streaming=True)
            self.store.set_job(pending["id"], "ready", "已接续摘要任务")
        except AnalysisError as error:
            if error.code == "NOT_FOUND":
                return
            self.store.update(record_id, summary_status="failed")
            self.store.set_job(pending["id"], "failed", "自动总结未启动", error.message, error.code)
        except Exception as error:
            # Continuation failure must not undo successfully saved subtitles.
            logger.warning("Auto summary continuation failed type=%s", type(error).__name__)
            self.store.update(record_id, summary_status="failed")
            self.store.set_job(pending["id"], "failed", "自动总结未启动",
                               "自动总结未启动，请手动重试。", "PROCESSING_FAILED")

    def _metadata(self, job_id, record_id, metadata):
        self.check(job_id)
        self.store.update(record_id, **metadata)

    def _client(self, record_id, job_id, config):
        return self.client_factory(
            config, lambda: self.check(job_id),
            lambda usage: self.store.record_usage(record_id, job_id, config.model, usage),
        )

    def start_summary(self, record_id: str, force: bool = False, streaming: bool = False) -> dict:
        with self.lock:
            record = self.store.get(record_id)
            if record["subtitle_status"] != "ready":
                raise AnalysisError("TRANSCRIPT_NOT_READY", "需先成功获取有效字幕，才能生成摘要。", 409)
            active = self.store.active_job(record_id, "summary")
            if active:
                return {"id": record_id, "job_id": active["id"], "cached": False}
            config = get_config()
            config.require_key()
            fingerprint = summary_service.fingerprint(record, config)
            saved = self.store.summary(record_id)
            if saved and saved["fingerprint"] == fingerprint and record["summary_status"] == "ready" and not force:
                return {"id": record_id, "job_id": None, "cached": True}
            salt = ":" + identifier() if force else ""
            if not force and record["summary_status"] in {"failed", "interrupted"}:
                previous = next((j for j in self.store.latest_jobs(record_id) if j["kind"] == "summary" and j["fingerprint"].startswith(fingerprint)), None)
                if previous:
                    salt = previous["fingerprint"][len(fingerprint):]
            self._reserve()
            try:
                job_id = identifier()
                self.store.new_job(job_id, record_id, "summary", "等待总结", fingerprint + salt)
                self.store.update(record_id, summary_status="queued")
            except Exception:
                self.slots.release()
                raise
            if streaming:
                self.summary_streams[job_id] = {"record_id": record_id, "text": "", "stage": "等待总结", "phase": "waiting", "parts": []}
            def action():
                cues = self.store.cues(record_id)
                if not cues:
                    raise AnalysisError("EMPTY_TRANSCRIPT", "有效字幕不存在，无法总结。")
                preview_args = {
                    "on_preview": lambda text, stage, phase: self._summary_preview(job_id, text, stage, phase),
                    "on_retry": lambda stage, reason: self._summary_retry(job_id, stage, reason),
                } if streaming else {}
                content = summary_service.generate_summary(
                    record, cues, self._client(record_id, job_id, config), config, self.store,
                    lambda text: self.store.set_job(job_id, "processing", text),
                    lambda: self.check(job_id), salt,
                    **preview_args,
                )
                self.check(job_id)
                self.store.save_summary(record_id, identifier(), fingerprint, content, config.model, summary_service.PROMPT_VERSION)
            try:
                self._schedule(job_id, record_id, "summary", action)
            except Exception:
                self.summary_streams.pop(job_id, None)
                raise
            return {"id": record_id, "job_id": job_id, "cached": False}

    def _summary_preview(self, job_id, text, stage, phase):
        self.check(job_id)
        with self.lock:
            if job_id in self.summary_streams:
                state = self.summary_streams[job_id]
                parts = state["parts"]
                if phase == "starting" or not parts or parts[-1]["stage"] != stage:
                    parts.append({"id": len(parts) + 1, "stage": stage, "attempt": 1, "text": "", "phase": phase})
                elif phase == "retrying":
                    parts[-1]["phase"] = "superseded"
                    parts.append({"id": len(parts) + 1, "stage": stage, "attempt": parts[-1]["attempt"] + 1,
                                  "text": "", "phase": phase, "retry_reason": state.pop("next_retry_reason", "模型输出未通过校验。")})
                parts[-1].update(text=text, phase=phase)
                state.update(text=text, stage=stage, phase=phase)

    def _summary_retry(self, job_id, stage, reason):
        self.check(job_id)
        with self.lock:
            state = self.summary_streams.get(job_id)
            if state and state["stage"] == stage:
                state["next_retry_reason"] = reason

    def summary_preview(self, job_id):
        with self.lock:
            state = self.summary_streams.get(job_id)
            if not state:
                return {}
            return {**state, "parts": [dict(part) for part in state["parts"]]}

    def start_chat(self, record_id: str, question: str, request_id: str, streaming: bool = False) -> dict:
        question = question.strip()
        if not question:
            raise AnalysisError("QUESTION_EMPTY", "请输入针对视频内容的问题。")
        with self.lock:
            record = self.store.get(record_id)
            if record["subtitle_status"] != "ready":
                raise AnalysisError("TRANSCRIPT_NOT_READY", "需先获取有效字幕，才能针对视频提问。", 409)
            history = self.store.messages(record_id)
            prior = next((m for m in history if m["request_id"] == request_id), None)
            if prior:
                if prior["question"] != question:
                    raise AnalysisError("REQUEST_ID_CONFLICT", "请求标识已用于另一个问题，请重新发送。", 409)
                return {"message_id": prior["id"], "job_id": prior["job_id"], "cached": True}
            if self.store.active_job(record_id, "chat"):
                raise AnalysisError("CHAT_BUSY", "上一条回答仍在处理中，请等待完成。", 409)
            config = get_config()
            config.require_key()
            self._reserve()
            try:
                job_id, message_id = identifier(), identifier()
                self.store.new_job(job_id, record_id, "chat", "等待回答")
                self.store.new_message(message_id, record_id, job_id, request_id, question)
            except Exception:
                self.slots.release()
                raise
            if streaming:
                self.chat_streams[message_id] = {"record_id": record_id, "text": "", "stage": "waiting"}
            def action():
                self.store.set_job(job_id, "processing", "根据字幕回答")
                answer = chat_service.generate_answer(record, self.store.cues(record_id), question, history,
                                                      self._client(record_id, job_id, config), config,
                                                      (lambda text, stage: self._chat_preview(message_id, job_id, text, stage)) if streaming else None)
                self.check(job_id)
                self.store.set_message(message_id, "ready", answer=answer)
            try:
                self._schedule(job_id, record_id, "chat", action, message_id)
            except Exception:
                self.chat_streams.pop(message_id, None)
                raise
            return {"message_id": message_id, "job_id": job_id, "cached": False}

    def _chat_preview(self, message_id, job_id, text, stage):
        self.check(job_id)
        with self.lock:
            if message_id in self.chat_streams:
                self.chat_streams[message_id].update(text=text, stage=stage)

    def chat_preview(self, message_id):
        with self.lock:
            return dict(self.chat_streams.get(message_id, {}))

    def _clear_chat_previews(self, record_id):
        for message_id, state in list(self.chat_streams.items()):
            if state["record_id"] == record_id:
                self.chat_streams.pop(message_id, None)

    def delete(self, record_id: str):
        with self.lock:
            self.store.delete(record_id)
            self._clear_chat_previews(record_id)
            for job_id, state in list(self.summary_streams.items()):
                if state["record_id"] == record_id:
                    self.summary_streams.pop(job_id, None)
            for job_id, future in list(self.futures.items()):
                if not self.store.job(job_id):
                    future.cancel()

    def clear_messages(self, record_id: str):
        with self.lock:
            self.store.clear_messages(record_id)
            self._clear_chat_previews(record_id)

    def close(self):
        with self.lock:
            self.closed = True
            self.chat_streams.clear()
            self.summary_streams.clear()
            self.store.recover()
            self.executor.shutdown(wait=False, cancel_futures=True)


_engine = None
_engine_lock = threading.RLock()


def get_engine() -> AnalysisEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            default_path = Path(__file__).resolve().parents[1] / "data" / "learning.sqlite3"
            try:
                _engine = AnalysisEngine(AnalysisStore(Path(setting("VIDEO_LEARNING_DB", str(default_path)))))
            except (OSError, sqlite3.Error, RuntimeError) as error:
                raise AnalysisError("STORE_UNAVAILABLE", "本机学习数据库无法打开，请检查数据目录权限或数据库版本。下载功能仍可使用。", 503) from error
        return _engine


def close_engine():
    global _engine
    with _engine_lock:
        if _engine:
            _engine.close()
            _engine = None
