"""Caption-only extraction. No speech recognition or title-based substitute."""

import hashlib
import html
import json
import logging
import math
import re
from contextlib import contextmanager
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from yt_dlp import YoutubeDL

from . import douyin, platform_adapters, video_service
from .ai_config import AIConfig, get_config
from .analysis_errors import AnalysisError
from .security import validate_public_http_url

logger = logging.getLogger(__name__)


def platform_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    platform = ""
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        platform = "YouTube"
    elif host == "b23.tv" or host == "bilibili.com" or host.endswith(".bilibili.com"):
        platform = "Bilibili"
    elif douyin.is_douyin_url(url):
        platform = "Douyin"
    if not platform:
        raise AnalysisError("PLATFORM_UNSUPPORTED", "视频学习首版支持 B 站、抖音和 YouTube 的单视频链接。")
    try:
        validate_public_http_url(url)
    except HTTPException as error:
        raise AnalysisError("URL_INVALID", "请使用三平台有效的公开 HTTP(S) 视频链接。", 400) from error
    query = parse_qs(parsed.query)
    if platform == "YouTube":
        video_id = query.get("v", [""])[0]
        if host == "youtu.be":
            video_id = parsed.path.strip("/")
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = parsed.path.split("/")[2]
        if re.fullmatch(r"[\w-]{6,32}", video_id):
            return platform, "https://www.youtube.com/watch?" + urlencode({"v": video_id})
    elif platform == "Douyin":
        video_id = douyin.extract_video_id(url)
        if video_id:
            return platform, "https://www.douyin.com/video/" + video_id
    # Strip tracking queries. The Bilibili part selector remains part of identity.
    keep = {"p": query["p"][0]} if platform == "Bilibili" and query.get("p") else {}
    return platform, urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(keep), ""))


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\{\\[^}]+\}", "", value)
    value = html.unescape(value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("Invalid timestamp")
    numbers = [float(part) for part in parts]
    if any(not math.isfinite(n) or n < 0 for n in numbers) or numbers[-1] >= 60 or numbers[-2] >= 60:
        raise ValueError("Invalid timestamp")
    return sum(n * 60 ** i for i, n in enumerate(reversed(numbers)))


def parse_captions(body: str, extension: str) -> list[dict]:
    if extension in {"srt", "vtt", "webvtt"}:
        cues = []
        for block in re.split(r"\n\s*\n", body.replace("\r", "").lstrip("\ufeff")):
            lines = block.splitlines()
            if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
                continue
            for index, line in enumerate(lines):
                match = re.match(r"\s*(\d+(?::\d+){1,2}[.,]\d+)\s*-->\s*(\d+(?::\d+){1,2}[.,]\d+)", line)
                if match:
                    try:
                        cues.append({"start": _seconds(match[1]), "end": _seconds(match[2]), "text": "\n".join(lines[index + 1:])})
                    except ValueError:
                        pass
                    break
        return cues
    if extension in {"json", "json3", "bcc"}:
        try:
            data = json.loads(body)
        except (ValueError, RecursionError) as error:
            raise AnalysisError("SUBTITLE_FORMAT_UNSUPPORTED", "字幕 JSON 无法解析，请重新获取。") from error
        if not isinstance(data, dict):
            raise AnalysisError("SUBTITLE_FORMAT_UNSUPPORTED", "暂不支持此字幕结构。")
        if isinstance(data.get("body"), list):
            return [{"start": c.get("from"), "end": c.get("to"), "text": c.get("content")} for c in data["body"] if isinstance(c, dict)]
        if isinstance(data.get("utterances"), list):
            return [{"start": _milliseconds(c.get("start_time")), "end": _milliseconds(c.get("end_time")), "text": c.get("text")} for c in data["utterances"] if isinstance(c, dict)]
        if isinstance(data.get("events"), list):
            events = [e for e in data["events"] if isinstance(e, dict) and isinstance(e.get("segs"), list)]
            result = []
            for i, event in enumerate(events):
                start = _milliseconds(event.get("tStartMs"))
                duration = _milliseconds(event.get("dDurationMs"))
                next_start = _milliseconds(events[i + 1].get("tStartMs")) if i + 1 < len(events) else None
                end = start + duration if start is not None and duration is not None else next_start
                result.append({"start": start, "end": end, "text": "".join(s.get("utf8", "") for s in event["segs"] if isinstance(s, dict) and isinstance(s.get("utf8"), str))})
            return result
        raise AnalysisError("SUBTITLE_FORMAT_UNSUPPORTED", "暂不支持此字幕 JSON 结构。")
    raise AnalysisError("SUBTITLE_FORMAT_UNSUPPORTED", "暂不支持此字幕格式，需要 SRT、VTT 或已适配的字幕 JSON。")


def _milliseconds(value) -> float | None:
    return float(value) / 1000 if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def normalize_cues(raw: list[dict], duration: float | None, config: AIConfig) -> tuple[list[dict], list[str]]:
    if len(raw) > 50000:
        raise AnalysisError("TRANSCRIPT_TOO_LARGE", "字幕片段过多，超过首版处理上限。")
    result, skipped = [], 0
    for cue in raw:
        start, end, text = cue.get("start"), cue.get("end"), _text(cue.get("text"))
        if (not isinstance(start, (int, float)) or isinstance(start, bool) or not isinstance(end, (int, float))
                or isinstance(end, bool) or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or not text):
            skipped += 1
            continue
        if start >= config.max_duration or end > config.max_duration + 1:
            raise AnalysisError("VIDEO_TOO_LONG", "字幕时间轴超过首版两小时上限。")
        if duration and start >= duration:
            skipped += 1
            continue
        if duration and end > duration:
            end = duration
            skipped += 1
        result.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    result.sort(key=lambda c: (c["start"], c["end"]))
    cleaned = []
    for cue in result:
        if cleaned and cue["start"] < cleaned[-1]["end"] and cue["text"].startswith(cleaned[-1]["text"]):
            # Rolling captions extend an already displayed phrase.
            cleaned[-1]["text"] = cue["text"]
            cleaned[-1]["end"] = max(cue["end"], cleaned[-1]["end"])
        else:
            cleaned.append(cue)
    if not cleaned:
        raise AnalysisError("EMPTY_TRANSCRIPT", "获取到了字幕轨道，但没有有效的带时间戳文本，暂不能总结。")
    if sum(len(c["text"]) for c in cleaned) > config.max_characters:
        raise AnalysisError("TRANSCRIPT_TOO_LARGE", "字幕文本超过首版处理上限，未截断生成摘要。")
    for index, cue in enumerate(cleaned):
        cue["id"] = f"c{index + 1:06d}"
    notes = [f"已排除或修正 {skipped} 个空白/非法时间轴片段。"] if skipped else []
    notes.append("仅根据获取到的字幕整理，未分析视频画面。")
    return cleaned, notes


class _CaptionLogger(video_service._YtdlpLogger):
    def __init__(self):
        self.access_required = False
        self.fetch_failed = False

    def warning(self, message):
        safe = str(message).casefold()
        if "subtitles are only available when logged in" in safe or "sign in" in safe or "fresh cookies" in safe:
            self.access_required = True
        if "unable to download" in safe or "failed to download" in safe or "429" in safe or "403" in safe or video_service.error_category(message) == "upstream_blocked":
            self.fetch_failed = True
        super().warning(message)


def caption_tracks(info: dict) -> list[dict]:
    tracks = []
    for field, default_kind in (("subtitles", "unknown"), ("automatic_captions", "automatic")):
        for language, entries in (info.get(field) or {}).items():
            if language == "danmaku" or not isinstance(entries, list):
                continue
            resources = [e for e in entries if isinstance(e, dict) and e.get("ext") in {"srt", "vtt", "webvtt", "json3", "json", "bcc"} and (e.get("data") or e.get("url"))]
            if not resources:
                continue
            kind = default_kind
            if field == "subtitles":
                if language.startswith("ai-"):
                    kind = "automatic"
                elif str(info.get("extractor_key", "")).lower().startswith("youtube"):
                    kind = "manual"
            tracks.append({"language": language, "kind": kind, "resources": resources})
    return tracks


def choose_track(tracks: list[dict], requested: str, original_language: str | None = None) -> dict:
    candidates = tracks if requested == "auto" else [t for t in tracks if t["language"] == requested]
    if not candidates:
        raise AnalysisError("LANGUAGE_UNAVAILABLE", "所选字幕语言不可用，请返回自动选择或选择已提供的语言。")
    def rank(track):
        language = track["language"].lower()
        chinese = language.startswith(("zh", "ai-zh", "cmn"))
        original = language.endswith("-orig") or bool(original_language and language.split("-")[0] == original_language.lower().split("-")[0])
        return (not chinese, not (chinese or original), {"manual": 0, "unknown": 1, "automatic": 2}[track["kind"]], not language.endswith("-orig"))
    return sorted(candidates, key=rank)[0]


def _resource_body(resource: dict, info: dict, ydl, platform: str, config: AIConfig) -> str:
    inline = resource.get("data")
    if isinstance(inline, str):
        if len(inline.encode("utf-8")) > config.max_resource_bytes:
            raise AnalysisError("TRANSCRIPT_TOO_LARGE", "字幕资源超过 5 MiB 上限。")
        return inline
    target = resource.get("url")
    if not isinstance(target, str):
        raise AnalysisError("CAPTIONS_FETCH_FAILED", "字幕轨道未提供可用文本。")
    headers = {"Accept-Encoding": "identity"}
    for name, value in {**(info.get("http_headers") or {}), **(resource.get("http_headers") or {})}.items():
        if name.lower() in {"user-agent", "referer", "accept-language"} and isinstance(value, str):
            headers[name] = value
    proxy = ydl.params.get("proxy") if platform == "YouTube" else None
    try:
        with httpx.Client(headers=headers, cookies=ydl.cookiejar, proxy=proxy, timeout=httpx.Timeout(25, connect=10), follow_redirects=False) as client:
            for _ in range(9):
                validate_public_http_url(target)
                with client.stream("GET", target) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        target = urljoin(target, response.headers.get("location", ""))
                        continue
                    if response.status_code in {401, 403}:
                        raise AnalysisError("CAPTIONS_ACCESS_REQUIRED", "平台拒绝提供字幕，暂不能总结；视频下载仍可单独尝试。")
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes(65536):
                        body.extend(chunk)
                        if len(body) > config.max_resource_bytes:
                            raise AnalysisError("TRANSCRIPT_TOO_LARGE", "字幕资源超过 5 MiB 上限。")
                    return body.decode("utf-8-sig", errors="replace")
    except AnalysisError:
        raise
    except (httpx.HTTPError, HTTPException, ImportError, ValueError) as error:
        raise AnalysisError("CAPTIONS_FETCH_FAILED", "字幕获取失败，请检查平台连接、代理或链接后重试。") from error
    raise AnalysisError("CAPTIONS_FETCH_FAILED", "字幕地址跳转过多，请重新获取。")


@contextmanager
def _caption_downloader(options: dict, optional_firefox: bool, platform: str = ''):
    settings = dict(options)
    client = None
    if optional_firefox:
        candidate = None
        try:
            candidate = YoutubeDL(settings)
            # Cookie loading is lazy. Resolve it before extraction, so a browser
            # setup failure can fall back without retrying platform/rights errors.
            candidate.cookiejar
        except Exception as error:
            if candidate is not None:
                candidate.close()
            if not platform_adapters.cookie_load_failed(error):
                raise
            logger.info("Optional Firefox captions session unavailable; using anonymous flow")
            settings.pop("cookiesfrombrowser", None)
            settings["cookiefile"] = None
        else:
            client = candidate
    if client is None:
        client = YoutubeDL(settings)
    with client:
        if platform == 'Bilibili' and platform_adapters.bilibili_metadata_source() == 'api':
            client.add_info_extractor(platform_adapters.BilibiliIE())
        yield client


def extract_transcript(url: str, requested_language: str = "auto", config: AIConfig | None = None, on_metadata=None) -> dict:
    config = config or get_config()
    platform, safe_url = platform_url(url)
    if platform == "Douyin" and not douyin.extract_video_id(safe_url):
        try:
            video = douyin.resolve_video(safe_url)
            safe_url = "https://www.douyin.com/video/" + video.video_id
        except Exception as error:
            raise AnalysisError("CAPTIONS_FETCH_FAILED", "抖音分享链接解析受阻，请稍后重试；原下载功能仍可使用。") from error
    caption_logger = _CaptionLogger()
    options = video_service._video_options(
        source_url=safe_url, skip_download=True, writesubtitles=True,
        writeautomaticsub=True, subtitleslangs=["all", "-live_chat"], ignore_no_formats_error=True,
        logger=caption_logger, extract_flat=False,
    )
    # Opt-in learning configuration only. Download settings remain untouched.
    optional_firefox = platform in {"Bilibili", "Douyin"} and config.firefox_subtitle_session
    if optional_firefox:
        options["cookiesfrombrowser"] = ("firefox", config.firefox_subtitle_profile)
    try:
        with _caption_downloader(options, optional_firefox, platform) as ydl:
            info = ydl.extract_info(safe_url, download=False)
            if not isinstance(info, dict) or info.get("_type") in {"playlist", "multi_video"}:
                raise AnalysisError("SINGLE_VIDEO_REQUIRED", "请提供单个视频或明确的 B 站分 P 链接。")
            if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
                raise AnalysisError("LIVE_UNSUPPORTED", "首版暂不支持直播或尚未完成的视频。")
            duration = info.get("duration")
            duration = float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration > 0 else None
            if duration and duration > config.max_duration:
                raise AnalysisError("VIDEO_TOO_LONG", "首版视频学习最长支持两小时，原下载功能仍可使用。")
            tracks = caption_tracks(info)
            if on_metadata:
                on_metadata({
                    "title": str(info.get("title") or "未命名视频"), "duration": duration,
                    "tracks": [{"language": t["language"], "kind": t["kind"]} for t in tracks],
                })
            if not tracks:
                if caption_logger.access_required:
                    message = "该平台的字幕需要登录会话。云端后端不能读取你电脑上的 Firefox Cookie；可在本机启动后端并启用字幕专用 Firefox 会话后重试。视频下载仍可单独尝试。"
                    raise AnalysisError("CAPTIONS_ACCESS_REQUIRED", message)
                if caption_logger.fetch_failed:
                    raise AnalysisError("CAPTIONS_FETCH_FAILED", "字幕信息获取受阻，请检查网络或稍后重试。")
                raise AnalysisError("NO_CAPTIONS", "没有可提取的平台字幕，暂不能总结；你仍可下载视频。语音转录后续支持。")
            selected = choose_track(tracks, requested_language, info.get("language"))
            formats = {"srt": 0, "vtt": 1, "webvtt": 1, "json3": 2, "json": 3, "bcc": 3}
            errors = []
            for resource in sorted(selected["resources"], key=lambda r: formats[r["ext"]]):
                try:
                    raw = parse_captions(_resource_body(resource, info, ydl, platform, config), resource["ext"])
                    cues, notes = normalize_cues(raw, duration, config)
                    break
                except AnalysisError as error:
                    errors.append(error)
            else:
                raise errors[-1]
    except AnalysisError:
        raise
    except Exception as error:
        category = video_service.error_category(error)
        if category == "upstream_blocked":
            raise AnalysisError("CAPTIONS_FETCH_FAILED", video_service.friendly_error(error)) from error
        if caption_logger.access_required or platform_adapters.cookie_load_failed(error) or category.startswith("cookie") or category in {"login_required", "forbidden"} or "fresh cookies" in str(error).lower():
            raise AnalysisError("CAPTIONS_ACCESS_REQUIRED", "平台字幕需要可用登录会话或受到访问限制。请检查后端所在设备的会话与权限；云端后端不能读取访问者电脑的 Cookie。本机 B 站／抖音可启用字幕专用 Firefox 会话，YouTube 沿用已选择的会话。") from error
        raise AnalysisError("CAPTIONS_FETCH_FAILED", "视频或字幕信息获取失败，请检查平台链接、网络和代理后重试。") from error
    source_id = str(info.get("id") or "")
    if platform == "Bilibili":
        source_id += ":p" + parse_qs(urlsplit(safe_url).query).get("p", ["1"])[0]
    return {
        "title": str(info.get("title") or "未命名视频"), "duration": duration, "source_id": source_id,
        "language": selected["language"], "track_kind": selected["kind"],
        "tracks": [{"language": t["language"], "kind": t["kind"]} for t in tracks],
        "cues": cues, "notes": notes,
        "transcript_hash": hashlib.sha256(json.dumps(cues, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
    }
