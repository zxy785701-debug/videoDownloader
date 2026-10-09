import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from . import mail
from .security import digest, password_hash, password_matches, token


class BillingError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def identifier():
    return secrets.token_urlsafe(18)


def beijing_day(now):
    return datetime.fromtimestamp(now, timezone(timedelta(hours=8))).date().isoformat()


class MembershipService:
    def __init__(self, config, store, provider, clock=time.time):
        self.config, self.store, self.provider, self.clock = config, store, provider, clock
        # A constant-cost fallback avoids cheaply detecting unknown users at login.
        self.dummy_password = password_hash(token())

    def throttle(self, scope, identity, limit=10, window=600):
        now = int(self.clock()) // window
        key = scope + ":" + digest(identity)
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT * FROM rate_limits WHERE key=?", (key,)).fetchone()
            count = row["count"] + 1 if row and row["period"] == now else 1
            db.execute("INSERT INTO rate_limits VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET period=excluded.period,count=excluded.count", (key, now, count))
        if count > limit:
            raise BillingError("RATE_LIMITED", "操作过于频繁，请稍后再试。", 429)

    def email(self, value):
        value = value.strip().lower()
        if len(value) > 254 or not re.fullmatch(r"[^@\s\x00-\x1f]+@[^@\s\x00-\x1f]+\.[^@\s\x00-\x1f]+", value):
            raise BillingError("EMAIL_INVALID", "请输入有效的邮箱地址。")
        return value

    def password(self, value):
        if not 12 <= len(value) <= 128:
            raise BillingError("PASSWORD_INVALID", "密码需为 12～128 个字符。")

    def issue_mail(self, user, kind):
        code = token()
        with self.store.connection(write=True) as db:
            db.execute("DELETE FROM mail_tokens WHERE user_id=? AND kind=?", (user["id"], kind))
            db.execute("INSERT INTO mail_tokens VALUES(?,?,?,?,0)", (digest(code), user["id"], kind, self.clock() + 1800))
        try:
            mail.deliver(self.config, user["email"], kind, code)
        except Exception:
            with self.store.connection(write=True) as db:
                db.execute("DELETE FROM mail_tokens WHERE digest=?", (digest(code),))
            raise BillingError("MAIL_UNAVAILABLE", "邮件发送暂不可用，请稍后重试或联系运营者。", 503) from None

    def register(self, email, password):
        email = self.email(email)
        self.password(password)
        self.throttle("register", email)
        hashed = password_hash(password)
        with self.store.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO users VALUES(?,?,?,0,?)", (identifier(), email, hashed, self.clock()))
            user = dict(db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())
        if self.config.require_email_verification and not user["verified"]:
            self.issue_mail(user, "verify")
        return {"message": self.mail_notice() if self.config.require_email_verification else "注册已处理，无需邮箱验证，请使用邮箱和密码登录；已有账号请使用原密码。",
                "verification_required": self.config.require_email_verification}

    def mail_notice(self):
        if mail.delivery_mode(self.config) == "local_file":
            return "若邮箱符合操作条件，邮件仅保存在本机测试目录，未发送到真实邮箱。"
        return "若邮箱符合操作条件，邮件已提交发信服务器，请检查收件箱或垃圾邮件；提交成功不代表已送达。"

    def send_code(self, email, kind):
        email = self.email(email)
        self.throttle(kind, email)
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row and (kind == "reset" or not row["verified"]):
            self.issue_mail(dict(row), kind)
        return {"message": self.mail_notice()}

    def verify_email(self, code):
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT * FROM mail_tokens WHERE digest=? AND kind='verify' AND used=0 AND expires>?", (digest(code), self.clock())).fetchone()
            if not row:
                raise BillingError("CODE_INVALID", "验证码无效或已过期。")
            db.execute("UPDATE mail_tokens SET used=1 WHERE digest=?", (digest(code),))
            db.execute("UPDATE users SET verified=1 WHERE id=?", (row["user_id"],))
        return {"message": "邮箱已验证，请登录。"}

    def reset_password(self, code, password):
        self.password(password)
        hashed = password_hash(password)
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT * FROM mail_tokens WHERE digest=? AND kind='reset' AND used=0 AND expires>?", (digest(code), self.clock())).fetchone()
            if not row:
                raise BillingError("CODE_INVALID", "重置码无效或已过期。")
            db.execute("UPDATE users SET password=?,verified=1 WHERE id=?", (hashed, row["user_id"]))
            db.execute("UPDATE mail_tokens SET used=1 WHERE user_id=?", (row["user_id"],))
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
        return {"message": "密码已重置，旧登录已失效，请重新登录。"}

    def login(self, email, password):
        email = self.email(email)
        self.throttle("login", email)
        with self.store.connection() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        valid = password_matches(password, user["password"] if user else self.dummy_password)
        if not user or not valid or (self.config.require_email_verification and not user["verified"]):
            message = "邮箱、密码或邮箱验证状态不正确。" if self.config.require_email_verification else "邮箱或密码不正确。"
            raise BillingError("LOGIN_FAILED", message, 401)
        access = token()
        expires = self.clock() + 7 * 86400
        with self.store.connection(write=True) as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (self.clock(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(access), user["id"], expires))
        return {"token": access, "expires": expires}

    def authenticate(self, access):
        if not access:
            raise BillingError("LOGIN_REQUIRED", "请先登录账号。", 401)
        with self.store.connection() as db:
            row = db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.digest=? AND s.expires>? AND (u.verified=1 OR ?=0)", (digest(access), self.clock(), int(self.config.require_email_verification))).fetchone()
        if not row:
            raise BillingError("LOGIN_REQUIRED", "登录已失效，请重新登录。", 401)
        return dict(row)

    def logout(self, access):
        with self.store.connection(write=True) as db:
            db.execute("DELETE FROM sessions WHERE digest=?", (digest(access),))

    def active_expiry(self, db, user_id):
        row = db.execute("SELECT MAX(expires) FROM grants WHERE user_id=? AND revoked=0 AND disputed=0 AND starts<=? AND expires>?", (user_id, self.clock(), self.clock())).fetchone()
        return row[0]

    def expire_reservations(self, db):
        # An expired worker may have completed before its deadline while settlement was offline.
        # Keep its daily slot until reconciliation; a new day has an independent allowance.
        db.execute("UPDATE reservations SET state='expired' WHERE state='reserved' AND expires<=?", (self.clock(),))

    def quota(self, db, user_id):
        self.expire_reservations(db)
        day = beijing_day(self.clock())
        expires = self.active_expiry(db, user_id)
        counts = dict((r["state"], r["n"]) for r in db.execute("SELECT state,COUNT(*) n FROM reservations WHERE user_id=? AND day=? GROUP BY state", (user_id, day)))
        limit = self.config.member_limit if expires else self.config.free_limit
        used, reserved = counts.get("consumed", 0), counts.get("reserved", 0) + counts.get("expired", 0)
        return {"day": day, "timezone": "Asia/Shanghai", "limit": limit, "used": used, "reserved": reserved, "remaining": max(0, limit-used-reserved), "member_expires": expires}

    def me(self, user):
        with self.store.connection(write=True) as db:
            quota = self.quota(db, user["id"])
            order = db.execute("SELECT id,status,created FROM orders WHERE user_id=? ORDER BY created DESC LIMIT 1", (user["id"],)).fetchone()
        return {"email": user["email"], "quota": quota, "order": dict(order) if order else None,
                "plan": {"amount": 1990, "currency": "cny", "days": 30, "auto_renew": False}, "simulated": self.config.provider == "mock"}

    def checkout(self, user):
        self.throttle("checkout", user["id"], 30, 600)
        # Price validation occurs before any order or Stripe write.
        price = self.provider.price()
        if not (price.get("active") and price.get("type") == "one_time" and price.get("unit_amount") == 1990 and price.get("currency") == "cny" and price.get("livemode") == self.config.live):
            raise BillingError("PRICE_INVALID", "运营者配置的 Stripe 商品需为一次性 ¥19.90 人民币，请联系运营者。", 503)
        with self.store.connection(write=True) as db:
            if self.active_expiry(db, user["id"]):
                raise BillingError("ALREADY_MEMBER", "会员仍在有效期内，暂不重复购买。", 409)
            row = db.execute("SELECT * FROM orders WHERE user_id=? AND status IN ('creating','unknown','open','waiting','review')", (user["id"],)).fetchone()
            if not row:
                order_id = identifier()
                created = int(self.clock())
                params = {"mode": "payment", "line_items": [{"price": price["id"], "quantity": 1}],
                          "client_reference_id": user["id"], "metadata": {"order_id": order_id, "user_id": user["id"]},
                          "payment_intent_data": {"metadata": {"order_id": order_id, "user_id": user["id"]}},
                          "success_url": self.config.public_url + "/checkout-return", "cancel_url": self.config.public_url + "/checkout-return?cancelled=1",
                          "expires_at": created + 3600, "allow_promotion_codes": False,
                          "adaptive_pricing": {"enabled": False}}
                db.execute("INSERT INTO orders(id,user_id,status,created,params) VALUES(?,?,'creating',?,?)", (order_id, user["id"], created, json.dumps(params, sort_keys=True)))
                row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            order = dict(row)
        if order["session_id"]:
            self.reconcile(order)
            with self.store.connection() as db:
                order = dict(db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone())
            if order["status"] == "open":
                return self.public_order(order)
            if order["status"] == "expired":
                raise BillingError("ORDER_EXPIRED", "之前的支付页已过期，请再次点击购买创建新订单。", 409)
            if order["status"] == "review":
                raise BillingError("ORDER_REVIEW", "异步支付未成功且旧付款状态需核实，请运营者处理原订单后再购买。", 409)
            raise BillingError("ORDER_PENDING", "已有订单待确认，请刷新状态；若已付款，请勿重复购买。", 409)
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
            if row["session_id"]:
                return self.public_order(dict(row))
            if row["status"] == "review" or self.clock() >= row["created"] + 3500:
                db.execute("UPDATE orders SET status='review',last_error='creation_window_elapsed' WHERE id=?", (row["id"],))
                blocked = True
            elif row["creation_lease"] > self.clock():
                raise BillingError("ORDER_BUSY", "支付页正在准备，请稍后重试同一订单。", 409)
            else:
                blocked = False
                db.execute("UPDATE orders SET creation_lease=?,status='creating' WHERE id=?", (self.clock()+180, row["id"]))
        if blocked:
            raise BillingError("ORDER_REVIEW", "订单创建结果待核实，已暂停再次付款；请运营者在 Stripe 后台按订单标识对账。", 409)
        try:
            result = self.provider.create(json.loads(order["params"]), "saveany-order-" + order["id"])
            if not result.get("id") or not self.safe_checkout_url(result.get("url", "")):
                raise ValueError("Invalid Checkout response")
        except Exception:
            with self.store.connection(write=True) as db:
                db.execute("UPDATE orders SET status='unknown',creation_lease=0,last_error='creation_unknown' WHERE id=? AND session_id IS NULL", (order["id"],))
            raise BillingError("PAYMENT_UNAVAILABLE", "支付页创建暂未确认，请重试同一订单，不要另开付款。", 503) from None
        with self.store.connection(write=True) as db:
            # A webhook can arrive before create() returns; never overwrite paid state.
            db.execute("UPDATE orders SET session_id=?,checkout_url=?,creation_lease=0,status=CASE WHEN status IN ('creating','unknown') THEN 'open' ELSE status END WHERE id=?", (result["id"], result["url"], order["id"]))
            order = dict(db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone())
        return self.public_order(order)

    def safe_checkout_url(self, url):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.username or parsed.password:
            return False
        if self.config.provider == "mock":
            return url.startswith(self.config.public_url + "/dev/checkout/")
        return parsed.scheme == "https" and parsed.hostname == "checkout.stripe.com"

    def public_order(self, order):
        return {"id": order["id"], "status": order["status"], "checkout_url": order["checkout_url"] if order["status"] == "open" else None, "simulated": self.config.provider == "mock"}

    def refresh(self, user):
        with self.store.connection() as db:
            orders = [dict(r) for r in db.execute("SELECT * FROM orders WHERE user_id=? AND session_id IS NOT NULL AND status IN ('open','waiting','review','paid','disputed') ORDER BY created DESC LIMIT 10", (user["id"],))]
        for order in orders:
            self.reconcile(order)
        return self.me(user)

    def reconcile(self, order):
        session = self.provider.session(order["session_id"])
        self.apply_session(session)

    def validate_session(self, session, order):
        metadata = session.get("metadata", {})
        lines = session.get("line_items", {})
        items = lines.get("data", [])
        intent = session.get("payment_intent")
        params = json.loads(order["params"])
        if not (session.get("mode") == "payment" and session.get("livemode") == self.config.live
                and metadata.get("order_id") == order["id"] and metadata.get("user_id") == order["user_id"]
                and session.get("client_reference_id") == order["user_id"]
                and session.get("amount_total") == 1990 and session.get("currency") == "cny"
                and len(items) == 1 and not lines.get("has_more") and items[0].get("quantity") == 1
                and items[0].get("price", {}).get("id") == params["line_items"][0]["price"]
                and (not order["session_id"] or order["session_id"] == session.get("id"))):
            raise BillingError("PAYMENT_MISMATCH", "支付信息与订单不匹配，需运营者核实。", 409)
        if session.get("payment_status") == "paid" and not (isinstance(intent, dict) and intent.get("id") and intent.get("status") == "succeeded" and isinstance(intent.get("latest_charge"), dict)):
            raise BillingError("PAYMENT_INCOMPLETE", "支付状态尚未完整确认，请稍后刷新。", 409)

    def apply_session(self, session, event=None):
        order_id = session.get("metadata", {}).get("order_id")
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row:
            return False  # Other products and Stripe CLI fixtures never grant membership.
        order = dict(row)
        self.validate_session(session, order)
        now = self.clock()
        dispute_statuses = []
        if session.get("payment_status") == "paid" and session["payment_intent"]["latest_charge"].get("disputed"):
            dispute_statuses = [d["status"] for d in self.provider.disputes(session["payment_intent"]["id"])]
            if not dispute_statuses:
                raise BillingError("DISPUTE_PENDING", "争议状态待核实，请稍后刷新。", 409)
        with self.store.connection(write=True) as db:
            if event and db.execute("SELECT 1 FROM events WHERE id=?", (event["id"],)).fetchone():
                return True
            current = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if current["session_id"] and current["session_id"] != session["id"]:
                raise BillingError("SESSION_CONFLICT", "支付会话冲突，请运营者核实。", 409)
            if session.get("payment_status") == "paid":
                intent = session["payment_intent"]
                charge = intent["latest_charge"]
                revoked = bool(charge.get("refunded") or charge.get("amount_refunded", 0) >= 1990 or "lost" in dispute_statuses)
                disputed = any(status not in {"won", "warning_closed"} for status in dispute_statuses)
                db.execute("INSERT OR IGNORE INTO grants VALUES(?,?,?,?,?,?)", (order_id, order["user_id"], now, now+30*86400, int(revoked), int(disputed)))
                db.execute("UPDATE grants SET revoked=MAX(revoked,?),disputed=? WHERE order_id=?", (int(revoked), int(disputed), order_id))
                status = "refunded" if revoked else "disputed" if disputed else "paid"
                db.execute("UPDATE orders SET status=?,session_id=?,payment_id=?,paid_at=COALESCE(paid_at,?),creation_lease=0,last_error=NULL WHERE id=?", (status, session["id"], intent["id"], now, order_id))
            elif not db.execute("SELECT 1 FROM grants WHERE order_id=?", (order_id,)).fetchone():
                cancelled = isinstance(session.get("payment_intent"), dict) and session["payment_intent"].get("status") == "canceled"
                status = "expired" if session.get("status") == "expired" or cancelled else "review" if current["last_error"] == "async_failed_requires_review" else "waiting" if session.get("status") == "complete" else "open"
                db.execute("UPDATE orders SET status=?,session_id=?,creation_lease=0 WHERE id=?", (status, session["id"], order_id))
            if event:
                db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?)", (event["id"], event["type"], session["id"], now))
        return True

    def webhook(self, payload, signature):
        try:
            event = self.provider.verify(payload, signature)
        except Exception:
            raise BillingError("SIGNATURE_INVALID", "支付通知签名无效。", 400) from None
        if event.get("livemode") != self.config.live:
            raise BillingError("MODE_MISMATCH", "支付通知环境不匹配。", 400)
        if not isinstance(event.get("id"), str) or not isinstance(event.get("type"), str):
            raise BillingError("EVENT_INVALID", "支付通知格式错误。")
        with self.store.connection() as db:
            if db.execute("SELECT 1 FROM events WHERE id=?", (event["id"],)).fetchone():
                return {"received": True}
        kind, obj = event["type"], event.get("data", {}).get("object", {})
        if kind in {"checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.async_payment_failed", "checkout.session.expired"}:
            session = self.provider.session(obj["id"])
            self.apply_session(session, event)
            # Async failure is terminal only when the PaymentIntent is definitively cancelled.
            if kind == "checkout.session.async_payment_failed" and session.get("payment_status") != "paid":
                with self.store.connection(write=True) as db:
                    # Checkout-linked intents usually cannot be directly cancelled.
                    # Never make a second chargeable intent merely because an async failure arrived.
                    db.execute("UPDATE orders SET status='review',last_error='async_failed_requires_review' WHERE session_id=? AND status='waiting'", (session["id"],))
        elif kind in {"charge.refunded", "refund.updated", "refund.created", "charge.dispute.created", "charge.dispute.closed", "charge.dispute.updated"}:
            payment_id = obj.get("payment_intent")
            if isinstance(payment_id, dict):
                payment_id = payment_id.get("id")
            if payment_id:
                # Read latest state, never undo a full refund due to an old event.
                for item in self.provider.sessions_for_payment(payment_id):
                    self.apply_session(self.provider.session(item["id"]))
        with self.store.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?)", (event["id"], kind, str(obj.get("id", "")), self.clock()))
        return {"received": True}

    def reserve(self, user, task_id, receipt):
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", task_id) or not re.fullmatch(r"[A-Za-z0-9_-]{32,100}", receipt):
            raise BillingError("RESERVATION_INVALID", "额度任务标识不合法。")
        with self.store.connection(write=True) as db:
            self.expire_reservations(db)
            row = db.execute("SELECT * FROM reservations WHERE user_id=? AND task_id=?", (user["id"], task_id)).fetchone()
            if row:
                if row["receipt_digest"] != digest(receipt):
                    raise BillingError("RESERVATION_CONFLICT", "额度任务凭据不匹配。", 409)
                return {"id": row["id"], "state": row["state"], "expires": row["expires"]}
            quota = self.quota(db, user["id"])
            if quota["remaining"] <= 0:
                raise BillingError("QUOTA_EXCEEDED", f"今日 AI 总结额度已用完（{quota['limit']} 次），请明天再试或查看会员。", 429)
            reservation_id, expires = identifier(), self.clock() + 7200
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,'reserved',?,?)", (reservation_id, user["id"], task_id, quota["day"], digest(receipt), expires))
        return {"id": reservation_id, "state": "reserved", "expires": expires}

    def settle(self, reservation_id, receipt, success, completed_at=None):
        with self.store.connection(write=True) as db:
            self.expire_reservations(db)
            row = db.execute("SELECT * FROM reservations WHERE id=? AND receipt_digest=?", (reservation_id, digest(receipt))).fetchone()
            if not row:
                raise BillingError("RESERVATION_NOT_FOUND", "额度凭据无效。", 404)
            if row["state"] in {"reserved", "expired"}:
                stamp = completed_at if completed_at is not None else self.clock()
                if success and not (row["expires"]-7200 <= stamp <= row["expires"] and stamp <= self.clock()+60):
                    raise BillingError("RESERVATION_EXPIRED", "任务未在额度预留期限内成功，请重新生成。", 409)
                db.execute("UPDATE reservations SET state=? WHERE id=?", ("consumed" if success else "released", reservation_id))
                state = "consumed" if success else "released"
            else:
                state = row["state"]
            if success and state != "consumed":
                raise BillingError("RESERVATION_EXPIRED", "额度预留已释放或到期，请重新生成。", 409)
        return {"state": state}

    def recover_reservation(self, task_id, receipt):
        with self.store.connection() as db:
            row = db.execute("SELECT id,state,expires FROM reservations WHERE task_id=? AND receipt_digest=?", (task_id, digest(receipt))).fetchone()
        if not row:
            raise BillingError("RESERVATION_NOT_FOUND", "额度预留尚未找到。", 404)
        return dict(row)
