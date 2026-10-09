"""Local Firefox sessions and platform-specific yt-dlp adapters.

Only Bilibili uploads and MangoTV use this layer. Browser credentials and media
URLs stay inside the downloader; no installed yt-dlp files are modified.
"""
import base64
import json
import logging
import math
import os
import re
import subprocess
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.cookies import CookieLoadError
from yt_dlp.extractor.bilibili import BiliBiliIE
from yt_dlp.extractor.mgtv import MGTVIE
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import ExtractorError, float_or_none, int_or_none, parse_m3u8_attributes, url_or_none

logger = logging.getLogger(__name__)
MAX_METADATA_BYTES = 2 * 1024 * 1024


class PlatformError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def cookie_load_failed(error):
    """yt-dlp can wrap CookieLoadError in DownloadError while reporting it.

    Match typed causes only, never message substrings. Callers use this only
    while preparing the optional browser session, before media extraction.
    """
    pending, seen = [error], set()
    while pending and len(seen) < 20:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, CookieLoadError):
            return True
        pending.extend((current.__cause__, current.__context__))
        exc_info = getattr(current, 'exc_info', None)
        if isinstance(exc_info, tuple) and len(exc_info) == 3:
            pending.append(exc_info[1])
    return False


def platform_for(url):
    host = (urlsplit(url).hostname or '').lower()
    if host in {'bilibili.com', 'www.bilibili.com'} and BiliBiliIE.suitable(url):
        return 'bilibili'
    if host in {'mgtv.com', 'www.mgtv.com', 'w.mgtv.com'} and MGTVIE.suitable(url):
        return 'mgtv'
    return None


def bilibili_metadata_source():
    source = os.environ.get('BILIBILI_METADATA_SOURCE', 'webpage').strip().lower()
    if source not in {'webpage', 'api'}:
        raise PlatformError('CONFIG_INVALID', 'BILIBILI_METADATA_SOURCE 需为 webpage 或 api。')
    return source


def read_json(ydl, url, headers=None):
    with ydl.urlopen(Request(url, headers=headers or {})) as response:
        body = response.read(MAX_METADATA_BYTES + 1)
    if len(body) > MAX_METADATA_BYTES:
        raise PlatformError('METADATA_TOO_LARGE', '平台元信息过大，请换一个视频重试。')
    return json.loads(body)


def _valid_cookies(ydl, domain):
    return any((cookie.domain.lstrip('.') == domain or cookie.domain.endswith('.' + domain))
               and not cookie.is_expired() for cookie in ydl.cookiejar)


def _session_usable(ydl, platform):
    domain = 'bilibili.com' if platform == 'bilibili' else 'mgtv.com'
    if not _valid_cookies(ydl, domain):
        return False
    if platform == 'mgtv':
        return True  # The authenticated player API still decides playback rights.
    try:
        result = read_json(ydl, 'https://api.bilibili.com/x/web-interface/nav',
                           {'Referer': 'https://www.bilibili.com/'})
    except Exception as error:
        raise PlatformError('SESSION_CHECK_FAILED', 'B 站登录状态检查失败，请检查网络后重试。') from error
    if result.get('code') not in (0, -101) or not isinstance(result.get('data', {}).get('isLogin'), bool):
        raise PlatformError('SESSION_CHECK_FAILED', 'B 站未返回有效登录状态，请稍后重试。')
    return result['data']['isLogin']


class _PlatformLogger:
    def __init__(self, delegate):
        self.delegate = delegate

    def debug(self, message):
        self.delegate.debug(message)

    def warning(self, message):
        if 'only the preview' in str(message).lower() or 'only preview format' in str(message).lower():
            raise PlatformError('PREVIEW_ONLY', '平台仅返回试看内容，请确认 Firefox 登录账号能够完整播放该视频。')
        self.delegate.warning(message)

    def error(self, message):
        self.delegate.error(message)


@contextmanager
def open_downloader(url, options):
    platform = platform_for(url)
    if platform is None:
        raise ValueError('Unsupported platform adapter')
    prefix = platform.upper()
    settings = dict(options)
    if settings.get('logger'):
        settings['logger'] = _PlatformLogger(settings['logger'])
    settings.update(cookiefile=None, cachedir=False, geo_bypass=False,
                    skip_unavailable_fragments=False, retries=1, fragment_retries=1,
                    concurrent_fragment_downloads=4, merge_output_format='mp4')
    enabled = os.environ.get(prefix + '_USE_FIREFOX_SESSION', '1').strip().lower()
    if enabled not in {'0', '1', 'false', 'true'}:
        raise PlatformError('CONFIG_INVALID', prefix + '_USE_FIREFOX_SESSION 需为 1 或 0。')
    settings.pop('cookiesfrombrowser', None)
    client = None
    if enabled in {'1', 'true'}:
        profile = os.environ.get(prefix + '_FIREFOX_PROFILE', '').strip() or None
        candidate = None
        try:
            candidate = PlatformYoutubeDL({**settings, 'cookiesfrombrowser': ('firefox', profile, None, None)})
            usable = _session_usable(candidate, platform)
        except Exception as error:
            if not cookie_load_failed(error):
                if candidate is not None:
                    candidate.close()
                raise
            usable = False
            logger.info('Firefox session unavailable platform=%s; using anonymous flow', platform)
        if usable:
            client = candidate
        else:
            if candidate is not None:
                candidate.close()
            logger.info('No usable Firefox login platform=%s; using anonymous flow', platform)
    if client is None:
        client = PlatformYoutubeDL(settings)
    # There is deliberately no anonymous retry around extraction or downloading.
    with client:
        client.add_info_extractor(BilibiliIE() if platform == 'bilibili' else MangoTVIE())
        yield client


def _retryable_transfer(error):
    text = str(error).lower()
    if any(word in text for word in ('permission denied', 'access is denied', 'no space left', 'disk full')):
        return False
    return any(word in text for word in (
        'timed out', 'timeout', 'connection reset', 'connection closed', 'remote end closed',
        'certificate verify', 'ssl', 'tls', 'unable to connect', 'incomplete read',
        'getaddrinfo', 'name resolution', 'http error 403', 'http error 404',
        'http error 408', 'http error 429', 'http error 5', 'downloaded file is empty',
    ))


class PlatformYoutubeDL(YoutubeDL):
    def dl(self, name, info, subtitle=False, test=False):
        backups = [] if subtitle or test else info.get('_platform_backup_urls', [])
        targets = list(dict.fromkeys([info.get('url'), *backups]))[:3]
        for index, target in enumerate(targets):
            try:
                result = super().dl(name, {**info, 'url': target}, subtitle=subtitle, test=test)
                if not result[0]:
                    raise PlatformError('TRANSFER_FAILED', '平台媒体下载未完成，请稍后重试。')
                return result
            except Exception as error:
                if index + 1 >= len(targets) or not _retryable_transfer(error):
                    raise
                # Same response, same format, same output/resume file; no quality downgrade.
                logger.info('Retrying platform-provided backup CDN attempt=%s', index + 1)


class BilibiliIE(BiliBiliIE):
    @classmethod
    def ie_key(cls):
        return BiliBiliIE.ie_key()

    def _download_json(self, url, *args, **kwargs):
        result = super()._download_json(url, *args, **kwargs)
        if urlsplit(url).path == '/x/player/pagelist' and isinstance(result, dict):
            self._part_pages = result.get('data') if isinstance(result.get('data'), list) else []
        return result

    def report_warning(self, message, *args, **kwargs):
        if 'only the preview' in str(message).lower() or 'only preview format' in str(message).lower():
            raise PlatformError('PREVIEW_ONLY', 'B 站仅返回试看内容，请在 Firefox 中登录有权完整观看的账号后重试。')
        return super().report_warning(message, *args, **kwargs)

    def extract_formats(self, play_info):
        play_info = play_info or {}
        if any('试看' in str(value) for value in play_info.get('accept_description', [])) or play_info.get('is_preview'):
            raise PlatformError('PREVIEW_ONLY', 'B 站仅返回试看内容，请确认当前账号具有完整观看权限。')
        formats = super().extract_formats(play_info)
        dash = play_info.get('dash') or {}
        resources = (dash.get('video') or []) + (dash.get('audio') or []) + (play_info.get('durl') or [])
        backups = {entry.get('baseUrl') or entry.get('base_url') or entry.get('url'):
                   entry.get('backupUrl') or entry.get('backup_url') or [] for entry in resources}
        for fmt in formats:
            if not fmt.get('fragments'):
                values = backups.get(fmt.get('url'), [])
                fmt['_platform_backup_urls'] = [value for value in values if url_or_none(value)] if isinstance(values, list) else []
        return formats

    def _extract_api(self, url, part):
        """Use the public metadata API and yt-dlp's signed playback helper.

        Selected before extraction, never as a retry after a permission failure.
        Cookies, signing and transport remain owned by this same downloader.
        """
        match = self._match_valid_url(url)
        prefix, identifier = match.group('prefix', 'id')
        if not re.fullmatch(r'[\w]{10}' if prefix.upper() == 'BV' else r'\d+', identifier):
            raise PlatformError('METADATA_INVALID', 'B 站视频标识无效，请检查直接视频链接。')
        query = {'bvid': 'BV' + identifier} if prefix.upper() == 'BV' else {'aid': identifier}
        headers = {'Referer': 'https://www.bilibili.com/', 'Origin': 'https://www.bilibili.com'}
        result = self._download_json('https://api.bilibili.com/x/web-interface/view', identifier,
                                     query=query, headers=headers, note='Downloading public video metadata')
        if not isinstance(result, dict) or result.get('code') != 0 or not isinstance(result.get('data'), dict):
            raise PlatformError('METADATA_REJECTED', 'B 站未提供可用的视频信息，请检查链接、访问权限或稍后重试。')
        data = result['data']
        bvid, aid = data.get('bvid'), int_or_none(data.get('aid'))
        if (not isinstance(bvid, str) or not re.fullmatch(r'BV[\w]{10}', bvid)
                or not aid or (query.get('bvid') and bvid != query['bvid'])
                or (query.get('aid') and aid != int(query['aid']))):
            raise PlatformError('METADATA_INVALID', 'B 站返回的视频标识与链接不一致，请重新解析。')
        if data.get('redirect_url') or (data.get('rights') or {}).get('is_stein_gate'):
            raise PlatformError('API_UNSUPPORTED', 'B 站 API 模式暂不支持跳转番剧或互动视频，请使用普通投稿的直接链接。')
        self._part_pages = data.get('pages') if isinstance(data.get('pages'), list) else []
        page = next((entry for entry in self._part_pages if isinstance(entry, dict) and entry.get('page') == part), None)
        if not page or (int_or_none(page.get('cid')) or 0) <= 0:
            raise PlatformError('PART_INVALID', '该 B 站分 P 不存在，请检查链接。')
        expected = float_or_none(page.get('duration'))
        if not expected or not math.isfinite(expected) or expected < 0:
            raise PlatformError('METADATA_INVALID', 'B 站未返回可校验的完整分 P 时长，请稍后重试。')
        cid = int(page['cid'])
        play_info = self._download_playinfo(bvid, cid, headers=headers, query={'try_look': 1})
        formats = self.extract_formats(play_info)
        if not formats:
            raise PlatformError('NO_FORMATS', 'B 站未提供可下载格式，请确认当前会话具有完整观看权限。')
        # Legacy FLV fragments need a separate multi-video merge workflow; never
        # concatenate them as though they were a complete single media stream.
        formats = [fmt for fmt in formats if not fmt.get('fragments')]
        if not formats:
            raise PlatformError('API_UNSUPPORTED', 'B 站 API 模式暂不支持该分段格式，请使用其他视频或本机网页模式。')
        duration = float_or_none(play_info.get('timelength'), scale=1000)
        if not duration or not math.isfinite(duration) or abs(duration - expected) > max(3, expected * 0.005):
            raise PlatformError('PREVIEW_ONLY', 'B 站返回的时长与完整分 P 不一致，当前内容可能仅为试看。')
        selected_part = len(self._part_pages) > 1 or 'p' in parse_qs(urlsplit(url).query)
        title = data.get('title') or bvid
        if len(self._part_pages) > 1:
            title += f' p{part:02d} {page.get("part") or ""}'
        owner, stat = data.get('owner') or {}, data.get('stat') or {}
        return {
            'id': f'{bvid}_p{part}' if selected_part else bvid,
            'title': title, 'duration': duration, 'formats': formats,
            'thumbnail': url_or_none(data.get('pic')), 'description': data.get('desc'),
            'uploader': owner.get('name'), 'uploader_id': str(owner['mid']) if owner.get('mid') else None,
            'timestamp': int_or_none(data.get('pubdate')), 'view_count': int_or_none(stat.get('view')),
            'http_headers': {'Referer': url, 'Origin': headers['Origin']},
            'subtitles': self.extract_subtitles(bvid, cid, aid),
        }

    def _real_extract(self, url):
        self._part_pages = []
        try:
            part = int(parse_qs(urlsplit(url).query).get('p', ['1'])[-1])
            if part < 1:
                raise ValueError
        except ValueError:
            raise PlatformError('PART_INVALID', 'B 站分 P 编号必须是正整数。') from None
        try:
            info = self._extract_api(url, part) if bilibili_metadata_source() == 'api' else super()._real_extract(url)
        except ExtractorError as error:
            if 'supporter-only video' in str(error).lower():
                raise PlatformError('RIGHTS_REQUIRED', '当前 B 站账号未取得此充电视频的完整观看权限，请确认 Firefox 中能够完整播放。') from error
            raise
        if info.get('_type') in ('playlist', 'multi_video', 'url', 'url_transparent'):
            return info
        page = next((page for page in self._part_pages if page.get('page') == part), None)
        if self._part_pages and not page:
            raise PlatformError('PART_INVALID', '该 B 站分 P 不存在，请检查链接。')
        if part > 1 and not str(info.get('id')).endswith(f'_p{part}'):
            raise PlatformError('PART_MISMATCH', '平台返回了不同的分 P，请重新解析。')
        expected = float((page or {}).get('duration') or 0)
        actual = float(info.get('duration') or 0)
        if expected and (not actual or abs(actual - expected) > max(3, expected * 0.005)):
            raise PlatformError('PREVIEW_ONLY', 'B 站返回的时长与完整分 P 不一致，当前内容可能仅为试看。')
        info['_platform_expected_duration'] = expected or actual
        return info


def inspect_manifest(ydl, fmt, expected):
    with ydl.urlopen(Request(fmt['url'], headers=fmt.get('http_headers') or {})) as response:
        body = response.read(MAX_METADATA_BYTES + 1)
    if len(body) > MAX_METADATA_BYTES:
        raise PlatformError('MANIFEST_INVALID', '芒果 TV 播放清单过大，暂不支持此视频。')
    text = body.decode('utf-8-sig')
    if not text.startswith('#EXTM3U') or '#EXT-X-STREAM-INF:' in text:
        raise PlatformError('MANIFEST_INVALID', '芒果 TV 返回了未支持的播放清单。')
    for line in text.splitlines():
        if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')):
            attrs = parse_m3u8_attributes(line.partition(':')[2])
            if attrs.get('METHOD', 'NONE') not in ('NONE', 'AES-128') or attrs.get('KEYFORMAT', 'identity') != 'identity':
                raise PlatformError('DRM_UNSUPPORTED', '该芒果 TV 格式需要受保护播放，当前不支持下载。')
    lengths = [float(value) for value in re.findall(r'^#EXTINF:([\d.]+)', text, re.M)]
    if not lengths or '#EXT-X-ENDLIST' not in text or '#EXT-X-GAP' in text:
        raise PlatformError('MANIFEST_INVALID', '芒果 TV 未提供完整点播清单，请稍后重试。')
    duration = sum(lengths)
    if not expected or abs(duration - expected) > max(3, expected * 0.005):
        raise PlatformError('PREVIEW_ONLY', '芒果 TV 仅返回试看或不完整内容，请在 Firefox 中确认会员账号能完整播放。')
    height = re.search(r'#EXT-MGTV-VIDEO-HEIGHT:(\d+)', text)
    width = re.search(r'#EXT-MGTV-VIDEO-WIDTH:(\d+)', text)
    return {'duration': duration, 'height': int(height[1]) if height else None,
            'width': int(width[1]) if width else None,
            'estimated_bytes': sum(int(value) for value in re.findall(r'#EXT-MGTV-File-SIZE:(\d+)', text))}


class MangoTVIE(MGTVIE):
    @classmethod
    def ie_key(cls):
        return MGTVIE.ie_key()

    def _download_json(self, url, *args, **kwargs):
        query = dict(kwargs.get('query', {}))
        path = urlsplit(url).path
        if path in ('/player/video', '/player/getSource'):
            tk2 = query.get('tk2', b'')
            encoded = tk2.encode() if isinstance(tk2, str) else tk2
            device = re.search(r'did=([^|]+)', base64.urlsafe_b64decode(encoded[::-1]).decode())
            query.update(did=device[1] if device else '', auth_mode='1', _support='10000000', allowedRC='1')
            if path == '/player/getSource':
                url = 'https://pcweb.api.mgtv.com/player/getSource'
                query.update(src='', abroad='', definitionType='2')
            kwargs['query'] = query
        try:
            result = super()._download_json(url, *args, **kwargs)
        except Exception as error:
            cause = getattr(error, 'cause', None)
            if path in ('/player/video', '/player/getSource') and isinstance(cause, HTTPError):
                try:
                    code = json.loads(cause.response.read(MAX_METADATA_BYTES)).get('code')
                except (ValueError, OSError):
                    code = None
                self._check_api_code(code)
            raise
        if path in ('/player/video', '/player/getSource') and isinstance(result, dict):
            self._check_api_code(result.get('code'))
        return result

    @staticmethod
    def _check_api_code(code):
        if str(code) == '40005':
            raise PlatformError('PLAYBACK_REJECTED', '芒果 TV 拒绝该播放请求，请确认 Firefox 中同一账号、同一链接可以完整播放。')
        if code is not None and str(code) != '200':
            raise PlatformError('PLAYBACK_REJECTED', '芒果 TV 未提供播放权限，请确认 Firefox 登录状态与会员权限后重试。')

    def _real_extract(self, url):
        info = super()._real_extract(url)
        expected = float(info.get('duration') or 0)
        usable = []
        rejected = None
        for fmt in info.get('formats') or []:
            try:
                manifest = inspect_manifest(self._downloader, fmt, expected)
            except PlatformError as error:
                rejected = error
                logger.info('Skipping unsupported MangoTV format category=%s', error.code)
                continue
            fmt['_platform_manifest'] = manifest
            if not fmt.get('height'):
                label = re.search(r'(\d{3,4})[pP]', fmt.get('format_note') or '')
                fmt['height'] = int(label[1]) if label else manifest['height']
                fmt['width'] = manifest['width']
            fmt['vcodec'] = fmt.get('vcodec') or 'unknown'
            fmt['acodec'] = fmt.get('acodec') or 'unknown'
            if manifest['estimated_bytes']:
                fmt['filesize_approx'] = manifest['estimated_bytes']
            usable.append(fmt)
        if not usable:
            raise rejected or PlatformError('NO_FORMATS', '芒果 TV 没有可下载的完整格式，请确认当前账号能完整播放。')
        info['formats'] = usable
        info['_platform_expected_duration'] = expected
        return info


def verify_media(ffmpeg, path, expected):
    if not ffmpeg:
        raise PlatformError('FFMPEG_MISSING', '此视频需要 FFmpeg 合并或校验音视频，请检查后端配置。')
    try:
        result = subprocess.run([ffmpeg, '-hide_banner', '-xerror', '-i', str(path),
                                 '-map', '0:v:0', '-map', '0:a:0', '-t', '0', '-f', 'null', '-'],
                                capture_output=True, timeout=30, encoding='utf-8', errors='replace')
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PlatformError('MEDIA_INVALID', '下载后的音视频校验失败，请检查 FFmpeg 后重试。') from error
    duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', result.stderr)
    seconds = sum(float(v) * scale for v, scale in zip(duration.groups(), (3600, 60, 1))) if duration else None
    if result.returncode or not seconds or not expected or abs(seconds - expected) > max(3, expected * 0.005):
        raise PlatformError('MEDIA_INVALID', '下载文件的音视频或时长不完整，请重试；当前文件不会标记为下载成功。')
