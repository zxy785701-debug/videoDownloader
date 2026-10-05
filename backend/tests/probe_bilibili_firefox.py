"""Standalone authorized Bilibili download probe; no production settings changed.

From the project root:
backend/.venv/Scripts/python.exe backend/tests/probe_bilibili_firefox.py --url "https://www.bilibili.com/video/BV18YEQz4E1M/?p=4" --download
Cookie values and signed media URLs are never printed or saved.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.extractor.bilibili import BiliBiliIE
from yt_dlp.networking import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.video_service import _ffmpeg_location, error_category


class ProbeError(Exception):
    pass


def safe_category(error):
    message = str(error).lower()
    status = re.search(r'(?:http error|http status|status code)[: ]+(\d{3})', message)
    if status:
        return 'upstream_http_' + status[1]
    os_error = re.search(r'\[(?:winerror|errno) (\d+)\]', message)
    if os_error:
        return 'os_error_' + os_error[1]
    tls_error = re.search(r'\[ssl: ([a-z_]+)\]', message)
    if tls_error:
        return 'tls_' + tls_error[1]
    for category, markers in (
        ('file_size_limit', ('max-filesize', 'max_filesize')),
        ('connection_closed', ('remote end closed', 'connection reset', 'incomplete read', 'incompleteread')),
        ('empty_media', ('downloaded file is empty',)),
        ('filesystem_access', ('permission denied', 'access is denied')),
        ('merge_failed', ('postprocessing', 'post-processing', 'ffmpeg exited')),
        ('ffmpeg_missing', ('ffmpeg is not installed',)),
        ('dns_failed', ('getaddrinfo failed',)),
    ):
        if any(marker in message for marker in markers):
            return category
    return error_category(error)


def diagnostic_words(error):
    # An allowlist gives a useful failure signature without emitting raw errors.
    allowed = set('error unable download video data file audio requested merging multiple formats '
                  'ffmpeg not installed failed network connection remote closed reset aborted '
                  'server proxy tunnel timeout timed out ssl tls certificate verify invalid '
                  'url protocol unsupported permission denied access http getaddrinfo name '
                  'resolution os winerror errno process postprocessing empty size exceeded '
                  'read expected response status code bytes downloaderror extractorerror'.split())
    return ' '.join(word.lower() for word in re.findall(r'[A-Za-z]+', str(error)) if word.lower() in allowed)


class SafeLogger:
    def __init__(self, report):
        self.report = report

    def debug(self, message):
        pass

    def warning(self, message):
        category = 'preview_only' if 'preview' in str(message).lower() else safe_category(message)
        self.report['events'].append({'warning': category})

    def error(self, message):
        self.report['events'].append({'error': safe_category(message), 'diagnostic_words': diagnostic_words(message)})


class ProbeBiliIE(BiliBiliIE):
    def __init__(self, report, backup_index):
        super().__init__()
        self.report = report
        self.backup_index = backup_index

    def extract_formats(self, play_info):
        formats = super().extract_formats(play_info)
        dash = (play_info or {}).get('dash') or {}
        resources = (dash.get('video') or []) + (dash.get('audio') or []) + ((play_info or {}).get('durl') or [])
        backups = {entry.get('baseUrl') or entry.get('base_url') or entry.get('url'):
                   entry.get('backupUrl') or entry.get('backup_url') or [] for entry in resources}
        self.report['backup_media_hosts'] = sorted({urlsplit(url).hostname for urls in backups.values() for url in urls})
        if not self.backup_index:
            return formats
        # Use only backup addresses returned by the same authorized platform response.
        return [{**fmt, 'url': backups[fmt['url']][self.backup_index - 1]} for fmt in formats
                if len(backups.get(fmt.get('url'), [])) >= self.backup_index and not fmt.get('fragments')]


def api(ydl, path, query=''):
    request = Request('https://api.bilibili.com' + path + query,
                      headers={'Referer': 'https://www.bilibili.com/'})
    with ydl.urlopen(request) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise ProbeError('metadata_response_too_large')
    data = json.loads(body)
    if data.get('code') != 0:
        raise ProbeError('metadata_api_rejected')
    return data['data']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--profile', help='Optional Firefox profile name or path')
    parser.add_argument('--anonymous', action='store_true', help='Control probe without cookies')
    parser.add_argument('--download', action='store_true', help='Download and fully decode the selected part')
    parser.add_argument('--direct', action='store_true', help='Use a direct network connection, ignoring system proxies')
    parser.add_argument('--backup-index', type=int, choices=(0, 1, 2), default=0,
                        help='0: primary CDN; 1/2: platform-provided backup CDN')
    parser.add_argument('--height', type=int, choices=(360, 480, 720, 1080), default=480)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})/?', parsed.path)
    if parsed.scheme != 'https' or parsed.hostname != 'www.bilibili.com' or not match:
        parser.error('Use a direct https://www.bilibili.com/video/BV... link')
    try:
        part = int(parse_qs(parsed.query).get('p', ['1'])[0])
        if part < 1:
            raise ValueError
    except ValueError:
        parser.error('p must be a positive integer')
    url = f'https://www.bilibili.com/video/{match[1]}/?p={part}'
    mode = 'anonymous' if args.anonymous else 'firefox'
    folder = Path(__file__).resolve().parents[2] / '.local' / 'bilibili-firefox-probe'
    folder = folder / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + mode)
    folder.mkdir(parents=True, exist_ok=False)
    report = {'url': url, 'part': part, 'mode': mode, 'download_requested': args.download,
              'height_limit': args.height, 'direct_connection': args.direct,
              'backup_index': args.backup_index, 'events': [], 'status': 'started'}
    started = time.monotonic()
    options = {
        'quiet': True, 'noprogress': True, 'logger': SafeLogger(report),
        'noplaylist': True, 'cachedir': False, 'cookiefile': None,
        'cookiesfrombrowser': None if args.anonymous else ('firefox', args.profile, None, None),
        'socket_timeout': 25, 'retries': 1, 'fragment_retries': 1, 'extractor_retries': 0,
        'format': f'bv*[height<={args.height}]+ba/b[height<={args.height}]',
        'merge_output_format': 'mp4', 'outtmpl': str(folder / 'video.%(ext)s'),
        'max_filesize': 300 * 1024 * 1024, 'overwrites': False,
    }
    if args.direct:
        options['proxy'] = ''
    try:
        ffmpeg = _ffmpeg_location()
        if ffmpeg:
            options['ffmpeg_location'] = ffmpeg
        if args.download and not ffmpeg:
            raise ProbeError('ffmpeg_missing')
        print(f'stage=metadata mode={mode} part={part}', flush=True)
        with YoutubeDL(options) as ydl:
            ydl.add_info_extractor(ProbeBiliIE(report, args.backup_index))
            # Only test login state; do not retain account identifiers or cookie values.
            report['logged_in'] = api(ydl, '/x/web-interface/nav').get('isLogin') is True if not args.anonymous else False
            metadata = api(ydl, '/x/web-interface/view', '?bvid=' + match[1])
            pages = metadata.get('pages') or []
            selected = next((page for page in pages if page.get('page') == part), None)
            if not selected:
                raise ProbeError('requested_part_not_found')
            expected = float(selected['duration'])
            report.update(title=metadata.get('title'), part_title=selected.get('part'),
                          cid=selected.get('cid'), expected_duration=expected,
                          supporter_only=bool(metadata.get('is_upower_exclusive')))
            info = ydl.extract_info(url, download=False, ie_key=ProbeBiliIE.ie_key())
            if not info or info.get('_type') in ('playlist', 'multi_video'):
                raise ProbeError('not_a_single_video_part')
            actual = float(info.get('duration') or 0)
            report.update(extracted_id=info.get('id'), extracted_duration=actual,
                          video_heights=sorted({f['height'] for f in info.get('formats', []) if f.get('height')}),
                          selected_format=info.get('format_id'),
                          media_hosts=sorted({urlsplit(f['url']).hostname for f in info.get('requested_formats', [info]) if f.get('url')}))
            if part > 1 and info.get('id') != f'{match[1]}_p{part}':
                raise ProbeError('wrong_video_part')
            tolerance = max(3, expected * 0.01)
            if any(event.get('warning') == 'preview_only' for event in report['events']) or abs(actual - expected) > tolerance:
                raise ProbeError('preview_or_duration_mismatch')
            if args.download:
                print(f'stage=download expected_seconds={expected} format={info.get("format_id")}', flush=True)
                ydl.process_ie_result(info, download=True)
        if args.download:
            files = [p for p in folder.glob('video.*') if p.suffix in ('.mp4', '.mkv', '.webm', '.flv')]
            if len(files) != 1 or not files[0].stat().st_size:
                raise ProbeError('merged_file_missing')
            media = files[0]
            print('stage=full_audio_video_decode', flush=True)
            decoded = subprocess.run([ffmpeg, '-hide_banner', '-xerror', '-i', str(media),
                                      '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                                     capture_output=True, timeout=600, encoding='utf-8', errors='replace')
            duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', decoded.stderr)
            seconds = sum(float(value) * scale for value, scale in zip(duration.groups(), (3600, 60, 1))) if duration else None
            report.update(file=str(media), file_bytes=media.stat().st_size, media_duration=seconds,
                          full_decode_exit_code=decoded.returncode)
            if decoded.returncode != 0 or seconds is None or abs(seconds - expected) > tolerance:
                raise ProbeError('media_validation_failed')
        report['status'] = 'download_verified' if args.download else 'full_metadata_available'
    except Exception as error:
        report.update(status='failed', error_category=str(error) if isinstance(error, ProbeError) else safe_category(error),
                      exception=type(error).__name__, diagnostic_words=diagnostic_words(error))
    report['elapsed_seconds'] = round(time.monotonic() - started, 2)
    destination = folder / 'report.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print('report=' + str(destination))
    return 0 if report['status'] != 'failed' else 1


if __name__ == '__main__':
    sys.exit(main())
