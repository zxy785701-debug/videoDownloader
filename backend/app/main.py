import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import video_service
from .analysis_errors import AnalysisError
from .analysis_jobs import close_engine, get_engine
from .analysis_routes import router as analysis_router
from .membership_routes import router as membership_router
from .membership_client import close_membership_client
from .schemas import DownloadCreated, DownloadRequest, DownloadStatus, ParseRequest, ParseResponse

logging.basicConfig(level=logging.INFO)
@asynccontextmanager
async def lifespan(app):
    try:
        await run_in_threadpool(get_engine)
    except AnalysisError as error:
        logging.warning("Learning storage unavailable code=%s", error.code)
    try:
        yield
    finally:
        try:
            await run_in_threadpool(close_engine)
        finally:
            await run_in_threadpool(close_membership_client)


app = FastAPI(title="Video Downloader API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(AnalysisError)
async def analysis_error_handler(request, error: AnalysisError):
    return JSONResponse(status_code=error.status_code, content={"detail": {"code": error.code, "message": error.message}})


@app.exception_handler(RequestValidationError)
async def local_validation_handler(request, error):
    if request.url.path.startswith("/api/v1/account/"):
        return JSONResponse(status_code=422, content={"detail": {"code": "INPUT_INVALID", "message": "账号输入不符合要求，请检查字段和长度。"}})
    return await request_validation_exception_handler(request, error)


app.include_router(analysis_router)
app.include_router(membership_router)


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/thumbnails/{token}")
async def get_thumbnail(token: str) -> Response:
    try:
        result = await run_in_threadpool(video_service.fetch_thumbnail, token)
    except ValueError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if not result:
        raise HTTPException(status_code=404, detail="封面不存在或已过期")
    body, media_type = result
    return Response(
        content=body,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=600", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/api/v1/parse", response_model=ParseResponse)
async def parse_video(request: ParseRequest) -> ParseResponse:
    try:
        return await run_in_threadpool(video_service.parse_video, request.url)
    except HTTPException:
        raise
    except Exception as error:
        logging.info("Video parse failed category=%s (%s)", video_service.error_category(error), type(error).__name__)
        raise HTTPException(
            status_code=422,
            detail=video_service.friendly_error(error),
        ) from error


@app.post("/api/v1/downloads", response_model=DownloadCreated, status_code=202)
async def create_download(
    request: DownloadRequest,
    background_tasks: BackgroundTasks,
) -> DownloadCreated:
    video_service.cleanup_expired_tasks()
    video_service.validate_public_http_url(request.url)
    task_id = secrets.token_urlsafe(18)
    video_service.create_task(task_id, request.delivery_mode)
    background_tasks.add_task(
        video_service.process_download,
        task_id,
        request.url,
        request.format_id,
        request.delivery_mode,
    )
    return DownloadCreated(
        task_id=task_id,
        status="pending",
        status_url=f"/api/v1/downloads/{task_id}",
        download_url=f"/api/v1/downloads/{task_id}/file",
    )


@app.get("/api/v1/downloads/{task_id}", response_model=DownloadStatus)
async def get_download_status(task_id: str) -> dict:
    state = video_service.get_task(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="下载任务不存在或已过期")
    if state["expires_at"].timestamp() <= time.time():
        video_service.expire_task(task_id)
        raise HTTPException(status_code=404, detail="下载任务不存在或已过期")
    return video_service.public_task(state)


@app.get("/api/v1/downloads/{task_id}/file")
async def get_download_file(task_id: str):
    state = video_service.get_task(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="下载任务不存在或已过期")
    if state["expires_at"].timestamp() <= time.time():
        video_service.expire_task(task_id)
        raise HTTPException(status_code=404, detail="下载任务不存在或已过期")
    if state["status"] == "failed":
        raise HTTPException(status_code=422, detail=state["error"] or "下载失败")
    if state["status"] != "ready":
        raise HTTPException(status_code=409, detail="下载仍在处理中")
    if state["delivery_mode"] == "redirect" and state["redirect_url"]:
        return RedirectResponse(state["redirect_url"], status_code=302)

    file_path = Path(state["file_path"] or "")
    if not file_path.is_file() or not file_path.resolve().is_relative_to(video_service.DOWNLOAD_DIR.resolve()):
        raise HTTPException(status_code=404, detail="下载文件不存在或已清理")
    return FileResponse(file_path, filename=state["filename"] or file_path.name)


# Personal deployment: serve the built Vue app from the same local API process.
# Keep this mount last so that API routes take precedence.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="website")
