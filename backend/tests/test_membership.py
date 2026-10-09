"""Isolated payment/account/quota tests. No Stripe network, funds or model calls."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from email import policy
from email.parser import Parser
import json
import secrets
import ssl
import time

import httpx
from fastapi.testclient import TestClient
import pytest

from billing.config import Config, load_config
from billing.main import create_app
from billing.provider import MockProvider
from billing.provider import StripeProvider
from billing.service import BillingError, beijing_day
from billing.security import digest
from app.analysis_errors import AnalysisError
from app.membership_client import MembershipClient
from app import summary_service, subtitle_service
from test_learning import engine, store, ready_record, content, finish, transcript_result


PASSWORD = "test-password-very-long"


@pytest.mark.parametrize("url", ["http://127.0.0.1:8010", "https://members.example.com"])
def test_pooled_http_requests_isolate_credentials_and_close_safely(tmp_path, monkeypatch, url):
    requests = []
    creations = []
    real_client = httpx.Client
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True}, headers={"Set-Cookie": "account=another-user; Path=/"})
    def factory(**options):
        creations.append(options)
        return real_client(transport=httpx.MockTransport(handler), **options)
    monkeypatch.setattr(httpx, "Client", factory)
    bridge = MembershipClient(url, tmp_path / "local.sqlite3")
    assert not creations  # The local navigation check does not construct a network client.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda access: bridge.call("/me", access=access), ["first-user", "second-user", None]))
    assert all(r == {"ok": True} for r in results)
    assert len(creations) == 1
    assert sorted(r.headers.get("Authorization", "") for r in requests) == ["", "Bearer first-user", "Bearer second-user"]
    assert all("Cookie" not in r.headers for r in requests)
    assert creations[0]["follow_redirects"] is False
    if url.startswith("https"):
        assert creations[0]["verify"] is True and creations[0]["trust_env"] is True
    else:
        context = creations[0]["verify"]
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert creations[0]["trust_env"] is False
    bridge.close()
    assert bridge.http_client.is_closed
    with pytest.raises(AnalysisError) as error:
        bridge.call("/config")
    assert error.value.code == "MEMBERSHIP_UNAVAILABLE" and len(creations) == 1


def test_navigation_config_does_not_wait_for_cloud_and_guests_do_not_flush_other_jobs(tmp_path, monkeypatch):
    from app import membership_routes
    from app.main import app
    bridge = MembershipClient("http://127.0.0.1:8010", tmp_path / "local.sqlite3")
    def unavailable(*args, **kwargs):
        raise AssertionError("Local config/guest status must not contact the cloud or settle jobs")
    bridge.call = unavailable
    bridge.flush = unavailable
    monkeypatch.setattr(membership_routes, "get_membership_client", lambda: bridge)
    api = TestClient(app, base_url="http://127.0.0.1:8000")
    assert api.get("/api/v1/account/config").json() == {"enabled": True}
    assert api.get("/api/v1/account/me").status_code == 401
    bridge.close()


def read_code(directory):
    file = max(directory.glob("*.eml"), key=lambda p: p.stat().st_mtime_ns)
    message = Parser(policy=policy.default).parsestr(file.read_text(encoding="utf-8"))
    return message.get_content().split("\n\n")[1].strip()


@pytest.fixture
def billing(tmp_path):
    config = Config(provider="mock", database=tmp_path / "billing.sqlite3", mail_directory=tmp_path / "mail", require_email_verification=True)
    app = create_app(config)
    service = app.state.service
    service.register("buyer@example.com", PASSWORD)
    service.verify_email(read_code(config.mail_directory))
    access = service.login("buyer@example.com", PASSWORD)["token"]
    return service, service.authenticate(access), access, TestClient(app, base_url=config.public_url)


def paid(service, user):
    order = service.checkout(user)
    session_id = order["checkout_url"].rsplit("/", 1)[1]
    value = service.provider.pay(session_id)
    payload, signature = service.provider.signed_event("checkout.session.completed", value)
    service.webhook(payload, signature)
    return order, value, payload, signature


def test_default_registration_allows_login_and_membership_without_sending_mail(tmp_path, monkeypatch):
    config = Config(provider="mock", database=tmp_path / "billing.sqlite3", mail_directory=tmp_path / "mail")
    app = create_app(config)
    service = app.state.service
    api = TestClient(app, base_url=config.public_url)
    def no_mail(*args):
        raise AssertionError("Registration must not send or save email when verification is disabled")
    monkeypatch.setattr("billing.mail.deliver", no_mail)
    assert api.get("/api/membership/v1/config").json() == {
        "verification_required": False, "mail_delivery": "local_file", "simulated": True,
    }
    registered = api.post("/api/membership/v1/register", json={"email": "new@example.com", "password": PASSWORD})
    assert registered.status_code == 200 and registered.json()["verification_required"] is False
    login = api.post("/api/membership/v1/login", json={"email": "new@example.com", "password": PASSWORD})
    assert login.status_code == 200
    user = service.authenticate(login.json()["token"])
    assert user["verified"] == 0
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM mail_tokens").fetchone()[0] == 0
    assert not config.mail_directory.exists()
    assert service.me(user)["quota"]["limit"] == 3
    reservation = service.reserve(user, secrets.token_urlsafe(18), secrets.token_urlsafe(32))
    assert reservation["state"] == "reserved"
    paid(service, user)
    assert service.me(user)["quota"]["limit"] == 30


def test_existing_unverified_account_can_login_without_registration_or_password_overwrite(billing):
    service, _, _, _ = billing
    service.register("pending@example.com", PASSWORD)
    service.config = replace(service.config, require_email_verification=False)
    first_access = service.login("pending@example.com", PASSWORD)["token"]
    assert service.authenticate(first_access)["verified"] == 0
    service.register("pending@example.com", PASSWORD + "different")
    assert service.authenticate(service.login("pending@example.com", PASSWORD)["token"])
    with pytest.raises(BillingError) as error:
        service.login("pending@example.com", PASSWORD + "different")
    assert error.value.code == "LOGIN_FAILED"


def test_enabling_verification_requires_existing_unverified_accounts_to_verify(tmp_path):
    config = Config(provider="mock", database=tmp_path / "billing.sqlite3", mail_directory=tmp_path / "mail")
    service = create_app(config).state.service
    service.register("pending@example.com", PASSWORD)
    access = service.login("pending@example.com", PASSWORD)["token"]
    gated = create_app(replace(config, require_email_verification=True)).state.service
    with pytest.raises(BillingError) as error:
        gated.authenticate(access)
    assert error.value.code == "LOGIN_REQUIRED"
    with pytest.raises(BillingError):
        gated.login("pending@example.com", PASSWORD)
    gated.send_code("pending@example.com", "verify")
    gated.verify_email(read_code(config.mail_directory))
    assert gated.authenticate(gated.login("pending@example.com", PASSWORD)["token"])["verified"] == 1


@pytest.mark.parametrize("required", [False, True])
def test_verification_environment_switch_is_loaded_explicitly(tmp_path, monkeypatch, required):
    monkeypatch.setenv("BILLING_CONFIG_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("BILLING_PROVIDER", "mock")
    monkeypatch.setenv("BILLING_ENV", "development")
    monkeypatch.setenv("BILLING_PUBLIC_URL", "http://127.0.0.1:8010")
    monkeypatch.setenv("BILLING_REQUIRE_EMAIL_VERIFICATION", str(required).lower())
    assert load_config().require_email_verification is required
    monkeypatch.setenv("BILLING_REQUIRE_EMAIL_VERIFICATION", "typo")
    with pytest.raises(ValueError, match="true or false"):
        load_config()


def test_mail_notice_distinguishes_local_file_and_smtp_without_exposing_account_existence(billing, monkeypatch):
    service, user, _, _ = billing
    local = service.send_code(user["email"], "reset")
    assert "未发送到真实邮箱" in local["message"]
    assert service.send_code("unknown@example.com", "reset") == local
    code = read_code(service.config.mail_directory)
    service.reset_password(code, PASSWORD + "reset")
    assert service.login(user["email"], PASSWORD + "reset")
    service.config = replace(service.config, mail_host="smtp.example.com")
    monkeypatch.setattr("billing.mail.deliver", lambda *args: None)
    smtp = service.send_code(user["email"], "reset")
    assert "已提交发信服务器" in smtp["message"] and "不代表已送达" in smtp["message"]
    assert service.send_code("unknown@example.com", "reset") == smtp


def test_signup_verification_and_reset_are_single_use_and_revoke_sessions(billing):
    service, user, access, api = billing
    service.send_code(user["email"], "reset")
    code = read_code(service.config.mail_directory)
    service.reset_password(code, PASSWORD + "new")
    with pytest.raises(BillingError, match="旧|失效"):
        service.authenticate(access)
    with pytest.raises(BillingError, match="无效"):
        service.reset_password(code, PASSWORD)
    assert service.authenticate(service.login(user["email"], PASSWORD + "new")["token"])
    with service.store.connection() as db:
        assert PASSWORD not in db.execute("SELECT password FROM users").fetchone()[0]
        assert access not in [r[0] for r in db.execute("SELECT digest FROM sessions")]


def test_unverified_login_is_rejected_and_verification_expires(billing):
    service, _, _, _ = billing
    service.register("new@example.com", PASSWORD)
    code = read_code(service.config.mail_directory)
    with pytest.raises(BillingError) as error:
        service.login("new@example.com", PASSWORD)
    assert error.value.code == "LOGIN_FAILED"
    now = service.clock()
    service.clock = lambda: now + 1801
    with pytest.raises(BillingError):
        service.verify_email(code)


def test_public_auth_is_rate_limited_and_does_not_disclose_unknown_email(billing):
    service, user, _, api = billing
    unknown = api.post("/api/membership/v1/login", json={"email": "unknown@example.com", "password": PASSWORD})
    wrong = api.post("/api/membership/v1/login", json={"email": user["email"], "password": PASSWORD+"wrong"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    for _ in range(10):
        service.throttle("example", "same", 10)
    with pytest.raises(BillingError) as error:
        service.throttle("example", "same", 10)
    assert error.value.status == 429


def test_concurrent_checkout_has_one_order_and_one_provider_session(billing):
    service, user, _, _ = billing
    def buy(_):
        try:
            return service.checkout(user)
        except BillingError as error:
            assert error.code == "ORDER_BUSY"
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = [r for r in pool.map(buy, range(20)) if r]
    assert results and len({r["id"] for r in results}) == 1
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM mock_sessions").fetchone()[0] == 1


def test_unknown_create_retries_same_key_parameters_after_restart(billing, monkeypatch):
    service, user, _, _ = billing
    original = service.provider.create
    calls = []
    def timeout_after_create(params, key):
        calls.append((json.dumps(params, sort_keys=True), key))
        result = original(params, key)
        if len(calls) == 1:
            raise TimeoutError("response lost")
        return result
    monkeypatch.setattr(service.provider, "create", timeout_after_create)
    with pytest.raises(BillingError) as error:
        service.checkout(user)
    assert error.value.code == "PAYMENT_UNAVAILABLE"
    result = service.checkout(user)
    assert calls[0] == calls[1]
    app = create_app(service.config)
    assert app.state.service.checkout(user)["id"] == result["id"]
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM mock_sessions").fetchone()[0] == 1


def test_unknown_order_blocks_new_key_after_safe_creation_window(billing, monkeypatch):
    service, user, _, _ = billing
    monkeypatch.setattr(service.provider, "create", lambda *a: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(BillingError):
        service.checkout(user)
    now = service.clock()
    service.clock = lambda: now + 86401
    with pytest.raises(BillingError) as error:
        service.checkout(user)
    assert error.value.code == "ORDER_REVIEW"
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_only_verified_expiry_releases_pending_purchase(billing):
    service, user, _, _ = billing
    first = service.checkout(user)
    session_id = first["checkout_url"].rsplit("/", 1)[1]
    service.provider.set_session(session_id, status="expired")
    with pytest.raises(BillingError) as error:
        service.checkout(user)
    assert error.value.code == "ORDER_EXPIRED"
    assert service.checkout(user)["id"] != first["id"]


def test_duplicate_and_distinct_events_never_extend_grant_or_allow_repurchase(billing):
    service, user, _, _ = billing
    order, value, payload, signature = paid(service, user)
    before = service.me(user)["quota"]["member_expires"]
    service.webhook(payload, signature)
    p, s = service.provider.signed_event("checkout.session.async_payment_succeeded", value)
    service.webhook(p, s)
    assert service.me(user)["quota"]["member_expires"] == before
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 1
    with pytest.raises(BillingError) as error:
        service.checkout(user)
    assert error.value.code == "ALREADY_MEMBER"


@pytest.mark.parametrize("change", ["amount", "currency", "owner", "price", "quantity", "mode", "environment", "intent", "session"])
def test_payment_mismatch_never_grants(billing, change):
    service, user, _, _ = billing
    order = service.checkout(user)
    value = service.provider.pay(order["checkout_url"].rsplit("/", 1)[1])
    if change == "amount": value["amount_total"] = 1
    if change == "currency": value["currency"] = "usd"
    if change == "owner": value["metadata"]["user_id"] = "other"
    if change == "price": value["line_items"]["data"][0]["price"]["id"] = "price_other"
    if change == "quantity": value["line_items"]["data"][0]["quantity"] = 2
    if change == "mode": value["mode"] = "subscription"
    if change == "environment": value["livemode"] = True
    if change == "intent": value["payment_intent"] = "pi_unexpanded"
    if change == "session": value["id"] = "cs_other"
    with pytest.raises(BillingError):
        service.apply_session(value)
    assert service.me(user)["quota"]["limit"] == 3


def test_unsigned_tampered_and_stale_notifications_rejected(billing):
    service, user, _, _ = billing
    order = service.checkout(user)
    value = service.provider.pay(order["checkout_url"].rsplit("/", 1)[1])
    payload, signature = service.provider.signed_event("checkout.session.completed", value)
    for raw, sig in [(payload, ""), (payload+b" ", signature), (payload, signature.replace("t=", "t=1"))]:
        with pytest.raises(BillingError) as error:
            service.webhook(raw, sig)
        assert error.value.code == "SIGNATURE_INVALID"
    assert service.me(user)["quota"]["limit"] == 3


def test_success_redirect_and_unpaid_completion_do_not_grant(billing):
    service, user, _, api = billing
    assert api.get("/checkout-return?paid=true&cancelled=0").status_code == 200
    order = service.checkout(user)
    value = service.provider.set_session(order["checkout_url"].rsplit("/", 1)[1], status="complete")
    payload, signature = service.provider.signed_event("checkout.session.completed", value)
    service.webhook(payload, signature)
    assert service.me(user)["quota"]["limit"] == 3
    with pytest.raises(BillingError) as error:
        service.checkout(user)
    assert error.value.code == "ORDER_PENDING"


def test_full_refund_before_delayed_completed_never_reactivates(billing):
    service, user, _, _ = billing
    order, value, payload, signature = paid(service, user)
    intent = value["payment_intent"]
    intent["latest_charge"].update(refunded=True, amount_refunded=1990)
    service.provider.set_session(value["id"], payment_intent=intent)
    p, s = service.provider.signed_event("charge.refunded", {"id": "ch_test", "payment_intent": intent["id"]})
    service.webhook(p, s)
    delayed, sig = service.provider.signed_event("checkout.session.completed", value)
    service.webhook(delayed, sig)
    assert service.refresh(user)["quota"]["limit"] == 3


def test_partial_refund_preserves_member_and_dispute_uses_latest_status(billing):
    service, user, _, _ = billing
    _, value, _, _ = paid(service, user)
    intent = value["payment_intent"]
    intent["latest_charge"].update(amount_refunded=100, disputed=True)
    intent["mock_dispute_status"] = "needs_response"
    service.provider.set_session(value["id"], payment_intent=intent)
    assert service.refresh(user)["quota"]["limit"] == 3
    intent["mock_dispute_status"] = "won"
    service.provider.set_session(value["id"], payment_intent=intent)
    p, s = service.provider.signed_event("charge.dispute.created", {"id": "dp_old", "payment_intent": intent["id"], "status": "needs_response"})
    service.webhook(p, s)
    assert service.refresh(user)["quota"]["limit"] == 30
    intent["mock_dispute_status"] = "lost"
    service.provider.set_session(value["id"], payment_intent=intent)
    assert service.refresh(user)["quota"]["limit"] == 3


def test_concurrent_quota_reserves_three_and_failure_releases_once(billing):
    service, user, _, _ = billing
    def reserve(_):
        receipt = secrets.token_urlsafe(32)
        try:
            return service.reserve(user, secrets.token_urlsafe(18), receipt), receipt
        except BillingError as error:
            assert error.code == "QUOTA_EXCEEDED"
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = [r for r in pool.map(reserve, range(20)) if r]
    assert len(results) == 3
    value, receipt = results[0]
    service.settle(value["id"], receipt, False)
    service.settle(value["id"], receipt, False)
    assert service.me(user)["quota"]["remaining"] == 1
    with pytest.raises(BillingError):
        service.settle(value["id"], receipt, True)


def test_consumption_idempotency_midnight_and_member_expiry(billing):
    service, user, _, _ = billing
    start = 1791388740.0  # 2026-10-07 23:59 Beijing
    service.clock = lambda: start
    receipt, task = secrets.token_urlsafe(32), secrets.token_urlsafe(18)
    reserved = service.reserve(user, task, receipt)
    assert service.reserve(user, task, receipt)["id"] == reserved["id"]
    service.clock = lambda: start + 120
    service.settle(reserved["id"], receipt, True)
    service.settle(reserved["id"], receipt, True)
    assert service.me(user)["quota"]["used"] == 0
    paid(service, user)
    expires = service.me(user)["quota"]["member_expires"]
    assert expires == service.clock() + 30*86400
    service.clock = lambda: expires
    assert service.me(user)["quota"]["limit"] == 3


def test_expired_reservation_rejects_late_success_and_wrong_receipt(billing):
    service, user, _, _ = billing
    # Keep this expiry check within one Beijing day; rollover is tested separately.
    service.clock = lambda: 1791345600.0  # 2026-10-07 12:00 Beijing
    receipt = secrets.token_urlsafe(32)
    value = service.reserve(user, secrets.token_urlsafe(18), receipt)
    with pytest.raises(BillingError):
        service.settle(value["id"], "wrong", True)
    service.clock = lambda: value["expires"] + 1
    with pytest.raises(BillingError) as error:
        service.settle(value["id"], receipt, True)
    assert error.value.code == "RESERVATION_EXPIRED"
    assert service.me(user)["quota"]["reserved"] == 1
    service.settle(value["id"], receipt, False)
    assert service.me(user)["quota"]["reserved"] == 0


def test_public_api_requires_auth_and_rejects_client_price_fields(billing):
    service, user, access, api = billing
    assert api.get("/api/membership/v1/me").status_code == 401
    assert api.get("/api/membership/v1/me", headers={"Authorization": "Bearer other"}).status_code == 401
    assert api.get("/health").headers["x-robots-tag"] == "noindex, nofollow"
    assert api.get("/robots.txt").text.endswith("Disallow: /\n")
    response = api.post("/api/membership/v1/checkout", json={"amount": 1, "currency": "usd", "user_id": "other"}, headers={"Authorization": "Bearer " + access})
    assert response.status_code == 200
    with service.store.connection() as db:
        order = db.execute("SELECT * FROM orders WHERE id=?", (response.json()["id"],)).fetchone()
    assert order["user_id"] == user["id"]
    assert json.loads(order["params"])["line_items"] == [{"price": "price_mock_30days", "quantity": 1}]


def test_production_rejects_mock_plain_http_and_missing_mail(tmp_path):
    config = Config(database=tmp_path / "billing.sqlite3", provider="mock")
    for changed in [replace(config, environment="production"), replace(config, public_url="http://example.com"), replace(config, public_url="https://example.com")]:
        with pytest.raises(ValueError):
            changed.validate()


@pytest.fixture
def bridge(billing, tmp_path):
    service, user, _, api = billing
    bridge = MembershipClient(service.config.public_url, tmp_path / "local.sqlite3")
    calls = []
    def call(path, body=None, access=None, method=None):
        calls.append((path, body))
        response = api.request(method or ("POST" if body is not None else "GET"), "/api/membership/v1" + path, json=body,
                               headers={"Authorization": "Bearer " + access} if access else {})
        if not response.is_success:
            detail = response.json()["detail"]
            raise AnalysisError(detail["code"], detail["message"], response.status_code)
        return response.json()
    bridge.call = call
    session, _ = bridge.login(user["email"], PASSWORD)
    return bridge, session, calls


def test_real_engine_manual_cache_regenerate_and_failure_quota(engine, bridge, monkeypatch):
    local, session, calls = bridge
    engine.membership = local
    ready_record(engine.store)
    monkeypatch.setattr(summary_service, "generate_summary", lambda *a, **k: content())
    for i in range(3):
        result = engine.start_summary("record-1", force=i > 0, member_session=session)
        finish(engine, result["job_id"])
    assert engine.start_summary("record-1", member_session=None)["cached"]
    with pytest.raises(AnalysisError) as error:
        engine.start_summary("record-1", force=True, member_session=session)
    assert error.value.code == "QUOTA_EXCEEDED"
    assert local.me(session)["quota"]["used"] == 3
    serialized = json.dumps(calls)
    assert "youtube.com" not in serialized and "字幕" not in serialized


def test_real_engine_auto_uses_captured_account_and_failure_is_free(engine, bridge, monkeypatch):
    local, session, _ = bridge
    engine.membership = local
    monkeypatch.setattr(subtitle_service, "extract_transcript", lambda *a, **k: transcript_result())
    def fail(*a, **k):
        raise AnalysisError("MOCK_MODEL_FAILED", "模型模拟失败")
    monkeypatch.setattr(summary_service, "generate_summary", fail)
    result = engine.start_transcript("https://www.youtube.com/watch?v=abcdefghijk", "auto", True, session)
    for _ in range(500):
        if not engine.futures and engine.store.get(result["id"])["summary_status"] == "failed":
            break
        time.sleep(.01)
    assert engine.store.get(result["id"])["subtitle_status"] == "ready"
    assert local.me(session)["quota"]["used"] == 0
    assert local.me(session)["quota"]["reserved"] == 0
    monkeypatch.setattr(summary_service, "generate_summary", lambda *a, **k: content())
    finish(engine, engine.start_summary(result["id"], member_session=session)["job_id"])
    for _ in range(300):
        if not engine.futures:
            break
        time.sleep(.01)
    assert local.me(session)["quota"]["used"] == 1


def test_pinned_stripe_sdk_sends_stable_key_and_checkout_params(tmp_path):
    import stripe
    from urllib.parse import parse_qs
    calls = []
    class Capture(stripe.HTTPClient):
        name = "capture"
        def request(self, method, url, headers, post_data=None, **kwargs):
            calls.append((method, url, headers, post_data))
            return json.dumps({"id": "cs_test_contract", "url": "https://checkout.stripe.com/c/pay/test"}), 200, {}
    config = Config(secret_key="sk_test_contract", webhook_secret="whsec_contract", price_id="price_contract", database=tmp_path / "unused.sqlite3")
    provider = StripeProvider(config)
    provider.client = stripe.StripeClient(config.secret_key, http_client=Capture(), max_network_retries=0)
    params = {"mode": "payment", "line_items": [{"price": config.price_id, "quantity": 1}], "adaptive_pricing": {"enabled": False}, "metadata": {"order_id": "contract"}}
    result = provider.create(params, "stable-contract-key")
    provider.create(params, "stable-contract-key")
    assert result["id"] == "cs_test_contract"
    assert calls[0][3] == calls[1][3]
    headers = {key.lower(): value for key, value in calls[0][2].items()}
    assert headers["idempotency-key"] == "stable-contract-key"
    assert headers["stripe-version"] == "2026-09-30.endive"
    encoded = parse_qs(calls[0][3])
    assert encoded["line_items[0][quantity]"] == ["1"]
    assert encoded["adaptive_pricing[enabled]"] == ["false"]


def test_local_quota_outbox_survives_settlement_disconnect_and_restart(engine, bridge, monkeypatch):
    local, session, _ = bridge
    ready_record(engine.store)
    engine.membership = local
    original = local.call
    def disconnected(path, *args, **kwargs):
        if path.endswith("/settle"):
            raise AnalysisError("MEMBERSHIP_UNAVAILABLE", "模拟结算断网", 503)
        return original(path, *args, **kwargs)
    local.call = disconnected
    monkeypatch.setattr(summary_service, "generate_summary", lambda *a, **k: content())
    result = engine.start_summary("record-1", member_session=session)
    finish(engine, result["job_id"])
    for _ in range(300):
        if not engine.futures:
            break
        time.sleep(.01)
    restarted = MembershipClient(local.url, local.path)
    restarted.call = original
    restarted.recover(engine.store)
    restarted.flush()
    assert restarted.me(session)["quota"]["used"] == 1
    with restarted.db() as db:
        row = db.execute("SELECT settled,receipt FROM quota_jobs WHERE job_id=?", (result["job_id"],)).fetchone()
    assert tuple(row) == (1, "")


def test_local_proxy_preserves_local_access_and_hides_validation_password(monkeypatch):
    from app.main import app
    api = TestClient(app, base_url="http://127.0.0.1:8000")
    assert api.get("/api/v1/account/config").json() == {"enabled": False}
    assert api.post("/api/v1/account/login", json={"email": "test@example.com", "password": "x"*129}).status_code == 422
    assert "x"*129 not in api.post("/api/v1/account/login", json={"password": "x"*129}).text
    assert api.post("/api/v1/account/login", json={}, headers={"Origin": "https://example.com"}).status_code == 403
    assert TestClient(app, base_url="https://public.example.com").get("/api/v1/account/config").status_code == 403


def test_timely_completed_task_settles_after_network_outage_without_reopening_slot(billing):
    service, user, _, _ = billing
    start = service.clock()
    receipt = secrets.token_urlsafe(32)
    value = service.reserve(user, secrets.token_urlsafe(18), receipt)
    service.clock = lambda: start+7201
    with service.store.connection(write=True) as db:
        service.expire_reservations(db)
        assert db.execute("SELECT state FROM reservations WHERE id=?", (value["id"],)).fetchone()[0] == "expired"
    service.settle(value["id"], receipt, True, completed_at=start+10)
    service.settle(value["id"], receipt, True, completed_at=start+10)
    with service.store.connection() as db:
        assert db.execute("SELECT state FROM reservations WHERE id=?", (value["id"],)).fetchone()[0] == "consumed"


@pytest.mark.parametrize("state", ["requires_payment_method", "processing"])
def test_async_failure_cannot_start_another_charge_until_terminal_state_is_verified(billing, state):
    service, user, _, _ = billing
    order = service.checkout(user)
    session_id = order["checkout_url"].rsplit("/", 1)[1]
    intent = {"id": "pi_failed_test", "status": state, "latest_charge": None}
    value = service.provider.set_session(session_id, status="complete", payment_intent=intent)
    payload, signature = service.provider.signed_event("checkout.session.async_payment_failed", value)
    service.webhook(payload, signature)
    assert service.refresh(user)["order"]["status"] == "review"
    with pytest.raises(BillingError) as error:
        service.checkout(user)
    assert error.value.code == "ORDER_REVIEW"
    intent["status"] = "canceled"
    service.provider.set_session(session_id, payment_intent=intent)
    assert service.refresh(user)["order"]["status"] == "expired"
    assert service.checkout(user)["id"] != order["id"]
