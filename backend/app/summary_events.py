"""Observe an existing summary job, including staged long-video drafts."""

import asyncio
import time

from .analysis_errors import AnalysisError
from .chat_events import event
from .summary_service import public_summary


def summary_job(engine, record_id, job_id):
    engine.store.get(record_id)
    job = engine.store.job(job_id)
    if not job or job["analysis_id"] != record_id or job["kind"] != "summary":
        raise AnalysisError("JOB_NOT_FOUND", "这个摘要任务已删除或不存在。", 404)
    return job


def saved_summary(engine, record_id):
    saved = engine.store.summary(record_id)
    if not saved:
        return None
    return {"id": saved["id"], "model": saved["model"], "prompt_version": saved["prompt_version"],
            "created_at": saved["created_at"], **public_summary(saved["content"], engine.store.cues(record_id))}


async def summary_events(engine, record_id, job_id, request):
    last = None
    heartbeat = time.monotonic()
    yield ": connected\n\n"
    while not await request.is_disconnected():
        try:
            job = summary_job(engine, record_id, job_id)
            if job["status"] == "ready":
                yield event("complete", {"job_id": job_id, "summary": saved_summary(engine, record_id),
                                         "usage": engine.store.usage(record_id)})
                return
        except AnalysisError as error:
            yield event("removed", {"job_id": job_id, "code": error.code, "message": error.message})
            return
        if job["status"] not in {"queued", "processing"}:
            yield event("failed", {"job_id": job_id, "status": job["status"], "error": job["error"], "error_code": job["error_code"]})
            return
        preview = engine.summary_preview(job_id)
        snapshot = {"job_id": job_id, "text": preview.get("text", ""),
                    "stage": preview.get("stage", job["stage"]), "phase": preview.get("phase", job["status"]),
                    "parts": preview.get("parts", [])}
        if snapshot != last:
            yield event("snapshot", snapshot)
            last = snapshot
        if time.monotonic() - heartbeat >= 15:
            yield ": heartbeat\n\n"
            heartbeat = time.monotonic()
        await asyncio.sleep(0.08)
