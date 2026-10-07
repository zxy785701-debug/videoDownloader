"""Controlled SSE browser fixture; isolated data and fake model only."""

import json
import threading
import time

import httpx
from fastapi import Body

from tests.learning_preview import app, get_engine, model_response
from app.deepseek_client import DeepSeekClient

LOCK = threading.Lock()
CALLS = {}
GATES = {}
TEXT = '通过主动回忆检查学习效果。\n先复述 "概念"，再结合例子练习 😀。' * 3


@app.get("/_test/chat-stream/stats")
def stats():
    with LOCK:
        return {"calls": dict(CALLS)}


@app.post("/_test/chat-stream/release")
def release(body: dict = Body()):
    with LOCK:
        gate = GATES.get((body["question"], body.get("attempt", 1)))
    if gate:
        gate.set()
    return {"released": bool(gate)}


def respond(request):
    payload = json.loads(request.content)
    user = json.loads(payload["messages"][1]["content"])
    question = user.get("question", "")
    if not question.startswith("SSE测试") or not payload.get("stream"):
        return model_response(request)
    with LOCK:
        attempt = CALLS.get(question, 0) + 1
        CALLS[question] = attempt
        gate = GATES[question, attempt] = threading.Event()
    wrong = "修复" in question and attempt == 1 or "无效引用" in question
    answer = {"answer": "第一版待校验草稿：" + TEXT if wrong else TEXT,
              "evidence": "supported", "cue_ids": ["missing"] if wrong else ["c000150"]}
    raw = json.dumps(answer, ensure_ascii=True)

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            held = False
            for offset in range(0, len(raw), 16):
                time.sleep(.025)
                if not held and offset > len(raw) / 2:
                    held = True
                    if not gate.wait(40):
                        raise httpx.ReadTimeout("Fixture release timed out")
                    if "断流" in question and attempt == 1:
                        raise httpx.ReadError("Simulated lost stream")
                chunk = {"choices": [{"delta": {"content": raw[offset:offset + 16]}, "finish_reason": None}]}
                yield ("data: " + json.dumps(chunk) + "\r\n\r\n").encode()
            yield ("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 100, "completion_tokens": 80}}) + "\r\n\r\n").encode()
            yield b"data: [DONE]\r\n\r\n"
    return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Stream())


get_engine().client_factory = lambda config, check, usage: DeepSeekClient(config, check, usage, httpx.MockTransport(respond))
# The production app mounts StaticFiles last; fixture routes must precede it.
test_routes = [route for route in app.router.routes if getattr(route, "path", "").startswith("/_test/")]
app.router.routes[:] = test_routes + [route for route in app.router.routes if route not in test_routes]
