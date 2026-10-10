"""Local learning records. Network requests never hold a SQLite transaction."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .analysis_errors import AnalysisError


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class AnalysisStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Unsupported learning database version")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL, platform TEXT NOT NULL,
                    requested_language TEXT NOT NULL, title TEXT NOT NULL,
                    duration REAL, source_id TEXT, language TEXT, track_kind TEXT,
                    tracks TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '[]',
                    transcript_hash TEXT, subtitle_status TEXT NOT NULL DEFAULT 'pending',
                    subtitle_error TEXT, subtitle_error_code TEXT,
                    summary_status TEXT NOT NULL DEFAULT 'idle', current_summary_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS analyses_url ON analyses(url, requested_language);
                CREATE TABLE IF NOT EXISTS cues (
                    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                    id TEXT NOT NULL, position INTEGER NOT NULL,
                    start REAL NOT NULL, end REAL NOT NULL, text TEXT NOT NULL,
                    PRIMARY KEY(analysis_id, id)
                );
                CREATE INDEX IF NOT EXISTS cue_position ON cues(analysis_id, position);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    stage TEXT NOT NULL, error TEXT, error_code TEXT,
                    fingerprint TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS summaries (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL, content TEXT NOT NULL, model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunk_cache (
                    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                    cache_key TEXT NOT NULL, content TEXT NOT NULL,
                    PRIMARY KEY(analysis_id, cache_key)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL, question TEXT NOT NULL, answer TEXT,
                    status TEXT NOT NULL DEFAULT 'queued', error TEXT, error_code TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(analysis_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    model TEXT NOT NULL, usage TEXT NOT NULL, created_at TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)
            # Additive migration; existing cues and API fields keep their values.
            columns = {row[1] for row in db.execute("PRAGMA table_info(cues)")}
            if "source" not in columns:
                db.execute("ALTER TABLE cues ADD COLUMN source TEXT NOT NULL DEFAULT 'native_subtitle'")
            if "provider" not in columns:
                db.execute("ALTER TABLE cues ADD COLUMN provider TEXT NOT NULL DEFAULT 'platform'")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, record_id: str, url: str, platform: str, language: str):
        stamp = now()
        with self.connection() as db:
            db.execute(
                "INSERT INTO analyses(id,url,platform,requested_language,title,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (record_id, url, platform, language, "正在获取视频信息…", stamp, stamp),
            )

    def find(self, url: str, language: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM analyses WHERE url=? AND requested_language=? ORDER BY created_at DESC LIMIT 1",
                (url, language),
            ).fetchone()
        return self._record(row) if row else None

    @staticmethod
    def _record(row) -> dict:
        item = dict(row)
        item["tracks"] = json.loads(item["tracks"])
        item["notes"] = json.loads(item["notes"])
        return item

    def get(self, record_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM analyses WHERE id=?", (record_id,)).fetchone()
        if not row:
            raise AnalysisError("NOT_FOUND", "学习记录不存在或已删除。", 404)
        return self._record(row)

    def list(self, offset: int, limit: int) -> dict:
        with self.connection() as db:
            count = db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
            rows = db.execute(
                "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return {"items": [self._record(row) for row in rows], "total": count}

    def update(self, record_id: str, **fields):
        allowed = {
            "title", "duration", "source_id", "language", "track_kind", "tracks", "notes",
            "transcript_hash", "subtitle_status", "subtitle_error", "subtitle_error_code",
            "summary_status", "current_summary_id",
        }
        if not fields.keys() <= allowed:
            raise ValueError("Unsupported record fields")
        fields["updated_at"] = now()
        values = [encode(v) if k in {"tracks", "notes"} else v for k, v in fields.items()]
        with self.connection() as db:
            db.execute(
                "UPDATE analyses SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?",
                (*values, record_id),
            )

    def save_transcript(self, record_id: str, result: dict):
        fields = ("title", "duration", "source_id", "language", "track_kind", "transcript_hash")
        with self.connection() as db:
            if not db.execute("SELECT 1 FROM analyses WHERE id=?", (record_id,)).fetchone():
                return
            db.execute("DELETE FROM cues WHERE analysis_id=?", (record_id,))
            db.executemany(
                "INSERT INTO cues(analysis_id,id,position,start,end,text,source,provider) VALUES(?,?,?,?,?,?,?,?)",
                [(record_id, c["id"], i, c["start"], c["end"], c["text"], c.get("source", "native_subtitle"), c.get("provider", "platform")) for i, c in enumerate(result["cues"])],
            )
            db.execute(
                "UPDATE analyses SET " + ",".join(k + "=?" for k in fields) +
                ",tracks=?,notes=?,subtitle_status='ready',subtitle_error=NULL,subtitle_error_code=NULL,updated_at=? WHERE id=?",
                (*[result.get(k) for k in fields], encode(result["tracks"]), encode(result["notes"]), now(), record_id),
            )

    def cues(self, record_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,start,end,text,source,provider FROM cues WHERE analysis_id=? ORDER BY position", (record_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def transcript(self, record_id: str, offset: int, limit: int, query: str, anchor: str | None) -> dict:
        self.get(record_id)
        with self.connection() as db:
            if anchor and not query:
                row = db.execute("SELECT position FROM cues WHERE analysis_id=? AND id=?", (record_id, anchor)).fetchone()
                if row:
                    offset = row[0] // limit * limit
            clause = "analysis_id=?"
            args: list = [record_id]
            if query:
                clause += " AND text LIKE ? ESCAPE '\\'"
                args.append("%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
            total = db.execute("SELECT COUNT(*) FROM cues WHERE " + clause, args).fetchone()[0]
            rows = db.execute(
                "SELECT id,start,end,text,source,provider FROM cues WHERE " + clause + " ORDER BY position LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "offset": offset, "limit": limit}

    def new_job(self, job_id: str, record_id: str, kind: str, stage: str, fingerprint: str = ""):
        stamp = now()
        with self.connection() as db:
            db.execute(
                "INSERT INTO jobs(id,analysis_id,kind,stage,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (job_id, record_id, kind, stage, fingerprint, stamp, stamp),
            )

    def job(self, job_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def latest_jobs(self, record_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM jobs AS current WHERE analysis_id=? AND id=(
                    SELECT id FROM jobs AS other WHERE other.analysis_id=current.analysis_id
                    AND other.kind=current.kind ORDER BY created_at DESC LIMIT 1
                ) ORDER BY created_at DESC""", (record_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def active_job(self, record_id: str, kind: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE analysis_id=? AND kind=? AND status IN ('queued','processing') LIMIT 1",
                (record_id, kind),
            ).fetchone()
        return dict(row) if row else None

    def set_job(self, job_id: str, status: str, stage: str, error=None, code=None):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status=?,stage=?,error=?,error_code=?,updated_at=? WHERE id=?",
                (status, stage, error, code, now(), job_id),
            )

    def save_summary(self, record_id: str, version_id: str, fingerprint: str, content: dict, model: str, prompt_version: str, completed_job_id: str | None = None):
        with self.connection() as db:
            if not db.execute("SELECT 1 FROM analyses WHERE id=?", (record_id,)).fetchone():
                return
            if completed_job_id:
                # Durable job outcome and saved result must agree for quota recovery after a crash.
                updated = db.execute("UPDATE jobs SET status='ready',stage='处理完成',updated_at=? WHERE id=? AND analysis_id=? AND kind='summary' AND status='processing'", (now(), completed_job_id, record_id))
                if updated.rowcount != 1:
                    from .analysis_errors import JobStopped
                    raise JobStopped()
            db.execute(
                "INSERT INTO summaries VALUES(?,?,?,?,?,?,?)",
                (version_id, record_id, fingerprint, encode(content), model, prompt_version, now()),
            )
            db.execute(
                "UPDATE analyses SET current_summary_id=?,summary_status='ready',updated_at=? WHERE id=?",
                (version_id, now(), record_id),
            )

    def summary(self, record_id: str) -> dict | None:
        record = self.get(record_id)
        with self.connection() as db:
            row = db.execute("SELECT * FROM summaries WHERE id=?", (record["current_summary_id"],)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["content"] = json.loads(item["content"])
        return item

    def cached_chunk(self, record_id: str, key: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT content FROM chunk_cache WHERE analysis_id=? AND cache_key=?", (record_id, key)).fetchone()
        return json.loads(row[0]) if row else None

    def save_chunk(self, record_id: str, key: str, content: dict):
        with self.connection() as db:
            if db.execute("SELECT 1 FROM analyses WHERE id=?", (record_id,)).fetchone():
                db.execute("INSERT OR REPLACE INTO chunk_cache VALUES(?,?,?)", (record_id, key, encode(content)))

    def new_message(self, message_id: str, record_id: str, job_id: str, request_id: str, question: str):
        with self.connection() as db:
            db.execute(
                "INSERT INTO messages(id,analysis_id,job_id,request_id,question,created_at) VALUES(?,?,?,?,?,?)",
                (message_id, record_id, job_id, request_id, question, now()),
            )

    def messages(self, record_id: str) -> list[dict]:
        self.get(record_id)
        with self.connection() as db:
            rows = db.execute("SELECT * FROM messages WHERE analysis_id=? ORDER BY created_at", (record_id,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["answer"] = json.loads(item["answer"]) if item["answer"] else None
            items.append(item)
        return items

    def set_message(self, message_id: str, status: str, answer=None, error=None, code=None):
        with self.connection() as db:
            db.execute(
                "UPDATE messages SET status=?,answer=?,error=?,error_code=? WHERE id=?",
                (status, encode(answer) if answer else None, error, code, message_id),
            )

    def message(self, record_id: str, message_id: str) -> dict:
        self.get(record_id)
        with self.connection() as db:
            row = db.execute("SELECT * FROM messages WHERE analysis_id=? AND id=?", (record_id, message_id)).fetchone()
        if not row:
            raise AnalysisError("MESSAGE_NOT_FOUND", "这条对话已删除或不存在。", 404)
        item = dict(row)
        item["answer"] = json.loads(item["answer"]) if item["answer"] else None
        return item

    def record_usage(self, record_id: str, job_id: str, model: str, usage: dict):
        with self.connection() as db:
            if db.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
                db.execute(
                    "INSERT INTO usage_events(analysis_id,job_id,model,usage,created_at) VALUES(?,?,?,?,?)",
                    (record_id, job_id, model, encode(usage), now()),
                )

    def usage(self, record_id: str) -> dict:
        with self.connection() as db:
            rows = db.execute("SELECT usage FROM usage_events WHERE analysis_id=?", (record_id,)).fetchall()
        total = {"calls": len(rows), "prompt_tokens": 0, "completion_tokens": 0, "prompt_cache_hit_tokens": 0}
        for row in rows:
            event = json.loads(row[0])
            for key in total.keys() - {"calls"}:
                total[key] += event.get(key, 0)
        return total

    def recover(self):
        with self.connection() as db:
            db.execute("UPDATE analyses SET subtitle_status='failed',subtitle_error_code='INTERRUPTED',subtitle_error='获取被中断，请手动重试。' WHERE subtitle_status IN ('pending','fetching')")
            db.execute("UPDATE analyses SET summary_status='interrupted' WHERE summary_status IN ('queued','processing')")
            db.execute("UPDATE jobs SET status='interrupted',error_code='INTERRUPTED',error='服务已重启或停止，请手动重试。',stage='处理中断' WHERE status IN ('queued','processing')")
            db.execute("UPDATE messages SET status='interrupted',error_code='INTERRUPTED',error='回答被中断，可重新发送问题。' WHERE status IN ('queued','processing')")

    def delete(self, record_id: str):
        self.get(record_id)
        with self.connection() as db:
            db.execute("DELETE FROM analyses WHERE id=?", (record_id,))

    def clear_messages(self, record_id: str):
        self.get(record_id)
        with self.connection() as db:
            db.execute("UPDATE jobs SET status='cancelled',stage='对话已清空' WHERE analysis_id=? AND kind='chat' AND status IN ('queued','processing')", (record_id,))
            db.execute("DELETE FROM messages WHERE analysis_id=?", (record_id,))
