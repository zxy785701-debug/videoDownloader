import base64
import logging
import subprocess
from contextlib import contextmanager
from http.cookiejar import Cookie
from pathlib import Path
from types import SimpleNamespace

import pytest
import yt_dlp.cookies as browser_cookies
from fastapi.testclient import TestClient
from yt_dlp.cookies import CookieLoadError, YoutubeDLCookieJar
from yt_dlp.extractor.bilibili import BiliBiliIE
from yt_dlp.extractor.mgtv import MGTVIE
from yt_dlp.utils import DownloadError

from app import main, platform_adapters as adapters, video_service as service

BILI = 'https://www.bilibili.com/video/BV18YEQz4E1M/?p=4'
MGTV = 'https://www.mgtv.com/b/321423/5546935.html'
MANIFEST = '#EXTM3U\n#EXT-MGTV-VIDEO-WIDTH:832\n#EXT-MGTV-VIDEO-HEIGHT:348\n#EXTINF:10,\na.ts\n#EXTINF:10,\nb.ts\n#EXT-X-ENDLIST\n'


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    for platform in ('BILIBILI', 'MGTV'):
        for suffix in ('USE_FIREFOX_SESSION', 'FIREFOX_PROFILE'):
            monkeypatch.delenv(platform + '_' + suffix, raising=False)


@pytest.mark.parametrize('url,expected', [
    (BILI, 'bilibili'), (MGTV, 'mgtv'), ('https://w.mgtv.com/b/1/2.html', 'mgtv'),
    ('https://www.bilibili.com.example.org/video/BV18YEQz4E1M/', None),
    ('https://mgtv.com.example.org/b/1/2.html', None),
    ('https://www.youtube.com/watch?v=test', None), ('https://b23.tv/abc', None),
])
def test_platform_routing(url, expected):
    assert adapters.platform_for(url) == expected


def test_adapters_replace_existing_extractor_keys():
    # add_info_extractor must replace, rather than sit behind, the built-in entry.
    with adapters.PlatformYoutubeDL({'quiet': True}) as client:
        client.add_info_extractor(adapters.BilibiliIE())
        client.add_info_extractor(adapters.MangoTVIE())
        assert isinstance(client.get_info_extractor(BiliBiliIE.ie_key()), adapters.BilibiliIE)
        assert isinstance(client.get_info_extractor(MGTVIE.ie_key()), adapters.MangoTVIE)


@pytest.mark.parametrize('platform,url', [('BILIBILI', BILI), ('MGTV', MGTV)])
@pytest.mark.parametrize('session', [True, False, 'unreadable'])
def test_session_priority_and_anonymous_fallback(monkeypatch, platform, url, session):
    calls = []

    class Client:
        def __init__(self, options):
            self.options = options
            self.closed = False
            calls.append(self)

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def add_info_extractor(self, extractor):
            self.extractor = extractor

    def usable(*args):
        if session == 'unreadable':
            raise CookieLoadError('do not expose profile path')
        return session

    monkeypatch.setattr(adapters, 'PlatformYoutubeDL', Client)
    monkeypatch.setattr(adapters, '_session_usable', usable)
    monkeypatch.setenv(platform + '_FIREFOX_PROFILE', 'profile-for-test')
    with adapters.open_downloader(url, {'cookiesfrombrowser': ('edge', None, None, None)}) as client:
        assert client.options.get('cookiesfrombrowser') == (('firefox', 'profile-for-test', None, None) if session is True else None)
        assert client.options['cookiefile'] is None
        assert client.options['skip_unavailable_fragments'] is False
        if session is not True:
            assert calls[0].closed
    assert all(client.closed for client in calls)
    assert len(calls) == (1 if session is True else 2)


def test_session_check_failure_does_not_downgrade_to_anonymous(monkeypatch):
    class Client:
        def __init__(self, options):
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(adapters, 'PlatformYoutubeDL', Client)
    monkeypatch.setattr(adapters, '_session_usable', lambda *args: (_ for _ in ()).throw(adapters.PlatformError('SESSION_CHECK_FAILED', 'network failed')))
    with pytest.raises(adapters.PlatformError, match='network failed'):
        with adapters.open_downloader(BILI, {}):
            pytest.fail('must not enter after a login-check network failure')


def test_cookie_load_failure_during_constructor_also_falls_back(monkeypatch):
    real = adapters.PlatformYoutubeDL

    def client(options):
        if options.get('cookiesfrombrowser'):
            raise CookieLoadError('cookie path must stay private')
        return real(options)

    monkeypatch.setattr(adapters, 'PlatformYoutubeDL', client)
    with adapters.open_downloader(BILI, {'quiet': True}) as anonymous:
        assert 'cookiesfrombrowser' not in anonymous.params


@pytest.mark.parametrize('url', [BILI, MGTV])
@pytest.mark.parametrize('failure', [FileNotFoundError, PermissionError])
def test_real_ytdlp_wrapped_cookie_load_error_falls_back(monkeypatch, caplog, url, failure):
    # Real load_cookies -> CookieLoadError -> YoutubeDL.report_error -> DownloadError.
    # No access to the developer's actual browser or the network.
    def unavailable(*args, **kwargs):
        raise failure('PRIVATE_PROFILE Cookie=PRIVATE_SESSION')
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', unavailable)
    with caplog.at_level(logging.INFO), adapters.open_downloader(url, service._video_options()) as client:
        assert 'cookiesfrombrowser' not in client.params
        assert client.params['cookiefile'] is None
        assert not list(client.cookiejar)
    assert 'anonymous' in caplog.text
    assert 'PRIVATE_PROFILE' not in caplog.text and 'PRIVATE_SESSION' not in caplog.text


@pytest.mark.parametrize('platform,url', [('bilibili', BILI), ('mgtv', MGTV)])
def test_real_available_firefox_session_remains_selected(monkeypatch, platform, url):
    jar = YoutubeDLCookieJar()
    domain = '.bilibili.com' if platform == 'bilibili' else '.mgtv.com'
    jar.set_cookie(Cookie(0, 'SESSDATA', 'SYNTHETIC_SESSION', None, False, domain, True, True,
                         '/', True, False, None, True, None, None, {}))
    reads = []
    def browser(name, profile, *args, **kwargs):
        reads.append(name)
        return jar
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', browser)
    monkeypatch.setattr(adapters, 'read_json', lambda *a, **kw: {'code': 0, 'data': {'isLogin': True}})
    with adapters.open_downloader(url, service._video_options()) as client:
        assert client.params['cookiesfrombrowser'][0] == 'firefox'
        assert any(cookie.value == 'SYNTHETIC_SESSION' for cookie in client.cookiejar)
        assert client.params['cookiefile'] is None
    assert reads == ['firefox']


@pytest.mark.parametrize('error', ['Permission denied: ssl-file', 'No space left on disk: tls-file'])
def test_disk_errors_do_not_trigger_cdn_fallback(error):
    assert not adapters._retryable_transfer(DownloadError(error))


@pytest.mark.parametrize('prefix,url', [('BILIBILI', BILI), ('MGTV', MGTV)])
def test_disabling_session_does_not_read_browser(monkeypatch, prefix, url):
    monkeypatch.setenv(prefix + '_USE_FIREFOX_SESSION', '0')
    monkeypatch.setattr(adapters, '_session_usable', lambda *args: pytest.fail('must not read browser'))
    with adapters.open_downloader(url, {'quiet': True}) as client:
        assert 'cookiesfrombrowser' not in client.params
        assert client.params['cookiefile'] is None


def test_missing_selected_quality_is_not_silently_changed(monkeypatch, tmp_path):
    options = []

    @contextmanager
    def downloader(url, settings):
        options.append(settings)

        class Client:
            def extract_info(self, *args, **kwargs):
                return {'id': 'test', 'duration': 120, 'formats': []}

            def process_ie_result(self, *args, **kwargs):
                raise DownloadError('Requested format is not available')

        yield Client()

    monkeypatch.setattr(service, 'validate_public_http_url', lambda value: value)
    monkeypatch.setattr(service, 'DOWNLOAD_DIR', tmp_path)
    monkeypatch.setattr(adapters, 'open_downloader', downloader)
    service.create_task('missing-quality', 'auto')
    try:
        service.process_download('missing-quality', BILI, 'video:30080', 'auto')
        assert options[0]['format'] == '30080+ba'
        assert service.get_task('missing-quality')['status'] == 'failed'
    finally:
        service.TASKS.pop('missing-quality', None)


def test_session_network_error_has_safe_message(monkeypatch):
    monkeypatch.setattr(adapters, '_valid_cookies', lambda *args: True)
    monkeypatch.setattr(adapters, 'read_json', lambda *args: (_ for _ in ()).throw(RuntimeError('https://api.test/?token=SECRET cookie=PASSWORD')))
    with pytest.raises(adapters.PlatformError) as caught:
        adapters._session_usable(None, 'bilibili')
    assert caught.value.code == 'SESSION_CHECK_FAILED'
    assert 'SECRET' not in str(caught.value)
    assert 'PASSWORD' not in str(caught.value)


@pytest.mark.parametrize('logged_in,expected', [(True, True), (False, False)])
def test_bilibili_login_is_verified_with_platform(monkeypatch, logged_in, expected):
    monkeypatch.setattr(adapters, '_valid_cookies', lambda *args: True)
    monkeypatch.setattr(adapters, 'read_json', lambda *args: {'code': 0 if logged_in else -101, 'data': {'isLogin': logged_in}})
    assert adapters._session_usable(None, 'bilibili') is expected


def test_unrelated_cookie_does_not_enable_session():
    cookie = Cookie(0, 'SESSDATA', 'NEVER_PRINT', None, False, '.example.org', True, True, '/', True, False, None, True, None, None, {})
    assert not adapters._valid_cookies(SimpleNamespace(cookiejar=[cookie]), 'bilibili.com')


def test_bilibili_backups_keep_format_identity_and_primary(monkeypatch):
    video = {'baseUrl': 'https://primary/v', 'backupUrl': ['https://backup/v'], 'id': 80}
    audio = {'base_url': 'https://primary/a', 'backup_url': ['https://backup/a'], 'id': 30280}
    monkeypatch.setattr(BiliBiliIE, 'extract_formats', lambda *args: [
        {'url': video['baseUrl'], 'format_id': 'v80'}, {'url': audio['base_url'], 'format_id': 'a30280'},
        {'url': 'https://primary/legacy', 'format_id': 'legacy', 'fragments': [{'url': 'https://primary/legacy'}]},
    ])
    formats = adapters.BilibiliIE().extract_formats({'dash': {'video': [video], 'audio': [audio]}})
    assert [fmt['format_id'] for fmt in formats] == ['v80', 'a30280', 'legacy']
    assert formats[0]['url'] == video['baseUrl']
    assert formats[0]['_platform_backup_urls'] == video['backupUrl']
    assert formats[1]['_platform_backup_urls'] == audio['backup_url']
    assert '_platform_backup_urls' not in formats[2]


def test_network_failure_tries_same_format_backup_without_leaking(caplog, monkeypatch):
    calls = []

    def download(self, name, info, **kwargs):
        calls.append((name, info['url'], info['format_id']))
        if len(calls) == 1:
            raise DownloadError('SSL failed https://primary/v?token=SECRET')
        return True, True

    monkeypatch.setattr(adapters.YoutubeDL, 'dl', download)
    with adapters.PlatformYoutubeDL({'quiet': True}) as ydl, caplog.at_level(logging.INFO):
        assert ydl.dl('same-file.part', {'url': 'https://primary/v?token=SECRET', 'format_id': '1080p', '_platform_backup_urls': ['https://backup/v?token=PASSWORD']}) == (True, True)
    assert [item[2] for item in calls] == ['1080p', '1080p']
    assert [item[0] for item in calls] == ['same-file.part', 'same-file.part']
    assert not any(word in caplog.text for word in ('SECRET', 'PASSWORD', 'https://'))


def test_non_network_failure_does_not_retry_backup(monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise DownloadError('ffmpeg postprocessing failed')

    monkeypatch.setattr(adapters.YoutubeDL, 'dl', fail)
    with adapters.PlatformYoutubeDL({'quiet': True}) as ydl:
        with pytest.raises(DownloadError):
            ydl.dl('file', {'url': 'https://primary/v', '_platform_backup_urls': ['https://backup/v']})
    assert len(calls) == 1


@pytest.mark.parametrize('actual,part', [(30, 4), (2503, 9)])
def test_bilibili_rejects_preview_and_nonexistent_part(monkeypatch, actual, part):
    def extract(self, url):
        self._part_pages = [{'page': 4, 'duration': 2503}]
        return {'id': f'BV18YEQz4E1M_p{part}', 'duration': actual}

    monkeypatch.setattr(BiliBiliIE, '_real_extract', extract)
    with pytest.raises(adapters.PlatformError):
        adapters.BilibiliIE()._real_extract(BILI.replace('p=4', f'p={part}'))


def test_bilibili_accepts_correct_complete_part(monkeypatch):
    def extract(self, url):
        self._part_pages = [{'page': 4, 'duration': 2503}]
        return {'id': 'BV18YEQz4E1M_p4', 'duration': 2502.686}

    monkeypatch.setattr(BiliBiliIE, '_real_extract', extract)
    assert adapters.BilibiliIE()._real_extract(BILI)['_platform_expected_duration'] == 2503
    with pytest.raises(adapters.PlatformError, match='试看'):
        adapters.BilibiliIE().report_warning('only the preview will be extracted: sensitive data')


def test_mgtv_uses_web_api_and_same_device_nonce(monkeypatch):
    captured = []
    monkeypatch.setattr(MGTVIE, '_download_json', lambda self, url, *args, **kwargs: captured.append((url, kwargs['query'])) or {'code': 200})
    tk2 = base64.urlsafe_b64encode(b'did=TEST_DEVICE|pno=1030')[::-1]
    adapters.MangoTVIE()._download_json('https://tinker.glb.mgtv.com/player/getSource', '1', query={'tk2': tk2, 'pm2': 'NEVER_PRINT', 'src': 'intelmgtv', 'abroad': '10'})
    url, query = captured[0]
    assert url == 'https://pcweb.api.mgtv.com/player/getSource'
    assert query['did'] == 'TEST_DEVICE'
    assert query['src'] == query['abroad'] == ''
    assert query['definitionType'] == '2'


class Body:
    def __init__(self, text):
        self.text = text.encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.text[:size]


@pytest.mark.parametrize('body,expected,code', [
    (MANIFEST, 20, None), (MANIFEST, 1250, 'PREVIEW_ONLY'),
    (MANIFEST.replace('#EXT-X-ENDLIST', ''), 20, 'MANIFEST_INVALID'),
    (MANIFEST + '#EXT-X-GAP\n', 20, 'MANIFEST_INVALID'),
    (MANIFEST + '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://protected"\n', 20, 'DRM_UNSUPPORTED'),
])
def test_complete_clear_manifest_required(body, expected, code):
    ydl = SimpleNamespace(urlopen=lambda request: Body(body))
    if code:
        with pytest.raises(adapters.PlatformError) as caught:
            adapters.inspect_manifest(ydl, {'url': 'https://cdn/manifest'}, expected)
        assert caught.value.code == code
    else:
        assert adapters.inspect_manifest(ydl, {'url': 'https://cdn/manifest'}, expected)['height'] == 348


def test_new_mgtv_labels_are_exposed_as_muxed_quality_options(monkeypatch):
    monkeypatch.setattr(MGTVIE, '_real_extract', lambda *args: {'duration': 20, 'extractor_key': 'MangoTV', 'formats': [
        {'format_id': '400', 'format_note': '480P', 'url': 'https://cdn/manifest', 'ext': 'mp4'},
        {'format_id': '600', 'format_note': '576P', 'url': 'https://cdn/manifest', 'ext': 'mp4'},
    ]})
    ie = adapters.MangoTVIE()
    ie._downloader = SimpleNamespace(urlopen=lambda request: Body(MANIFEST))
    info = ie._real_extract(MGTV)
    choices = service._format_choices(info)
    assert [choice.format_id for choice in choices] == ['best', '400', '600']
    assert [choice.resolution for choice in choices[1:]] == ['480p', '576p']


def test_platform_error_messages_do_not_expose_raw_upstream_values():
    error = adapters.PlatformError('PLAYBACK_REJECTED', '请确认 Firefox 登录状态。')
    assert service.friendly_error(error) == service.download_error(error) == str(error)


def test_preview_warning_from_redirected_bilibili_extractor_is_rejected():
    logger = adapters._PlatformLogger(service._YtdlpLogger())
    with pytest.raises(adapters.PlatformError, match='试看') as caught:
        logger.warning('Only preview format is available, cookie=SECRET https://cdn/?token=PASSWORD')
    assert 'SECRET' not in str(caught.value) and 'PASSWORD' not in str(caught.value)


@pytest.fixture(scope='module')
def fixture_video(tmp_path_factory):
    path = tmp_path_factory.mktemp('media') / 'video.mp4'
    result = subprocess.run([service._ffmpeg_location(), '-hide_banner', '-loglevel', 'error',
                             '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=5',
                             '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1',
                             '-c:v', 'mpeg4', '-c:a', 'aac', str(path)], capture_output=True)
    assert result.returncode == 0
    return path.read_bytes()


@pytest.mark.parametrize('url', [BILI, MGTV])
def test_api_parse_download_and_range_use_same_session_policy(monkeypatch, tmp_path, fixture_video, url):
    calls = []

    @contextmanager
    def downloader(target, options):
        calls.append((target, options))

        class Client:
            def extract_info(self, target_url, download=False, process=True):
                assert not download
                return {'id': 'test', 'title': '完整视频', 'extractor_key': 'MangoTV' if url == MGTV else 'Bilibili',
                        'duration': 1, '_platform_expected_duration': 1, 'formats': [
                            {'format_id': '480', 'height': 480, 'vcodec': 'h264', 'acodec': 'aac', 'ext': 'mp4', 'url': 'https://cdn/?token=SECRET'},
                        ]}

            def process_ie_result(self, info, download):
                assert download
                directory = Path(options['outtmpl']).parent
                (directory / 'result.mp4').write_bytes(fixture_video)

        yield Client()

    monkeypatch.setattr(service, 'validate_public_http_url', lambda value: value)
    monkeypatch.setattr(service, 'DOWNLOAD_DIR', tmp_path)
    monkeypatch.setattr(adapters, 'open_downloader', downloader)
    with TestClient(main.app) as client:
        parsed = client.post('/api/v1/parse', json={'url': url})
        assert parsed.status_code == 200
        assert 'SECRET' not in parsed.text and 'https://cdn/' not in parsed.text
        created = client.post('/api/v1/downloads', json={'url': url, 'format_id': '480', 'delivery_mode': 'auto'}).json()
        status = client.get(created['status_url']).json()
        assert status['status'] == 'ready' and status['delivery_mode'] == 'server'
        assert client.get(created['download_url']).content == fixture_video
        partial = client.get(created['download_url'], headers={'Range': 'bytes=0-15'})
        assert partial.status_code == 206 and partial.content == fixture_video[:16]
    service.TASKS.pop(created['task_id'], None)
    assert len(calls) == 2 and all(target == url for target, options in calls)
    assert calls[1][1]['format'] == '480'


@pytest.mark.parametrize('url', [BILI, MGTV])
def test_cloud_parse_and_download_succeed_after_real_cookie_wrapper_failure(monkeypatch, tmp_path, fixture_video, url):
    modes = []
    def unavailable(*args, **kwargs):
        raise FileNotFoundError('PRIVATE_SERVER_PROFILE')
    def metadata(self, target, download=False, process=True):
        modes.append(self.params.get('cookiesfrombrowser'))
        return {'id': 'test', 'title': '匿名公开视频', 'extractor_key': 'Bilibili',
                'duration': 1, '_platform_expected_duration': 1,
                'formats': [{'format_id': '480', 'height': 480, 'vcodec': 'h264', 'acodec': 'aac', 'ext': 'mp4'}]}
    def download(self, info, download):
        assert download and 'cookiesfrombrowser' not in self.params
        (Path(self.params['outtmpl']['default']).parent / 'complete.mp4').write_bytes(fixture_video)
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', unavailable)
    monkeypatch.setattr(service, 'validate_public_http_url', lambda value: value)
    monkeypatch.setattr(service, 'DOWNLOAD_DIR', tmp_path)
    monkeypatch.setattr(adapters.PlatformYoutubeDL, 'extract_info', metadata)
    monkeypatch.setattr(adapters.PlatformYoutubeDL, 'process_ie_result', download)
    with TestClient(main.app) as api:
        assert api.post('/api/v1/parse', json={'url': url}).json()['title'] == '匿名公开视频'
        created = api.post('/api/v1/downloads', json={'url': url, 'format_id': '480'}).json()
        try:
            state = api.get(created['status_url']).json()
            assert state['status'] == 'ready'
            assert api.get(created['download_url']).content == fixture_video
        finally:
            service.TASKS.pop(created['task_id'], None)
    assert modes == [None, None]


def test_cookie_failure_after_platform_extraction_started_does_not_retry_anonymous(monkeypatch):
    created = []
    real = adapters.PlatformYoutubeDL
    def factory(options):
        created.append(options)
        return real(options)
    monkeypatch.setattr(adapters, 'PlatformYoutubeDL', factory)
    monkeypatch.setattr(adapters, '_session_usable', lambda *args: True)
    with pytest.raises(CookieLoadError):
        with adapters.open_downloader(BILI, service._video_options()):
            raise CookieLoadError('late media error')
    assert len(created) == 1


def test_cookie_error_detection_uses_types_and_handles_exception_cycles():
    message_only = DownloadError('could not find firefox cookies database')
    assert not adapters.cookie_load_failed(message_only)
    message_only.__context__ = message_only
    assert not adapters.cookie_load_failed(message_only)
    wrapper = DownloadError('redacted', (CookieLoadError, CookieLoadError('redacted'), None))
    assert adapters.cookie_load_failed(wrapper)


def test_short_file_cannot_be_marked_complete(tmp_path, fixture_video):
    path = tmp_path / 'preview.mp4'
    path.write_bytes(fixture_video)
    with pytest.raises(adapters.PlatformError, match='不完整'):
        adapters.verify_media(service._ffmpeg_location(), path, 120)


def test_api_does_not_deliver_incomplete_platform_file(monkeypatch, tmp_path, fixture_video):
    @contextmanager
    def downloader(url, options):
        class Client:
            def extract_info(self, *args, **kwargs):
                return {'id': 'test', 'duration': 120, 'formats': []}

            def process_ie_result(self, *args, **kwargs):
                (Path(options['outtmpl']).parent / 'preview.mp4').write_bytes(fixture_video)

        yield Client()

    monkeypatch.setattr(service, 'validate_public_http_url', lambda value: value)
    monkeypatch.setattr(service, 'DOWNLOAD_DIR', tmp_path)
    monkeypatch.setattr(adapters, 'open_downloader', downloader)
    with TestClient(main.app) as client:
        created = client.post('/api/v1/downloads', json={'url': MGTV, 'format_id': 'best'}).json()
        status = client.get(created['status_url']).json()
        assert status['status'] == 'failed' and '不完整' in status['error']
        assert client.get(created['download_url']).status_code == 422
    service.TASKS.pop(created['task_id'], None)
