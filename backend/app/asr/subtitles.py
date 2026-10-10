import hashlib
import json

from ..ai_config import get_config
from ..analysis_errors import AnalysisError
from ..subtitle_service import normalize_cues


def transcript(data, metadata, language, provider):
    if not isinstance(data, dict) or not isinstance(data.get("transcripts"), list):
        raise AnalysisError("ASR_RESULT_INVALID", "云端返回了无法解析的转录结构。")
    raw = []
    try:
        for track in data["transcripts"]:
            if track.get("channel_id") != 0:
                continue
            for sentence in track.get("sentences", []):
                raw.append({"start": sentence["begin_time"] / 1000,
                            "end": sentence["end_time"] / 1000, "text": sentence["text"]})
    except (KeyError, TypeError, AttributeError) as error:
        raise AnalysisError("ASR_RESULT_INVALID", "云端转录缺少有效句子或时间戳。") from error
    cues, notes = normalize_cues(raw, metadata["duration"], get_config())
    for cue in cues:
        cue.update(source="asr", provider=provider)
    notes.append("原生字幕不可用，已使用云端语音转录；识别文本可能存在错漏。")
    return {**metadata, "language": language if language != "auto" else "auto",
            "track_kind": "asr", "tracks": [], "notes": notes, "cues": cues,
            "transcript_hash": hashlib.sha256(json.dumps(cues, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
