"""Public Douyin share-page extraction, using an isolated anonymous session.

The legacy iteminfo API can return HTTP 200 with an empty body. Mobile share
pages still expose videoInfoRes after issuing their own visitor cookie. No
browser cookies, external parsing services, or JavaScript execution are used.
"""

import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

import httpx

from .security import validate_public_http_url

# httpx INFO messages include full signed media URLs under the API's root logger.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Referer": "https://www.iesdouyin.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "identity",
}
MAX_REDIRECTS = 8
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_VIDEO_BYTES = 1024 * 1024 * 1024
REDIRECT_CODES = {301, 302, 303, 307, 308}
VIDEO_ID = re.compile(r"\d{8,24}")
SHARE_RETRY_DELAYS = (0.5, 1.0)


class DouyinError(ValueError):
    """Safe, actionable messages without upstream URLs or cookie values."""

    def __init__(self, message: str, code: str = "DOUYIN_UNAVAILABLE"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DouyinVideo:
    video_id: str
    title: str
    media_urls: tuple[str, ...]
    thumbnail: str | None
    duration: float | None
    width: int | None
    height: int | None
    subtitles: dict = field(default_factory=dict, repr=False)

    @property
    def resolution(self) -> str | None:
        return f"{self.width}×{self.height}" if self.width and self.height else None


def is_douyin_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in ("douyin.com", "iesdouyin.com"))


def extract_video_id(url: str) -> str | None:
    if not is_douyin_url(url):
        return None
    parsed = urlsplit(url)
    for name in ("modal_id", "aweme_id", "item_ids", "group_id"):
        values = parse_qs(parsed.query).get(name, [])
        if values and VIDEO_ID.fullmatch(values[0]):
            return values[0]
    match = re.search(r"/(?:video|note|slides)/(\d{8,24})(?:/|$)", parsed.path)
    return match[1] if match else None


def _client() -> httpx.Client:
    return httpx.Client(headers=MOBILE_HEADERS, timeout=httpx.Timeout(25, connect=10), follow_redirects=False)


@contextmanager
def _response(client: httpx.Client, url: str, *, platform_only: bool = False):
    # Validate each target before it is requested, including relative redirects.
    for _ in range(MAX_REDIRECTS + 1):
        validate_public_http_url(url)
        if platform_only and not is_douyin_url(url):
            raise DouyinError("抖音分享链接跳转到了其他网站，请复制原视频的分享链接重试。")
        with client.stream("GET", url) as response:
            if response.status_code in REDIRECT_CODES:
                location = response.headers.get("Location")
                if not location:
                    raise DouyinError("抖音分享地址未返回有效跳转，请重新复制链接。")
                url = urljoin(str(response.url), location)
                continue
            response.raise_for_status()
            yield response
            return
    raise DouyinError("抖音链接跳转次数过多，请重新复制原视频链接。")


def _read_page(response: httpx.Response) -> str:
    body = bytearray()
    for chunk in response.iter_bytes(64 * 1024):
        body.extend(chunk)
        if len(body) > MAX_PAGE_BYTES:
            raise DouyinError("抖音分享页返回内容异常，请稍后重试。")
    return body.decode("utf-8", errors="replace")


def _find_item(data: object, video_id: str) -> dict | None:
    pending = [data]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if str(node.get("aweme_id")) == video_id and isinstance(node.get("video"), dict):
                return node
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return None


def _item_from_html(html: str, video_id: str) -> dict | None:
    # raw_decode handles nested objects and braces in strings without evaluating JS.
    for marker in re.finditer(r"(?:window\.)?_ROUTER_DATA\s*=\s*", html):
        try:
            data, _ = json.JSONDecoder().raw_decode(html[marker.end():].lstrip())
        except (ValueError, RecursionError):
            continue
        item = _find_item(data, video_id)
        if item:
            return item
    render = re.search(r'<script\b[^>]*\bid=[\"\']RENDER_DATA[\"\'][^>]*>(.*?)</script>', html, re.S)
    if render:
        try:
            return _find_item(json.loads(unquote(render[1])), video_id)
        except (ValueError, RecursionError):
            pass
    return None


def _positive_number(value: object) -> float | None:
    return float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and value > 0 else None


def _urls(node: object) -> list[str]:
    if not isinstance(node, dict):
        return []
    urls = node.get("url_list")
    return [url for url in urls if isinstance(url, str) and urlsplit(url).scheme in {"http", "https"}] if isinstance(urls, list) else []


def _play_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.path == "/aweme/v1/playwm/" and any(host == domain or host.endswith(f".{domain}") for domain in ("snssdk.com", "iesdouyin.com", "douyin.com")):
        # Only change the endpoint path; preserve the signed query unchanged.
        return urlunsplit(parsed._replace(path="/aweme/v1/play/"))
    return url


def _subtitles_from_item(item: dict) -> dict:
    """Only explicit subtitle resources, never description/comments/music text.

    Match the caption resource schemas supported by yt-dlp's TikTokBaseIE;
    actual retrieval/format validation stays in the existing subtitle service.
    """
    video = item["video"]
    subtitles = {}
    extensions = {"srt": "srt", "webvtt": "vtt", "creator_caption": "json"}

    def entries(value):
        return value if isinstance(value, list) else []

    def extension(value):
        return extensions.get(value) if isinstance(value, str) else None

    def add(language, url, extension):
        if isinstance(url, str) and extension in {"srt", "vtt", "json"}:
            language = language if isinstance(language, str) and language else "zh-Hans"
            resource = {"url": url, "ext": extension}
            resources = subtitles.setdefault(language, [])
            if resource not in resources:
                resources.append(resource)

    for caption in entries(video.get("subtitleInfos")):
        if isinstance(caption, dict):
            add(caption.get("LanguageCodeName"), caption.get("Url"), extension(caption.get("Format")))
    cla_info = video.get("cla_info")
    for caption in entries(cla_info.get("caption_infos")) if isinstance(cla_info, dict) else []:
        if isinstance(caption, dict):
            add(caption.get("lang"), caption.get("url"), extension(caption.get("Format")))
    for sticker in entries(item.get("interaction_stickers")):
        info = sticker.get("auto_video_caption_info") if isinstance(sticker, dict) else None
        for caption in entries(info.get("auto_captions")) if isinstance(info, dict) else []:
            if isinstance(caption, dict):
                resource = caption.get("url")
                for url in entries(resource.get("url_list")) if isinstance(resource, dict) else []:
                    add(caption.get("language"), url, "json")
    return subtitles


def _video_from_item(item: dict, video_id: str) -> DouyinVideo:
    if item.get("images"):
        raise DouyinError("这个抖音链接是图集，目前只支持视频。请换用视频作品链接。", "DOUYIN_IMAGE_POST")
    video = item["video"]
    media_urls = tuple(dict.fromkeys(_play_url(url) for url in _urls(video.get("play_addr"))))
    if not media_urls:
        raise DouyinError("抖音未提供可下载的视频地址，请确认作品公开且能正常播放后重试。")
    covers = _urls(video.get("origin_cover")) or _urls(video.get("cover"))
    milliseconds = _positive_number(video.get("duration"))
    width, height = _positive_number(video.get("width")), _positive_number(video.get("height"))
    return DouyinVideo(
        video_id=video_id,
        title=str(item.get("desc") or f"抖音视频 {video_id}"),
        media_urls=media_urls,
        thumbnail=covers[0] if covers else None,
        duration=milliseconds / 1000 if milliseconds else None,
        width=int(width) if width else None,
        height=int(height) if height else None,
        subtitles=_subtitles_from_item(item),
    )


def _network_error(error: httpx.HTTPError) -> DouyinError:
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {403, 429}:
        return DouyinError("抖音暂时拒绝访问或请求过于频繁，请稍后重试并确认本机网络能播放该视频。", "DOUYIN_ACCESS_DENIED")
    return DouyinError("连接抖音超时或中断，请检查本机网络后重试。", "DOUYIN_NETWORK_UNAVAILABLE")


def resolve_video(url: str, *, on_probe: Callable[[dict], None] | None = None) -> DouyinVideo:
    if not is_douyin_url(url):
        raise DouyinError("请提供有效的抖音视频链接。")
    try:
        with _client() as client:
            video_id = extract_video_id(url)
            if not video_id:
                with _response(client, url, platform_only=True) as response:
                    video_id = extract_video_id(str(response.url))
            if not video_id:
                raise DouyinError("未找到抖音作品编号，请复制视频分享链接，勿使用作者主页或直播地址。")
            share_url = f"https://www.iesdouyin.com/share/video/{video_id}/?from_ssr=1"
            # Visitor state is not always usable immediately after Set-Cookie.
            # Keep the same isolated jar and allow propagation between requests;
            # never retry HTTP denials or create unbounded polling here.
            for attempt in range(len(SHARE_RETRY_DELAYS) + 1):
                if attempt:
                    time.sleep(SHARE_RETRY_DELAYS[attempt - 1])
                started = time.monotonic()
                with _response(client, share_url, platform_only=True) as response:
                    page = _read_page(response)
                    item = _item_from_html(page, video_id)
                    # Never log page bodies, headers, cookies or media URLs.
                    observation = {
                        "attempt": attempt + 1, "http_status": response.status_code,
                        "page_chars": len(page), "router_data": "_ROUTER_DATA" in page,
                        "render_data": "RENDER_DATA" in page, "requested_id_present": video_id in page,
                        "parsed_item": item is not None,
                        "visitor_cookie_present": any(cookie.name == "ttwid" for cookie in client.cookies.jar),
                        "seconds": round(time.monotonic() - started, 3),
                    }
                logger.info("Douyin share attempt=%d status=%d chars=%d visitor=%s parsed=%s",
                    observation["attempt"], observation["http_status"], observation["page_chars"],
                    observation["visitor_cookie_present"], observation["parsed_item"])
                if on_probe:
                    on_probe(observation)
                if item:
                    return _video_from_item(item, video_id)
            logger.warning("Douyin share metadata unavailable after bounded retries attempts=%d",
                           len(SHARE_RETRY_DELAYS) + 1)
            raise DouyinError("抖音分享页未返回视频信息。请确认作品公开可播放，重新复制分享链接或稍后重试。", "DOUYIN_METADATA_EMPTY")
    except httpx.HTTPError as error:
        raise _network_error(error) from error


def _validate_mp4(path: Path) -> None:
    # Walk top-level ISO BMFF boxes, catching clean EOF inside a truncated box
    # even when a chunked response has no Content-Length. This is not a decoder.
    size, offset, boxes = path.stat().st_size, 0, set()
    with path.open("rb") as media:
        while offset < size:
            media.seek(offset)
            header = media.read(8)
            if len(header) != 8:
                raise DouyinError("抖音视频文件不完整，请重新解析后重试。")
            box_size, box_type = int.from_bytes(header[:4], "big"), header[4:8]
            header_size = 8
            if box_size == 1:
                extended = media.read(8)
                if len(extended) != 8:
                    raise DouyinError("抖音视频文件不完整，请重新解析后重试。")
                box_size, header_size = int.from_bytes(extended, "big"), 16
            elif box_size == 0:
                box_size = size - offset
            if box_size < header_size or offset + box_size > size:
                raise DouyinError("抖音视频文件不完整，请重新解析后重试。")
            boxes.add(box_type)
            offset += box_size
    if not {b"ftyp", b"moov", b"mdat"}.issubset(boxes):
        raise DouyinError("抖音视频缺少媒体数据，请重新解析后重试。")


def download_video(video: DouyinVideo, directory: Path, progress: Callable[[float | None], None]) -> Path:
    try:
        return _download_video(video, directory, progress)
    except OSError as error:
        raise DouyinError("本机无法写入视频文件，请检查下载目录权限或磁盘空间后重试。") from error
    finally:
        # Also runs when URL validation rejects a redirect before any I/O.
        # Successful/nonempty directories are preserved; no recursive removal.
        try:
            directory.rmdir()
        except OSError:
            pass


def _download_video(video: DouyinVideo, directory: Path, progress: Callable[[float | None], None]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    # No untrusted title is used as a filesystem path, including on Windows.
    filename = f"douyin_{video.video_id}.mp4"
    target = directory / filename
    partial = directory / f"{filename}.part"
    last_error: Exception | None = None
    with _client() as client:
        for url in video.media_urls:
            try:
                progress(None)
                with _response(client, url) as response:
                    media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if media_type not in {"video/mp4", "application/octet-stream"}:
                        raise DouyinError("抖音返回的内容不是 MP4 视频，请重新解析后重试。")
                    length = response.headers.get("Content-Length", "")
                    total = int(length) if length.isdigit() and int(length) > 0 else None
                    if total and total > MAX_VIDEO_BYTES:
                        raise DouyinError("此抖音视频超过本地下载的 1 GB 限制，请换用较小的视频。")
                    received, prefix = 0, bytearray()
                    with partial.open("wb") as output:
                        for chunk in response.iter_bytes(64 * 1024):
                            received += len(chunk)
                            if received > MAX_VIDEO_BYTES:
                                raise DouyinError("此抖音视频超过本地下载的 1 GB 限制。")
                            prefix.extend(chunk[: max(0, 32 - len(prefix))])
                            if len(prefix) >= 12 and prefix[4:8] != b"ftyp":
                                raise DouyinError("抖音返回的视频文件无效，请重新解析后重试。")
                            output.write(chunk)
                            progress(min(99.9, round(received / total * 100, 1)) if total else None)
                    if len(prefix) < 12 or prefix[4:8] != b"ftyp" or (total is not None and received != total):
                        raise DouyinError("抖音视频下载不完整，请重新解析后重试。")
                _validate_mp4(partial)
                partial.replace(target)
                return target
            except (httpx.HTTPError, DouyinError) as error:
                last_error = _network_error(error) if isinstance(error, httpx.HTTPError) else error
            finally:
                partial.unlink(missing_ok=True)
    raise last_error or DouyinError("抖音视频下载失败，请重新解析后重试。")
