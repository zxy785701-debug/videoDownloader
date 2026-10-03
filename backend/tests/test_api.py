from fastapi.testclient import TestClient

from app import main, video_service
from app.schemas import ParseResponse, VideoFormat
from app.security import validate_public_http_url

client = TestClient(main.app)


def test_parse_returns_metadata_without_source_urls(monkeypatch):
    monkeypatch.setattr(main.video_service, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(
        main.video_service,
        "parse_video",
        lambda url: ParseResponse(
            title="Test video",
            extractor="Example",
            thumbnail="https://cdn.example.test/thumb.jpg",
            duration=42,
            formats=[VideoFormat(format_id="best", label="最佳画质")],
        ),
    )

    response = client.post("/api/v1/parse", json={"url": "https://example.test/video"})

    assert response.status_code == 200
    assert response.json()["title"] == "Test video"
    assert "url" not in response.json()


def test_download_creates_ready_server_task(monkeypatch, tmp_path):
    monkeypatch.setattr(main.video_service, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(video_service, "DOWNLOAD_DIR", tmp_path)

    def fake_process(task_id, url, format_id, delivery_mode):
        path = tmp_path / f"{task_id}.mp4"
        path.write_bytes(b"video")
        video_service._set_state(
            task_id,
            status="ready",
            delivery_mode="server",
            file_path=str(path),
            filename="test.mp4",
            progress=100.0,
        )

    monkeypatch.setattr(main.video_service, "process_download", fake_process)
    response = client.post(
        "/api/v1/downloads",
        json={
            "url": "https://example.test/video",
            "format_id": "best",
            "delivery_mode": "server",
        },
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    status = client.get(f"/api/v1/downloads/{task_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "ready"
    file_response = client.get(f"/api/v1/downloads/{task_id}/file")
    assert file_response.content == b"video"
    video_service.TASKS.pop(task_id, None)


def test_download_file_redirects_only_for_ready_redirect_task(monkeypatch):
    task_id = "redirect-test"
    video_service.create_task(task_id, "auto")
    video_service._set_state(
        task_id,
        status="ready",
        delivery_mode="redirect",
        redirect_url="https://cdn.example.test/video.mp4",
    )

    response = client.get(f"/api/v1/downloads/{task_id}/file", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://cdn.example.test/video.mp4"
    video_service.TASKS.pop(task_id, None)


def test_health_endpoint():
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_url_validator_rejects_private_addresses():
    from fastapi import HTTPException

    try:
        validate_public_http_url("http://127.0.0.1/video")
    except HTTPException as error:
        assert error.status_code == 400
    else:
        raise AssertionError("private IP addresses must be rejected")


def test_url_validator_rejects_non_http_protocols():
    from fastapi import HTTPException

    try:
        validate_public_http_url("file:///etc/passwd")
    except HTTPException as error:
        assert error.status_code == 400
    else:
        raise AssertionError("non-HTTP protocols must be rejected")


def test_split_video_formats_include_mergeable_quality_options():
    choices = video_service._format_choices(
        {
            "formats": [
                {"format_id": "30280", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"},
                {"format_id": "30016", "height": 296, "vcodec": "avc1", "acodec": "none", "ext": "mp4"},
                {"format_id": "30032", "height": 394, "vcodec": "avc1", "acodec": "none", "ext": "mp4"},
                {"format_id": "30033", "height": 394, "vcodec": "hvc1", "acodec": "none", "ext": "mp4"},
            ]
        }
    )

    assert [choice.format_id for choice in choices] == ["best", "video:30016", "video:30032"]
    assert "自动合并音频" in choices[2].label


def test_default_and_video_only_formats_map_to_audio_merge_selectors():
    assert video_service._safe_format_id("best") == "bv*+ba/best"
    assert video_service._safe_format_id("video:30080") == "30080+ba/best"


def test_thumbnail_proxy_only_accepts_registered_tokens(monkeypatch):
    monkeypatch.setattr(main.video_service, "fetch_thumbnail", lambda token: None)
    response = client.get("/api/v1/thumbnails/not-registered")

    assert response.status_code == 404


def test_thumbnail_endpoint_returns_image_response(monkeypatch):
    monkeypatch.setattr(
        main.video_service,
        "fetch_thumbnail",
        lambda token: (b"image-bytes", "image/jpeg"),
    )

    response = client.get("/api/v1/thumbnails/registered-token")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == b"image-bytes"


def test_bundled_ffmpeg_is_used_when_system_binary_is_missing(monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("YTDLP_FFMPEG_LOCATION", raising=False)
    monkeypatch.setattr(video_service.shutil, "which", lambda _: None)

    ffmpeg = video_service._ffmpeg_location()

    assert ffmpeg is not None
    assert Path(ffmpeg).is_file()


def test_browser_cookies_are_opt_in_and_support_profile(monkeypatch):
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)
    assert "cookiesfrombrowser" not in video_service._video_options(source_url="https://youtube.com/watch?v=test")

    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge:Default")
    youtube_options = video_service._video_options(source_url="https://youtube.com/watch?v=test")
    other_site_options = video_service._video_options(source_url="https://www.bilibili.com/video/BVtest")
    assert youtube_options["cookiesfrombrowser"] == ("edge", "Default", None, None)
    assert "cookiesfrombrowser" not in other_site_options


def test_youtube_bot_check_has_local_cookie_guidance(monkeypatch):
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)

    message = video_service.friendly_error(RuntimeError("Sign in to confirm you're not a bot"))

    assert "YTDLP_COOKIES_FROM_BROWSER" in message
    assert "不要把 Cookie 发到聊天" in message


def test_locked_browser_cookie_database_has_actionable_guidance(monkeypatch):
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")

    message = video_service.friendly_error(RuntimeError("Could not copy Chrome cookie database"))

    assert "完全退出该浏览器" in message
    assert "edge" in message


def test_dpapi_failure_explains_browser_encryption_limit():
    message = video_service.friendly_error(RuntimeError("Failed to decrypt with DPAPI"))

    assert "不会绕过浏览器加密" in message
    assert "YTDLP_COOKIES_FROM_BROWSER=firefox" in message