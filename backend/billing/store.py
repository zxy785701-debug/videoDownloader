from contextlib import contextmanager
from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
 verified INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mail_tokens (
 digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
 expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rate_limits (
 key TEXT PRIMARY KEY, period INTEGER NOT NULL, count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
 created REAL NOT NULL, params TEXT NOT NULL, creation_lease REAL NOT NULL DEFAULT 0,
 session_id TEXT UNIQUE, checkout_url TEXT, payment_id TEXT UNIQUE,
 paid_at REAL, last_error TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_purchase ON orders(user_id)
 WHERE status IN ('creating','unknown','open','waiting','review');
CREATE TABLE IF NOT EXISTS grants (
 order_id TEXT PRIMARY KEY REFERENCES orders(id), user_id TEXT NOT NULL REFERENCES users(id),
 starts REAL NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
 disputed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, type TEXT NOT NULL, object_id TEXT NOT NULL, processed REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), task_id TEXT NOT NULL,
 day TEXT NOT NULL, state TEXT NOT NULL, receipt_digest TEXT NOT NULL, expires REAL NOT NULL,
 UNIQUE(user_id,task_id)
);
CREATE INDEX IF NOT EXISTS quota_day ON reservations(user_id,day,state);
CREATE UNIQUE INDEX IF NOT EXISTS quota_receipt ON reservations(receipt_digest);
PRAGMA user_version=1;
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in {0, 1}:
                raise RuntimeError("Unsupported membership database version")
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
