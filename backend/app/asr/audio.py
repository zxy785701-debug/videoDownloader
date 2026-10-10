import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from ..analysis_errors import AnalysisError


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def prepare_audio(url, directory, config, check):
    (directory / "request.json").write_text(json.dumps({
        "url": url, "max_duration": config.max_duration, "threads": config.threads,
        "audio_timeout": config.audio_timeout, "max_download_bytes": config.max_download_bytes,
        "max_audio_bytes": config.max_audio_bytes,
    }), encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "app.asr.audio_worker", str(directory)],
        cwd=Path(__file__).resolve().parents[2], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    started = time.monotonic()
    try:
        while process.poll() is None:
            check()
            if time.monotonic() - started > config.audio_timeout:
                raise AnalysisError("ASR_AUDIO_TIMEOUT", "音频提取超时，已终止临时处理进程。")
            time.sleep(0.1)
        check()
        path = directory / "response.json"
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            raise AnalysisError("ASR_AUDIO_FAILED", "音频处理进程未返回有效结果。")
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("error_code"):
            raise AnalysisError(result["error_code"], result["error"])
        return directory / "audio.flac", result["metadata"]
    finally:
        stop_process(process)
