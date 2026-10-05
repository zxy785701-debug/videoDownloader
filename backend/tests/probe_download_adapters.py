"""Real HTTP acceptance of the integrated Bilibili/MGTV backend adapters.

Run against a separate local test backend. Selects the returned 480p option;
validates task completion, attachment/Range delivery, full decoding and SHA-256.
No browser credentials or signed upstream URLs are recorded.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.video_service import _ffmpeg_location

CASES = [
    ('bilibili-paid-p4', 'https://www.bilibili.com/video/BV18YEQz4E1M/?p=4', 2503),
    ('mgtv-movie', 'https://www.mgtv.com/b/321423/5546935.html', 7503),
    ('mgtv-series', 'https://www.mgtv.com/b/855808/24564644.html', 1822),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8182')
    parser.add_argument('--case', choices=[case[0] for case in CASES], action='append')
    args = parser.parse_args()
    base = urlsplit(args.base_url)
    if base.scheme != 'http' or base.hostname != '127.0.0.1' or base.username or base.password:
        parser.error('Use a local http://127.0.0.1:<port> backend')
    folder = Path(__file__).resolve().parents[2] / '.local' / 'download-adapter-acceptance' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    report = {'base_url': args.base_url, 'cases': [], 'status': 'started'}
    ffmpeg = _ffmpeg_location()
    with httpx.Client(base_url=args.base_url, timeout=60, trust_env=False) as client:
        for name, url, expected in CASES:
            if args.case and name not in args.case:
                continue
            item = {'case': name, 'url': url, 'expected_duration': expected}
            report['cases'].append(item)
            started = time.monotonic()
            try:
                print('stage=parse case=' + name, flush=True)
                response = client.post('/api/v1/parse', json={'url': url})
                response.raise_for_status()
                metadata = response.json()
                item.update(title=metadata['title'], duration=metadata['duration'], formats=metadata['formats'])
                selected = next(fmt for fmt in metadata['formats'] if fmt.get('resolution') == '480p')
                item['selected_format'] = selected['format_id']
                response = client.post('/api/v1/downloads', json={'url': url, 'format_id': selected['format_id'], 'delivery_mode': 'auto'})
                response.raise_for_status()
                created = response.json()
                item['task_id'] = created['task_id']
                print('stage=download case=' + name, flush=True)
                deadline = time.monotonic() + 900
                last_update = 0
                while time.monotonic() < deadline:
                    response = client.get(created['status_url'])
                    response.raise_for_status()
                    state = response.json()
                    if state['status'] == 'ready':
                        break
                    if state['status'] == 'failed':
                        item['backend_error'] = state.get('error')
                        raise RuntimeError('backend_task_failed')
                    if time.monotonic() - last_update > 30:
                        print('case=' + name + ' progress=' + str(state.get('progress')), flush=True)
                        last_update = time.monotonic()
                    time.sleep(2)
                else:
                    raise RuntimeError('task_timeout')
                if state['delivery_mode'] != 'server':
                    raise RuntimeError('expected_server_delivery')
                response = client.get(created['download_url'], headers={'Range': 'bytes=0-31'})
                if response.status_code != 206 or len(response.content) != 32:
                    raise RuntimeError('range_delivery_failed')
                item['range_status'] = response.status_code
                media = folder / (name + '.mp4')
                digest = hashlib.sha256()
                with client.stream('GET', created['download_url']) as response:
                    response.raise_for_status()
                    if 'attachment' not in response.headers.get('content-disposition', ''):
                        raise RuntimeError('attachment_delivery_failed')
                    expected_bytes = int(response.headers['content-length'])
                    with media.open('wb') as output:
                        for chunk in response.iter_bytes():
                            output.write(chunk)
                            digest.update(chunk)
                if media.stat().st_size != expected_bytes:
                    raise RuntimeError('file_size_mismatch')
                print('stage=full_decode case=' + name, flush=True)
                decoded = subprocess.run([ffmpeg, '-hide_banner', '-xerror', '-i', str(media),
                                          '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                                         capture_output=True, timeout=900, encoding='utf-8', errors='replace')
                duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', decoded.stderr)
                video = re.search(r'Video: ([^, ]+)[^\n]*?(\d{2,5})x(\d{2,5})(?:[ ,\[])', decoded.stderr)
                audio = re.search(r'Audio: ([^, ]+)', decoded.stderr)
                actual = sum(float(value) * scale for value, scale in zip(duration.groups(), (3600, 60, 1))) if duration else None
                item.update(file=str(media), file_bytes=media.stat().st_size, sha256=digest.hexdigest(),
                            full_decode_exit_code=decoded.returncode, actual_duration=actual,
                            width=int(video[2]) if video else None, height=int(video[3]) if video else None,
                            video_codec=video[1] if video else None, audio_codec=audio[1] if audio else None)
                if decoded.returncode or actual is None or abs(actual - expected) > max(3, expected * 0.005):
                    raise RuntimeError('full_media_validation_failed')
                item['status'] = 'passed'
            except Exception as error:
                # Deliberately do not serialize request/exception objects.
                item.update(status='failed', exception=type(error).__name__)
            item['elapsed_seconds'] = round(time.monotonic() - started, 2)
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print('case=' + name + ' status=' + item['status'], flush=True)
    report['status'] = 'passed' if report['cases'] and all(item['status'] == 'passed' for item in report['cases']) else 'failed'
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('status=' + report['status'] + ' report=' + str(folder / 'report.json'))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
