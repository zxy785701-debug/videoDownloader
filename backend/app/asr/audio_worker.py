"""Short-lived media process. stdout/stderr are suppressed by the supervisor."""
import errno
import http.client
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException

from .. import douyin, video_service
from ..analysis_errors import AnalysisError
from ..subtitle_service import platform_url
from .network import download, resolve_short_link


def positive_duration(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise AnalysisError("ASR_DURATION_UNKNOWN", "无法确认视频时长，未提交付费转录。")
    if value > maximum:
        raise AnalysisError("ASR_VIDEO_TOO_LONG", f"语音转录最长支持 {maximum // 60} 分钟，原生字幕和下载沿用现有限制。")
    return float(value)


MAX_MEDIA_CANDIDATES = 4


def media_candidates(media):
    """Use the same track's platform backups without relaxing download policy.

    Bilibili can prefer peer/CDN URLs on 8082/4483 while returning a standard
    HTTPS backup for the identical audio track. Keep queries byte-for-byte;
    changing a signed URL's scheme, port or path can invalidate its signature.
    DNS/public-address checks still happen in download() for every request.
    """
    backups = media.get("_platform_backup_urls") or []
    values = [media.get("url"), *(backups if isinstance(backups, (list, tuple)) else [])]
    candidates = []
    for url in values:
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
            continue
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.port not in {None, 443}):
                continue
        except ValueError:
            continue
        if url not in candidates:
            candidates.append(url)
            if len(candidates) >= MAX_MEDIA_CANDIDATES:
                break
    return candidates


def select_media(info):
    formats = info.get("formats") or [info]
    direct = [f for f in formats if isinstance(f, dict) and media_candidates(f)
              and f.get("protocol", "https") in {"http", "https"}
              and not f.get("has_drm") and f.get("acodec") != "none"]
    if not direct:
        raise AnalysisError("ASR_AUDIO_UNAVAILABLE", "没有可安全提取的音频直链；当前 ASR 暂不支持仅有 HLS/DASH 清单的视频。")
    # Audio-only first, then the smallest progressive video as a bounded fallback.
    return min(direct, key=lambda f: (f.get("vcodec") != "none", f.get("abr") or f.get("tbr") or 99999,
                                      f.get("height") or 0))


def download_media(media, destination, limit, check, headers):
    candidates = media_candidates(media)
    if not candidates:
        raise AnalysisError("ASR_AUDIO_UNAVAILABLE", "平台未提供可安全访问的标准 HTTPS 音频地址。")
    last_error = None
    for url in candidates:
        check()
        try:
            download(url, destination, limit, check, headers)
            return
        except AnalysisError as error:
            # Unsafe DNS/redirects, cancellation, deadlines and size limits must
            # stop the task; only an unavailable resource may try a backup.
            if error.code != "ASR_RESOURCE_FAILED":
                raise
            last_error = error
        except (OSError, http.client.HTTPException) as error:
            if isinstance(error, PermissionError) or (isinstance(error, OSError)
                    and error.errno in {errno.ENOSPC, errno.EROFS, errno.EDQUOT}):
                raise AnalysisError("ASR_TEMP_UNAVAILABLE", "临时音频无法写入，请管理员检查磁盘空间和目录权限。") from error
            last_error = AnalysisError("ASR_RESOURCE_FAILED", "音频下载连接失败，平台备用地址也不可用，请稍后重试。")
        destination.unlink(missing_ok=True)
    raise last_error


def prepare(request, directory):
    deadline = time.monotonic() + request["audio_timeout"]
    def check():
        if time.monotonic() >= deadline:
            raise AnalysisError("ASR_AUDIO_TIMEOUT", "音频下载或转换超时，请稍后重试。")
    platform, safe_url = platform_url(request["url"])
    if platform == "Bilibili":
        if urlsplit(safe_url).hostname == "b23.tv":
            safe_url = resolve_short_link(safe_url)
        if not re.fullmatch(r"/video/(?:BV[A-Za-z0-9]{3,30}|av[0-9]+)/?", urlsplit(safe_url).path):
            raise AnalysisError("ASR_AUDIO_UNAVAILABLE", "请提供 B站单个视频的 BV/AV 链接。")
    elif platform == "YouTube":
        parsed = urlsplit(safe_url)
        if parsed.hostname != "www.youtube.com" or parsed.path != "/watch" or not re.fullmatch(r"[\w-]{6,32}", parse_qs(parsed.query).get("v", [""])[0]):
            raise AnalysisError("ASR_AUDIO_UNAVAILABLE", "请提供 YouTube 单个视频的标准链接。")
    if platform == "Douyin":
        try:
            video = douyin.resolve_video(safe_url)
        except douyin.DouyinError as error:
            raise AnalysisError("ASR_AUDIO_UNAVAILABLE", str(error)) from error
        except HTTPException as error:
            raise AnalysisError("ASR_URL_UNSAFE", "抖音分享链接未通过公网安全校验，未提交付费转录。") from error
        info = {"id": video.video_id, "title": video.title, "duration": video.duration,
                "url": video.media_urls[0], "_platform_backup_urls": video.media_urls[1:],
                "http_headers": douyin.MOBILE_HEADERS}
        selected = info
    else:
        options = video_service._video_options(source_url=safe_url, skip_download=True,
            writesubtitles=False, writeautomaticsub=False, cachedir=False,
            format="bestaudio/best", noplaylist=True, retries=1, concurrent_fragment_downloads=1)
        with video_service._open_video_downloader(safe_url, options) as ydl:
            info = ydl.extract_info(safe_url, download=False)
        if (not isinstance(info, dict) or info.get("_type") in {"playlist", "multi_video"}
                or info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}):
            raise AnalysisError("ASR_AUDIO_UNAVAILABLE", "语音转录仅支持已完成的单个视频。")
        selected = select_media(info)
    duration = positive_duration(info.get("duration"), request["max_duration"])
    raw = directory / "source.media"
    check()
    download_media(selected, raw, request["max_download_bytes"], check,
                   {**(info.get("http_headers") or {}), **(selected.get("http_headers") or {})})
    check()
    ffmpeg = video_service._ffmpeg_location()
    if not ffmpeg:
        raise AnalysisError("ASR_FFMPEG_MISSING", "请管理员安装 FFmpeg 或 imageio-ffmpeg。")
    audio = directory / "audio.flac"
    # No network protocols in FFmpeg; -t includes one extra second so overlong
    # media is rejected rather than silently summarized after truncation.
    command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error",
               "-max_alloc", "67108864", "-probesize", "5242880", "-analyzeduration", "5000000",
               "-threads", str(request["threads"]), "-protocol_whitelist", "file,pipe",
               "-format_whitelist", "mov,matroska,webm,mp3,wav,flac,aac,ogg,mpegts",
               "-i", str(raw), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
               "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
               "-c:a", "flac", "-threads", str(request["threads"]),
               "-t", str(request["max_duration"] + 1), "-fs", str(request["max_audio_bytes"]), str(audio)]
    converted = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=max(1, deadline - time.monotonic()))
    if converted.returncode or not audio.is_file() or audio.stat().st_size <= 0:
        raise AnalysisError("ASR_AUDIO_INVALID", "音频转换失败，未提交识别任务。")
    if audio.stat().st_size >= request["max_audio_bytes"]:
        raise AnalysisError("ASR_FILE_TOO_LARGE", "转换后的音频超过大小上限，未截断提交识别。")
    # FLAC STREAMINFO carries exact decoded sample count/rate. No ffprobe or
    # whole-file read needed, including imageio-ffmpeg-only deployments.
    with audio.open("rb") as stream:
        header = stream.read(42)
    if len(header) < 42 or header[:4] != b"fLaC" or header[4] & 0x7f != 0:
        raise AnalysisError("ASR_AUDIO_INVALID", "转换后的 FLAC 头部无效。")
    packed = int.from_bytes(header[18:26], "big")
    sample_rate, samples = packed >> 44, packed & ((1 << 36) - 1)
    actual = positive_duration(samples / sample_rate if sample_rate else None, request["max_duration"])
    if abs(actual - duration) > max(3, duration * 0.02):
        raise AnalysisError("ASR_AUDIO_INCOMPLETE", "提取音频时长与视频不符，未提交可能不完整的转录。")
    raw.unlink()
    return {"duration": actual, "title": str(info.get("title") or "未命名视频"),
            "source_id": str(info.get("id") or "")}


def main():
    directory = Path(sys.argv[1]).resolve()
    try:
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        result = {"metadata": prepare(request, directory)}
    except AnalysisError as error:
        result = {"error_code": error.code, "error": error.message}
    except subprocess.TimeoutExpired:
        result = {"error_code": "ASR_AUDIO_TIMEOUT", "error": "音频转换超时。"}
    except Exception:
        result = {"error_code": "ASR_AUDIO_FAILED", "error": "音频提取失败，请检查平台权限、网络及 FFmpeg 配置。"}
    (directory / "response.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
