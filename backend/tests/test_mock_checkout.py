"""Same-origin mock checkout through the real authenticated account bridge.

Only temporary SQLite and an in-memory HTTP transport; no real payment/service.
"""
import json
import re
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import membership_routes
from app.access_policy import install_access_policy, load_access_policy
from app.analysis_errors import AnalysisError
from app.main import analysis_error_handler
from app.membership_client import COOKIE, MembershipClient
from billing.config import Config
from billing.main import create_app
from billing.security import mock_checkout_path


ORIGIN = "http://localhost:8080"
PASSWORD = "mock-tunnel-password-long"


@pytest.fixture
def tunnel(tmp_path, monkeypatch):
    config = Config(provider="mock", public_url=ORIGIN, database=tmp_path / "billing.sqlite3",
                    mail_directory=tmp_path / "mail")
    billing_app = create_app(config)
    service = billing_app.state.service
    service.register("buyer@example.com", PASSWORD)
    billing_api = TestClient(billing_app, base_url="http://127.0.0.1:8010")
    bridge = MembershipClient("http://127.0.0.1:8010", tmp_path / "account.sqlite3")
    requests = []

    def forward(request):
        requests.append(request)
        response = billing_api.request(request.method, request.url.path, content=request.content,
                                       headers=dict(request.headers))
        return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))

    bridge.http_client = httpx.Client(transport=httpx.MockTransport(forward), follow_redirects=False)
    monkeypatch.setattr(membership_routes, "get_membership_client", lambda: bridge)
    app = FastAPI(exception_handlers={AnalysisError: analysis_error_handler})
    install_access_policy(app, load_access_policy({"ALLOWED_ORIGINS": ORIGIN, "ALLOWED_HOSTS": "localhost"}, tmp_path / "absent.env"))
    app.include_router(membership_routes.router)
    app.include_router(membership_routes.mock_checkout_router)
    api = TestClient(app, base_url=ORIGIN)
    # Nginx's $host strips :8080; the actual browser Origin keeps it.
    api.headers.update({"Host": "localhost", "Origin": ORIGIN})
    assert api.post("/api/v1/account/login", json={"email": "buyer@example.com", "password": PASSWORD}).status_code == 200
    user = service.authenticate(bridge.session(api.cookies[COOKIE])["access"])
    yield SimpleNamespace(api=api, app=app, bridge=bridge, billing=billing_api, config=config,
                          service=service, user=user, requests=requests)
    bridge.close()
    billing_api.close()
    api.close()


def checkout(tunnel):
    response = tunnel.api.post("/api/v1/account/checkout", json={})
    assert response.status_code == 200, response.text
    return response.json()


def csrf(tunnel, path):
    response = tunnel.api.get(path)
    assert response.status_code == 200, response.text
    assert "http://127.0.0.1:8010" not in response.text
    return re.search(r"name='csrf' value='([a-f0-9]{64})'", response.text)[1]


def state(tunnel, refresh=True):
    response = (tunnel.api.post("/api/v1/account/refresh", json={}) if refresh
                else tunnel.api.get("/api/v1/account/me"))
    assert response.status_code == 200
    return response.json()


def test_full_same_origin_checkout_cancel_decline_pay_refresh_and_order(tunnel):
    order = checkout(tunnel)
    path = order["checkout_url"]
    assert re.fullmatch(r"/dev/checkout/cs_test_mock_[A-Za-z0-9_-]{32}", path)
    initial_token = csrf(tunnel, path)
    for outcome, heading in [("cancelled", "已取消本次模拟付款"), ("declined", "模拟拒付")]:
        response = tunnel.api.post(path, data={"csrf": initial_token, "outcome": outcome})
        assert response.status_code == 200 and heading in response.text
        assert "href='/'" in response.text and "8010" not in response.text
        current = state(tunnel)
        assert current["order"]["id"] == order["id"] and current["order"]["status"] == "open"
        assert current["quota"]["limit"] == 3 and not current["quota"]["member_expires"]
        assert checkout(tunnel) == order
    token = csrf(tunnel, path)
    response = tunnel.api.post(path, data={"csrf": token, "outcome": "paid"})
    assert response.status_code == 200 and "模拟付款已处理" in response.text
    assert "href='/'" in response.text
    current = state(tunnel)
    assert current["order"]["id"] == order["id"] and current["order"]["status"] == "paid"
    assert current["quota"]["limit"] == 30 and current["quota"]["member_expires"]
    assert state(tunnel, refresh=False)["quota"] == current["quota"]
    for _ in range(2):
        assert tunnel.api.post(path, data={"csrf": token, "outcome": "paid"}).status_code == 200
    assert state(tunnel)["quota"]["member_expires"] == current["quota"]["member_expires"]
    assert tunnel.api.post("/api/v1/account/checkout", json={}).json()["detail"]["code"] == "ALREADY_MEMBER"
    assert "已处理或已过期" in tunnel.api.get(path).text
    with tunnel.service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 1
    page_requests = [r for r in tunnel.requests if r.url.path.startswith("/dev/checkout/")]
    assert page_requests and all(r.headers.get("Authorization", "").startswith("Bearer ") for r in page_requests)
    assert all("cookie" not in r.headers and "x-forwarded-host" not in r.headers for r in page_requests)


def test_legacy_saved_absolute_urls_and_unknown_create_reuse_session_without_migration(tunnel):
    service = tunnel.service
    old_order = checkout(tunnel)
    path = old_order["checkout_url"]
    session_id = path.rsplit("/", 1)[1]
    old_url = "http://127.0.0.1:8010" + path
    with service.store.connection(write=True) as db:
        row = db.execute("SELECT data FROM mock_sessions WHERE id=?", (session_id,)).fetchone()
        saved = json.loads(row["data"])
        saved["url"] = old_url
        db.execute("UPDATE mock_sessions SET data=? WHERE id=?", (json.dumps(saved), session_id))
        db.execute("UPDATE orders SET checkout_url=? WHERE id=?", (old_url, old_order["id"]))
        params = db.execute("SELECT params FROM orders WHERE id=?", (old_order["id"],)).fetchone()[0]
    assert checkout(tunnel) == old_order
    assert service.provider.session(session_id)["url"] == path
    assert service.provider.create(json.loads(params), "saveany-order-" + old_order["id"])["url"] == path
    with service.store.connection() as db:
        assert db.execute("SELECT checkout_url FROM orders WHERE id=?", (old_order["id"],)).fetchone()[0] == old_url
        assert json.loads(db.execute("SELECT data FROM mock_sessions WHERE id=?", (session_id,)).fetchone()[0])["url"] == old_url
        assert db.execute("SELECT COUNT(*) FROM mock_sessions").fetchone()[0] == 1
    # Reproduce a lost create response using that already saved idempotency key.
    with service.store.connection(write=True) as db:
        db.execute("UPDATE orders SET session_id=NULL,checkout_url=NULL,status='unknown' WHERE id=?", (old_order["id"],))
    assert checkout(tunnel) == old_order
    assert csrf(tunnel, path)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8010/dev/checkout/cs_test_mock_" + "a"*32,
    "//evil.example/dev/checkout/cs_test_mock_" + "a"*32,
    "/dev/checkout/cs_test_mock_" + "a"*32 + "?paid=1",
    "/dev/checkout/cs_test_mock_" + "a"*32 + "#paid",
    "/dev/checkout/../api/membership/v1/webhook", "/dev/checkout/", "javascript:alert(1)",
])
def test_mock_url_validation_only_accepts_exact_relative_session_path(tunnel, url):
    assert not tunnel.service.safe_checkout_url(url)
    assert tunnel.service.safe_checkout_url(mock_checkout_path("cs_test_mock_" + "a"*32))


@pytest.mark.parametrize("headers,code", [
    ({"Origin": "https://evil.example"}, "ORIGIN_FORBIDDEN"),
    ({"Origin": "null"}, "ORIGIN_FORBIDDEN"),
    ({"Host": "evil.example", "X-Forwarded-Host": "localhost"}, "HOST_FORBIDDEN"),
    ({"Origin": "http://localhost:8010", "X-Forwarded-Origin": ORIGIN}, "ORIGIN_FORBIDDEN"),
])
def test_untrusted_browser_headers_do_not_reach_payment(tunnel, headers, code):
    path = checkout(tunnel)["checkout_url"]
    before = len(tunnel.requests)
    response = tunnel.api.post(path, data={"csrf": "a"*64, "outcome": "paid"}, headers=headers)
    assert response.status_code == 403 and response.json()["detail"]["code"] == code
    assert len(tunnel.requests) == before
    assert not state(tunnel)["quota"]["member_expires"]


@pytest.mark.parametrize("token", [None, "a"*64, "中文", ""])
def test_missing_or_forged_csrf_never_grants(tunnel, token):
    path = checkout(tunnel)["checkout_url"]
    data = {"outcome": "paid"}
    if token is not None:
        data["csrf"] = token
    response = tunnel.api.post(path, data=data)
    assert response.status_code in {400, 403}
    assert not state(tunnel)["quota"]["member_expires"]


def test_get_query_flags_duplicate_fields_and_forged_metadata_cannot_pay(tunnel):
    path = checkout(tunnel)["checkout_url"]
    token = csrf(tunnel, path)
    assert tunnel.api.get(path + "?outcome=paid&paid=true&member=true").status_code == 200
    for body in [f"csrf={token}&outcome=paid&outcome=paid", f"csrf={token}&outcome=paid&amount=1",
                 f"csrf={token}&outcome=paid&user_id=another", f"csrf={token}&outcome=success"]:
        assert tunnel.api.post(path, content=body, headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 400
    assert not state(tunnel)["quota"]["member_expires"]


def test_missing_origin_browser_write_and_private_call_are_rejected(tunnel):
    path = checkout(tunnel)["checkout_url"]
    token = csrf(tunnel, path)
    del tunnel.api.headers["Origin"]
    response = tunnel.api.post(path, data={"csrf": token, "outcome": "paid"}, headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "ORIGIN_REQUIRED"
    access = tunnel.bridge.session(tunnel.api.cookies[COOKIE])["access"]
    assert tunnel.billing.post(path, data={"csrf": token, "outcome": "paid"}, headers={"Authorization": "Bearer " + access}).status_code == 403
    assert tunnel.billing.get(path).status_code == 401


def test_guest_expired_login_and_other_account_cannot_read_or_pay_order(tunnel):
    path = checkout(tunnel)["checkout_url"]
    token = csrf(tunnel, path)
    tunnel.service.register("other@example.com", PASSWORD)
    assert tunnel.api.post("/api/v1/account/login", json={"email": "other@example.com", "password": PASSWORD}).status_code == 200
    assert tunnel.api.get(path).status_code == 404
    assert tunnel.api.post(path, data={"csrf": token, "outcome": "paid"}).status_code == 404
    assert tunnel.api.post("/api/v1/account/logout", json={}).status_code == 200
    assert tunnel.api.get(path).status_code == 401
    assert tunnel.api.post(path, data={"csrf": token, "outcome": "paid"}).status_code == 401
    assert not tunnel.service.me(tunnel.user)["quota"]["member_expires"]


def test_expired_mock_order_does_not_grant(tunnel):
    order = checkout(tunnel)
    token = csrf(tunnel, order["checkout_url"])
    now = tunnel.service.clock()
    tunnel.service.clock = lambda: now + 3601
    assert tunnel.api.post(order["checkout_url"], data={"csrf": token, "outcome": "paid"}).status_code == 200
    current = state(tunnel)
    assert current["order"]["status"] == "expired" and not current["quota"]["member_expires"]


def test_html_security_headers_size_limit_and_no_internal_proxy(tunnel):
    path = checkout(tunnel)["checkout_url"]
    response = tunnel.api.get(path)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert "form-action 'self'" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert tunnel.api.post(path, content=b"a"*2049).status_code == 413
    before = len(tunnel.requests)
    for suffix in ["webhook", "health", "api/membership/v1/me", "cs_test_mock_bad"]:
        assert tunnel.api.get("/dev/checkout/" + suffix).status_code in {404, 405}
    assert len(tunnel.requests) == before


def test_mock_transport_does_not_follow_redirect_or_forward_cookie(tunnel):
    path = checkout(tunnel)["checkout_url"]
    tunnel.bridge.http_client.close()
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1:8010/health", "Set-Cookie": "private=secret"})

    tunnel.bridge.http_client = httpx.Client(transport=httpx.MockTransport(redirect))
    response = tunnel.api.get(path)
    assert response.status_code == 503 and "8010" not in response.text
    assert len(calls) == 1 and "Cookie" not in calls[0].headers
    assert "Set-Cookie" not in response.headers


def test_stripe_still_uses_absolute_hosted_url_and_original_return_params(tmp_path):
    class Provider:
        def price(self):
            return {"id": "price_contract", "active": True, "type": "one_time", "unit_amount": 1990, "currency": "cny", "livemode": False}

        def create(self, params, key):
            self.params = params
            return {"id": "cs_test_contract", "url": "https://checkout.stripe.com/c/pay/contract"}

    config = Config(provider="stripe", database=tmp_path / "stripe.sqlite3", public_url="http://127.0.0.1:8010",
                    secret_key="sk_test_contract", webhook_secret="whsec_contract", price_id="price_contract")
    provider = Provider()
    app = create_app(config, provider=provider)
    service = app.state.service
    service.register("stripe@example.com", PASSWORD)
    user = service.authenticate(service.login("stripe@example.com", PASSWORD)["token"])
    assert service.checkout(user)["checkout_url"] == "https://checkout.stripe.com/c/pay/contract"
    assert provider.params["success_url"] == config.public_url + "/checkout-return"
    assert provider.params["cancel_url"] == config.public_url + "/checkout-return?cancelled=1"
    assert not service.safe_checkout_url("/dev/checkout/cs_test_mock_" + "a"*32)
    assert TestClient(app).get("/dev/checkout/cs_test_mock_" + "a"*32).status_code == 404
