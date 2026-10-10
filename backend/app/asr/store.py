"""Durable cache, cloud task identity and conservative application budget.

Kept outside analysis foreign keys: deleting a UI record cannot erase a paid
task's identity or release an uncertain charge. Never stores signed URLs/keys.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from ..analysis_errors import AnalysisError
from ..analysis_store import AnalysisStore


class ASRStore(AnalysisStore):
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise RuntimeError("Unsupported ASR database version")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS asr_tasks (
                    cache_key TEXT PRIMARY KEY, state TEXT NOT NULL,
                    task_id TEXT, provider TEXT NOT NULL, model TEXT NOT NULL,
                    user_key TEXT NOT NULL, created REAL NOT NULL, month TEXT NOT NULL,
                    duration REAL NOT NULL, estimated_cny REAL NOT NULL,
                    reserved_cny REAL NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
                    reported_seconds REAL, actual_billed_cny REAL,
                    result TEXT, object_key TEXT, error_code TEXT, metadata TEXT
                );
                CREATE TABLE IF NOT EXISTS asr_videos (
                    video_key TEXT PRIMARY KEY, cache_key TEXT NOT NULL, metadata TEXT
                );
                CREATE INDEX IF NOT EXISTS asr_user_time ON asr_tasks(user_key,created);
            """)
            for table in ("asr_tasks", "asr_videos"):
                if "metadata" not in {r[1] for r in db.execute("PRAGMA table_info(" + table + ")")}:
                    db.execute("ALTER TABLE " + table + " ADD COLUMN metadata TEXT")
            db.execute("PRAGMA user_version=1")

    def get_task(self, key):
        with self.connection() as db:
            row = db.execute("SELECT * FROM asr_tasks WHERE cache_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def video_task(self, video_key):
        with self.connection() as db:
            row = db.execute("SELECT cache_key,metadata FROM asr_videos WHERE video_key=?", (video_key,)).fetchone()
        task = self.get_task(row[0]) if row else None
        if task and row[1]:
            task["metadata"] = row[1]
        return task

    def alias(self, video_key, key, metadata=None):
        with self.connection() as db:
            db.execute("INSERT INTO asr_videos(video_key,cache_key,metadata) VALUES(?,?,?) ON CONFLICT(video_key) DO UPDATE SET cache_key=excluded.cache_key,metadata=COALESCE(excluded.metadata,asr_videos.metadata)",
                       (video_key, key, json.dumps(metadata, ensure_ascii=False) if metadata else None))

    def reserve(self, key, video_key, duration, user_key, config, *, member=False):
        stamp = time.time()
        month = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m")
        estimate = round(duration * config.price_per_second, 6)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM asr_tasks WHERE cache_key=?", (key,)).fetchone()
            if prior and prior["state"] not in {"reserved", "preflight_failed", "rejected"}:
                db.execute("INSERT OR IGNORE INTO asr_videos(video_key,cache_key) VALUES(?,?)", (video_key, key))
                return dict(prior)
            if prior and prior["calls"] >= config.retries + 1:
                raise AnalysisError("ASR_RETRY_EXHAUSTED", "此前提交被云端拒绝，已达到有限重试上限，请管理员核查配置。")
            count = db.execute("SELECT COALESCE(SUM(MAX(1,calls)),0) FROM asr_tasks WHERE user_key=? AND created>? AND cache_key!=?", (user_key, stamp - 3600, key)).fetchone()[0]
            count += prior["calls"] if prior and prior["created"] > stamp - 3600 else 0
            hourly_limit = config.member_per_user_hour if member else config.per_user_hour
            if count >= hourly_limit:
                category = "会员" if member else "普通账号/未核验会话"
                raise AnalysisError("ASR_USER_RATE_LIMIT",
                    f"{category}语音转录已达到最近 60 分钟 {hourly_limit} 次上限，请稍后再试。原生字幕和已有转录缓存仍可使用。", 429)
            spent = db.execute("SELECT COALESCE(SUM(reserved_cny),0) FROM asr_tasks WHERE cache_key!=? AND (month=? OR state IN ('submitting','pending','unknown'))", (key, month)).fetchone()[0]
            if config.stop_over_budget and spent + estimate > config.budget:
                logging.getLogger(__name__).warning("ASR application monthly budget exceeded; new submission blocked")
                raise AnalysisError("ASR_BUDGET_EXCEEDED", "语音转录预计费用超过服务端月度预算，已停止提交新任务。", 429)
            if spent + estimate >= config.budget:
                logging.getLogger(__name__).warning("ASR application monthly budget warning")
            if prior:
                db.execute("UPDATE asr_tasks SET state='reserved',error_code=NULL,user_key=?,created=?,month=?,duration=?,estimated_cny=?,reserved_cny=? WHERE cache_key=?",
                           (user_key, stamp, month, duration, estimate, estimate, key))
            else:
                db.execute("""INSERT INTO asr_tasks(cache_key,state,provider,model,user_key,created,month,duration,estimated_cny,reserved_cny)
                              VALUES(?,'reserved',?,?,?,?,?,?,?,?)""",
                           (key, config.provider, config.model, user_key, stamp, month, duration, estimate, estimate))
            db.execute("INSERT OR IGNORE INTO asr_videos(video_key,cache_key) VALUES(?,?)", (video_key, key))
        return self.get_task(key)

    def update_task(self, key, **fields):
        allowed = {"state", "task_id", "calls", "reported_seconds", "actual_billed_cny",
                   "reserved_cny", "result", "object_key", "error_code", "metadata"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid ASR fields")
        if "result" in fields:
            fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
        if "metadata" in fields:
            fields["metadata"] = json.dumps(fields["metadata"], ensure_ascii=False)
        with self.connection() as db:
            db.execute("UPDATE asr_tasks SET " + ",".join(k + "=?" for k in fields) + " WHERE cache_key=?",
                       (*fields.values(), key))

    def artifacts(self):
        with self.connection() as db:
            # Cleanup must never materialize cached transcript bodies.
            return [dict(row) for row in db.execute("SELECT cache_key,state,object_key,created FROM asr_tasks WHERE object_key IS NOT NULL")]

    def usage_report(self):
        with self.connection() as db:
            rows = db.execute("SELECT month,SUM(calls) AS submission_attempts,COUNT(task_id) AS accepted_tasks,SUM(estimated_cny) AS estimated_cny,SUM(reserved_cny) AS budget_reserved_cny,SUM(reported_seconds) AS reported_seconds,SUM(actual_billed_cny) AS actual_billed_cny FROM asr_tasks GROUP BY month").fetchall()
        return [dict(row) for row in rows]
