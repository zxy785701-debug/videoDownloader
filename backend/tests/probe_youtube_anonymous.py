"""Manual network probe; never reads account cookies or saves upstream URLs.

Run from backend: .venv/Scripts/python.exe tests/probe_youtube_anonymous.py
This is intentionally not collected by pytest.
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.video_service import _video_options, _ffmpeg_location, error_category
from yt_dlp import YoutubeDL

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='https://www.youtube.com/watch?v=aqz-KE-bpKQ')
parser.add_argument('--clients', default='mweb')
parser.add_argument('--provider', default='http://127.0.0.1:4416')
parser.add_argument('--proxy', default='http://127.0.0.1:7890')
parser.add_argument('--download', action='store_true')
parser.add_argument('--supply-token', action='store_true')
parser.add_argument('--output', required=True)
args = parser.parse_args()
os.environ.pop('YTDLP_COOKIES_FROM_BROWSER', None)
os.environ.pop('YTDLP_POT_BASE_URL', None)
os.environ.pop('YTDLP_PROXY', None)
report = {'url': args.url, 'clients': args.clients, 'account_cookies': False, 'events': []}


class EvidenceLogger:
    def debug(self, message):
        # Only store known diagnostic lines; no raw config, token or media URLs.
        if 'playability status:' in message:
            status = message.split('playability status:', 1)[1].strip()
            if status in {'OK', 'LOGIN_REQUIRED', 'ERROR', 'UNPLAYABLE'}:
                report['events'].append({'playability': status})
        if 'PO Token Providers:' in message:
            report['provider_loaded'] = 'bgutil:http' in message
        if 'Generating a ' in message and 'PO Token' in message:
            report['events'].append({'token_generation_requested': True})

    def warning(self, message):
        report['events'].append({'warning': error_category(message)})

    def error(self, message):
        report['events'].append({'error': error_category(message)})


destination = Path(args.output).resolve()
destination.parent.mkdir(parents=True, exist_ok=True)
options = _video_options(source_url=args.url)
options.update({
    'logger': EvidenceLogger(), 'verbose': True, 'proxy': args.proxy,
    'cookiefile': None, 'cookiesfrombrowser': None, 'cachedir': False,
    'socket_timeout': 15, 'retries': 0, 'extractor_retries': 0,
    'extractor_args': {
        'youtube': {'player_client': args.clients.split(',')},
        'youtubepot-bgutilhttp': {'base_url': [args.provider]},
    },
    'format': 'bv*[height<=360]+ba/b[height<=360]',
    'ffmpeg_location': _ffmpeg_location(),
    'outtmpl': str(destination.parent / '%(id)s.%(ext)s'),
    'max_filesize': 50 * 1024 * 1024,
})
try:
    if args.supply_token:
        from urllib.parse import parse_qs, urlsplit
        video_id = parse_qs(urlsplit(args.url).query)['v'][0]
        request = urllib.request.Request(
            args.provider + '/get_pot',
            data=json.dumps({'content_binding': video_id, 'proxy': args.proxy}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=45) as response:
            token = json.load(response)['poToken']
        report['token_generated_and_supplied'] = bool(token)
        options['extractor_args']['youtube']['po_token'] = ['mweb.gvs+' + token]
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(args.url, download=args.download)
    report.update(status='ok', title=info.get('title'), formats=len(info.get('formats', [])), download_requested=args.download)
except Exception as error:
    report.update(status='failed', error_category=error_category(error), exception=type(error).__name__)
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True, indent=2))
sys.exit(0 if report['status'] == 'ok' else 1)
