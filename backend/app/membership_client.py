"""Local-only proxy and durable quota outbox. Does not import Stripe or upload video data."""
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
import os
import re
import secrets
import sqlite3
import ssl
import threading
import time
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

from .analysis_errors import AnalysisError


COOKIE = "saveany_account"


class MembershipClient:
    def __init__(self, url, path):
        self.url = url.rstrip("/")
        parsed = urlsplit(self.url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip("/") or (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})):
            raise ValueError("MEMBERSHIP_SERVICE_URL must be HTTPS or local HTTP origin")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.flush_lock = threading.Lock()
        self.http_lock = threading.Lock()
        self.http_client = None
        self.closed = False
        with self.db() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,access TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS auto_owners(job_id TEXT PRIMARY KEY,session_id TEXT);
            CREATE TABLE IF NOT EXISTS quota_jobs(job_id TEXT PRIMARY KEY,session_id TEXT,reservation_id TEXT,receipt TEXT NOT NULL,expires REAL,outcome INTEGER,settled INTEGER NOT NULL DEFAULT 0);
            """)
            if "completed_at" not in {r[1] for r in db.execute("PRAGMA table_info(quota_jobs)")}:
                db.execute("ALTER TABLE quota_jobs ADD COLUMN completed_at REAL")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def transport(self):
        with self.http_lock:
            if self.closed:
                raise RuntimeError("Membership transport is closed")
            if self.http_client is None:
                local_http = urlsplit(self.url).scheme == "http"
                # Only validated loopback HTTP uses this context: no TLS connection is
                # possible and redirects are disabled. Avoid loading an unused CA store.
                # HTTPS retains default certificate checks and configured proxy/CA support.
                verify = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if local_http else True
                self.http_client = httpx.Client(timeout=20, follow_redirects=False,
                                               verify=verify, trust_env=not local_http)
            return self.http_client

    def close(self):
        with self.http_lock:
            self.closed = True
            if self.http_client is not None:
                self.http_client.close()

    def call(self, path, body=None, access=None, method=None):
        try:
            # Explicit requests do not merge a pooled client's cookies/default headers:
            # sessions and settlement receipts must remain isolated across local users.
            request = httpx.Request(method or ("POST" if body is not None else "GET"), self.url + "/api/membership/v1" + path,
                                    json=body, headers={"Authorization": "Bearer " + access} if access else {})
            response = self.transport().send(request)
            data = response.json()
        except Exception:
            raise AnalysisError("MEMBERSHIP_UNAVAILABLE", "会员服务连接失败，请稍后重试。下载和已保存内容仍可使用。", 503) from None
        if not response.is_success:
            detail = data.get("detail", {}) if isinstance(data, dict) else {}
            if not isinstance(detail, dict):
                detail = {}
            raise AnalysisError(detail.get("code", "MEMBERSHIP_ERROR"), detail.get("message", "会员操作失败，请检查输入或稍后重试。"), response.status_code)
        return data

    def session(self, session_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND expires>?", (session_id, time.time())).fetchone()
        if not row:
            raise AnalysisError("LOGIN_REQUIRED", "请先在会员窗口登录，再生成新的 AI 总结。", 401)
        return dict(row)

    def mock_checkout_page(self, session_id, local_session, method, body, browser_headers):
        """Relay one authenticated mock page; never expose a general billing proxy."""
        if method not in {"GET", "POST"} or not re.fullmatch(r"cs_test_mock_[A-Za-z0-9_-]{32}", session_id):
            raise AnalysisError("ORDER_NOT_FOUND", "模拟订单不存在。", 404)
        access = self.session(local_session)["access"]
        headers = {"Authorization": "Bearer " + access}
        # Origin is checked by both services. Never copy browser cookies, Host,
        # Authorization or forwarded headers to the private membership service.
        for name in ("origin", "content-type", "sec-fetch-site"):
            if name in browser_headers:
                headers[name] = browser_headers[name]
        try:
            request = httpx.Request(method, self.url + "/dev/checkout/" + session_id,
                                    content=body, headers=headers)
            response = self.transport().send(request, stream=True, follow_redirects=False)
            try:
                if response.is_redirect:
                    raise ValueError("Unexpected mock checkout redirect")
                content = bytearray()
                for block in response.iter_bytes(chunk_size=8192):
                    content.extend(block)
                    if len(content) > 65536:
                        raise ValueError("Mock checkout response too large")
                allowed = ("content-type", "cache-control", "x-robots-tag", "x-content-type-options",
                           "referrer-policy", "content-security-policy")
                return response.status_code, bytes(content), {k: response.headers[k] for k in allowed if k in response.headers}
            finally:
                response.close()
        except Exception:
            raise AnalysisError("MEMBERSHIP_UNAVAILABLE", "模拟支付页暂不可用，请稍后重新打开原订单；不要重复购买。", 503) from None

    def login(self, email, password):
        result = self.call("/login", {"email": email, "password": password})
        session_id = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (session_id, result["token"], result["expires"]))
        return session_id, result["expires"]

    def logout(self, session_id):
        try:
            access = self.session(session_id)["access"]
        except AnalysisError:
            access = None
        # Local removal is unconditional; quota receipt still permits settling existing jobs.
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        if access:
            self.call("/logout", {}, access)

    def me(self, session_id, refresh=False):
        access = self.session(session_id)["access"]
        self.flush()
        return self.call("/refresh" if refresh else "/me", {} if refresh else None, access)

    def auto_owner(self, job_id, session_id=None, write=False):
        with self.db() as db:
            if write:
                db.execute("INSERT OR IGNORE INTO auto_owners VALUES(?,?)", (job_id, session_id))
            row = db.execute("SELECT session_id FROM auto_owners WHERE job_id=?", (job_id,)).fetchone()
        return row[0] if row else None

    def reserve(self, job_id, session_id):
        access = self.session(session_id)["access"]
        self.flush()
        receipt = secrets.token_urlsafe(32)
        # Save intent and receipt before the network call so an unknown response can be retried safely.
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO quota_jobs(job_id,session_id,receipt,expires) VALUES(?,?,?,?)", (job_id, session_id, receipt, time.time()+7200))
            row = db.execute("SELECT * FROM quota_jobs WHERE job_id=?", (job_id,)).fetchone()
        try:
            value = self.call("/quota/reserve", {"task_id": job_id, "receipt": row["receipt"]}, access)
            if value["state"] != "reserved":
                raise AnalysisError("QUOTA_RESERVATION_INVALID", "额度预留已结束，请重新发起总结。", 409)
            with self.db() as db:
                db.execute("UPDATE quota_jobs SET reservation_id=?,expires=? WHERE job_id=?", (value["id"], value["expires"], job_id))
        except BaseException:
            with self.db() as db:
                db.execute("UPDATE quota_jobs SET outcome=0 WHERE job_id=?", (job_id,))
            raise

    def check(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT expires FROM quota_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row and row[0] is not None and row[0] <= time.time():
            raise AnalysisError("QUOTA_RESERVATION_EXPIRED", "总结任务预留已超过两小时，请重新生成。", 409)

    def complete(self, job_id, success, completed_at=None):
        with self.db() as db:
            stamp = datetime.fromisoformat(completed_at).timestamp() if completed_at else time.time()
            db.execute("UPDATE quota_jobs SET outcome=?,completed_at=? WHERE job_id=? AND outcome IS NULL", (int(success), stamp, job_id))
        self.flush()

    def recover(self, learning_store):
        with self.db() as db:
            rows = db.execute("SELECT job_id FROM quota_jobs WHERE outcome IS NULL").fetchall()
            for row in rows:
                job = learning_store.job(row[0])
                stamp = datetime.fromisoformat(job["updated_at"]).timestamp() if job else time.time()
                db.execute("UPDATE quota_jobs SET outcome=?,completed_at=? WHERE job_id=?", (int(bool(job and job["status"] == "ready")), stamp, row[0]))
        self.flush()

    def flush(self):
        if not self.flush_lock.acquire(blocking=False):
            return
        try:
            with self.db() as db:
                rows = [dict(r) for r in db.execute("SELECT * FROM quota_jobs WHERE outcome IS NOT NULL AND settled=0 LIMIT 30")]
            for row in rows:
                try:
                    if not row["reservation_id"]:
                        value = self.call("/quota/recover", {"task_id": row["job_id"]}, row["receipt"])
                        row["reservation_id"] = value["id"]
                        with self.db() as db:
                            db.execute("UPDATE quota_jobs SET reservation_id=?,expires=? WHERE job_id=?", (value["id"], value["expires"], row["job_id"]))
                    self.call("/quota/" + row["reservation_id"] + "/settle", {"success": bool(row["outcome"]), "completed_at": row["completed_at"]}, row["receipt"])
                    with self.db() as db:
                        db.execute("UPDATE quota_jobs SET settled=1,receipt='' WHERE job_id=?", (row["job_id"],))
                except AnalysisError as error:
                    if error.code == "RESERVATION_NOT_FOUND" and row["expires"] <= time.time():
                        with self.db() as db:
                            db.execute("UPDATE quota_jobs SET settled=1,receipt='' WHERE job_id=?", (row["job_id"],))
                    if error.status_code == 503:
                        break
                    # Keep durable work for the next status read/reservation/restart. Remote stale leases expire.
                    continue
        finally:
            self.flush_lock.release()


_client = None
_lock = threading.RLock()


def close_membership_client():
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None


def get_membership_client():
    global _client
    with _lock:
        if _client is None:
            file = Path(__file__).resolve().parents[2] / ".env"
            settings = dotenv_values(file) if file.is_file() else {}
            url = os.environ.get("MEMBERSHIP_SERVICE_URL", settings.get("MEMBERSHIP_SERVICE_URL") or "")
            if not url:
                return None
            path = os.environ.get("MEMBERSHIP_LOCAL_DB", settings.get("MEMBERSHIP_LOCAL_DB") or str(Path(__file__).resolve().parents[1] / "data/local-account.sqlite3"))
            try:
                _client = MembershipClient(url, path)
            except (ValueError, OSError, sqlite3.Error):
                raise AnalysisError("MEMBERSHIP_CONFIG_INVALID", "本机会员服务地址或数据目录配置错误，请检查 MEMBERSHIP_SERVICE_URL 和本机账号数据目录。下载功能仍可使用。", 503) from None
        return _client
