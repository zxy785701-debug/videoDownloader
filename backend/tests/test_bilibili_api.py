"""Real adapter/SDK with synthetic API replies, no cookies or platform traffic."""
import copy
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from yt_dlp.cookies import YoutubeDLCookieJar
from yt_dlp.extractor.bilibili import BiliBiliIE
from yt_dlp.utils import DownloadError

from app import main, platform_adapters as adapters, subtitle_service, video_service
from app.ai_config import get_config
from app.analysis_errors import AnalysisError

URL = 'https://www.bilibili.com/video/BV1N2pc6gErK/'
DATA = {
    'bvid': 'BV1N2pc6gErK', 'aid': 123456, 'title': 'API video',
    'pages': [{'page': 1, 'cid': 11, 'duration': 126, 'part': 'First'},
              {'page': 2, 'cid': 22, 'duration': 60, 'part': 'Second'}],
}


def play_info(seconds=125.888):
    return {'timelength': seconds * 1000, 'dash': {
        'video': [{'id': 80, 'baseUrl': 'https://media.example/video.mp4',
                   'backupUrl': ['https://backup.example/video.mp4'], 'height': 1080,
                   'codecs': 'avc1.640028', 'mimeType': 'video/mp4'}],
        'audio': [{'id': 30280, 'baseUrl': 'https://media.example/audio.m4a',
                   'codecs': 'mp4a.40.2', 'mimeType': 'audio/mp4'}],
    }}


def extract_adapter(url):
    with adapters.PlatformYoutubeDL(video_service._video_options()) as client:
        return adapters.BilibiliIE(client)._real_extract(url)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv('BILIBILI_METADATA_SOURCE', 'api')
    monkeypatch.setenv('BILIBILI_USE_FIREFOX_SESSION', '0')
    monkeypatch.setattr(video_service, 'validate_public_http_url', lambda url: url)
    monkeypatch.setattr(subtitle_service, 'validate_public_http_url', lambda url: url)
    monkeypatch.setattr(adapters.BilibiliIE, '_download_webpage_handle',
                        lambda *a, **kw: pytest.fail('API mode must not fetch HTML'))
    data, calls = copy.deepcopy(DATA), []

    def metadata(self, url, *args, **kwargs):
        calls.append(('metadata', url, kwargs))
        assert url == 'https://api.bilibili.com/x/web-interface/view'
        return {'code': 0, 'data': data}

    def playback(self, bvid, cid, **kwargs):
        calls.append(('playback', bvid, cid, kwargs))
        return play_info(125.888 if cid == 11 else 60)

    monkeypatch.setattr(adapters.BilibiliIE, '_download_json', metadata)
    monkeypatch.setattr(adapters.BilibiliIE, '_download_playinfo', playback)
    return data, calls


@pytest.mark.parametrize('suffix,cid,seconds', [('', 11, 125.888), ('?p=2', 22, 60)])
def test_api_part_selection_complete_duration_and_backups(api, suffix, cid, seconds):
    with adapters.open_downloader(URL + suffix, video_service._video_options()) as client:
        info = client.extract_info(URL + suffix, download=False, process=False)
    assert info['id'].endswith('_p2' if cid == 22 else '_p1')
    assert info['duration'] == seconds
    assert info['_platform_expected_duration'] == (60 if cid == 22 else 126)
    assert info['formats'][1]['_platform_backup_urls'] == ['https://backup.example/video.mp4']
    assert api[1][1][1:3] == ('BV1N2pc6gErK', cid)
    assert api[1][1][3]['headers']['Origin'] == 'https://www.bilibili.com'


def test_api_accepts_av_identity_and_rejects_other_video(api):
    url = URL.replace('BV1N2pc6gErK', 'av123456')
    assert extract_adapter(url)['title'].startswith('API video')
    assert api[1][0][2]['query'] == {'aid': '123456'}
    api[0]['aid'] = 999999
    with pytest.raises(adapters.PlatformError) as caught:
        extract_adapter(url)
    assert caught.value.code == 'METADATA_INVALID'


@pytest.mark.parametrize('change,code', [
    ({'bvid': 'BV18YEQz4E1M'}, 'METADATA_INVALID'),
    ({'pages': []}, 'PART_INVALID'),
    ({'rights': {'is_stein_gate': 1}}, 'API_UNSUPPORTED'),
    ({'redirect_url': 'https://www.bilibili.com/bangumi/play/ep1'}, 'API_UNSUPPORTED'),
    ({'pages': [{'page': 1, 'cid': 11, 'duration': float('nan')}]}, 'METADATA_INVALID'),
])
def test_api_rejects_unverifiable_metadata_before_playback(api, change, code):
    api[0].update(change)
    with pytest.raises(adapters.PlatformError) as caught:
        extract_adapter(URL)
    assert caught.value.code == code
    assert not any(call[0] == 'playback' for call in api[1])


@pytest.mark.parametrize('suffix', ['?p=0', '?p=3', '?p=abc'])
def test_api_rejects_invalid_or_nonexistent_part(api, suffix):
    with pytest.raises(adapters.PlatformError) as caught:
        extract_adapter(URL + suffix)
    assert caught.value.code == 'PART_INVALID'
    assert not any(call[0] == 'playback' for call in api[1])


@pytest.mark.parametrize('changes', [
    {'timelength': 30000}, {'timelength': float('inf')}, {'is_preview': True},
    {'accept_description': ['试看']},
])
def test_api_rejects_preview_or_invalid_playback_duration(api, monkeypatch, changes):
    monkeypatch.setattr(adapters.BilibiliIE, '_download_playinfo', lambda *a, **kw: {**play_info(), **changes})
    with pytest.raises(adapters.PlatformError) as caught:
        extract_adapter(URL)
    assert caught.value.code == 'PREVIEW_ONLY'


@pytest.mark.parametrize('response', [{'code': -403, 'message': 'PRIVATE_SESSION'}, {}])
def test_metadata_rejection_has_safe_message_no_html_retry(api, monkeypatch, response):
    monkeypatch.setattr(adapters.BilibiliIE, '_download_json', lambda *a, **kw: response)
    with pytest.raises(adapters.PlatformError) as caught:
        extract_adapter(URL)
    assert caught.value.code == 'METADATA_REJECTED'
    assert 'PRIVATE_SESSION' not in str(caught.value)


def test_playback_failure_is_not_retried_with_html_or_other_session(api, monkeypatch):
    calls = []
    def failure(*args, **kwargs):
        calls.append(1)
        raise DownloadError('HTTP Error 403: Forbidden')
    monkeypatch.setattr(adapters.BilibiliIE, '_download_playinfo', failure)
    with pytest.raises(DownloadError):
        extract_adapter(URL)
    assert calls == [1]


def test_default_webpage_flow_keeps_existing_extractor(monkeypatch):
    calls = []
    monkeypatch.setattr(BiliBiliIE, '_real_extract', lambda self, url: calls.append(url) or {'id': 'sample', 'duration': 60})
    monkeypatch.setattr(adapters.BilibiliIE, '_extract_api', lambda *a: pytest.fail('default must retain HTML flow'))
    assert extract_adapter(URL)['duration'] == 60
    assert calls == [URL]
    monkeypatch.setenv('BILIBILI_METADATA_SOURCE', 'https://user:PRIVATE@bad.example')
    with pytest.raises(adapters.PlatformError) as caught:
        extract_adapter(URL)
    assert caught.value.code == 'CONFIG_INVALID' and 'PRIVATE' not in str(caught.value)


def test_api_parse_and_download_use_same_metadata_path(api, monkeypatch, tmp_path):
    parsed = video_service.parse_video(URL)
    assert parsed.duration == 125.888 and len(parsed.formats) == 2
    monkeypatch.setattr(video_service, 'DOWNLOAD_DIR', tmp_path)
    monkeypatch.setattr(video_service, '_ffmpeg_location', lambda: 'synthetic-ffmpeg')
    checks = []
    def transfer(self, info, download=True, **kwargs):
        assert download and info['_platform_expected_duration'] == 126
        assert self.params['format'] == '80+ba'
        (tmp_path / 'api-download' / 'complete.mp4').write_bytes(b'synthetic media')
        return info
    monkeypatch.setattr(adapters.PlatformYoutubeDL, 'process_ie_result', transfer)
    monkeypatch.setattr(adapters, 'verify_media', lambda ffmpeg, path, expected: checks.append(expected))
    video_service.create_task('api-download', 'auto')
    try:
        video_service.process_download('api-download', URL, 'video:80', 'auto')
        assert video_service.get_task('api-download')['status'] == 'ready'
        assert checks == [126]
    finally:
        video_service.TASKS.pop('api-download', None)
    assert len([call for call in api[1] if call[0] == 'playback']) == 2


@pytest.mark.parametrize('requires_login', [False, True])
def test_api_captions_use_same_adapter_and_preserve_login_requirement(api, monkeypatch, requires_login):
    calls = []
    def subtitles(self, bvid, cid, aid):
        calls.append((bvid, cid, aid))
        if requires_login:
            self.report_warning('Subtitles are only available when logged in')
            return {'danmaku': [{'ext': 'xml', 'url': 'https://comment.bilibili.com/11.xml'}]}
        return {'zh': [{'ext': 'srt', 'data': '1\n00:00:00,000 --> 00:00:03,000\nAPI 字幕'}]}
    monkeypatch.setattr(adapters.BilibiliIE, '_get_subtitles', subtitles)
    config = replace(get_config(), firefox_subtitle_session=False)
    if requires_login:
        with pytest.raises(AnalysisError) as caught:
            subtitle_service.extract_transcript(URL, config=config)
        assert caught.value.code == 'CAPTIONS_ACCESS_REQUIRED'
    else:
        assert subtitle_service.extract_transcript(URL, config=config)['cues'][0]['text'] == 'API 字幕'
    assert calls == [('BV1N2pc6gErK', 11, 123456)]


def test_api_mode_keeps_available_local_firefox_session(api, monkeypatch):
    import yt_dlp.cookies
    from http.cookiejar import Cookie
    jar = YoutubeDLCookieJar()
    jar.set_cookie(Cookie(0, 'SESSDATA', 'SYNTHETIC_SESSION', None, False, '.bilibili.com', True, True,
                         '/', True, False, None, True, None, None, {}))
    monkeypatch.setenv('BILIBILI_USE_FIREFOX_SESSION', '1')
    monkeypatch.setattr(yt_dlp.cookies, 'extract_cookies_from_browser', lambda *a, **kw: jar)
    monkeypatch.setattr(adapters, '_session_usable', lambda *a: True)
    with adapters.open_downloader(URL, video_service._video_options()) as client:
        assert client.params['cookiesfrombrowser'][0] == 'firefox'
        assert 'SESSDATA' in client.get_info_extractor('BiliBili')._get_cookies('https://api.bilibili.com')
        assert client.extract_info(URL, download=False, process=False)['duration'] == 125.888


@pytest.mark.parametrize('logged_in', [False, True])
def test_api_uses_sdk_wbi_signing_and_preserves_authenticated_playback(monkeypatch, logged_in):
    from http.cookiejar import Cookie
    monkeypatch.setenv('BILIBILI_METADATA_SOURCE', 'api')
    monkeypatch.setattr(BiliBiliIE, '_wbi_key_cache', {})
    calls = []
    def reply(self, url, *args, **kwargs):
        calls.append((url, kwargs.get('query', {})))
        if url.endswith('/view'):
            return {'code': 0, 'data': DATA}
        if url.endswith('/nav'):
            return {'code': -101, 'data': {'wbi_img': {
                'img_url': 'https://i.example/' + 'a' * 32 + '.png',
                'sub_url': 'https://i.example/' + 'b' * 32 + '.png'}}}
        assert url.endswith('/x/player/wbi/playurl')
        return {'code': 0, 'data': play_info()}
    monkeypatch.setattr(adapters.BilibiliIE, '_download_json', reply)
    with adapters.PlatformYoutubeDL(video_service._video_options()) as client:
        if logged_in:
            client.cookiejar.set_cookie(Cookie(0, 'SESSDATA', 'SYNTHETIC', None, False, '.bilibili.com', True, True,
                                              '/', True, False, None, True, None, None, {}))
        assert adapters.BilibiliIE(client)._real_extract(URL)['duration'] == 125.888
    signed = calls[-1][1]
    assert signed['bvid'] == DATA['bvid'] and signed['cid'] == '11'
    assert len(signed['w_rid']) == 32 and signed['wts']
    assert ('try_look' not in signed) if logged_in else signed['try_look'] == '1'


@pytest.mark.parametrize('play,code', [
    ({'timelength': 126000}, 'NO_FORMATS'),
    ({'timelength': 126000, 'durl': [
        {'url': 'https://media.example/one.flv', 'length': 63000, 'size': 100},
        {'url': 'https://media.example/two.flv', 'length': 63000, 'size': 100},
    ]}, 'API_UNSUPPORTED'),
])
def test_api_does_not_claim_success_for_absent_or_unsupported_formats(api, monkeypatch, play, code):
    monkeypatch.setattr(adapters.BilibiliIE, '_download_playinfo', lambda *a, **kw: play)
    with pytest.raises(adapters.PlatformError) as caught:
        extract_adapter(URL)
    assert caught.value.code == code


def test_api_file_delivery_still_runs_real_media_validation(api, monkeypatch, tmp_path):
    ffmpeg = video_service._ffmpeg_location()
    fixture = tmp_path / 'fixture.mp4'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=10',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=22050',
                    '-t', '1', '-c:v', 'libx264', '-c:a', 'aac', str(fixture)], check=True)
    media = fixture.read_bytes()
    api[0]['pages'][0]['duration'] = 1
    monkeypatch.setattr(adapters.BilibiliIE, '_download_playinfo', lambda *a, **kw: play_info(1))
    monkeypatch.setattr(video_service, 'DOWNLOAD_DIR', tmp_path / 'downloads')
    def transfer(self, info, download=True, **kwargs):
        assert download and info['_platform_expected_duration'] == 1
        (Path(self.params['outtmpl']['default']).parent / 'complete.mp4').write_bytes(media)
        return info
    monkeypatch.setattr(adapters.PlatformYoutubeDL, 'process_ie_result', transfer)
    with TestClient(main.app) as client:
        created = client.post('/api/v1/downloads', json={'url': URL, 'format_id': 'best', 'delivery_mode': 'auto'})
        assert created.status_code == 202
        payload = created.json()
        try:
            state = client.get(payload['status_url']).json()
            assert state['status'] == 'ready'
            assert client.get(payload['download_url']).content == media
            ranged = client.get(payload['download_url'], headers={'Range': 'bytes=0-15'})
            assert ranged.status_code == 206 and ranged.content == media[:16]
        finally:
            video_service.TASKS.pop(payload['task_id'], None)
