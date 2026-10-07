"""Subscriptions only observe a job; disconnecting never starts or cancels it."""

import asyncio
import json
import time

from .analysis_errors import AnalysisError


def event(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def chat_events(engine, record_id, message_id, request):
    last = None
    heartbeat = time.monotonic()
    yield ": connected\n\n"
    while not await request.is_disconnected():
        try:
            message = engine.store.message(record_id, message_id)
        except AnalysisError as error:
            yield event("removed", {"message_id": message_id, "code": error.code, "message": error.message})
            return
        if message["status"] not in {"queued", "processing"}:
            yield event("complete" if message["status"] == "ready" else "failed", {"message_id": message_id, "message": message})
            return
        preview = engine.chat_preview(message_id)
        snapshot = {"message_id": message_id, "text": preview.get("text", ""), "stage": preview.get("stage", message["status"])}
        if snapshot != last:
            yield event("snapshot", snapshot)
            last = snapshot
        if time.monotonic() - heartbeat >= 15:
            yield ": heartbeat\n\n"
            heartbeat = time.monotonic()
        await asyncio.sleep(0.08)
