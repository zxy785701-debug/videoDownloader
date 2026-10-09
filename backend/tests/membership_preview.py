"""Existing fake video/model workspace connected to a separate fake billing server."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = Path(os.environ["MEMBERSHIP_TEST_DIR"]).resolve()
if not DIRECTORY.is_relative_to(ROOT / ".local"):
    raise RuntimeError("Test data must stay under .local")
os.environ["MEMBERSHIP_SERVICE_URL"] = os.environ.get("MEMBERSHIP_TEST_SERVICE_URL", "http://127.0.0.1:8190")
os.environ["MEMBERSHIP_LOCAL_DB"] = str(DIRECTORY / "local.sqlite3")

from tests.unified_preview import app, caption_release, download_release

caption_release.set()
download_release.set()
