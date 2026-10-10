"""Stripe API boundary; mock is persistent, visibly simulated and development-only."""
import hashlib
import hmac
import json
import secrets
import time

import stripe

from .security import mock_checkout_path


class StripeProvider:
    def __init__(self, config):
        self.config = config
        self.client = stripe.StripeClient(config.secret_key, max_network_retries=2,
                                          http_client=stripe.RequestsClient(timeout=15))

    def create(self, params, key):
        return self.client.v1.checkout.sessions.create(params=params, options={"idempotency_key": key}).to_dict()

    def session(self, session_id):
        return self.client.v1.checkout.sessions.retrieve(session_id, params={"expand": ["line_items.data.price", "payment_intent.latest_charge"]}).to_dict()

    def verify(self, payload, signature):
        return stripe.Webhook.construct_event(payload, signature, self.config.webhook_secret, tolerance=300).to_dict()

    def price(self):
        return self.client.v1.prices.retrieve(self.config.price_id).to_dict()

    def sessions_for_payment(self, payment_id):
        return self.client.v1.checkout.sessions.list(params={"payment_intent": payment_id, "limit": 10}).to_dict()["data"]

    def payment(self, payment_id):
        return self.client.v1.payment_intents.retrieve(payment_id, params={"expand": ["latest_charge"]}).to_dict()

    def disputes(self, payment_id):
        return self.client.v1.disputes.list(params={"payment_intent": payment_id, "limit": 100}).to_dict()["data"]


class MockProvider:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.clock = time.time
        with store.connection(write=True) as db:
            db.execute("CREATE TABLE IF NOT EXISTS mock_sessions (id TEXT PRIMARY KEY, key TEXT UNIQUE, params TEXT NOT NULL, data TEXT NOT NULL)")

    def price(self):
        return {"id": self.config.price_id or "price_mock_30days", "active": True, "currency": "cny", "unit_amount": 1990, "type": "one_time", "livemode": False}

    def create(self, params, key):
        with self.store.connection(write=True) as db:
            prior = db.execute("SELECT * FROM mock_sessions WHERE key=?", (key,)).fetchone()
            serialized = json.dumps(params, sort_keys=True)
            if prior:
                if prior["params"] != serialized:
                    raise ValueError("Mock idempotency parameter conflict")
                result = json.loads(prior["data"])
                result["url"] = mock_checkout_path(result["id"])
                return result
            session_id = "cs_test_mock_" + secrets.token_urlsafe(24)
            result = {"id": session_id, "mode": "payment", "livemode": False, "status": "open", "payment_status": "unpaid",
                      "currency": "cny", "amount_total": 1990, "metadata": params["metadata"], "client_reference_id": params["client_reference_id"],
                      "expires_at": params["expires_at"], "payment_intent": None,
                      "line_items": {"has_more": False, "data": [{"quantity": 1, "price": self.price()}]},
                      "url": mock_checkout_path(session_id)}
            db.execute("INSERT INTO mock_sessions VALUES (?,?,?,?)", (session_id, key, serialized, json.dumps(result)))
            return result

    def session(self, session_id):
        with self.store.connection() as db:
            row = db.execute("SELECT data FROM mock_sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise ValueError("Unknown mock session")
        result = json.loads(row["data"])
        result["url"] = mock_checkout_path(result["id"])
        if result["status"] == "open" and result["expires_at"] <= self.clock():
            result["status"] = "expired"
        return result

    def set_session(self, session_id, **fields):
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT data FROM mock_sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                raise ValueError("Unknown mock session")
            value = json.loads(row["data"])
            value.update(fields)
            db.execute("UPDATE mock_sessions SET data=? WHERE id=?", (json.dumps(value), session_id))
            return value

    def pay(self, session_id):
        value = self.session(session_id)
        if value["status"] != "open":
            return value
        payment_id = "pi_mock_" + session_id
        return self.set_session(session_id, status="complete", payment_status="paid",
                                payment_intent={"id": payment_id, "status": "succeeded", "latest_charge": {"refunded": False, "amount_refunded": 0, "disputed": False}})

    def payment(self, payment_id):
        with self.store.connection() as db:
            rows = db.execute("SELECT data FROM mock_sessions").fetchall()
        for row in rows:
            value = json.loads(row["data"])
            intent = value.get("payment_intent")
            if isinstance(intent, dict) and intent["id"] == payment_id:
                return intent
        raise ValueError("Unknown mock payment")

    def sessions_for_payment(self, payment_id):
        with self.store.connection() as db:
            rows = db.execute("SELECT data FROM mock_sessions").fetchall()
        return [value for row in rows if (value := json.loads(row["data"])).get("payment_intent", {}) and value["payment_intent"]["id"] == payment_id]

    def disputes(self, payment_id):
        intent = self.payment(payment_id)
        return [{"status": intent["mock_dispute_status"]}] if intent.get("mock_dispute_status") else []

    def signed_event(self, kind, value):
        payload = json.dumps({"id": "evt_mock_" + secrets.token_hex(16), "type": kind, "livemode": False, "data": {"object": value}}).encode()
        stamp = int(time.time())
        secret = self.config.webhook_secret or "whsec_mock_local_only"
        signature = hmac.new(secret.encode(), str(stamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
        return payload, f"t={stamp},v1={signature}"

    def verify(self, payload, signature):
        return stripe.Webhook.construct_event(payload, signature, self.config.webhook_secret or "whsec_mock_local_only", tolerance=300).to_dict()
