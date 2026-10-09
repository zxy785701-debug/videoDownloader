"""Loopback-only, fake payments for browser acceptance; not a deployment entrypoint."""
import os
from pathlib import Path

from billing.config import Config
from billing.main import create_app

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = Path(os.environ["MEMBERSHIP_TEST_DIR"]).resolve()
if not DIRECTORY.is_relative_to(ROOT / ".local"):
    raise RuntimeError("Test data must stay under .local")
app = create_app(Config(provider="mock", database=DIRECTORY / "billing.sqlite3", mail_directory=DIRECTORY / "mail",
                        require_email_verification=os.environ.get("MEMBERSHIP_TEST_VERIFY_EMAIL") == "1",
                        public_url=os.environ.get("MEMBERSHIP_TEST_SERVICE_URL", "http://127.0.0.1:8190")))
