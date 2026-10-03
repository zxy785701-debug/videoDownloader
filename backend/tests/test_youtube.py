import logging

import pytest

from app import video_service as service


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    for name in ("YTDLP_PROXY", "YTDLP_POT_BASE_URL", "YTDLP_NODE_PATH", "YTDLP_COOKIES_FROM_BROWSER"):
        monkeypatch.delenv(name, raising=False)


def test_youtube_settings_do_not_affect_bilibili_or_lookalike_hosts(monkeypatch):
    monkeypatch.setenv("YTDLP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("YTDLP_POT_BASE_URL", "http://127.0.0.1:4416")
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    for url in ("https://youtu.be/example", "https://www.youtube.com/watch?v=example"):
        options = service._video_options(source_url=url)
        assert options["proxy"] == "http://127.0.0.1:7890"
        assert options["extractor_args"]["youtube"]["player_client"] == ["mweb"]
        assert options["extractor_args"]["youtubepot-bgutilhttp"]["base_url"] == ["http://127.0.0.1:4416"]
        assert options["cookiesfrombrowser"][0] == "firefox"
    for url in ("https://www.bilibili.com/video/example", "https://youtube.com.example.org/video"):
        options = service._video_options(source_url=url)
        assert not {"proxy", "extractor_args", "cookiesfrombrowser"} & options.keys()


@pytest.mark.parametrize("name,value", [
    ("YTDLP_PROXY", "file:///secret"),
    ("YTDLP_POT_BASE_URL", "http://user:secret@localhost:4416"),
])
def test_invalid_configuration_has_safe_message(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError) as caught:
        service._video_options(source_url="https://youtube.com/watch?v=test")
    assert name in service.friendly_error(caught.value)
    assert "secret" not in service.friendly_error(caught.value)


@pytest.mark.parametrize("message,category", [
    ("Sign in to confirm you’re not a bot", "login_required"),
    ("Failed to decrypt with DPAPI", "cookie_decryption"),
    ("No supported JavaScript runtime", "js_challenge"),
    ("missing PO Token", "po_token"),
    ("HTTP Error 403: Forbidden", "forbidden"),
    ("HTTP Error 429", "rate_limited"),
    ("Connection timed out", "network"),
    ("This video is unavailable", "unavailable"),
    ("Requested format is not available", "formats"),
])
def test_errors_have_consistent_parse_and_download_guidance(message, category):
    error = RuntimeError(message)
    assert service.error_category(error) == category
    assert service.download_error(error) == service.friendly_error(error)


def test_upstream_logs_do_not_expose_credentials_or_signed_urls(caplog):
    upstream = service._video_options()["logger"]
    with caplog.at_level(logging.WARNING):
        upstream.warning("HTTP 403 https://cdn.test/v?token=SECRET Cookie: SESSION")
        upstream.error("ProxyError http://user:PASSWORD@localhost:7890")
        upstream.debug("SECRET")
    assert "category=forbidden" in caplog.text
    assert "category=network" in caplog.text
    assert all(value not in caplog.text for value in ("SECRET", "SESSION", "PASSWORD", "https://"))


def test_youtube_auto_download_skips_redirect_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(service, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setenv("YTDLP_PROXY", "http://127.0.0.1:7890")
    calls = []

    class Downloader:
        def __init__(self, options):
            calls.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, *args, **kwargs):
            pytest.fail("YouTube auto mode should not perform a redirect probe")

        def download(self, urls):
            (tmp_path / "youtube-test" / "video.mp4").write_bytes(b"video")

    monkeypatch.setattr(service, "YoutubeDL", Downloader)
    service.create_task("youtube-test", "auto")
    try:
        service.process_download("youtube-test", "https://youtu.be/example", "best", "auto")
        task = service.get_task("youtube-test")
        assert task["status"] == "ready"
        assert task["delivery_mode"] == "server"
        assert len(calls) == 1
        assert calls[0]["proxy"] == "http://127.0.0.1:7890"
        assert calls[0]["format"] == "bv*+ba/best"
    finally:
        service.TASKS.pop("youtube-test", None)


def test_youtube_redirect_explains_supported_mode(monkeypatch):
    monkeypatch.setattr(service, "validate_public_http_url", lambda url: url)
    service.create_task("youtube-redirect", "redirect")
    try:
        service.process_download("youtube-redirect", "https://youtu.be/example", "best", "redirect")
        task = service.get_task("youtube-redirect")
        assert task["status"] == "failed"
        assert "自动或服务端" in task["error"]
    finally:
        service.TASKS.pop("youtube-redirect", None)
