"""Offline contracts for the Douyin adapter; these are not live-site tests."""

import ipaddress
import json
import logging
import socket
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import douyin, main, security, video_service

VIDEO_ID = "7674550636700011810"
OTHER_ID = "7685345542323834441"
VIDEO_URL = f"https://www.douyin.com/video/{VIDEO_ID}"
MEDIA_URL = "https://cdn.example.test/video.mp4?token=private-media-token"
COVER_URL = "https://cdn.example.test/cover.jpg?token=private-cover-token"
# Synthetic complete top-level ISO-BMFF boxes, not an encoded/playable video.
# Actual codec/playback validation belongs to a live smoke test.
def atom(kind, payload):
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


MP4_BYTES = (
    atom(b"ftyp", b"isom\x00\x00\x02\x00isommp42")
    + atom(b"moov", b"")
    + atom(b"mdat", b"synthetic-payload" * 8)
)


@pytest.fixture(autouse=True)
def offline_public_dns(monkeypatch):
    """Keep the real URL validator; replace DNS only, never contact the network."""
    def addresses(host, port, **kwargs):
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            address = "127.0.0.1" if host == "localhost" else "8.8.8.8"
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(security.socket, "getaddrinfo", addresses)


@pytest.fixture
def mock_upstream(monkeypatch):
    original_client = httpx.Client
    requests = []

    def install(handler):
        def record(request):
            requests.append(request)
            return handler(request)

        def factory():
            return original_client(
                transport=httpx.MockTransport(record),
                headers=douyin.MOBILE_HEADERS,
                follow_redirects=False,
            )

        monkeypatch.setattr(douyin, "_client", factory)
        return requests

    return install


@pytest.fixture
def isolated_tasks(monkeypatch, tmp_path):
    monkeypatch.setattr(video_service, "TASKS", {})
    monkeypatch.setattr(video_service, "THUMBNAIL_SOURCES", {})
    monkeypatch.setattr(video_service, "DOWNLOAD_DIR", tmp_path)
    return tmp_path


def item(video_id=VIDEO_ID, *, title='嵌套 "标题" {保留花括号}', media_url=MEDIA_URL):
    return {
        "aweme_id": video_id,
        "desc": title,
        "video": {
            "play_addr": {"url_list": [media_url]},
            "origin_cover": {"url_list": [COVER_URL]},
            "duration": 12500,
            "width": 720,
            "height": 1280,
        },
    }


def share_html(items=None):
    payload = {"loaderData": {"video": {"videoInfoRes": {"item_list": items or [item()]}}}}
    return "<html><script>window._ROUTER_DATA = " + json.dumps(payload, ensure_ascii=False) + ";</script></html>"


def video(media_urls=(MEDIA_URL,)):
    return douyin.DouyinVideo(VIDEO_ID, "../CON unsafe title", media_urls, COVER_URL, 12.5, 720, 1280)


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks, *, disconnect=False):
        self.chunks = chunks
        self.disconnect = disconnect

    def __iter__(self):
        yield from self.chunks
        if self.disconnect:
            raise httpx.ReadError("simulated disconnect at signed media URL")


def test_anonymous_share_session_reuses_visitor_cookie_but_isolates_requests(mock_upstream, monkeypatch):
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls % 2:
            assert "cookie" not in request.headers
            return httpx.Response(200, text="<html>visitor initialized</html>", headers={"Set-Cookie": "ttwid=anonymous-visitor; Path=/; Secure"})
        assert request.headers["cookie"] == "ttwid=anonymous-visitor"
        return httpx.Response(200, text=share_html())

    requests = mock_upstream(handler)
    for _ in range(2):
        parsed = douyin.resolve_video(VIDEO_URL)
        assert parsed.title == '嵌套 "标题" {保留花括号}'
        assert parsed.duration == 12.5
        assert parsed.resolution == "720×1280"
    assert len(requests) == 4
    assert all(request.url.host == "www.iesdouyin.com" for request in requests)


@pytest.mark.parametrize("url", [
    VIDEO_URL,
    f"https://www.douyin.com/?modal_id={VIDEO_ID}",
    f"https://www.iesdouyin.com/share/video/{VIDEO_ID}/",
])
def test_direct_and_modal_links_resolve_without_fetching_pc_page(url, mock_upstream):
    requests = mock_upstream(lambda request: httpx.Response(200, text=share_html()))
    assert douyin.resolve_video(url).video_id == VIDEO_ID
    assert len(requests) == 1
    assert requests[0].url.path == f"/share/video/{VIDEO_ID}/"


def test_short_link_follows_relative_redirect_and_extracts_target_id(mock_upstream):
    def handler(request):
        if request.url.host == "v.douyin.com" and request.url.path == "/short/":
            return httpx.Response(302, headers={"Location": "/resolved/"})
        if request.url.host == "v.douyin.com":
            return httpx.Response(302, headers={"Location": f"https://www.douyin.com/?modal_id={VIDEO_ID}"})
        if request.url.host == "www.douyin.com":
            return httpx.Response(200, text="resolved")
        return httpx.Response(200, text=share_html())

    requests = mock_upstream(handler)
    assert douyin.resolve_video("https://v.douyin.com/short/").video_id == VIDEO_ID
    assert [request.url.host for request in requests] == ["v.douyin.com", "v.douyin.com", "www.douyin.com", "www.iesdouyin.com"]


def test_nested_share_json_selects_exact_video_not_first_recommendation():
    target = item(title="Correct target {nested}")
    html = share_html([item(OTHER_ID, title="Wrong recommendation"), target])
    assert douyin._item_from_html(html, VIDEO_ID) == target
    assert douyin._item_from_html(html, "1111111111111111111") is None


def test_encoded_render_data_is_supported_without_evaluating_javascript():
    target = item()
    encoded = quote(json.dumps({"deep": [{"more": target}]}))
    html = f'<script id="RENDER_DATA" type="application/json">{encoded}</script>'
    assert douyin._item_from_html(html, VIDEO_ID) == target


def test_wrong_video_id_never_returns_recommended_video(mock_upstream):
    mock_upstream(lambda request: httpx.Response(200, text=share_html([item(OTHER_ID)])))
    with pytest.raises(douyin.DouyinError, match="未返回视频信息"):
        douyin.resolve_video(VIDEO_URL)


def test_share_page_retry_count_is_bounded(mock_upstream):
    requests = mock_upstream(lambda request: httpx.Response(200, text="<html>no data</html>"))
    with pytest.raises(douyin.DouyinError, match="未返回视频信息"):
        douyin.resolve_video(VIDEO_URL)
    assert len(requests) == 3


@pytest.mark.parametrize("target,exception", [
    ("http://127.0.0.1/private", HTTPException),
    ("http://localhost/private", HTTPException),
    ("file:///C:/private", HTTPException),
    ("https://user:secret@www.douyin.com/video/7674550636700011810", HTTPException),
    ("https://example.test/elsewhere", douyin.DouyinError),
])
def test_short_link_rejects_unsafe_redirect_before_request(target, exception, mock_upstream):
    requests = mock_upstream(lambda request: httpx.Response(302, headers={"Location": target}))
    with pytest.raises(exception):
        douyin.resolve_video("https://v.douyin.com/short/")
    assert len(requests) == 1


def test_media_private_redirect_is_blocked_before_fetch(mock_upstream, tmp_path):
    requests = mock_upstream(lambda request: httpx.Response(302, headers={"Location": "http://127.0.0.1/private"}))
    task_directory = tmp_path / "rejected-task"
    with pytest.raises(HTTPException):
        douyin.download_video(video(), task_directory, lambda value: None)
    assert len(requests) == 1
    assert not task_directory.exists()


def test_playwm_rewrite_preserves_query_and_does_not_touch_unrelated_hosts():
    signed = f"https://www.iesdouyin.com/aweme/v1/playwm/?video_id={VIDEO_ID}&signature=playwm%2Fopaque"
    expected = signed.replace("/aweme/v1/playwm/", "/aweme/v1/play/")
    assert douyin._play_url(signed) == expected
    unrelated = "https://cdn.example.test/aweme/v1/playwm/?token=playwm"
    assert douyin._play_url(unrelated) == unrelated


def test_image_post_fails_with_specific_message(mock_upstream):
    target = item()
    target["images"] = [{"url_list": [COVER_URL]}]
    mock_upstream(lambda request: httpx.Response(200, text=share_html([target])))
    with pytest.raises(douyin.DouyinError, match="图集"):
        douyin.resolve_video(VIDEO_URL)


def test_oversized_share_page_is_rejected(mock_upstream, monkeypatch):
    monkeypatch.setattr(douyin, "MAX_PAGE_BYTES", 64)
    mock_upstream(lambda request: httpx.Response(200, text="x" * 65))
    with pytest.raises(douyin.DouyinError, match="分享页返回内容异常"):
        douyin.resolve_video(VIDEO_URL)


@pytest.mark.parametrize("content_type", ["text/html", "application/json", "video/webm", ""])
def test_download_rejects_non_mp4_mime_and_cleans_partial(content_type, mock_upstream, tmp_path):
    mock_upstream(lambda request: httpx.Response(200, content=MP4_BYTES, headers={"Content-Type": content_type}))
    with pytest.raises(douyin.DouyinError, match="不是 MP4"):
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert not list(tmp_path.glob("*"))


@pytest.mark.parametrize("body", [b"<html>not a video</html>", b"\x00\x00\x00\x18ftyp"])
def test_mp4_mime_alone_does_not_accept_invalid_or_short_file(body, mock_upstream, tmp_path):
    mock_upstream(lambda request: httpx.Response(200, content=body, headers={"Content-Type": "video/mp4"}))
    with pytest.raises(douyin.DouyinError, match="无效|不完整"):
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert not list(tmp_path.glob("*"))


def test_declared_file_size_limit_rejects_before_write(mock_upstream, monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "MAX_VIDEO_BYTES", 64)
    mock_upstream(lambda request: httpx.Response(200, content=MP4_BYTES, headers={"Content-Type": "video/mp4"}))
    with pytest.raises(douyin.DouyinError, match="限制"):
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert not list(tmp_path.glob("*"))


def test_stream_size_limit_applies_without_content_length(mock_upstream, monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "MAX_VIDEO_BYTES", 64)
    mock_upstream(lambda request: httpx.Response(200, stream=ChunkStream([MP4_BYTES]), headers={"Content-Type": "video/mp4"}))
    with pytest.raises(douyin.DouyinError, match="限制"):
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert not list(tmp_path.glob("*"))


def test_declared_length_mismatch_is_rejected_and_cleaned(mock_upstream, tmp_path):
    headers = {"Content-Type": "video/mp4", "Content-Length": str(len(MP4_BYTES) + 100)}
    mock_upstream(lambda request: httpx.Response(200, stream=ChunkStream([MP4_BYTES]), headers=headers))
    with pytest.raises(douyin.DouyinError, match="不完整"):
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert not list(tmp_path.glob("*"))


def test_twelve_byte_fake_mp4_without_content_length_is_rejected(mock_upstream, tmp_path):
    fake = b"\x00\x00\x00\x18ftypisom"
    mock_upstream(lambda request: httpx.Response(200, stream=ChunkStream([fake]), headers={"Content-Type": "video/mp4"}))
    with pytest.raises(douyin.DouyinError, match="不完整|无效"):
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert not list(tmp_path.glob("*"))


@pytest.mark.parametrize("trailer", [
    b"\x00\x00\x00\x04mdat",
    b"\x00\x00\x00\x80mdatshort",
    b"\x00\x00\x00\x01mdatshort",
    b"leftover",
])
def test_malformed_top_level_box_does_not_become_ready_file(trailer, mock_upstream, tmp_path):
    body = atom(b"ftyp", b"isom\x00\x00\x02\x00isom") + atom(b"moov", b"") + trailer
    mock_upstream(lambda request: httpx.Response(200, stream=ChunkStream([body]), headers={"Content-Type": "video/mp4"}))
    with pytest.raises(douyin.DouyinError, match="不完整|缺少媒体数据"):
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert not list(tmp_path.glob("*"))


@pytest.mark.parametrize("missing", [b"moov", b"mdat"])
def test_missing_metadata_or_media_box_is_rejected(missing, mock_upstream, tmp_path):
    boxes = {b"ftyp": b"isom\x00\x00\x02\x00isom", b"moov": b"", b"mdat": b"payload"}
    body = b"".join(atom(kind, payload) for kind, payload in boxes.items() if kind != missing)
    mock_upstream(lambda request: httpx.Response(200, content=body, headers={"Content-Type": "video/mp4"}))
    with pytest.raises(douyin.DouyinError, match="缺少媒体数据"):
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert not list(tmp_path.glob("*"))


@pytest.mark.parametrize("extended", [True, False])
def test_valid_extended_size_or_end_of_file_media_box_is_accepted(extended, mock_upstream, tmp_path):
    if extended:
        media = b"\x00\x00\x00\x01mdat" + (23).to_bytes(8, "big") + b"payload"
    else:
        media = b"\x00\x00\x00\x00mdatpayload"
    body = atom(b"ftyp", b"isom\x00\x00\x02\x00isom") + atom(b"moov", b"") + media
    mock_upstream(lambda request: httpx.Response(200, content=body, headers={"Content-Type": "video/mp4"}))
    result = douyin.download_video(video(), tmp_path, lambda value: None)
    assert result.read_bytes() == body


def test_signed_media_urls_are_not_emitted_by_http_client_logs(mock_upstream, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
    mock_upstream(lambda request: httpx.Response(200, content=MP4_BYTES, headers={"Content-Type": "video/mp4"}))
    douyin.download_video(video(), tmp_path, lambda value: None)
    assert "private-media-token" not in caplog.text
    assert MEDIA_URL not in caplog.text


def test_disconnect_after_partial_write_removes_file_and_sanitizes_error(mock_upstream, tmp_path):
    body = MP4_BYTES + b"x" * (65536 - len(MP4_BYTES))
    mock_upstream(lambda request: httpx.Response(200, stream=ChunkStream([body], disconnect=True), headers={"Content-Type": "video/mp4"}))
    with pytest.raises(douyin.DouyinError, match="超时或中断") as caught:
        douyin.download_video(video(), tmp_path, lambda value: None)
    assert "signed" not in str(caught.value)
    assert "private-media-token" not in str(caught.value)
    assert not list(tmp_path.glob("*"))


@pytest.mark.parametrize("known_length", [True, False])
def test_download_success_reports_real_or_unknown_progress_and_safe_filename(known_length, mock_upstream, tmp_path):
    headers = {"Content-Type": "application/octet-stream"}
    if known_length:
        headers["Content-Length"] = str(len(MP4_BYTES))
    mock_upstream(lambda request: httpx.Response(200, stream=ChunkStream([MP4_BYTES[:7], MP4_BYTES[7:]]), headers=headers))
    progress = []
    result = douyin.download_video(video(), tmp_path, progress.append)
    assert result == tmp_path / f"douyin_{VIDEO_ID}.mp4"
    assert result.read_bytes() == MP4_BYTES
    assert not list(tmp_path.glob("*.part"))
    assert progress[0] is None
    assert all(value is None or 0 < value < 100 for value in progress)
    assert (any(value is not None for value in progress)) == known_length


def test_failed_cdn_falls_back_without_leaving_partial(mock_upstream, tmp_path):
    second_url = "https://backup.example.test/video.mp4"

    def handler(request):
        if request.url.host == "cdn.example.test":
            return httpx.Response(403, text="blocked")
        return httpx.Response(200, content=MP4_BYTES, headers={"Content-Type": "video/mp4"})

    requests = mock_upstream(handler)
    result = douyin.download_video(video((MEDIA_URL, second_url)), tmp_path, lambda value: None)
    assert result.read_bytes() == MP4_BYTES
    assert len(requests) == 2
    assert not list(tmp_path.glob("*.part"))


def test_parse_api_returns_contract_and_thumbnail_proxy_without_signed_urls(mock_upstream, isolated_tasks, monkeypatch):
    mock_upstream(lambda request: httpx.Response(200, text=share_html()))
    monkeypatch.setattr(video_service, "YoutubeDL", lambda *args, **kwargs: pytest.fail("Douyin must not use yt-dlp"))
    with TestClient(main.app) as client:
        response = client.post("/api/v1/parse", json={"url": VIDEO_URL})
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"title", "extractor", "thumbnail", "duration", "formats"}
    assert payload["extractor"] == "Douyin"
    assert payload["duration"] == 12.5
    assert payload["formats"][0]["format_id"] == "best"
    assert payload["formats"][0]["resolution"] == "720×1280"
    assert payload["thumbnail"].startswith("/api/v1/thumbnails/")
    assert "private-media-token" not in response.text
    assert "private-cover-token" not in response.text
    assert MEDIA_URL not in response.text


@pytest.mark.parametrize("mode", ["auto", "server"])
def test_download_api_executes_adapter_and_delivers_file(mode, mock_upstream, isolated_tasks, monkeypatch):
    def handler(request):
        if request.url.host == "www.iesdouyin.com":
            return httpx.Response(200, text=share_html())
        assert "cookie" not in request.headers
        return httpx.Response(200, content=MP4_BYTES, headers={"Content-Type": "video/mp4"})

    requests = mock_upstream(handler)
    monkeypatch.setattr(video_service, "YoutubeDL", lambda *args, **kwargs: pytest.fail("Douyin must not use yt-dlp"))
    with TestClient(main.app) as client:
        parsed = client.post("/api/v1/parse", json={"url": VIDEO_URL})
        assert parsed.status_code == 200
        created = client.post("/api/v1/downloads", json={"url": VIDEO_URL, "format_id": "best", "delivery_mode": mode})
        assert created.status_code == 202
        status = client.get(created.json()["status_url"])
        assert status.status_code == 200
        assert status.json()["status"] == "ready"
        assert status.json()["delivery_mode"] == "server"
        assert status.json()["progress"] == 100
        assert "file_path" not in status.json()
        assert "private-media-token" not in status.text
        file_response = client.get(created.json()["download_url"])
        assert file_response.status_code == 200
        assert file_response.content == MP4_BYTES
        assert file_response.headers["content-type"] == "video/mp4"
        assert f"douyin_{VIDEO_ID}.mp4" in file_response.headers["content-disposition"]
        partial_response = client.get(created.json()["download_url"], headers={"Range": "bytes=0-11"})
        assert partial_response.status_code == 206
        assert partial_response.content == MP4_BYTES[:12]
    # Parse and download independently resolve metadata, avoiding cached expiring URLs.
    assert sum(request.url.host == "www.iesdouyin.com" for request in requests) == 2
    assert not list(isolated_tasks.rglob("*.part"))


@pytest.mark.parametrize("format_id,mode,message", [
    ("best", "redirect", "自动或服务端"),
    ("obsolete-format", "server", "重新解析"),
])
def test_invalid_delivery_selection_produces_failed_task_without_upstream_call(format_id, mode, message, mock_upstream, isolated_tasks):
    requests = mock_upstream(lambda request: pytest.fail("invalid selection must not request upstream"))
    with TestClient(main.app) as client:
        created = client.post("/api/v1/downloads", json={"url": VIDEO_URL, "format_id": format_id, "delivery_mode": mode})
        assert created.status_code == 202
        status = client.get(created.json()["status_url"])
        assert status.json()["status"] == "failed"
        assert message in status.json()["error"]
        failed_file = client.get(created.json()["download_url"])
        assert failed_file.status_code == 422
    assert requests == []


def test_douyin_failure_message_remains_actionable_through_parse_api(mock_upstream, isolated_tasks):
    mock_upstream(lambda request: httpx.Response(429, text="token=secret-denial"))
    with TestClient(main.app) as client:
        response = client.post("/api/v1/parse", json={"url": VIDEO_URL})
    assert response.status_code == 422
    assert "稍后重试" in response.json()["detail"]
    assert "secret-denial" not in response.text


def test_invalid_upstream_file_fails_task_and_removes_empty_directory(mock_upstream, isolated_tasks):
    def handler(request):
        if request.url.host == "www.iesdouyin.com":
            return httpx.Response(200, text=share_html())
        return httpx.Response(200, text="token=private-media-token", headers={"Content-Type": "text/html"})

    mock_upstream(handler)
    with TestClient(main.app) as client:
        created = client.post("/api/v1/downloads", json={"url": VIDEO_URL, "format_id": "best", "delivery_mode": "server"})
        assert created.status_code == 202
        status = client.get(created.json()["status_url"])
        assert status.json()["status"] == "failed"
        assert "重新解析" in status.json()["error"]
        assert "private-media-token" not in status.text
        assert client.get(created.json()["download_url"]).status_code == 422
    assert not (isolated_tasks / created.json()["task_id"]).exists()


@pytest.mark.parametrize("url", ["https://www.bilibili.com/video/BV1example", "https://www.youtube.com/watch?v=example"])
def test_other_platforms_still_parse_and_download_with_ytdlp(url, monkeypatch, isolated_tasks):
    calls = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            calls.append(("options", options))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def extract_info(self, target_url, download):
            calls.append(("parse", target_url, download))
            return {"id": "example", "title": "Existing source", "extractor_key": "ExistingExtractor", "duration": 15, "formats": []}

        def download(self, urls):
            calls.append(("download", urls))
            directory = Path(self.options["outtmpl"]).parent
            (directory / "existing.mp4").write_bytes(b"existing-downloader-file")

    monkeypatch.setattr(video_service, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(video_service, "_ffmpeg_location", lambda: None)
    monkeypatch.setattr(douyin, "resolve_video", lambda *args: pytest.fail("other platforms must not use Douyin adapter"))
    parsed = video_service.parse_video(url)
    assert parsed.title == "Existing source"
    assert parsed.extractor == "ExistingExtractor"
    video_service.create_task("existing-task", "server")
    video_service.process_download("existing-task", url, "best", "server")
    state = video_service.get_task("existing-task")
    assert state["status"] == "ready"
    assert Path(state["file_path"]).read_bytes() == b"existing-downloader-file"
    assert ("parse", url, False) in calls
    assert ("download", [url]) in calls
    assert all(call[1]["format"] == "bv*+ba/best" for call in calls if call[0] == "options" and "format" in call[1])
