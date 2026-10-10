"""Explicit real Bilibili -> ASR -> LLM -> browser acceptance, no cloud mocks.

Run via test-bilibili-e2e.ps1 with process or project-root .env credentials. Isolated
learning databases share the FIRST live ASR ledger; nothing is reset or deleted.
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
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn

from tests.e2e_metrics import Metrics

ROOT = Path(__file__).resolve().parents[2]
LEDGER_ROOT = ROOT / ".local" / "asr-live-first"


def write_json(path, data):
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def ensure(condition, code):
    if not condition:
        from app.analysis_errors import AnalysisError
        raise AnalysisError(code, "本地端到端检查未通过，详见脱敏报告。")


def validate_cues(cues, source, duration):
    import math
    ensure(bool(cues), "E2E_EMPTY_CUES")
    previous = -1
    for cue in cues:
        ensure(cue.get("source") == source and isinstance(cue.get("text"), str)
               and bool(cue["text"].strip()), "E2E_WRONG_SUBTITLE_SOURCE")
        start, end = cue.get("start"), cue.get("end")
        ensure(type(start) in {int, float} and type(end) in {int, float}
               and math.isfinite(start) and math.isfinite(end) and 0 <= start < end
               and start >= previous and (not duration or end <= duration + 3), "E2E_INVALID_TIMELINE")
        previous = start


def api(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code >= 400:
        from app.analysis_errors import AnalysisError
        try:
            code = response.json()["detail"]["code"]
        except (ValueError, KeyError, TypeError):
            code = "E2E_HTTP_FAILED"
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", code):
            code = "E2E_HTTP_FAILED"
        raise AnalysisError(code, "本地 API 检查失败。", response.status_code)
    return response


def wait_record(client, record_id, field, timeout):
    deadline = time.monotonic() + timeout
    while True:
        record = api(client, "GET", "/api/v1/analyses/" + record_id).json()
        status = record[field]
        if status == "ready":
            return record
        if status in {"failed", "unavailable", "interrupted"}:
            from app.analysis_errors import AnalysisError
            code = record.get("subtitle_error_code") if field == "subtitle_status" else next(
                (j.get("error_code") for j in record.get("jobs", []) if j["kind"] == "summary" and j["status"] == "failed"), None)
            raise AnalysisError(code or "E2E_JOB_FAILED", "任务失败，未自动重新提交。")
        ensure(time.monotonic() < deadline, "E2E_WAIT_TIMEOUT")
        time.sleep(0.25)


def trace_llm_pool(engine, report, metrics, state_path, save):
    """Persist transport intent; never retry an uncertain identical paid request."""
    original = engine.model_http.stream
    try:
        ledger = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        ledger = {}

    @contextmanager
    def observed(payload, api_key, deadline, check):
        key = hashlib.sha256(payload).hexdigest()
        prior = ledger.get(key, {})
        ensure(prior.get("state") not in {"submitting", "unknown", "response_received"}, "E2E_LLM_SUBMISSION_UNKNOWN")
        ensure(prior.get("attempts", 0) < 3, "E2E_LLM_RETRY_LIMIT")
        entry = {"state": "submitting", "started_utc": datetime.now(timezone.utc).isoformat(),
                 "attempts": prior.get("attempts", 0) + 1}
        ledger[key] = entry
        write_json(state_path, ledger)
        call = {"index": len(report["llm_requests"]) + 1, "state": "submitting"}
        report["llm_requests"].append(call)
        save()
        try:
            with metrics.phase("deepseek_http"), original(payload, api_key, deadline, check) as response:
                call["http_status"] = response.status_code
                entry["http_status"] = response.status_code
                # 5xx can be ambiguous; clear 4xx rejection is safe to diagnose.
                entry["state"] = "rejected" if 400 <= response.status_code < 500 else "unknown"
                write_json(state_path, ledger)
                yield response
                if response.status_code == 200:
                    entry["state"] = "response_received"
                call["state"] = entry["state"]
        except BaseException:
            call["state"] = entry["state"] = "unknown" if entry["state"] != "rejected" else "rejected"
            raise
        finally:
            write_json(state_path, ledger)
            save()

    engine.model_http.stream = observed


def run(args):
    mode = args.mode
    folder = Path(args.output).resolve()
    ensure(folder.is_relative_to(LEDGER_ROOT / "bilibili-e2e"), "E2E_OUTPUT_PATH_INVALID")
    ensure((LEDGER_ROOT / "asr.sqlite3").is_file(), "E2E_EXISTING_LEDGER_REQUIRED")
    folder.mkdir(parents=True, exist_ok=True)
    # All changes affect this test process only. Browser Cookie logic is untouched.
    os.environ.update({"VIDEO_LEARNING_DB": str(LEDGER_ROOT / ("bilibili-" + mode + ".sqlite3")),
        "ASR_TEMP_DIR": str(LEDGER_ROOT / "asr-tmp"), "ASR_ENABLED": "true",
        "BILIBILI_METADATA_SOURCE": "api", "BILIBILI_USE_FIREFOX_SESSION": "1" if mode == "native" else "0",
        "VIDEO_LEARNING_FIREFOX_SESSION": "1" if mode == "native" else "0",
        "MEMBERSHIP_SERVICE_URL": "", "ALLOWED_HOSTS": "localhost,127.0.0.1",
        "ALLOWED_ORIGINS": "http://localhost:8000,http://127.0.0.1:8000"})
    logging.disable(logging.CRITICAL)
    from app import subtitle_service
    from app.ai_config import get_config
    from app.analysis_jobs import get_engine
    from app.main import app
    from app.asr.temporary import file_slot
    from tests.asr_live_support import CHECKS, ObservedParaformer, ObservedStorage

    _, url = subtitle_service.platform_url(args.url)
    ensure(subtitle_service.platform_url(url)[0] == "Bilibili", "E2E_BILIBILI_REQUIRED")
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

    report = {"mode": mode, "url": url, "status": "RUNNING", "simulation": False,
        "started_utc": datetime.now(timezone.utc).isoformat(), "checks": {}, "llm_requests": [],
        "asr": {"checks": dict.fromkeys(CHECKS), "asr_submit_requests": 0,
                "asr_query_requests": 0, "cloud_responses": []},
        "scope": "Real platform/API/OSS/LLM and read-only browser acceptance; isolated learning DB, shared existing ASR ledger; membership/payment excluded."}
    metrics = Metrics()
    metrics.start()

    def save():
        write_json(folder / "report.json", report)

    engine = None
    original_native = subtitle_service.extract_transcript
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, workers=1,
        access_log=False, log_config=None, log_level="critical", ws="none", proxy_headers=False))
    thread = threading.Thread(target=server.run, daemon=True)
    try:
        with file_slot(LEDGER_ROOT / "live-check.lock") as acquired:
            ensure(acquired, "E2E_ANOTHER_LIVE_TEST_RUNNING")
            engine = get_engine()
            engine.asr.config.require()
            report["asr_usage_before"] = engine.asr.store.usage_report()
            engine.asr.storage = ObservedStorage(engine.asr.storage, report["asr"], save,
                                                 verification_limit=engine.asr.config.max_audio_bytes)
            engine.asr.provider = ObservedParaformer(engine.asr.config, report["asr"], save)
            for obj, method, name in [(engine.asr.storage, "connect", "oss_acl"),
                    (engine.asr.storage, "upload", "oss_upload_sign_verify"),
                    (engine.asr.storage, "delete", "oss_delete_verify"),
                    (engine.asr.provider, "submit", "paraformer_submit"),
                    (engine.asr.provider, "query", "paraformer_query"),
                    (engine.asr, "audio", "audio_extract_and_ffmpeg"),
                    (engine.asr, "read_result", "transcription_result_download")]:
                metrics.wrap(obj, method, name)
            metrics.wrap(subtitle_service, "extract_transcript", "native_subtitle_attempt")
            if mode == "native":
                def no_paid_fallback(*a, **kw):
                    ensure(False, "E2E_NATIVE_FALLBACK_BLOCKED")
                engine.asr.transcribe = no_paid_fallback
            trace_llm_pool(engine, report, metrics, LEDGER_ROOT / "bilibili-llm-ledger.json", save)
            save()
            thread.start()
            deadline = time.monotonic() + 20
            while not server.started:
                ensure(thread.is_alive() and time.monotonic() < deadline, "E2E_SERVER_START_FAILED")
                time.sleep(0.1)
            with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30, trust_env=False) as client:
                with metrics.phase("bilibili_download_parse"):
                    parsed = api(client, "POST", "/api/v1/parse", json={"url": url}).json()
                    report["download_parse"] = {"formats": len(parsed.get("formats") or []),
                        "duration": parsed.get("duration"), "success": True}
                with metrics.phase("transcript_api_end_to_end"):
                    created = api(client, "POST", "/api/v1/analyses", json={"url": url, "auto_summary": False}).json()
                    rid = report["record_id"] = created["id"]
                    record = wait_record(client, rid, "subtitle_status", engine.asr.config.job_timeout + 60)
                    cues = engine.store.cues(rid)
                    validate_cues(cues, "native_subtitle" if mode == "native" else "asr", record["duration"])
                    report["subtitle"] = {"count": len(cues), "duration": record["duration"],
                        "track_kind": record["track_kind"], "first_start": cues[0]["start"], "last_end": cues[-1]["end"]}
                    write_json(folder / "transcript.json", {"cues": cues})
                    report["checks"]["expected_subtitle_source"] = True
                    if mode == "native":
                        ensure(report["asr"]["asr_submit_requests"] == 0
                               and not report["asr"]["checks"]["uploaded"], "E2E_NATIVE_SPENT_ASR")
                        report["checks"]["native_no_asr"] = True
                    else:
                        identity = hashlib.sha256((url + ":" + engine.asr.config.fingerprint("auto")).encode()).hexdigest()
                        task = engine.asr.store.video_task(identity)
                        ensure(task and task["task_id"] and task["state"] == "ready", "E2E_ASR_TASK_NOT_SAVED")
                        report["asr"]["task"] = {key: task[key] for key in (
                            "task_id", "state", "calls", "duration", "estimated_cny", "reported_seconds", "actual_billed_cny")}
                        report["asr"]["execution"] = ("new_submission" if report["asr"]["asr_submit_requests"] else
                            "resumed_original_task" if report["asr"]["asr_query_requests"] else "cached_result")
                        if report["asr"]["asr_submit_requests"]:
                            ensure(all(report["asr"]["checks"][key] is True for key in (
                                "private_bucket", "uploaded", "unsigned_access_denied", "signed_https",
                                "short_lived_signature", "signed_audio_matches", "provider_succeeded", "object_deleted")),
                                "E2E_ASR_OBSERVATION_INCOMPLETE")
                with metrics.phase("summary_api_end_to_end"):
                    prior = api(client, "GET", f"/api/v1/analyses/{rid}/summary").json()
                    if prior["status"] in {"failed", "interrupted"}:
                        ensure(False, "E2E_PRIOR_SUMMARY_FAILED_NO_AUTO_RETRY")
                    api(client, "POST", f"/api/v1/analyses/{rid}/summary", json={"force": False, "stream": True})
                    wait_record(client, rid, "summary_status", get_config().summary_timeout + 30)
                    summary = api(client, "GET", f"/api/v1/analyses/{rid}/summary").json()
                    ensure(bool(summary.get("summary", {}).get("content", {}).get("chapters")), "E2E_SUMMARY_INVALID")
                    ensure(bool(summary["summary"]["mindmap"]["children"]), "E2E_MINDMAP_INVALID")
                    write_json(folder / "summary.json", summary)
                    report["checks"].update(summary=True, mindmap_data=True)
                with metrics.phase("chat_api_end_to_end"):
                    # Stable id gives one question per record, including subsequent runs.
                    question_id = "bilibili-e2e-core-question-v1"
                    chat = api(client, "POST", f"/api/v1/analyses/{rid}/chat", json={
                        "question": "请根据字幕概括视频的主要内容，并引用对应字幕。", "request_id": question_id, "stream": True}).json()
                    deadline = time.monotonic() + get_config().request_timeout + 30
                    while True:
                        messages = api(client, "GET", f"/api/v1/analyses/{rid}/messages").json()["items"]
                        message = next(m for m in messages if m["id"] == chat["message_id"])
                        if message["status"] == "ready":
                            break
                        ensure(message["status"] not in {"failed", "interrupted"}, "E2E_CHAT_FAILED_NO_AUTO_RETRY")
                        ensure(time.monotonic() < deadline, "E2E_CHAT_TIMEOUT_NO_AUTO_RETRY")
                        time.sleep(0.25)
                    ensure(bool(message["answer"]["answer"]) and bool(message["answer"]["references"]), "E2E_CHAT_INVALID")
                    write_json(folder / "messages.json", {"items": messages})
                    report["checks"]["chat"] = True
                with metrics.phase("subtitle_and_summary_api_exports"):
                    for extension in ("srt", "txt", "markdown"):
                        exported = api(client, "GET", f"/api/v1/analyses/{rid}/export?format={extension}").text
                        ensure(bool(exported.strip()), "E2E_EXPORT_EMPTY")
                        if extension != "markdown":
                            ensure(all(c["text"] in exported for c in cues), "E2E_EXPORT_INCOMPLETE")
                        (folder / ("export." + ("md" if extension == "markdown" else extension))).write_text(exported, encoding="utf-8")
                    report["checks"]["api_exports"] = True
                usage_before_ui = engine.store.usage(rid)
                with metrics.phase("browser_mindmap_chat_exports"):
                    result = subprocess.run([node, str(ROOT / "frontend/tests/bilibili-real-e2e.cjs"), rid, str(folder)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
                    report["browser"] = json.loads((folder / "browser-report.json").read_text(encoding="utf-8"))
                    ensure(result.returncode == 0 and report["browser"]["status"] == "PASSED", "E2E_BROWSER_FAILED")
                    ensure(engine.store.usage(rid) == usage_before_ui, "E2E_BROWSER_TRIGGERED_MODEL")
                    report["checks"]["browser_readonly_acceptance"] = True
                report["llm_usage"] = engine.store.usage(rid)
                report["status"] = "PASSED"
    except BaseException as error:
        code = getattr(error, "code", "E2E_INTERRUPTED")
        report.update(status="FAILED", error_code=code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", code) else "E2E_INTERRUPTED")
    finally:
        server.should_exit = True
        if thread.ident is not None:
            thread.join(timeout=15)
        # Only the isolated test engine is closed; existing services are untouched.
        if engine is not None:
            engine.close()
        subtitle_service.extract_transcript = original_native
        if engine is not None:
            report["asr_usage_after"] = engine.asr.store.usage_report()
            report["pending_object_cleanup"] = len(engine.asr.store.artifacts())
            if report.get("record_id"):
                report["llm_usage"] = engine.store.usage(report["record_id"])
        report["metrics"] = metrics.finish(folder)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        if report.get("pending_object_cleanup"):
            report.update(status="FAILED", error_code="E2E_OSS_CLEANUP_PENDING")
        save()
    print("BILIBILI_E2E_RESULT=" + json.dumps({"mode": mode, "status": report["status"],
        "record_id": report.get("record_id"), "error_code": report.get("error_code"),
        "asr_submit_requests": report["asr"]["asr_submit_requests"], "llm_requests": len(report["llm_requests"]),
        "peak_backend_rss_mib": report["metrics"]["peak_backend_rss_mib"]}, ensure_ascii=True))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("native", "anonymous"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    try:
        ensure(os.getenv("ASR_RUN_BILIBILI_E2E") == "1", "E2E_EXPLICIT_OPT_IN_REQUIRED")
        raise SystemExit(run(arguments))
    except Exception as error:
        # No exception repr, traceback, response bodies, keys or signed URLs.
        code = getattr(error, "code", "E2E_PREFLIGHT_FAILED")
        print("BILIBILI_E2E_PREFLIGHT=" + (code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", code) else "E2E_PREFLIGHT_FAILED"))
        raise SystemExit(1) from None
