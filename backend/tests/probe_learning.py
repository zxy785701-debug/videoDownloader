"""Read-only, real platform caption probe; never calls DeepSeek or downloads video.

Run from backend: .venv/Scripts/python.exe -m tests.probe_learning Bilibili
Outputs safe metadata only. Cookie contents and signed subtitle URLs are omitted.
"""

import json
import os
import sys
import time
from pathlib import Path

from app.ai_config import get_config
from app.analysis_errors import AnalysisError
from app.subtitle_service import extract_transcript


SAMPLES = {
    "Bilibili": "https://www.bilibili.com/video/BV1Y5aq6gEV3/",
    "Douyin": "https://www.douyin.com/video/7374305128272121103",
    "YouTube": "https://www.youtube.com/watch?v=Prjto1bDpI8",
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    platform = sys.argv[1]
    if platform not in SAMPLES:
        raise SystemExit("Use Bilibili, Douyin or YouTube")
    began = time.monotonic()
    metadata = {}
    result = {
        "platform": platform, "url": SAMPLES[platform], "simulation": False,
        "deepseek_called": False, "deepseek_configured": bool(get_config().api_key),
        "youtube_session_selected": bool(os.getenv("YTDLP_COOKIES_FROM_BROWSER")) if platform == "YouTube" else False,
        "firefox_subtitle_session": get_config().firefox_subtitle_session,
    }
    try:
        transcript = extract_transcript(SAMPLES[platform], on_metadata=metadata.update)
        cues = transcript["cues"]
        folder = Path(__file__).resolve().parents[2] / ".local" / "learning-real-probes"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{platform.lower()}-transcript.json").write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")
        result.update(status="ready", title=transcript["title"], duration=transcript["duration"],
                      language=transcript["language"], source_kind=transcript["track_kind"],
                      cue_count=len(cues), character_count=sum(len(c["text"]) for c in cues),
                      first_timestamp=cues[0]["start"], last_timestamp=cues[-1]["end"],
                      notes=transcript["notes"])
    except AnalysisError as error:
        result.update(status="unavailable", error_code=error.code, error_message=error.message, **metadata)
    result["elapsed_seconds"] = round(time.monotonic() - began, 2)
    folder = Path(__file__).resolve().parents[2] / ".local" / "learning-real-probes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{platform.lower()}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
