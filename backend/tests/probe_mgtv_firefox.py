"""Independent MGTV/Firefox probe. Does not modify production settings.

Metadata: backend/.venv/Scripts/python.exe backend/tests/probe_mgtv_firefox.py --url https://www.mgtv.com/b/321423/5546935.html --source-api pcweb-web --direct
Download: add --download (default quality ceiling: 480p). Omit --direct to use system proxy settings.
Reports contain no cookie values, signed media URLs or raw upstream responses.
"""
import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.extractor.mgtv import MGTVIE
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import parse_m3u8_attributes, url_or_none

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.video_service import _ffmpeg_location, error_category


class ProbeError(Exception):
    pass


def category(error):
    message = str(error).lower()
    for pattern, prefix in ((r'(?:http error|status code)[: ]+(\d{3})', 'http_'),
                            (r'\[ssl: ([a-z_]+)\]', 'tls_'),
                            (r'\[(?:winerror|errno) (\d+)\]', 'os_')):
        match = re.search(pattern, message)
        if match:
            return prefix + match[1]
    for kind, markers in (
        ('drm', ('drm protected', 'drm-protected')),
        ('region_restricted', ('geo restricted', 'geo-restricted', 'not available from your location')),
        ('preview', ('preview', '试看')),
        ('file_size_limit', ('max-filesize', 'max_filesize')),
        ('authentication', ('unauthorized', 'login required', '会员')),
    ):
        if any(marker in message for marker in markers):
            return kind
    return error_category(error)


class SafeLogger:
    def __init__(self, report):
        self.report = report

    def debug(self, message):
        pass

    def warning(self, message):
        self.report['events'].append({'warning': category(message)})

    def error(self, message):
        self.report['events'].append({'error': category(message)})


class ObservedMGTVIE(MGTVIE):
    def __init__(self, report, source_api):
        super().__init__()
        self.report = report
        self.source_api = source_api

    def _download_json(self, url, *args, **kwargs):
        query = dict(kwargs.get('query', {}))
        if self.source_api == 'pcweb-web' and urlsplit(url).path in ('/player/video', '/player/getSource'):
            tk2 = query.get('tk2', b'')
            encoded = tk2.encode() if isinstance(tk2, str) else tk2
            device = re.search(r'did=([^|]+)', base64.urlsafe_b64decode(encoded[::-1]).decode())
            query.update(did=device[1] if device else '', auth_mode='1', _support='10000000', allowedRC='1')
            if urlsplit(url).path == '/player/getSource':
                # Match the official webpage player's pcweb request, not the foreign client defaults.
                query.update(src='', abroad='', definitionType='2')
            kwargs['query'] = query
        if url == 'https://tinker.glb.mgtv.com/player/getSource' and self.source_api.startswith('pcweb'):
            url = 'https://pcweb.api.mgtv.com/player/getSource'
            if self.source_api == 'pcweb-legacy':
                kwargs['query'] = {key: value for key, value in kwargs.get('query', {}).items()
                                   if key in ('pm2', 'tk2', 'video_id')}
        parsed = urlsplit(url)
        event = {'host': parsed.hostname, 'endpoint': parsed.path}
        try:
            result = super()._download_json(url, *args, **kwargs)
        except Exception as error:
            event['error'] = category(error)
            cause = getattr(error, 'cause', None)
            if parsed.path == '/player/getSource' and isinstance(cause, HTTPError):
                try:
                    rejected = json.loads(cause.response.read(2 * 1024 * 1024))
                    code = rejected.get('code')
                    if isinstance(code, int):
                        event['code'] = code
                except (ValueError, OSError):
                    pass
            self.report['api_observations'].append(event)
            if event.get('code') == 40005:
                raise ProbeError('region_restricted_40005') from None
            raise
        if isinstance(result, dict):
            code = result.get('code')
            if isinstance(code, int) or isinstance(code, str) and code.isdecimal():
                event['code'] = int(code)
            data = result.get('data')
            if isinstance(data, dict):
                event['data_keys'] = sorted(data)
                if 'stream' in data:
                    stream = data['stream']
                    event.update(stream_type=type(stream).__name__,
                                 stream_count=len(stream) if isinstance(stream, (list, dict)) else 0)
                    if isinstance(stream, list):
                        event['streams_with_url'] = sum(bool(item.get('url')) for item in stream if isinstance(item, dict))
                info = data.get('info')
                if isinstance(info, dict):
                    duration = info.get('duration')
                    if isinstance(duration, (int, float)) or isinstance(duration, str) and duration.isdecimal():
                        event['duration'] = int(duration)
                        self.report['metadata_duration'] = int(duration)
                    if isinstance(info.get('title'), str):
                        self.report['title'] = info['title']
                user = data.get('user')
                if isinstance(user, dict):
                    event['user_flag_keys'] = sorted(user)
                    event['user_flags'] = {key: int(value) for key, value in user.items()
                                           if key.lower() in ('isvip', 'islogin', 'is_login', 'vip', 'is_vip') and str(value) in ('0', '1')}
                drm = data.get('drm')
                event['drm_field_type'] = type(drm).__name__
                if isinstance(drm, dict):
                    event['drm_flag_keys'] = sorted(drm)
                    drm_type = drm.get('drmType')
                    event['drm_type'] = int(drm_type) if str(drm_type).isdecimal() else 'unspecified'
                    event['has_license_endpoint'] = bool(drm.get('licenseUrl'))
                    firm = str(drm.get('drmFirm') or '').lower()
                    event['drm_provider'] = firm if firm in ('widevine', 'fairplay', 'playready', 'chinadrm') else ('other' if firm else 'none')
            resource = result.get('info')
            event['has_info_url'] = bool(url_or_none(resource))
            event['info_type'] = type(resource).__name__
            if isinstance(resource, dict):
                event['info_keys'] = sorted(resource)
            if event.get('code') not in (None, 200):
                message = str(result.get('msg') or result.get('message') or result.get('info') or '').lower()
                event['reason_markers'] = [label for label, words in (
                    ('region', ('地区', 'country', 'region')),
                    ('expired', ('过期', 'expired', 'expire')),
                    ('parameters', ('参数', 'parameter', 'param')),
                    ('authentication', ('权限', '登录', 'auth', 'permission')),
                    ('token', ('token', 'tk2', 'ticket')),
                ) if any(word in message for word in words)]
        self.report['api_observations'].append(event)
        if parsed.path == '/player/getSource' and isinstance(result, dict) and result.get('code') not in (200, '200'):
            code = result.get('code')
            raise ProbeError('region_restricted_40005' if str(code) == '40005' else 'source_api_rejected')
        return result


def inspect_manifest(ydl, info):
    request = Request(info['url'], headers=info.get('http_headers') or {})
    with ydl.urlopen(request) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise ProbeError('manifest_size_limit')
    text = body.decode('utf-8-sig')
    if not text.startswith('#EXTM3U'):
        raise ProbeError('not_hls_manifest')
    if '#EXT-X-STREAM-INF:' in text:
        raise ProbeError('master_playlist_needs_variant_selection')
    methods = set()
    for line in text.splitlines():
        if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')):
            attrs = parse_m3u8_attributes(line.partition(':')[2])
            method = attrs.get('METHOD', 'NONE')
            methods.add(method)
            if method not in ('NONE', 'AES-128') or attrs.get('KEYFORMAT', 'identity') != 'identity':
                raise ProbeError('drm_or_unsupported_encryption')
    durations = [float(value) for value in re.findall(r'^#EXTINF:([\d.]+)', text, re.M)]
    if not durations or '#EXT-X-ENDLIST' not in text:
        raise ProbeError('not_complete_vod_playlist')
    if '#EXT-X-GAP' in text:
        raise ProbeError('playlist_has_missing_segments')
    width = re.search(r'#EXT-MGTV-VIDEO-WIDTH:(\d+)', text)
    height = re.search(r'#EXT-MGTV-VIDEO-HEIGHT:(\d+)', text)
    return {'duration': round(sum(durations), 3), 'segments': len(durations),
            'encryption_methods': sorted(methods), 'width': int(width[1]) if width else None,
            'height': int(height[1]) if height else None,
            'estimated_bytes': sum(int(value) for value in re.findall(r'#EXT-MGTV-File-SIZE:(\d+)', text))}


def validate_media(ffmpeg, media):
    result = subprocess.run([ffmpeg, '-hide_banner', '-xerror', '-i', str(media),
                             '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                            capture_output=True, timeout=900, encoding='utf-8', errors='replace')
    duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', result.stderr)
    video = re.search(r'Video: ([^, ]+)[^\n]*?(\d{2,5})x(\d{2,5})(?:[ ,\[])', result.stderr)
    audio = re.search(r'Audio: ([^, ]+)', result.stderr)
    return {'full_decode_exit_code': result.returncode,
            'duration': sum(float(v) * scale for v, scale in zip(duration.groups(), (3600, 60, 1))) if duration else None,
            'video_codec': video[1] if video else None, 'audio_codec': audio[1] if audio else None,
            'width': int(video[2]) if video else None, 'height': int(video[3]) if video else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--profile', help='Optional Firefox profile name/path')
    parser.add_argument('--anonymous', action='store_true')
    parser.add_argument('--direct', action='store_true', help='Ignore system proxy for this probe only')
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--height', choices=(480, 540, 576, 720, 1080), type=int, default=480)
    parser.add_argument('--source-api', choices=('installed', 'pcweb', 'pcweb-legacy', 'pcweb-web'), default='installed',
                        help='installed: unchanged extractor; pcweb: endpoint only; pcweb-legacy: old parameters; pcweb-web: current official webpage parameters')
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('www.mgtv.com', 'w.mgtv.com') or not re.fullmatch(r'/[bv]/(?:\d+/)+\d+\.html', parsed.path):
        parser.error('Use a direct mgtv.com episode URL')
    url = 'https://www.mgtv.com' + parsed.path
    mode = 'anonymous' if args.anonymous else 'firefox'
    folder = Path(__file__).resolve().parents[2] / '.local' / 'mgtv-firefox-probe'
    folder = folder / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + mode)
    folder.mkdir(parents=True, exist_ok=False)
    report = {'url': url, 'mode': mode, 'direct': args.direct, 'height_limit': args.height,
              'download_requested': args.download, 'source_api': args.source_api,
              'yt_dlp_version': __import__('yt_dlp.version', fromlist=['__version__']).__version__,
              'events': [], 'api_observations': [], 'status': 'started'}
    started = time.monotonic()
    max_bytes = 1024 * 1024 * 1024
    options = {'quiet': True, 'noprogress': True, 'logger': SafeLogger(report),
               'cookiesfrombrowser': None if args.anonymous else ('firefox', args.profile, None, None),
               'cookiefile': None, 'cachedir': False, 'noplaylist': True, 'geo_bypass': False,
               'socket_timeout': 20, 'retries': 1, 'fragment_retries': 1, 'extractor_retries': 0,
               'concurrent_fragment_downloads': 4, 'skip_unavailable_fragments': False,
               'format': f'b[height<={args.height}]', 'max_filesize': max_bytes,
               'outtmpl': str(folder / 'video.%(ext)s'), 'overwrites': False,
               'http_headers': {'Referer': url, 'Origin': 'https://www.mgtv.com'},
               'allow_unplayable_formats': False}
    if args.direct:
        options['proxy'] = ''
    try:
        ffmpeg = _ffmpeg_location()
        if ffmpeg:
            options['ffmpeg_location'] = ffmpeg
        if args.download and not ffmpeg:
            raise ProbeError('ffmpeg_missing')
        print('stage=metadata mode=' + mode, flush=True)
        with YoutubeDL(options) as ydl:
            report['mgtv_cookie_count'] = sum((cookie.domain.lstrip('.') == 'mgtv.com' or cookie.domain.endswith('.mgtv.com')) and not cookie.is_expired() for cookie in ydl.cookiejar)
            ydl.add_info_extractor(ObservedMGTVIE(report, args.source_api))
            raw = ydl.extract_info(url, download=False, process=False, ie_key=ObservedMGTVIE.ie_key())
            if not raw or raw.get('_type') in ('playlist', 'multi_video'):
                raise ProbeError('not_single_video')
            report.update(title=raw.get('title'), video_id=raw.get('id'), metadata_duration=raw.get('duration'),
                          available_formats=[
                              {'id': fmt.get('format_id'), 'name': fmt.get('format_note'), 'height': fmt.get('height')}
                              for fmt in raw.get('formats', [])])
            if not raw.get('formats'):
                raise ProbeError('no_formats_returned')
            if raw.get('has_drm'):
                raise ProbeError('drm_protected')
            manifest_cache = {}
            # Current API labels can differ from the extractor's static name table.
            for fmt in raw['formats']:
                if not fmt.get('height'):
                    playlist = inspect_manifest(ydl, fmt)
                    fmt.update(height=playlist['height'], width=playlist['width'])
                    manifest_cache[fmt['format_id']] = playlist
            report['available_formats'] = [{'id': fmt.get('format_id'), 'name': fmt.get('format_note'),
                                             'height': fmt.get('height')} for fmt in raw['formats']]
            info = ydl.process_ie_result(raw, download=False)
            report['selected_format'] = info.get('format_id')
            manifest = manifest_cache.get(info['format_id']) or inspect_manifest(ydl, info)
            report['manifest'] = manifest
            expected = float(info.get('duration') or 0)
            tolerance = max(5, expected * 0.005)
            if not expected or abs(manifest['duration'] - expected) > tolerance:
                raise ProbeError('preview_or_duration_mismatch')
            if manifest['estimated_bytes'] > max_bytes:
                raise ProbeError('estimated_file_size_limit')
            if args.download:
                print(f'stage=download segments={manifest["segments"]} seconds={manifest["duration"]}', flush=True)
                ydl.process_ie_result(info, download=True)
        if args.download:
            files = [p for p in folder.glob('video.*') if p.suffix in ('.mp4', '.mkv', '.webm', '.ts')]
            if len(files) != 1 or not files[0].stat().st_size:
                raise ProbeError('media_missing')
            media = files[0]
            print('stage=full_audio_video_decode', flush=True)
            validation = validate_media(ffmpeg, media)
            report.update(file=str(media), file_bytes=media.stat().st_size, media=validation)
            if validation['full_decode_exit_code'] or validation['duration'] is None or abs(validation['duration'] - expected) > tolerance:
                raise ProbeError('media_validation_failed')
            with media.open('rb') as source:
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
                report['sha256'] = digest.hexdigest()
        report['status'] = 'download_verified' if args.download else 'full_manifest_available'
    except Exception as error:
        report.update(status='failed', exception=type(error).__name__,
                      error_category=str(error) if isinstance(error, ProbeError) else category(error))
    report['elapsed_seconds'] = round(time.monotonic() - started, 2)
    destination = folder / 'report.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print('report=' + str(destination))
    return 0 if report['status'] != 'failed' else 1


if __name__ == '__main__':
    sys.exit(main())
