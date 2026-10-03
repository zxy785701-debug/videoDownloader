import logging
import os
import re
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import HTTPException
from yt_dlp import YoutubeDL

from . import douyin
from .schemas import ParseResponse, VideoFormat
from .security import validate_public_http_url

logger = logging.getLogger(__name__)
DOWNLOAD_DIR = Path(__file__).resolve().parents[1] / "downloads"
TASK_TTL = timedelta(hours=2)
TASKS: dict[str, dict] = {}
TASKS_LOCK = threading.Lock()
FORMAT_ID_PATTERN = re.compile(r"^[\w.+-]{1,80}$")
THUMBNAIL_TTL_SECONDS = 3600
MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024
THUMBNAIL_SOURCES: dict[str, tuple[str, str, float]] = {}
IMAGE_CONTENT_TYPES = {"image/avif", "image/gif", "image/jpeg", "image/png", "image/webp"}
SUPPORTED_COOKIE_BROWSERS = {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"}


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def create_task(task_id: str, delivery_mode: str) -> dict:
    now = datetime.now(timezone.utc)
    state = {
        "task_id": task_id,
        "status": "pending",
        "delivery_mode": delivery_mode,
        "progress": None,
        "filename": None,
        "file_path": None,
        "redirect_url": None,
        "error": None,
        "expires_at": now + TASK_TTL,
    }
    with TASKS_LOCK:
        TASKS[task_id] = state
    return state


def get_task(task_id: str) -> dict | None:
    with TASKS_LOCK:
        state = TASKS.get(task_id)
        return dict(state) if state else None


def public_task(state: dict) -> dict:
    return {
        "task_id": state["task_id"],
        "status": state["status"],
        "delivery_mode": state["delivery_mode"],
        "progress": state["progress"],
        "filename": state["filename"],
        "error": state["error"],
        "expires_at": _timestamp(state["expires_at"]),
    }


def _is_youtube(url: str | None) -> bool:
    host = (urlsplit(url).hostname or "").lower() if url else ""
    return host in {"youtu.be", "youtube.com"} or host.endswith(".youtube.com")


def error_category(error: object) -> str:
    message = str(error).casefold().replace("’", "'")
    for category, markers in (
        ("cookie_decryption", ("dpapi", "decrypt cookies")),
        ("cookie_database", ("could not copy chrome cookie database",)),
        ("cookie_profile", ("could not find firefox cookies database",)),
        ("login_required", ("sign in to confirm", "confirm you're not a bot", "login_required")),
        ("js_challenge", ("javascript runtime", "js runtime", "challenge solving failed", "n challenge", "signature solving", "yt-dlp-ejs")),
        ("po_token", ("po token", "po_token", "proof of origin")),
        ("rate_limited", ("429", "too many requests")),
        ("forbidden", ("403", "forbidden")),
        ("network_permission", ("winerror 10013",)),
        ("network", ("timed out", "timeout", "proxyerror", "connection refused", "unable to connect", "failed to establish a new connection", "name resolution", "certificate verify failed")),
        ("unavailable", ("video unavailable", "video is unavailable", "private video", "not available in your country", "video has been removed")),
        ("formats", ("requested format is not available", "no video formats")),
    ):
        if any(marker in message for marker in markers):
            return category
    return "unknown"


class _YtdlpLogger:
    # Upstream messages may contain cookies, proxy credentials or signed URLs.
    # Log allowlisted categories only, never raw upstream text.
    def debug(self, message):
        pass

    def warning(self, message):
        logger.warning("yt-dlp warning category=%s", error_category(message))

    def error(self, message):
        logger.warning("yt-dlp error category=%s", error_category(message))


def _video_options(*, source_url: str | None = None, **extra) -> dict:
    options = {
        "quiet": True,
        "no_warnings": False,
        "logger": _YtdlpLogger(),
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 1,
    }
    node_runtime = os.environ.get("YTDLP_NODE_PATH", "").strip() or shutil.which("node")
    if node_runtime:
        options["js_runtimes"] = {"node": {"path": node_runtime}}

    is_youtube = _is_youtube(source_url)
    # Leave other extractors on their existing network settings.
    if is_youtube:
        proxy = os.environ.get("YTDLP_PROXY", "").strip()
        if proxy:
            parsed_proxy = urlsplit(proxy)
            if parsed_proxy.scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"} or not parsed_proxy.hostname:
                raise ValueError("YTDLP_PROXY 必须是有效的 HTTP(S) 或 SOCKS 代理地址")
            options["proxy"] = proxy
        provider = os.environ.get("YTDLP_POT_BASE_URL", "").strip()
        if provider:
            parsed_provider = urlsplit(provider)
            if parsed_provider.scheme not in {"http", "https"} or not parsed_provider.hostname or parsed_provider.username or parsed_provider.password or parsed_provider.query or parsed_provider.fragment:
                raise ValueError("YTDLP_POT_BASE_URL 必须是不含凭据或查询参数的 HTTP(S) 服务地址")
            options["extractor_args"] = {
                "youtube": {"player_client": ["mweb"]},
                "youtubepot-bgutilhttp": {"base_url": [provider]},
            }
    browser_setting = os.environ.get("YTDLP_COOKIES_FROM_BROWSER", "").strip()
    if is_youtube and browser_setting:
        browser, separator, profile = browser_setting.partition(":")
        browser = browser.lower()
        if browser not in SUPPORTED_COOKIE_BROWSERS:
            raise ValueError("YTDLP_COOKIES_FROM_BROWSER must name a supported browser, such as edge or chrome")
        options["cookiesfrombrowser"] = (browser, profile if separator and profile else None, None, None)

    options.update(extra)
    return options


def friendly_error(error: Exception) -> str:
    if isinstance(error, douyin.DouyinError):
        return str(error)
    message = str(error).casefold().replace("’", "'")
    if isinstance(error, ValueError) and str(error).startswith("YTDLP_"):
        return str(error)
    if "failed to decrypt with dpapi" in message:
        return (
            "Windows 无法解密当前浏览器的 Cookie（DPAPI）；程序不会绕过浏览器加密。"
            "若 Firefox 已登录 YouTube，可改用 YTDLP_COOKIES_FROM_BROWSER=firefox；"
            "否则请使用 yt-dlp 支持且能在本机正常读取的登录会话。"
        )
    if "could not copy chrome cookie database" in message:
        browser = os.environ.get("YTDLP_COOKIES_FROM_BROWSER", "browser").split(":", 1)[0]
        return f"无法读取 {browser} 的 Cookie 数据库。请完全退出该浏览器（包括后台进程）后重试；Cookie 只会在本机读取，不要导出或分享。"
    if "sign in to confirm" in message or "confirm you're not a bot" in message:
        if os.environ.get("YTDLP_COOKIES_FROM_BROWSER"):
            return "YouTube 仍拒绝当前浏览器会话。请确认所选浏览器能播放视频、已登录 YouTube，且后端由同一 Windows 用户启动并使用一致的网络出口。PO Token 不能保证解决登录验证。"
        return (
            "YouTube 要求登录验证。若你已登录，请在启动后端的 PowerShell 中设置 "
            "$env:YTDLP_COOKIES_FROM_BROWSER=\"firefox\"（也支持 edge、chrome），再重启后端。"
            "只读取本机浏览器会话；不要把 Cookie 发到聊天或上传到网站。"
        )
    messages = {
        "cookie_profile": "后端无法访问 Firefox 登录配置。请通过本机 PowerShell 运行 start-local.ps1；如仍失败，请检查 Firefox 配置目录及进程访问权限。",
        "network_permission": "当前后端进程的网络访问被限制（Windows 10013）。请通过本机 PowerShell 运行 start-local.ps1，并检查该进程的网络权限。",
        "js_challenge": "YouTube JavaScript 挑战解析失败。请检查 Node.js 22+ 或受支持的 Deno，以及 yt-dlp[default] / EJS 版本；修改后重启后端。",
        "po_token": "YouTube 需要 PO Token。请安装并启动 bgutil Provider，配置 YTDLP_POT_BASE_URL 后重试；Token 不能保证解决登录验证。",
        "rate_limited": "上游请求过于频繁（429），请稍后重试并减少并发。",
        "forbidden": "上游拒绝访问（403）。请检查会话、网络出口和链接有效性；若为 YouTube，再检查 PO Token 配置。",
        "network": "无法连接视频平台或连接超时。YouTube 可通过 YTDLP_PROXY 配置后端代理，请检查代理、网络和证书。",
        "unavailable": "视频不可用，可能已删除、设为私密或受地区限制。请先确认浏览器可以播放。",
        "formats": "当前没有可用的所选格式。请重新解析并选择最佳画质；YouTube 还需检查 JS runtime 和 PO Token 警告。",
    }
    return messages.get(error_category(error), "无法解析此链接。请检查地址，或确认视频无需登录且可以公开访问。")


def download_error(error: Exception) -> str:
    if isinstance(error, douyin.DouyinError):
        return str(error)
    if error_category(error) != "unknown":
        return friendly_error(error)
    return "下载失败，请确认链接可访问后重试。"


def _safe_format_id(format_id: str) -> str:
    if format_id == "best":
        return "bv*+ba/best"
    if format_id.startswith("video:"):
        video_id = format_id.removeprefix("video:")
        if FORMAT_ID_PATTERN.fullmatch(video_id):
            return f"{video_id}+ba/best"
        raise ValueError("Unsupported format selection")
    if not FORMAT_ID_PATTERN.fullmatch(format_id):
        raise ValueError("Unsupported format selection")
    return format_id


def _ffmpeg_location() -> str | None:
    configured = os.environ.get("YTDLP_FFMPEG_LOCATION")
    if configured:
        return configured
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def _format_choices(info: dict) -> list[VideoFormat]:
    choices = [
        VideoFormat(format_id="best", label="最佳画质", ext=None, resolution=None)
    ]
    seen = {"best"}
    seen_video_resolutions: set[str] = set()
    for item in info.get("formats") or []:
        raw_format_id = str(item.get("format_id") or "")
        if not raw_format_id:
            continue
        if item.get("vcodec") in (None, "none"):
            continue
        height = item.get("height")
        resolution = f"{height}p" if height else item.get("resolution")
        ext = item.get("ext")
        is_video_only = item.get("acodec") in (None, "none")
        resolution_key = str(resolution or raw_format_id)
        if is_video_only and resolution_key in seen_video_resolutions:
            continue
        format_id = f"video:{raw_format_id}" if is_video_only else raw_format_id
        if format_id in seen:
            continue
        label_parts = [resolution, ext.upper() if ext else None]
        if is_video_only:
            label_parts.append("自动合并音频")
            seen_video_resolutions.add(resolution_key)
        label = " · ".join(part for part in label_parts if part)
        choices.append(
            VideoFormat(
                format_id=format_id,
                label=label or f"格式 {format_id}",
                ext=ext,
                resolution=resolution,
                filesize=None if is_video_only else (item.get("filesize") or item.get("filesize_approx")),
                fps=item.get("fps"),
            )
        )
        seen.add(format_id)
        if len(choices) == 12:
            break
    return choices


def parse_video(url: str) -> ParseResponse:
    safe_url = validate_public_http_url(url)
    if douyin.is_douyin_url(safe_url):
        video = douyin.resolve_video(safe_url)
        thumbnail = None
        if video.thumbnail:
            try:
                thumbnail = register_thumbnail(video.thumbnail, "https://www.iesdouyin.com/")
            except Exception as error:
                logger.info("Thumbnail registration failed (%s)", type(error).__name__)
        return ParseResponse(
            title=video.title,
            extractor="Douyin",
            thumbnail=thumbnail,
            duration=video.duration,
            formats=[VideoFormat(format_id="best", label="原始视频 · MP4", ext="mp4", resolution=video.resolution)],
        )
    with YoutubeDL(_video_options(source_url=safe_url, skip_download=True)) as ydl:
        info = ydl.extract_info(safe_url, download=False)
    if not info or info.get("_type") == "playlist":
        raise ValueError("Playlists are not supported in this version")
    thumbnail = None
    if info.get("thumbnail"):
        try:
            thumbnail = register_thumbnail(info["thumbnail"], safe_url)
        except Exception as error:
            logger.info("Thumbnail registration failed (%s)", type(error).__name__)
    return ParseResponse(
        title=str(info.get("title") or "Untitled video"),
        extractor=info.get("extractor_key") or info.get("extractor"),
        thumbnail=thumbnail,
        duration=info.get("duration"),
        formats=_format_choices(info),
    )


def _direct_url(info: dict) -> str | None:
    requested = info.get("requested_formats") or []
    if len(requested) > 1:
        return None
    selected = requested[0] if requested else info
    target = selected.get("url")
    if not target or selected.get("http_headers"):
        return None
    parsed = urlsplit(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    validate_public_http_url(target)
    return target


def _set_state(task_id: str, **changes) -> None:
    with TASKS_LOCK:
        if task_id in TASKS:
            TASKS[task_id].update(changes)


def _progress_hook(task_id: str, data: dict) -> None:
    if data.get("status") == "downloading":
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        progress = round(data["downloaded_bytes"] / total * 100, 1) if total else None
        _set_state(task_id, progress=progress)
    elif data.get("status") == "finished":
        _set_state(task_id, progress=100.0)


def process_download(task_id: str, url: str, format_id: str, delivery_mode: str) -> None:
    _set_state(task_id, status="processing")
    try:
        safe_url = validate_public_http_url(url)
        if douyin.is_douyin_url(safe_url):
            if delivery_mode == "redirect":
                raise douyin.DouyinError("抖音请使用自动或服务端下载，以处理播放地址跳转和文件校验。")
            if format_id != "best":
                raise douyin.DouyinError("此抖音格式已不可用，请重新解析并选择原始视频。")
            # Resolve again so expiring media links are never reused from parse.
            video = douyin.resolve_video(safe_url)
            file_path = douyin.download_video(
                video,
                DOWNLOAD_DIR / task_id,
                lambda progress: _set_state(task_id, progress=progress),
            )
            _set_state(task_id, status="ready", delivery_mode="server", file_path=str(file_path), filename=file_path.name, progress=100.0)
            return
        if _is_youtube(safe_url):
            if delivery_mode == "redirect":
                raise ValueError("YouTube 请使用自动或服务端下载，以支持会话和音视频合并")
            delivery_mode = "server"
        selected_format = _safe_format_id(format_id)
        resolved_info = None
        direct_url = None
        if delivery_mode in {"auto", "redirect"}:
            with YoutubeDL(_video_options(source_url=safe_url, format=selected_format, skip_download=True)) as ydl:
                resolved_info = ydl.extract_info(safe_url, download=False)
            direct_url = _direct_url(resolved_info or {})

        if direct_url and delivery_mode in {"auto", "redirect"}:
            _set_state(
                task_id,
                status="ready",
                delivery_mode="redirect",
                redirect_url=direct_url,
                filename=(resolved_info or {}).get("title") or "video",
            )
            return
        if delivery_mode == "redirect":
            raise ValueError("此格式需要服务端处理，请改用自动或服务端下载")

        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        task_directory = DOWNLOAD_DIR / task_id
        task_directory.mkdir(parents=True, exist_ok=True)
        output_template = str(task_directory / "%(title).120s [%(id)s].%(ext)s")
        options = _video_options(
            source_url=safe_url,
            format=selected_format,
            outtmpl=output_template,
            progress_hooks=[lambda data: _progress_hook(task_id, data)],
        )
        ffmpeg_location = _ffmpeg_location()
        if ffmpeg_location:
            options["ffmpeg_location"] = ffmpeg_location
        with YoutubeDL(options) as ydl:
            ydl.download([safe_url])

        files = [path for path in task_directory.iterdir() if path.is_file() and not path.name.endswith(".part")]
        if not files:
            raise RuntimeError("yt-dlp completed without producing a file")
        file_path = max(files, key=lambda path: path.stat().st_size)
        _set_state(
            task_id,
            status="ready",
            delivery_mode="server",
            file_path=str(file_path),
            filename=file_path.name,
            progress=100.0,
        )
    except Exception as error:
        logger.warning("Download task %s failed category=%s (%s)", task_id, error_category(error), type(error).__name__)
        message = str(error) if isinstance(error, ValueError) else download_error(error)
        _set_state(task_id, status="failed", error=message)


def expire_task(task_id: str) -> None:
    with TASKS_LOCK:
        state = TASKS.pop(task_id, None)
    if state and state.get("file_path"):
        try:
            file_path = Path(state["file_path"])
            file_path.unlink(missing_ok=True)
            file_path.parent.rmdir()
        except OSError:
            logger.exception("Could not remove expired download %s", task_id)


def cleanup_expired_tasks() -> None:
    now = datetime.now(timezone.utc)
    with TASKS_LOCK:
        expired = [task_id for task_id, state in TASKS.items() if state["expires_at"] <= now]
    for task_id in expired:
        expire_task(task_id)


def register_thumbnail(thumbnail_url: str, source_url: str) -> str:
    validate_public_http_url(thumbnail_url)
    source = urlsplit(source_url)
    referer = f"{source.scheme}://{source.netloc}/"
    token = secrets.token_urlsafe(18)
    with TASKS_LOCK:
        THUMBNAIL_SOURCES[token] = (thumbnail_url, referer, time.time() + THUMBNAIL_TTL_SECONDS)
    return f"/api/v1/thumbnails/{token}"


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, new_url):
        validate_public_http_url(new_url)
        return super().redirect_request(req, fp, code, msg, headers, new_url)


def fetch_thumbnail(token: str) -> tuple[bytes, str] | None:
    with TASKS_LOCK:
        thumbnail = THUMBNAIL_SOURCES.get(token)
        if not thumbnail:
            return None
        thumbnail_url, referer, expires_at = thumbnail
        if expires_at <= time.time():
            THUMBNAIL_SOURCES.pop(token, None)
            return None

    validate_public_http_url(thumbnail_url)
    request = Request(
        thumbnail_url,
        headers={"Referer": referer, "User-Agent": "Mozilla/5.0"},
    )
    try:
        with build_opener(_PublicRedirectHandler()).open(request, timeout=15) as response:
            content_type = response.headers.get_content_type()
            if content_type not in IMAGE_CONTENT_TYPES:
                raise ValueError("Thumbnail response is not a supported image")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_THUMBNAIL_BYTES:
                raise ValueError("Thumbnail image is too large")
            body = response.read(MAX_THUMBNAIL_BYTES + 1)
            if len(body) > MAX_THUMBNAIL_BYTES:
                raise ValueError("Thumbnail image is too large")
            return body, content_type
    except (OSError, HTTPException, ValueError) as error:
        logger.info("Thumbnail fetch failed (%s)", type(error).__name__)
        raise ValueError("视频封面暂时无法加载") from error
