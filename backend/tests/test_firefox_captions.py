"""Real yt-dlp cookie-loading machinery with synthetic sessions and metadata only."""
import logging
from dataclasses import replace
from http.cookiejar import Cookie

import pytest
import yt_dlp.cookies as browser_cookies
from yt_dlp.utils import DownloadError
from yt_dlp.cookies import YoutubeDLCookieJar as CookieJar

from app import subtitle_service, video_service
from app.ai_config import get_config
from app.analysis_errors import AnalysisError

URLS = ['https://www.bilibili.com/video/BV18YEQz4E1M/', 'https://www.douyin.com/video/123456789']
SUBTITLES = {'id': 'sample', 'duration': 60, 'subtitles': {'zh': [
    {'ext': 'srt', 'data': '1\n00:00:00,000 --> 00:00:03,000\n模拟字幕'}]}}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(subtitle_service, 'validate_public_http_url', lambda value: value)


@pytest.mark.parametrize('url', URLS)
@pytest.mark.parametrize('failure', [FileNotFoundError, PermissionError])
def test_missing_firefox_falls_back_before_caption_extraction(monkeypatch, caplog, url, failure):
    calls = []
    closed = []
    real_close = subtitle_service.YoutubeDL.close
    def close(self):
        closed.append(self.params.get('cookiesfrombrowser'))
        real_close(self)
    def unavailable(*args, **kwargs):
        raise failure('PRIVATE_PROFILE Cookie=PRIVATE_SESSION')
    def extract(self, *args, **kwargs):
        calls.append(self.params.get('cookiesfrombrowser'))
        assert self.params.get('cookiefile') is None
        return SUBTITLES
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', unavailable)
    monkeypatch.setattr(subtitle_service.YoutubeDL, 'extract_info', extract)
    monkeypatch.setattr(subtitle_service.YoutubeDL, 'close', close)
    config = replace(get_config(), firefox_subtitle_session=True)
    with caplog.at_level(logging.INFO):
        result = subtitle_service.extract_transcript(url, config=config)
    assert calls == [None] and result['cues'][0]['text'] == '模拟字幕'
    assert len(closed) == 2 and closed[0][0] == 'firefox' and closed[1] is None
    assert 'anonymous' in caplog.text
    assert all(value not in caplog.text for value in ['PRIVATE_PROFILE', 'PRIVATE_SESSION'])


@pytest.mark.parametrize('url', URLS)
def test_local_firefox_session_remains_in_memory_for_captions(monkeypatch, url):
    jar = CookieJar()
    jar.set_cookie(Cookie(0, 'SESSDATA', 'SYNTHETIC_SESSION', None, False, '.bilibili.com', True, True,
                         '/', True, False, None, True, None, None, {}))
    reads, calls = [], []
    def browser(name, profile, *args, **kwargs):
        reads.append((name, profile))
        return jar
    def extract(self, *args, **kwargs):
        calls.append(self.params.get('cookiesfrombrowser'))
        assert any(cookie.value == 'SYNTHETIC_SESSION' for cookie in self.cookiejar)
        return SUBTITLES
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', browser)
    monkeypatch.setattr(subtitle_service.YoutubeDL, 'extract_info', extract)
    config = replace(get_config(), firefox_subtitle_session=True, firefox_subtitle_profile='SYNTHETIC_PROFILE')
    result = subtitle_service.extract_transcript(url, config=config)
    assert reads == [('firefox', 'SYNTHETIC_PROFILE')]
    assert calls == [('firefox', 'SYNTHETIC_PROFILE')]
    assert 'SYNTHETIC_SESSION' not in str(result) and 'SYNTHETIC_PROFILE' not in str(result)


@pytest.mark.parametrize('url', URLS)
def test_server_anonymous_mode_never_reads_browser(monkeypatch, url):
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', lambda *a, **kw: pytest.fail('browser must not be read'))
    monkeypatch.setattr(subtitle_service.YoutubeDL, 'extract_info', lambda *a, **kw: SUBTITLES)
    result = subtitle_service.extract_transcript(url, config=replace(get_config(), firefox_subtitle_session=False))
    assert result['cues'][0]['text'] == '模拟字幕'


@pytest.mark.parametrize('requires_login,code', [(True, 'CAPTIONS_ACCESS_REQUIRED'), (False, 'NO_CAPTIONS')])
def test_fallback_distinguishes_login_required_from_missing_captions(monkeypatch, requires_login, code):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError('PRIVATE_PROFILE')
    def extract(self, *args, **kwargs):
        if requires_login:
            self.params['logger'].warning('Subtitles are only available when logged in')
        return {'id': 'sample', 'duration': 60, 'subtitles': {}}
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', unavailable)
    monkeypatch.setattr(subtitle_service.YoutubeDL, 'extract_info', extract)
    with pytest.raises(AnalysisError) as caught:
        subtitle_service.extract_transcript(URLS[0], config=replace(get_config(), firefox_subtitle_session=True))
    assert caught.value.code == code and 'PRIVATE_PROFILE' not in caught.value.message
    if requires_login:
        assert '云端' in caught.value.message and '视频下载' in caught.value.message


@pytest.mark.parametrize('failure', ['HTTP Error 403: forbidden', 'Connection timed out'])
def test_platform_extraction_error_is_not_retried_as_anonymous(monkeypatch, failure):
    calls = []
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', lambda *a, **kw: CookieJar())
    def extract(self, *args, **kwargs):
        calls.append(self.params.get('cookiesfrombrowser'))
        raise DownloadError(failure)
    monkeypatch.setattr(subtitle_service.YoutubeDL, 'extract_info', extract)
    with pytest.raises(AnalysisError):
        subtitle_service.extract_transcript(URLS[0], config=replace(get_config(), firefox_subtitle_session=True))
    assert len(calls) == 1 and calls[0][0] == 'firefox'


def test_explicit_youtube_cookie_failure_is_not_silently_downgraded(monkeypatch):
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(1)
        raise FileNotFoundError('PRIVATE_YOUTUBE_PROFILE')
    def extract(self, *args, **kwargs):
        self.cookiejar
        pytest.fail('missing explicit YouTube session must fail')
    monkeypatch.setenv('YTDLP_COOKIES_FROM_BROWSER', 'firefox')
    monkeypatch.setattr(browser_cookies, 'extract_cookies_from_browser', unavailable)
    monkeypatch.setattr(subtitle_service.YoutubeDL, 'extract_info', extract)
    with pytest.raises(AnalysisError) as caught:
        subtitle_service.extract_transcript('https://www.youtube.com/watch?v=abcdefghijk')
    assert calls == [1] and caught.value.code == 'CAPTIONS_ACCESS_REQUIRED'
    assert 'PRIVATE_YOUTUBE_PROFILE' not in caught.value.message


def test_cookie_profile_error_guidance_supports_cloud_and_windows():
    message = video_service.friendly_error(DownloadError('could not find firefox cookies database in PRIVATE_PROFILE'))
    assert '云端' in message and '本地' in message and 'PRIVATE_PROFILE' not in message
    assert 'PowerShell' not in message
