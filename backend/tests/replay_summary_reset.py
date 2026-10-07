"""Replay a cached two-part summary with a truncated fake SSE response.

Reads the source database in read-only mode and runs the production task engine
on a unique local copy. All model responses use MockTransport and a fake key;
no network requests, paid calls or source database writes are performed.
"""

import argparse
import json
import sqlite3
import time
import uuid
from dataclasses import replace
from pathlib import Path

import httpx

from app import analysis_jobs, summary_service
from app.ai_config import get_config
from app.analysis_jobs import AnalysisEngine
from app.analysis_store import AnalysisStore
from app.deepseek_client import DeepSeekClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_db.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    copied = output_dir / ("replay-" + uuid.uuid4().hex + ".sqlite3")
    assert copied != source
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(copied) as destination:
            original.backup(destination)

    config = replace(get_config(), api_key="fake-local-replay-key")
    analysis_jobs.get_config = lambda: config
    store = AnalysisStore(copied)
    record = store.find(args.video_url, "auto")
    assert record, "The requested video is not cached locally."
    cues = store.cues(record["id"])
    chunks = summary_service.split_cues(cues, config.chunk_characters)
    assert len(chunks) == 2, "This regression replay expects the reported two-part video."
    calls, transitions = [], []

    def respond(request):
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert request.headers["Authorization"] == "Bearer fake-local-replay-key"
        user = json.loads(payload["messages"][1]["content"])
        ids = ([cue["id"] for cue in user["cues"]] if "cues" in user else
               sorted(set().union(*(summary_service.summary_ids(note) for note in user["notes"]))))
        calls.append({"max_tokens": payload["max_tokens"], "kind": "segment" if "cues" in user else "merge",
                      "first_cue_id": ids[0], "last_cue_id": ids[-1]})
        selected = list(dict.fromkeys([ids[0], ids[-1]]))
        content = {"headline": "隔离回放：摘要结构验证", "overview": "此内容由本地模拟模型生成，仅用于测试流式修复。",
                   "chapters": [{"title": "分段或汇总", "overview": "检查前后段引用与保存。", "cue_ids": selected,
                                 "points": [{"text": "模拟输出，不能作为视频的真实摘要。", "cue_ids": selected}]}]}
        raw = json.dumps(content, ensure_ascii=False)
        truncated = len(calls) == 1
        if truncated:
            raw = raw[:len(raw) // 2]
        class Stream(httpx.SyncByteStream):
            def __iter__(self):
                for offset in range(0, len(raw), 11):
                    event = {"choices": [{"delta": {"content": raw[offset:offset + 11]}, "finish_reason": None}]}
                    yield ("data: " + json.dumps(event) + "\n\n").encode()
                event = {"choices": [{"delta": {}, "finish_reason": "length" if truncated else "stop"}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 80}}
                yield ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode()
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Stream())

    engine = AnalysisEngine(store)
    engine.client_factory = lambda cfg, check, usage: DeepSeekClient(cfg, check, usage, httpx.MockTransport(respond))
    original_preview = engine._summary_preview
    def preview(job_id, text, stage, phase):
        original_preview(job_id, text, stage, phase)
        if phase in {"starting", "retrying", "cached", "validated"}:
            snapshot = engine.summary_preview(job_id)
            transitions.append({"stage": stage, "phase": phase,
                                "parts": [{key: part[key] for key in ("id", "stage", "attempt", "phase")} |
                                          {"text_characters": len(part["text"])} for part in snapshot["parts"]]})
    engine._summary_preview = preview
    before_usage = store.usage(record["id"])
    try:
        submitted = engine.start_summary(record["id"], streaming=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = store.job(submitted["job_id"])
            if job["status"] not in {"queued", "processing"}:
                break
            time.sleep(.02)
        assert job["status"] == "ready", job
        saved = store.summary(record["id"])
        allowed = {cue["id"] for cue in cues}
        references = summary_service.summary_ids(saved["content"])
        assert references <= allowed and cues[-1]["id"] in references
        assert [call["max_tokens"] for call in calls] == [4096, 8192, 4096], calls
        assert calls[0]["first_cue_id"] == chunks[1][0]["id"], "Validated first segment was not reused."
        retry = next(state for state in transitions if state["phase"] == "retrying")
        assert retry["parts"][0]["phase"] == "cached" and retry["parts"][0]["text_characters"] > 0
        assert retry["parts"][1]["phase"] == "superseded" and retry["parts"][1]["text_characters"] > 0
        merge = next(state for state in transitions if state["phase"] == "starting" and state["stage"].startswith("汇总"))
        assert merge["parts"][-2]["phase"] == "validated" and merge["parts"][-2]["text_characters"] > 0
        assert store.usage(record["id"])["calls"] - before_usage["calls"] == 3
        report = {"simulation": True, "network_calls": 0, "source_opened_readonly": True,
                  "video_url": record["url"], "duration": record["duration"], "cue_count": len(cues),
                  "text_characters": sum(len(cue["text"]) for cue in cues), "chunks": len(chunks),
                  "validated_first_chunk_reused": True, "retained_previous_attempt": True,
                  "retained_previous_stage": True, "references_valid": True, "includes_last_cue": True,
                  "status": job["status"], "calls": calls, "transitions": transitions}
        (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "transitions"}, ensure_ascii=False))
    finally:
        engine.close()


if __name__ == "__main__":
    main()
