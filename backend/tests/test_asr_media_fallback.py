"""Offline regression for Bilibili's nonstandard-port CDN primary URLs.

No real platform, OSS or paid ASR calls. Existing download security is retained.
"""
import errno
import http.client

import pytest

from app.analysis_errors import AnalysisError, JobStopped
from app.asr import audio_worker


PRIMARY = "https://peer.mcdn.bilivideo.cn:8082/audio.m4s?token=private-primary"
SECONDARY = "https://peer.example:4483/audio.m4s?token=private-secondary"
BACKUP = "https://upos.example/audio.m4s?token=a%2Bb%2Fc&expires=123"


def media():
    return {"url": PRIMARY, "_platform_backup_urls": [SECONDARY, BACKUP],
            "protocol": "https", "vcodec": "none", "acodec": "aac", "abr": 64}


def fetch(fmt, target):
    return audio_worker.download_media(fmt, target, 1024, lambda: None, {"Referer": "https://www.bilibili.com/"})


def test_nonstandard_primary_uses_identical_audio_https_backup(tmp_path, monkeypatch):
    fmt = media()
    progressive = {"url": "https://video.example/video.mp4", "vcodec": "h264", "acodec": "aac", "tbr": 16}
    selected = audio_worker.select_media({"formats": [progressive, fmt]})
    calls = []

    def download(url, destination, limit, check, headers):
        calls.append((url, limit, headers))
        destination.write_bytes(b"complete-audio")

    monkeypatch.setattr(audio_worker, "download", download)
    target = tmp_path / "source.media"
    fetch(selected, target)
    assert selected is fmt  # Do not silently select a video-only/lower track.
    assert calls == [(BACKUP, 1024, {"Referer": "https://www.bilibili.com/"})]
    assert fmt["url"] == PRIMARY and fmt["_platform_backup_urls"] == [SECONDARY, BACKUP]
    assert target.read_bytes() == b"complete-audio"


@pytest.mark.parametrize("url", [
    "http://cdn.example/audio", "https://cdn.example:4483/audio", "https://cdn.example:8082/audio",
    "https://user:password@cdn.example/audio", "https://cdn.example:wrong/audio",
    "file:///etc/passwd", "https://[invalid/audio", "https://cdn.example/audio\r\nInjected:value",
])
def test_unsupported_candidate_cannot_be_requested(tmp_path, monkeypatch, url):
    monkeypatch.setattr(audio_worker, "download", lambda *a: pytest.fail("unsafe candidate requested"))
    fmt = {"url": url}
    assert audio_worker.media_candidates(fmt) == []
    with pytest.raises(AnalysisError) as caught:
        fetch(fmt, tmp_path / "source.media")
    assert caught.value.code == "ASR_AUDIO_UNAVAILABLE"


def test_standard_primary_is_retained_and_candidates_are_deduplicated():
    assert audio_worker.media_candidates({"url": BACKUP, "_platform_backup_urls": [BACKUP, PRIMARY]}) == [BACKUP]


def test_audio_without_safe_backup_is_not_selected_over_usable_video():
    video = {"url": "https://video.example/file.mp4", "vcodec": "h264", "acodec": "aac"}
    assert audio_worker.select_media({"formats": [{**media(), "_platform_backup_urls": []}, video]}) is video


@pytest.mark.parametrize("failure", [
    AnalysisError("ASR_RESOURCE_FAILED", "无法下载"),
    OSError("private-url-do-not-show"),
    http.client.IncompleteRead(b"partial", 100),
])
def test_transport_failure_tries_backup_and_removes_partial(tmp_path, monkeypatch, failure):
    calls = []
    target = tmp_path / "source.media"

    def download(url, destination, *args):
        calls.append(url)
        if len(calls) == 1:
            destination.write_bytes(b"partial")
            raise failure
        assert not destination.exists()
        destination.write_bytes(b"complete")

    monkeypatch.setattr(audio_worker, "download", download)
    fetch({"url": "https://first.example/audio", "_platform_backup_urls": [BACKUP]}, target)
    assert calls == ["https://first.example/audio", BACKUP]
    assert target.read_bytes() == b"complete"


@pytest.mark.parametrize("failure", [
    AnalysisError("ASR_URL_UNSAFE", "内网重定向"),
    AnalysisError("ASR_FILE_TOO_LARGE", "文件超限"),
    AnalysisError("ASR_TIMEOUT", "任务超时"),
    JobStopped(),
])
def test_security_resource_limits_and_cancellation_do_not_try_backup(tmp_path, monkeypatch, failure):
    calls = []

    def download(url, *args):
        calls.append(url)
        raise failure

    monkeypatch.setattr(audio_worker, "download", download)
    with pytest.raises(type(failure)):
        fetch({"url": "https://first.example/audio", "_platform_backup_urls": [BACKUP]}, tmp_path / "source.media")
    assert calls == ["https://first.example/audio"]


def test_backup_attempts_are_finite_and_transport_details_are_redacted(tmp_path, monkeypatch):
    calls = []
    target = tmp_path / "source.media"

    def download(url, destination, *args):
        calls.append(url)
        destination.write_bytes(b"partial")
        raise OSError("private-url-do-not-show")

    monkeypatch.setattr(audio_worker, "download", download)
    with pytest.raises(AnalysisError) as caught:
        fetch({"url": BACKUP, "_platform_backup_urls": [f"https://backup{i}.example/a" for i in range(10)]}, target)
    assert len(calls) == audio_worker.MAX_MEDIA_CANDIDATES == 4
    assert caught.value.code == "ASR_RESOURCE_FAILED"
    assert "private-url" not in str(caught.value)
    assert not target.exists()


@pytest.mark.parametrize("failure", [PermissionError("private-path"), OSError(errno.ENOSPC, "private-path")])
def test_local_storage_failure_is_not_retried_as_a_cdn_failure(tmp_path, monkeypatch, failure):
    calls = []

    def download(url, *args):
        calls.append(url)
        raise failure

    monkeypatch.setattr(audio_worker, "download", download)
    with pytest.raises(AnalysisError) as caught:
        fetch({"url": "https://first.example/audio", "_platform_backup_urls": [BACKUP]}, tmp_path / "source.media")
    assert caught.value.code == "ASR_TEMP_UNAVAILABLE"
    assert "private-path" not in str(caught.value)
    assert calls == ["https://first.example/audio"]
