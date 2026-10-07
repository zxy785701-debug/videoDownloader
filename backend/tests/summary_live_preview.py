"""Explicit paid summary verification on a copied database, with safe diagnostics.

Requires VIDEO_LEARNING_DB and SUMMARY_LIVE_ARTIFACTS to point under .local.
Only the configured official model client is used. Never logs request headers,
keys or complete input subtitles. This fixture is not used by normal startup.
"""

import json
import os
import threading
from pathlib import Path

from app.analysis_jobs import get_engine
from app.deepseek_client import DeepSeekClient
from app.analysis_errors import AnalysisError

ROOT = Path(__file__).resolve().parents[2]
DB = Path(os.environ["VIDEO_LEARNING_DB"]).resolve()
ARTIFACTS = Path(os.environ["SUMMARY_LIVE_ARTIFACTS"]).resolve()
if not DB.is_relative_to(ROOT / ".local") or not ARTIFACTS.is_relative_to(ROOT / ".local"):
    raise RuntimeError("Live verification must use an explicit .local database copy and output directory.")
ARTIFACTS.mkdir(parents=True, exist_ok=True)
LOCK, CALLS = threading.Lock(), []


class TracedClient(DeepSeekClient):
    def complete(self, messages, max_tokens, deadline, *, on_content=None):
        with LOCK:
            self.trace = {"index": len(CALLS) + 1, "max_tokens": max_tokens, "stream": on_content is not None,
                          "status": "processing", "repair_prompt": len(messages) > 2}
            CALLS.append(self.trace)
        try:
            result = super().complete(messages, max_tokens, deadline, on_content=on_content)
            self.trace["status"] = "ready"
            return result
        except AnalysisError as error:
            self.trace.update(status="failed", error_code=error.code, error=error.message)
            raise
        finally:
            with LOCK:
                (ARTIFACTS / "model-calls.json").write_text(json.dumps(CALLS, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_stream(self, response, deadline, on_content):
        result = super()._read_stream(response, deadline, on_content)
        choice = result["choices"][0]
        self.trace.update(finish_reason=choice["finish_reason"], output_characters=len(choice["message"]["content"]))
        (ARTIFACTS / f"model-output-{self.trace['index']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


from app.main import app  # Guard copied DB paths before application initialization.

get_engine().client_factory = TracedClient

@app.get("/_test/summary-live/stats")
def stats():
    with LOCK:
        return {"calls": [dict(item) for item in CALLS]}

test_routes = [route for route in app.router.routes if getattr(route, "path", "").startswith("/_test/")]
app.router.routes[:] = test_routes + [route for route in app.router.routes if route not in test_routes]
