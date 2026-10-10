"""Read-only Douyin metadata diagnosis. No .env, database, ASR or LLM imports."""
import argparse
import json
import time

from fastapi import HTTPException

from . import douyin


def probe(url):
    observations = []
    started = time.monotonic()
    report = {"status": "FAILED", "attempts": observations, "paid_calls": 0}
    try:
        video = douyin.resolve_video(url, on_probe=observations.append)
        report.update(status="PASSED", video_id=video.video_id, duration=video.duration,
                      media_url_count=len(video.media_urls))
    except douyin.DouyinError as error:
        report["error_code"] = error.code
    except HTTPException:
        report["error_code"] = "URL_REJECTED"
    except Exception as error:
        # No exception text: HTTP/proxy failures can contain credentials or URLs.
        report["error_code"] = "DIAGNOSIS_FAILED"
        report["error_type"] = type(error).__name__
    report["seconds"] = round(time.monotonic() - started, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description="Free, sanitized public Douyin metadata check")
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    report = probe(args.url)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
