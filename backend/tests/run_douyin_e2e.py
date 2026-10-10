"""Explicit PAID Douyin acceptance; preserves the existing ASR ledger.

No cloud mocks. One normal summary operation; no new paid chat request.
Run only via test-douyin-e2e.ps1 with process or project-root .env credentials.
"""
import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn

from tests.e2e_metrics import Metrics
from tests.run_bilibili_e2e import api, ensure, trace_llm_pool, validate_cues, wait_record, write_json

ROOT = Path(__file__).resolve().parents[2]
LEDGER_ROOT = ROOT / ".local" / "asr-live-first"


def run(args):
    ensure(os.getenv("ASR_RUN_DOUYIN_E2E") == "1", "E2E_EXPLICIT_OPT_IN_REQUIRED")
    folder = Path(args.output).resolve()
    ensure(folder.is_relative_to(LEDGER_ROOT / "douyin-e2e"), "E2E_OUTPUT_PATH_INVALID")
    ensure((LEDGER_ROOT / "asr.sqlite3").is_file(), "E2E_EXISTING_LEDGER_REQUIRED")
    folder.mkdir(parents=True, exist_ok=True)
    # This process only: production config and Firefox login code stay untouched.
    os.environ.update({"ASR_TEMP_DIR": str(LEDGER_ROOT / "asr-tmp"), "ASR_ENABLED": "true",
        "VIDEO_LEARNING_FIREFOX_SESSION": "0", "MEMBERSHIP_SERVICE_URL": "",
        "ALLOWED_HOSTS": "localhost,127.0.0.1",
        "ALLOWED_ORIGINS": "http://localhost:8000,http://127.0.0.1:8000"})
    logging.disable(logging.CRITICAL)
    from app import subtitle_service
    from app.ai_config import get_config
    from app.analysis_jobs import get_engine
    from app.asr.temporary import file_slot
    from app.main import app
    from tests.asr_live_support import CHECKS, ObservedParaformer, ObservedStorage

    platform, url = subtitle_service.platform_url(args.url)
    ensure(platform == "Douyin", "E2E_DOUYIN_REQUIRED")
    identity = hashlib.sha256(url.encode()).hexdigest()[:16]
    os.environ["VIDEO_LEARNING_DB"] = str(LEDGER_ROOT / ("douyin-" + identity + ".sqlite3"))
    get_config().require_key()  # Fail before ASR spending if summary cannot run.
    node = shutil.which("node")
    ensure(node is not None and (ROOT / "frontend/dist/index.html").is_file(), "E2E_FRONTEND_MISSING")
    ensure(subprocess.run([node, "-e", "require('playwright')"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, timeout=15).returncode == 0, "E2E_PLAYWRIGHT_MISSING")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError:
            ensure(False, "E2E_PORT_8000_IN_USE")

    report = {"platform": "Douyin", "url": url, "status": "RUNNING", "simulation": False,
        "started_utc": datetime.now(timezone.utc).isoformat(), "checks": {}, "llm_requests": [],
        "asr": {"checks": dict.fromkeys(CHECKS), "asr_submit_requests": 0,
                "asr_query_requests": 0, "cloud_responses": []},
        "scope": "Real Douyin/OSS/Paraformer/summary and read-only browser; shared ASR ledger; no paid chat, membership/payment or production changes."}
    metrics = Metrics()
    metrics.start()
    save = lambda: write_json(folder / "report.json", report)
    engine = None
    original_native = subtitle_service.extract_transcript
    temporary_before = set()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, workers=1,
        access_log=False, log_config=None, log_level="critical", ws="none", proxy_headers=False))
    thread = threading.Thread(target=server.run, daemon=True)
    try:
        with file_slot(LEDGER_ROOT / "live-check.lock") as acquired:
            ensure(acquired, "E2E_ANOTHER_LIVE_TEST_RUNNING")
            engine = get_engine()
            temporary_before = {p.name for p in engine.asr.config.temp_root.iterdir() if p.is_dir()}
            engine.asr.config.require()
            report["asr_usage_before"] = engine.asr.store.usage_report()
            engine.asr.storage = ObservedStorage(engine.asr.storage, report["asr"], save,
                                                 verification_limit=engine.asr.config.max_audio_bytes)
            engine.asr.provider = ObservedParaformer(engine.asr.config, report["asr"], save)
            original_submit = engine.asr.provider.submit
            def submit_once(*a, **kw):
                ensure(report["asr"]["asr_submit_requests"] == 0, "E2E_ASR_SECOND_SUBMISSION_BLOCKED")
                return original_submit(*a, **kw)
            engine.asr.provider.submit = submit_once
            for obj, method, name in [(engine.asr.storage, "connect", "oss_acl"),
                    (engine.asr.storage, "upload", "oss_upload_sign_verify"),
                    (engine.asr.storage, "delete", "oss_delete_verify"),
                    (engine.asr.provider, "submit", "paraformer_submit"),
                    (engine.asr.provider, "query", "paraformer_query"),
                    (engine.asr, "audio", "audio_extract_and_ffmpeg"),
                    (engine.asr, "read_result", "transcription_result_download")]:
                metrics.wrap(obj, method, name)
            metrics.wrap(subtitle_service, "extract_transcript", "native_subtitle_attempt")
            trace_llm_pool(engine, report, metrics, LEDGER_ROOT / "douyin-llm-ledger.json", save)
            save()
            thread.start()
            deadline = time.monotonic() + 20
            while not server.started:
                ensure(thread.is_alive() and time.monotonic() < deadline, "E2E_SERVER_START_FAILED")
                time.sleep(0.1)
            with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30, trust_env=False) as client:
                with metrics.phase("douyin_download_parse"):
                    parsed = api(client, "POST", "/api/v1/parse", json={"url": url}).json()
                    ensure(parsed.get("extractor") == "Douyin" and parsed.get("formats"), "E2E_PARSE_INVALID")
                    report["download_parse"] = {"formats": len(parsed["formats"]), "duration": parsed.get("duration")}
                    report["estimated_asr_cny"] = round((parsed.get("duration") or 0) * engine.asr.config.price_per_second, 6)
                with metrics.phase("transcript_api_end_to_end"):
                    created = api(client, "POST", "/api/v1/analyses", json={"url": url, "auto_summary": False}).json()
                    rid = report["record_id"] = created["id"]
                    record = wait_record(client, rid, "subtitle_status", engine.asr.config.job_timeout + 60)
                    cues = engine.store.cues(rid)
                    source = "asr" if record["track_kind"] == "asr" else "native_subtitle"
                    validate_cues(cues, source, record["duration"])
                    if source == "asr":
                        report["asr"]["checks"]["subtitle_valid"] = True
                    report["subtitle"] = {"count": len(cues), "duration": record["duration"], "source": source,
                                          "first_start": cues[0]["start"], "last_end": cues[-1]["end"]}
                    write_json(folder / "transcript.json", {"cues": cues})
                    if source == "asr":
                        cache_key = hashlib.sha256((url + ":" + engine.asr.config.fingerprint("auto")).encode()).hexdigest()
                        task = engine.asr.store.video_task(cache_key)
                        ensure(task and task["task_id"] and task["state"] == "ready", "E2E_ASR_TASK_NOT_SAVED")
                        report["asr"]["checks"]["task_id_saved"] = True
                        report["asr"]["task"] = {key: task[key] for key in ("task_id", "state", "calls", "duration",
                            "estimated_cny", "reported_seconds", "actual_billed_cny")}
                        report["asr"]["execution"] = ("new_submission" if report["asr"]["asr_submit_requests"] else
                            "resumed_original_task" if report["asr"]["asr_query_requests"] else "cached_result")
                    else:
                        ensure(report["asr"]["asr_submit_requests"] == 0, "E2E_NATIVE_SPENT_ASR")
                        report["asr"]["execution"] = "native_subtitle"
                    if report["asr"]["asr_submit_requests"]:
                        ensure(all(report["asr"]["checks"][key] is True for key in ("private_bucket", "uploaded",
                            "unsigned_access_denied", "signed_https", "short_lived_signature", "signed_audio_matches",
                            "provider_succeeded", "object_deleted")), "E2E_ASR_OBSERVATION_INCOMPLETE")
                    report["checks"]["subtitle_timeline"] = True
                with metrics.phase("summary_api_end_to_end"):
                    prior = api(client, "GET", f"/api/v1/analyses/{rid}/summary").json()
                    ensure(prior["status"] not in {"failed", "interrupted"}, "E2E_PRIOR_SUMMARY_FAILED_NO_AUTO_RETRY")
                    api(client, "POST", f"/api/v1/analyses/{rid}/summary", json={"force": False, "stream": True})
                    wait_record(client, rid, "summary_status", get_config().summary_timeout + 30)
                    summary = api(client, "GET", f"/api/v1/analyses/{rid}/summary").json()
                    ensure(summary["summary"]["content"]["chapters"] and summary["summary"]["mindmap"]["children"], "E2E_SUMMARY_INVALID")
                    write_json(folder / "summary.json", summary)
                    write_json(folder / "messages.json", {"items": api(client, "GET", f"/api/v1/analyses/{rid}/messages").json()["items"]})
                    report["checks"].update(summary=True, mindmap_data=True)
                with metrics.phase("repeat_cache_and_exports"):
                    repeated = api(client, "POST", "/api/v1/analyses", json={"url": url, "auto_summary": False}).json()
                    ensure(repeated["cached"] and repeated["id"] == rid, "E2E_REPEAT_CACHE_FAILED")
                    if source == "asr":
                        report["asr"]["checks"]["repeat_cache_hit"] = True
                    for extension in ("srt", "txt", "markdown"):
                        exported = api(client, "GET", f"/api/v1/analyses/{rid}/export?format={extension}").text
                        ensure(exported.strip() and (extension == "markdown" or all(c["text"] in exported for c in cues)), "E2E_EXPORT_INCOMPLETE")
                    report["checks"].update(repeat_cache=True, api_exports=True)
                usage_before_ui = engine.store.usage(rid)
                save()
                with metrics.phase("browser_readonly_acceptance"):
                    result = subprocess.run([node, str(ROOT / "frontend/tests/bilibili-real-e2e.cjs"), rid, str(folder)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
                    report["browser"] = json.loads((folder / "browser-report.json").read_text(encoding="utf-8"))
                    ensure(result.returncode == 0 and report["browser"]["status"] == "PASSED", "E2E_BROWSER_FAILED")
                    ensure(engine.store.usage(rid) == usage_before_ui, "E2E_BROWSER_TRIGGERED_MODEL")
                report["status"] = "PASSED"
    except BaseException as error:
        code = getattr(error, "code", "E2E_INTERRUPTED")
        report.update(status="FAILED", error_code=code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", code) else "E2E_INTERRUPTED")
    finally:
        server.should_exit = True
        if thread.ident is not None:
            thread.join(timeout=15)
        if engine is not None:
            engine.close()
            subtitle_service.extract_transcript = original_native
            report["asr_usage_after"] = engine.asr.store.usage_report()
            report["pending_object_cleanup"] = len(engine.asr.store.artifacts())
            temporary_after = {p.name for p in engine.asr.config.temp_root.iterdir() if p.is_dir()}
            report["asr"]["checks"]["local_tmp_cleaned"] = temporary_after.issubset(temporary_before)
            if not report["asr"]["checks"]["local_tmp_cleaned"]:
                report.update(status="FAILED", error_code="E2E_LOCAL_CLEANUP_PENDING")
            if report.get("record_id"):
                report["llm_usage"] = engine.store.usage(report["record_id"])
        report["metrics"] = metrics.finish(folder)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        if report.get("pending_object_cleanup"):
            report.update(status="FAILED", error_code="E2E_OSS_CLEANUP_PENDING")
        save()
    print("DOUYIN_E2E_RESULT=" + json.dumps({"status": report["status"], "record_id": report.get("record_id"),
        "error_code": report.get("error_code"), "asr_submit_requests": report["asr"]["asr_submit_requests"],
        "llm_requests": len(report["llm_requests"]), "peak_backend_rss_mib": report["metrics"]["peak_backend_rss_mib"]}))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    try:
        raise SystemExit(run(parser.parse_args()))
    except Exception as error:
        code = getattr(error, "code", "E2E_PREFLIGHT_FAILED")
        print("DOUYIN_E2E_PREFLIGHT=" + (code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", code) else "E2E_PREFLIGHT_FAILED"))
        raise SystemExit(1) from None
