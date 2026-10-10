"""Sample only process names/RSS, never environment, command lines or credentials."""
import csv
import threading
import time
from contextlib import contextmanager

import psutil


class Metrics:
    def __init__(self):
        self.started = time.monotonic()
        self.samples, self.phases = [], []
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.process = psutil.Process()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def start(self):
        self.thread.start()

    def _sample(self):
        while not self.stop.is_set():
            try:
                root = self.process.memory_info().rss
                children = self.process.children(recursive=True)
                child_rss = ffmpeg_rss = 0
                for child in children:
                    try:
                        rss = child.memory_info().rss
                        child_rss += rss
                        if "ffmpeg" in child.name().lower():
                            ffmpeg_rss += rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                with self.lock:
                    self.samples.append({"elapsed_seconds": round(time.monotonic() - self.started, 3),
                        "backend_rss_mib": round(root / 1048576, 3),
                        "children_rss_mib": round(child_rss / 1048576, 3),
                        "tree_rss_mib": round((root + child_rss) / 1048576, 3),
                        "ffmpeg_rss_mib": round(ffmpeg_rss / 1048576, 3)})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            self.stop.wait(0.2)

    @contextmanager
    def phase(self, name):
        started = time.monotonic()
        item = {"name": name, "start_seconds": round(started - self.started, 3), "status": "processing"}
        with self.lock:
            self.phases.append(item)
        try:
            yield item
            item["status"] = "passed"
        except BaseException as error:
            item["status"] = "failed"
            code = getattr(error, "code", None)
            item["error_code"] = code if isinstance(code, str) and (code.startswith(("ASR_", "AI_", "E2E_", "CAPTIONS_", "LIVE_"))
                or code in {"NO_CAPTIONS", "EMPTY_TRANSCRIPT", "VIDEO_TOO_LONG", "SUBTITLE_FORMAT_UNSUPPORTED"}) else "E2E_STAGE_FAILED"
            raise
        finally:
            item["duration_seconds"] = round(time.monotonic() - started, 3)
            with self.lock:
                samples = [s for s in self.samples if s["elapsed_seconds"] >= item["start_seconds"]]
                for field in ("backend_rss_mib", "tree_rss_mib", "ffmpeg_rss_mib"):
                    item["peak_" + field] = max((s[field] for s in samples), default=None)
                item["memory_sample_count"] = len(samples)

    def wrap(self, obj, method, name):
        original = getattr(obj, method)

        def observed(*args, **kwargs):
            with self.phase(name):
                return original(*args, **kwargs)

        setattr(obj, method, observed)

    def finish(self, directory):
        self.stop.set()
        self.thread.join(timeout=2)
        with (directory / "memory.csv").open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=["elapsed_seconds", "backend_rss_mib",
                "children_rss_mib", "tree_rss_mib", "ffmpeg_rss_mib"])
            writer.writeheader()
            writer.writerows(self.samples)
        return {"sample_interval_seconds": 0.2, "samples": len(self.samples),
                "peak_backend_rss_mib": max((s["backend_rss_mib"] for s in self.samples), default=None),
                "peak_tree_rss_mib": max((s["tree_rss_mib"] for s in self.samples), default=None),
                "phases": self.phases,
                "limitations": "Local RSS samples, not server measurements; tree sum includes browser during UI phase and can double-count shared pages. Very short phases may have no sample."}
