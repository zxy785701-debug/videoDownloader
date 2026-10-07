"""Controlled summary SSE fixture. Fake model, subtitles and isolated DB only."""

import json
import threading
import time
from dataclasses import replace

import httpx
from fastapi import Body

from tests.learning_preview import app, fake_transcript, get_engine, model_response, subtitle_service
from app import analysis_jobs, analysis_routes
from app.ai_config import get_config
from app.deepseek_client import DeepSeekClient
from app.summary_service import summary_ids

LOCK, CALLS, GATES, BUDGETS = threading.Lock(), {}, {}, {}
DISCONNECT = set()
MODES = {"sseshort001": "正常", "sserepair01": "修复", "ssebroken01": "断流", "ssebadref01": "无效引用",
         "sselong0001": "长视频", "ssedelete01": "删除", "sseswitch01": "切换", "ssecut00001": "截断",
         "sslegacy001": "旧协议"}


def transcript(url, language="auto", config=None, on_metadata=None):
    result = fake_transcript(url, language, config)
    mode = next((label for suffix, label in MODES.items() if suffix in url), "正常")
    result["title"] = "SSE摘要模拟：" + mode
    result["cues"] = [result["cues"][0], result["cues"][-1]]
    if mode in {"长视频", "旧协议"}:
        result["cues"] = [{"id": f"c{i:06}", "start": i * 10, "end": i * 10 + 5,
                           "text": f"第 {i} 段独有知识。" + "练习概念" * 150} for i in range(1, 6)]
    if on_metadata:
        on_metadata({key: result[key] for key in ("title", "duration", "tracks")})
    return result


@app.get("/_test/summary-stream/stats")
def stats():
    with LOCK:
        return {"calls": dict(CALLS), "budgets": {mode: list(values) for mode, values in BUDGETS.items()}}


@app.post("/_test/summary-stream/release")
def release(body: dict = Body()):
    with LOCK:
        gate = GATES.get((body["mode"], body.get("attempt", 1)))
    if gate:
        gate.set()
    return {"released": bool(gate)}


@app.post("/_test/summary-stream/disconnect")
def disconnect(body: dict = Body()):
    with LOCK:
        DISCONNECT.add(body["record_id"])
    return {"scheduled": True}


def respond(request):
    payload = json.loads(request.content)
    user = json.loads(payload["messages"][1]["content"])
    if "question" in user:
        return model_response(request)
    assert payload.get("stream") is True
    mode = user["title"].split("：")[-1]
    with LOCK:
        attempt = CALLS.get(mode, 0) + 1
        CALLS[mode] = attempt
        BUDGETS.setdefault(mode, []).append(payload["max_tokens"])
        gate = GATES[mode, attempt] = threading.Event()
    ids = [cue["id"] for cue in user["cues"]] if "cues" in user else sorted(set().union(*(summary_ids(note) for note in user["notes"])))
    wrong = mode == "无效引用" or mode == "修复" and attempt == 1 or mode == "旧协议" and attempt in {1, 4, 7}
    if wrong: ids = ["wrong"]
    output = {"headline": f"{mode}：第 {attempt} 次概览 😀", "overview": '先复述 "概念"，再结合例子练习。\n通过主动回忆检查学习效果。' * 3,
              "chapters": [{"title": "主动回忆", "overview": "使用例子检查理解。", "cue_ids": ids,
                            "points": [{"text": "先回忆，再练习；保留全部分段独有内容。", "cue_ids": ids}]}]}
    raw = json.dumps(output, ensure_ascii=True)
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            held = False
            for offset in range(0, len(raw), 16):
                time.sleep(.015)
                if not held and offset > len(raw) / 2:
                    held = True
                    if not gate.wait(45): raise httpx.ReadTimeout("Fixture release timed out")
                    if mode == "断流" and attempt == 2: raise httpx.ReadError("Simulated lost stream")
                    if mode == "截断" and attempt == 1: break
                chunk = {"choices": [{"delta": {"content": raw[offset:offset + 16]}, "finish_reason": None}]}
                yield ("data: " + json.dumps(chunk) + "\n\n").encode()
            yield ("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "length" if mode == "截断" and attempt == 1 else "stop"}],
                   "usage": {"prompt_tokens": 100, "completion_tokens": 80}}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"
    return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Stream())


subtitle_service.extract_transcript = transcript
analysis_jobs.get_config = lambda: replace(get_config(), chunk_characters=1000)
get_engine().client_factory = lambda config, check, usage: DeepSeekClient(config, check, usage, httpx.MockTransport(respond))

# Emulate an already-running backend loaded before stage history was introduced.
# Only this fixture's explicit legacy record strips parts from SSE snapshots.
current_events = analysis_routes.summary_events
async def compatible_events(engine, record_id, job_id, request):
    legacy = engine.store.get(record_id)["title"].endswith("旧协议")
    async for frame in current_events(engine, record_id, job_id, request):
        with LOCK:
            dropped = record_id in DISCONNECT
            DISCONNECT.discard(record_id)
        if dropped:
            return
        if legacy and frame.startswith("event: snapshot\n"):
            payload = json.loads(frame.split("data: ", 1)[1])
            payload.pop("parts", None)
            payload["phase"] = {"starting": "generating", "retrying": "generating", "validated": "validating"}.get(payload["phase"], payload["phase"])
            frame = "event: snapshot\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
        yield frame
analysis_routes.summary_events = compatible_events
test_routes = [route for route in app.router.routes if getattr(route, "path", "").startswith("/_test/")]
app.router.routes[:] = test_routes + [route for route in app.router.routes if route not in test_routes]
