"""One explicit live Q&A call against a server using a copied learning DB.

Unlike pytest fixtures this uses the configured paid model. Supply both arguments
explicitly; reconnect only observes the submitted job and never resubmits it.
"""

import argparse
import json
import time
import uuid
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = args.base_url.rstrip("/") + "/api/v1"
    endpoint = root + "/analyses/" + args.record_id
    report = {"simulation": False, "record_id": args.record_id, "ok": False}
    started = time.monotonic()
    with httpx.Client(timeout=200, trust_env=False) as client:
        config = client.get(root + "/ai/config").json()
        report["model"] = config.get("model")
        if not config.get("configured"):
            raise SystemExit("Live model key is not configured; no request submitted.")
        before = client.get(endpoint).json()["usage"]
        response = client.post(endpoint + "/chat", json={
            "question": "请依据视频字幕，用三个要点概括核心内容，并引用支持这些要点的原文。",
            "request_id": "live-sse-" + uuid.uuid4().hex, "stream": True,
        })
        if response.status_code != 202:
            raise SystemExit("Live chat submission failed with HTTP " + str(response.status_code))
        submitted = response.json()
        report["message_id"] = submitted["message_id"]
        stream_url = endpoint + "/messages/" + submitted["message_id"] + "/stream"
        event_name, data, drafts, result = "", [], [], None
        with client.stream("GET", stream_url) as stream:
            for line in stream.iter_lines():
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif not line and data:
                    payload = json.loads("\n".join(data)); data = []
                    if event_name == "snapshot" and payload.get("text"):
                        if not drafts:
                            report["first_text_seconds"] = round(time.monotonic() - started, 3)
                        drafts.append(payload["text"])
                    elif event_name in {"complete", "failed", "removed"}:
                        report["terminal"] = event_name
                        result = payload
                        break
        report["total_seconds"] = round(time.monotonic() - started, 3)
        report["text_snapshots"] = len(drafts)
        report["distinct_text_snapshots"] = len(set(drafts))
        saved = next((message for message in client.get(endpoint + "/messages").json()["items"]
                      if message["id"] == submitted["message_id"]), None)
        after = client.get(endpoint).json()["usage"]
        report["usage_delta"] = {key: after[key] - before.get(key, 0) for key in after}
        if saved and saved["status"] == "ready" and saved.get("answer"):
            report["answer"] = saved["answer"]
            allowed = {cue["id"] for cue in client.get(endpoint + "/transcript?limit=200").json()["items"]}
            total = client.get(endpoint + "/transcript?limit=200").json()["total"]
            for offset in range(200, total, 200):
                allowed.update(cue["id"] for cue in client.get(endpoint + f"/transcript?limit=200&offset={offset}").json()["items"])
            report["references_valid"] = bool(saved["answer"]["cue_ids"]) and set(saved["answer"]["cue_ids"]) <= allowed
            # Opening a completed stream reads the saved answer, never starts AI.
            completed = client.get(stream_url)
            report["reopen_complete"] = completed.status_code == 200 and "event: complete" in completed.text
            report["reopen_usage_unchanged"] = client.get(endpoint).json()["usage"] == after
            report["ok"] = bool(result and report["terminal"] == "complete" and len(set(drafts)) > 1
                                and report["references_valid"] and report["reopen_complete"] and report["reopen_usage_unchanged"])
        elif saved:
            report["error_code"] = saved.get("error_code")
            report["error"] = saved.get("error")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "answer"}, ensure_ascii=False))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
