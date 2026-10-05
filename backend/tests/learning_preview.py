"""Isolated browser test server. Simulated data; never used by production startup.

Run from the repository root:
backend/.venv/Scripts/python.exe -m uvicorn tests.learning_preview:app --app-dir backend --port 8180
"""

import json
import os
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = ROOT / ".local" / "learning-browser-test"
TEST_DIR.mkdir(parents=True, exist_ok=True)
os.environ["VIDEO_LEARNING_DB"] = str(TEST_DIR / ("preview-" + uuid.uuid4().hex + ".sqlite3"))
os.environ["DEEPSEEK_API_KEY"] = "fake-browser-test-key"
os.environ["DEEPSEEK_MODEL"] = "deepseek-flash"

from app import main, subtitle_service, video_service
from app.analysis_errors import AnalysisError
from app.analysis_jobs import get_engine
from app.deepseek_client import DeepSeekClient
from app.schemas import ParseResponse, VideoFormat

app = main.app
CUES = [{"id": f"c{i + 1:06d}", "start": i * 20, "end": i * 20 + 8,
         "text": f"第 {i + 1} 段：理解概念，并结合具体例子练习。"} for i in range(150)]
CUES[-1]["text"] = "最后用主动回忆检查学习效果，先回想概念，再用例子检验。"


def fake_transcript(url, language="auto", config=None, on_metadata=None):
    if "nocaptions" in url:
        raise AnalysisError("NO_CAPTIONS", "【模拟验收】没有可提取字幕，暂不能总结，仍可下载视频。")
    result = {"title": "【模拟验收】长视频学习方法", "duration": 3000, "source_id": "simulated-video",
              "language": "en" if language == "en" else "zh-Hans", "track_kind": "manual",
              "tracks": [{"language": "zh-Hans", "kind": "manual"}, {"language": "en", "kind": "manual"}],
              "notes": ["此记录为自动化模拟验收数据，未调用真实平台或付费模型。"],
              "cues": CUES, "transcript_hash": "browser-fixture-" + language}
    if on_metadata:
        on_metadata({key: result[key] for key in ("title", "duration", "tracks")})
    return result


def model_response(request):
    time.sleep(0.08)
    payload = json.loads(request.content)
    user = json.loads(payload["messages"][1]["content"])
    if "question" in user:
        if "画面" in user["question"]:
            answer = {"answer": "可用字幕没有提供图表颜色，需要查看画面才能判断。", "evidence": "insufficient", "cue_ids": []}
        else:
            answer = {"answer": "可以通过主动回忆检查：先回想概念，再用例子检验。", "evidence": "supported", "cue_ids": ["c000150"]}
    else:
        answer = {
            "headline": "理解、练习与主动回忆形成学习闭环",
            "overview": "【模拟验收】先理解核心概念，结合例子练习，最后用主动回忆检查效果。",
            "chapters": [
                {"title": "理解与练习", "overview": "通过例子理解知识。", "cue_ids": ["c000001"],
                 "points": [{"text": "学习概念时结合具体例子练习。", "cue_ids": ["c000001"]}]},
                {"title": "主动回忆", "overview": "用回忆与检验检查效果。", "cue_ids": ["c000150"],
                 "points": [{"text": "先回想概念，再用例子检验，发现理解漏洞。", "cue_ids": ["c000150"]}]},
            ],
        }
    return httpx.Response(200, json={
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 80, "prompt_cache_hit_tokens": 20},
    })


def fake_parse(url):
    return ParseResponse(title="【模拟验收】原有下载流程", extractor="YouTube", duration=3000,
                         formats=[VideoFormat(format_id="best", label="最佳画质"),
                                  VideoFormat(format_id="video:137", label="1080p · 自动合并音频")])


def fake_download(task_id, url, format_id, delivery_mode):
    directory = TEST_DIR / task_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "simulated-download.mp4"
    path.write_bytes(b"SIMULATED-BROWSER-TEST-NOT-A-REAL-MEDIA-FILE")
    video_service._set_state(task_id, status="ready", delivery_mode="server", file_path=str(path),
                             filename=path.name, progress=100)


subtitle_service.validate_public_http_url = lambda url: url
subtitle_service.extract_transcript = fake_transcript
video_service.validate_public_http_url = lambda url: url
video_service.parse_video = fake_parse
video_service.process_download = fake_download
video_service.DOWNLOAD_DIR = TEST_DIR
get_engine().client_factory = lambda config, check, usage: DeepSeekClient(config, check, usage, httpx.MockTransport(model_response))
