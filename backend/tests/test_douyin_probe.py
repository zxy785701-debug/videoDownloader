"""Offline checks for bounded share-page recovery and secret-free diagnostics."""
import json
import logging

import httpx
import pytest

from app import douyin, douyin_probe
from test_douyin import MEDIA_URL, VIDEO_ID, VIDEO_URL, mock_upstream, offline_public_dns, share_html


def test_visitor_warmup_waits_and_preserves_same_cookie(mock_upstream, monkeypatch):
    waits, observations = [], []
    monkeypatch.setattr(douyin.time, "sleep", waits.append)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            assert "cookie" not in request.headers
            return httpx.Response(200, text="initializing", headers={"Set-Cookie": "ttwid=fake-private-cookie; Path=/; Secure"})
        assert request.headers["cookie"] == "ttwid=fake-private-cookie"
        return httpx.Response(200, text="still initializing" if len(calls) == 2 else share_html())

    mock_upstream(handler)
    video = douyin.resolve_video(VIDEO_URL, on_probe=observations.append)
    assert video.video_id == VIDEO_ID and len(calls) == 3
    assert waits == [0.5, 1.0]
    assert [step["parsed_item"] for step in observations] == [False, False, True]
    assert all(step["visitor_cookie_present"] for step in observations)


def test_ready_share_does_not_wait_or_refetch(mock_upstream, monkeypatch):
    monkeypatch.setattr(douyin.time, "sleep", lambda _: pytest.fail("No wait after a successful response"))
    requests = mock_upstream(lambda _: httpx.Response(200, text=share_html()))
    assert douyin.resolve_video(VIDEO_URL).video_id == VIDEO_ID
    assert len(requests) == 1


def test_empty_share_stops_at_three_and_trace_contains_no_body_or_cookie(mock_upstream, monkeypatch, caplog):
    waits, observations = [], []
    caplog.set_level(logging.INFO, logger="app.douyin")
    monkeypatch.setattr(douyin.time, "sleep", waits.append)
    requests = mock_upstream(lambda _: httpx.Response(200,
        text="fake-private-response " + MEDIA_URL,
        headers={"Set-Cookie": "ttwid=fake-private-cookie; Path=/; Secure"}))
    with pytest.raises(douyin.DouyinError) as error:
        douyin.resolve_video(VIDEO_URL, on_probe=observations.append)
    assert error.value.code == "DOUYIN_METADATA_EMPTY"
    assert len(requests) == 3 and waits == [0.5, 1.0]
    output = caplog.text + json.dumps(observations)
    assert "fake-private" not in output and MEDIA_URL not in output
    assert all(not step["parsed_item"] for step in observations)


@pytest.mark.parametrize("status", [403, 429, 500])
def test_http_denials_are_not_retried(mock_upstream, monkeypatch, status):
    monkeypatch.setattr(douyin.time, "sleep", lambda _: pytest.fail("Do not retry an HTTP denial"))
    requests = mock_upstream(lambda _: httpx.Response(status, text="fake-private-denial"))
    report = douyin_probe.probe(VIDEO_URL)
    assert report["status"] == "FAILED" and report["paid_calls"] == 0
    assert len(requests) == 1 and "fake-private" not in json.dumps(report)


def test_probe_success_reports_metadata_without_fetching_media(mock_upstream, tmp_path):
    requests = mock_upstream(lambda _: httpx.Response(200, text=share_html()))
    report = douyin_probe.probe(VIDEO_URL)
    assert report["status"] == "PASSED" and report["video_id"] == VIDEO_ID
    assert report["duration"] == 12.5 and report["media_url_count"] == 1
    assert report["paid_calls"] == 0 and len(requests) == 1
    assert requests[0].url.host == "www.iesdouyin.com"
    assert MEDIA_URL not in json.dumps(report) and not list(tmp_path.iterdir())


def test_probe_hides_unknown_exception_contents(monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("fake-private-credential " + MEDIA_URL)

    monkeypatch.setattr(douyin, "resolve_video", failed)
    report = douyin_probe.probe(VIDEO_URL)
    assert report["error_code"] == "DIAGNOSIS_FAILED" and report["error_type"] == "RuntimeError"
    assert "fake-private" not in json.dumps(report) and MEDIA_URL not in json.dumps(report)


def test_probe_rejects_untrusted_redirect_before_request(mock_upstream):
    requests = mock_upstream(lambda _: httpx.Response(302, headers={"Location": "http://127.0.0.1/private"}))
    report = douyin_probe.probe("https://v.douyin.com/short/")
    assert report["error_code"] == "URL_REJECTED" and report["paid_calls"] == 0
    assert len(requests) == 1
