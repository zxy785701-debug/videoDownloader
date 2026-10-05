"""Exercise real caption jobs through the local API; no summary/model calls."""

import json
import sys
import time
from pathlib import Path

import httpx

from tests.probe_learning import SAMPLES


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8181"
    results = []
    with httpx.Client(base_url=base, timeout=20, trust_env=False) as client:
        for platform, url in SAMPLES.items():
            response = client.post("/api/v1/analyses", json={"url": url})
            response.raise_for_status()
            results.append({"platform": platform, "id": response.json()["id"], "simulation": False})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            active = False
            for result in results:
                response = client.get("/api/v1/analyses/" + result["id"])
                response.raise_for_status()
                record = response.json()
                result.update(status=record["subtitle_status"], title=record["title"], error_code=record["subtitle_error_code"],
                              error_message=record["subtitle_error"], language=record["language"], duration=record["duration"])
                active |= result["status"] in {"pending", "fetching"}
                if result["status"] == "ready":
                    page = client.get("/api/v1/analyses/" + result["id"] + "/transcript").json()
                    result["cue_count"] = page["total"]
            if not active:
                break
            time.sleep(1)
    folder = Path(__file__).resolve().parents[2] / ".local" / "learning-real-probes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "api-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
