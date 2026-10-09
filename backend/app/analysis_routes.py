import re
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse

from .ai_config import get_config
from .analysis_errors import AnalysisError
from .analysis_jobs import get_engine
from .analysis_schemas import AnalysisCreate, ChatCreate, SummaryCreate
from .summary_service import public_summary
from .chat_events import chat_events
from .summary_events import summary_events, summary_job
from .membership_client import COOKIE


def local_access(request: Request):
    if request.url.hostname not in {"localhost", "127.0.0.1"}:
        raise AnalysisError("LOCAL_ONLY", "视频学习 API 仅用于本机访问。", 403)
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        allowed = {
            f"http://localhost:{request.url.port or 80}", f"http://127.0.0.1:{request.url.port or 80}",
            "http://localhost:5173", "http://127.0.0.1:5173",
        }
        if origin not in allowed or parsed.username or parsed.password:
            raise AnalysisError("ORIGIN_FORBIDDEN", "不允许该网页访问本机学习记录或触发模型调用。", 403)


router = APIRouter(prefix="/api/v1", dependencies=[Depends(local_access)], tags=["视频学习"])


@router.get("/ai/config")
def ai_config():
    return get_config().public()


@router.post("/analyses", status_code=202)
def create_analysis(body: AnalysisCreate, request: Request):
    return get_engine().start_transcript(body.url, body.language, body.auto_summary, request.cookies.get(COOKIE))


@router.get("/analyses")
def list_analyses(offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
    return get_engine().store.list(offset, limit)


@router.get("/analyses/{record_id}")
def get_analysis(record_id: str):
    store = get_engine().store
    record = store.get(record_id)
    record["jobs"] = store.latest_jobs(record_id)
    record["usage"] = store.usage(record_id)
    return record


@router.get("/analyses/{record_id}/transcript")
def transcript(record_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200),
               q: str = Query("", max_length=200), anchor: str | None = Query(None, max_length=30)):
    return get_engine().store.transcript(record_id, offset, limit, q.strip(), anchor)


@router.post("/analyses/{record_id}/summary", status_code=202)
def create_summary(record_id: str, body: SummaryCreate, request: Request):
    return get_engine().start_summary(record_id, body.force, body.stream, request.cookies.get(COOKIE))


@router.get("/analyses/{record_id}/summary/{job_id}/stream")
def summary_stream(record_id: str, job_id: str, request: Request):
    engine = get_engine()
    summary_job(engine, record_id, job_id)
    return StreamingResponse(summary_events(engine, record_id, job_id, request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.get("/analyses/{record_id}/summary")
def summary(record_id: str):
    store = get_engine().store
    record = store.get(record_id)
    saved = store.summary(record_id)
    result = {"status": record["summary_status"], "summary": None, "usage": store.usage(record_id)}
    if saved:
        result["summary"] = {
            "id": saved["id"], "model": saved["model"], "prompt_version": saved["prompt_version"],
            "created_at": saved["created_at"], **public_summary(saved["content"], store.cues(record_id)),
        }
    return result


@router.post("/analyses/{record_id}/chat", status_code=202)
def chat(record_id: str, body: ChatCreate):
    return get_engine().start_chat(record_id, body.question, body.request_id, body.stream)


@router.get("/analyses/{record_id}/messages/{message_id}/stream")
def message_stream(record_id: str, message_id: str, request: Request):
    engine = get_engine()
    engine.store.message(record_id, message_id)
    return StreamingResponse(chat_events(engine, record_id, message_id, request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.get("/analyses/{record_id}/messages")
def messages(record_id: str):
    return {"items": get_engine().store.messages(record_id)}


@router.delete("/analyses/{record_id}/messages", status_code=204)
def clear_messages(record_id: str):
    get_engine().clear_messages(record_id)
    return Response(status_code=204)


def srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


@router.get("/analyses/{record_id}/export")
def export(record_id: str, format: str = Query("markdown", pattern="^(markdown|srt|txt)$")):
    store = get_engine().store
    record = store.get(record_id)
    if format in {"srt", "txt"}:
        cues = store.cues(record_id)
        if not cues:
            raise AnalysisError("TRANSCRIPT_NOT_READY", "暂无可导出的字幕。", 409)
        if format == "srt":
            text = "\n\n".join(f"{i + 1}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}" for i, c in enumerate(cues)) + "\n"
        else:
            text = "\n\n".join(f"[{srt_time(c['start']).replace(',', '.')} --> {srt_time(c['end']).replace(',', '.')}]\n{c['text']}" for c in cues) + "\n"
        filename = f"video-subtitles.{format}"
        title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", record["title"]).strip()[:100].rstrip(". ") or "video"
        if re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", title, re.I):
            title = "_" + title
        language = re.sub(r"[^\w-]", "_", record["language"] or "unknown")[:40]
        unicode_filename = f"{title}-{language}.{format}"
    else:
        saved = store.summary(record_id)
        if not saved:
            raise AnalysisError("SUMMARY_NOT_READY", "暂无可导出的摘要。", 409)
        content = public_summary(saved["content"], store.cues(record_id))["content"]
        parts = ["# " + record["title"], "来源：" + record["url"],
                 f"字幕：{record['language']} / {record['track_kind']}", "仅依据获取到的字幕，未分析视频画面。",
                 "## " + content["headline"], content["overview"]]
        for chapter in content["chapters"]:
            parts.extend(["## " + chapter["title"], chapter["overview"]])
            for point in chapter["points"]:
                times = "、".join(srt_time(r["start"]).replace(",", ".") for r in point["references"])
                parts.append("- " + point["text"] + f"（原文 {times}）")
        text, filename = "\n\n".join(parts) + "\n", "video-summary.md"
        unicode_filename = filename
    return Response(text, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(unicode_filename, safe="")}', "X-Content-Type-Options": "nosniff"})


@router.delete("/analyses/{record_id}", status_code=204)
def delete_analysis(record_id: str):
    get_engine().delete(record_id)
    return Response(status_code=204)
