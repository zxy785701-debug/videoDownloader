"""Isolated deterministic unified-workspace browser acceptance fixture."""
import json
import threading
import time

import httpx
from fastapi import Body

from tests import learning_preview as preview
from app import subtitle_service, video_service
from app.analysis_errors import AnalysisError
from app.analysis_jobs import get_engine
from app.deepseek_client import DeepSeekClient
from app.schemas import ParseResponse, VideoFormat

app = preview.app
calls = {'summary': 0, 'chat': 0, 'captions': [], 'downloads': []}
caption_release = threading.Event()
download_release = threading.Event()


def extract(url, language='auto', config=None, on_metadata=None):
    calls['captions'].append({'url': url, 'language': language})
    if 'slowcaption' in url:
        caption_release.wait(30)
    result = preview.fake_transcript(url, language, config, on_metadata)
    result['title'] = '【模拟验收】同屏视频 ' + url.split('=')[-1].split('/')[-1]
    result['transcript_hash'] += url
    return result


def parse(url):
    if 'parsefails' in url:
        raise AnalysisError('PARSE_FAILED', '【模拟验收】解析失败')
    if 'lateparse' in url:
        time.sleep(3)
    return ParseResponse(title='【模拟验收】视频信息 ' + url.split('=')[-1].split('/')[-1],
        extractor='Mgtv' if 'mgtv.com' in url else 'YouTube', duration=3000,
        formats=[VideoFormat(format_id='best', label='最佳画质', ext='mp4'),
                 VideoFormat(format_id='video:137', label='1080p · 自动合并音频', ext='mp4', filesize=10485760)])


def model(request):
    payload = json.loads(request.content)
    user = json.loads(payload['messages'][1]['content'])
    calls['chat' if 'question' in user else 'summary'] += 1
    if 'badsummary' in json.dumps(user):
        return httpx.Response(401, json={'error': {'message': '模拟模型拒绝'}})
    return preview.model_response(request)


def download(task_id, url, format_id, delivery_mode):
    calls['downloads'].append({'url': url, 'format_id': format_id, 'delivery_mode': delivery_mode})
    download_release.wait(30)
    preview.fake_download(task_id, url, format_id, delivery_mode)


@app.get('/_test/unified/stats')
def stats():
    return calls


@app.post('/_test/unified/release')
def release(kind: str = Body(embed=True)):
    (caption_release if kind == 'caption' else download_release).set()
    return {'released': True}


subtitle_service.extract_transcript = extract
video_service.parse_video = parse
video_service.process_download = download
get_engine().client_factory = lambda config, check, usage: DeepSeekClient(config, check, usage, httpx.MockTransport(model))
test_routes = [route for route in app.router.routes if getattr(route, 'path', '').startswith('/_test/')]
app.router.routes[:] = test_routes + [route for route in app.router.routes if route not in test_routes]
