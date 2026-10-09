"""Proxy/origin regressions exercise the actual AI and account routers, without IO."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import analysis_routes, membership_routes
from app.access_policy import DEFAULT_ORIGINS, install_access_policy, load_access_policy
from app.analysis_errors import AnalysisError
from app.main import analysis_error_handler
from app.membership_client import COOKIE


@pytest.fixture
def make_api(monkeypatch, tmp_path):
    calls = []

    class Membership:
        def login(self, email, password):
            calls.append(("login", email))
            return "local-session", 2000000000

        def call(self, path, body):
            calls.append((path, body["email"]))
            return {"message": "test registration"}

        def me(self, session):
            if session != "local-session":
                raise AnalysisError("LOGIN_REQUIRED", "请登录。", 401)
            return {"email": "account@example.test"}

        def logout(self, session):
            calls.append(("logout", session))

    def start_transcript(*args):
        calls.append(("analysis", args))
        return {"id": "test-analysis", "subtitle_status": "queued"}

    def start_summary(*args):
        calls.append(("summary", args))
        return {"job_id": "test-job"}

    monkeypatch.setattr(membership_routes, "get_membership_client", lambda: Membership())
    monkeypatch.setattr(analysis_routes, "get_engine", lambda: SimpleNamespace(start_transcript=start_transcript, start_summary=start_summary))

    def factory(settings=None, base_url="http://127.0.0.1:8000"):
        app = FastAPI(exception_handlers={AnalysisError: analysis_error_handler})
        install_access_policy(app, load_access_policy(settings or {}, tmp_path / "absent.env"))
        app.include_router(analysis_routes.router)
        app.include_router(membership_routes.router)
        return TestClient(app, base_url=base_url), calls

    return factory


def tunnel_settings():
    return {"ALLOWED_ORIGINS": "http://localhost:8080,http://127.0.0.1:8080"}


@pytest.mark.parametrize("origin", DEFAULT_ORIGINS)
def test_default_local_origins_support_account_and_ai(make_api, origin):
    api, calls = make_api()
    assert api.get("/api/v1/ai/config", headers={"Origin": origin}).status_code == 200
    assert api.post("/api/v1/account/login", json={}, headers={"Origin": origin}).status_code == 200
    assert calls == [("login", "")]


@pytest.mark.parametrize("host", ["localhost", "localhost:8080", "127.0.0.1:8000"])
def test_explicit_tunnel_origin_does_not_depend_on_upstream_host_port(make_api, host):
    api, calls = make_api(tunnel_settings())
    headers = {"Host": host, "Origin": "http://localhost:8080"}
    assert api.get("/api/v1/ai/config", headers=headers).status_code == 200
    assert api.post("/api/v1/account/register", json={"email": "account@example.test"}, headers=headers).status_code == 200
    assert api.post("/api/v1/account/login", json={}, headers=headers).status_code == 200
    assert api.get("/api/v1/account/me", headers=headers).json() == {"email": "account@example.test"}
    assert api.post("/api/v1/analyses", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"}, headers=headers).status_code == 202
    assert api.post("/api/v1/analyses/test-analysis/summary", json={"stream": True}, headers=headers).status_code == 202
    assert calls[-1] == ("summary", ("test-analysis", False, True, "local-session"))


def test_tunnel_is_opt_in_and_custom_ports_need_no_source_change(make_api):
    api, calls = make_api()
    assert api.get("/api/v1/ai/config", headers={"Origin": "http://localhost:8080"}).status_code == 403
    assert not calls
    api, _ = make_api({"ALLOWED_ORIGINS": "http://localhost:12345"})
    assert api.get("/api/v1/ai/config", headers={"Origin": "http://localhost:12345"}).status_code == 200
    assert api.get("/api/v1/ai/config", headers={"Origin": "http://localhost:5173"}).status_code == 403


BAD_ORIGINS = [
    "https://evil.example", "http://localhost:8081", "https://localhost:8080", "null", "", "*",
    "http://localhost:8080/", "http://localhost:8080/path", "http://localhost:8080?", "http://localhost:8080#",
    "http://user@localhost:8080", "http://user:password@localhost:8080",
    "http://localhost:8080@evil.example", "http://localhost:8080.evil.example",
    "http://localhost.evil.example:8080", "http://localhost.:8080",
    "http://localhost:8080 https://evil.example", "http://localhost:8080,https://evil.example",
    "http://localhost:8080\\@evil.example", "http://local%68ost:8080", "http://localhost:08080",
    "http://localhost:0", "http://localhost:65536", "http://localhost:invalid", "//localhost:8080",
    "http://[::1", "http://[::1%25eth0]:8080", "file://localhost:8080", " http://localhost:8080",
    "http://local\thost:8080", "http://localhost:8080\r\nX-Injected: yes",
]


@pytest.mark.parametrize("origin", BAD_ORIGINS)
@pytest.mark.parametrize("kind", ["account", "ai"])
def test_untrusted_and_malformed_origins_rejected_before_any_operation(make_api, origin, kind):
    api, calls = make_api(tunnel_settings())
    path = "/api/v1/account/login" if kind == "account" else "/api/v1/analyses"
    response = api.post(path, json={}, headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ORIGIN_FORBIDDEN"
    assert not calls


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "localhost@evil.example", "localhost/path", "localhost:65536", "localhost:bad", "localhost:", "localhost:08000", "localhost.", "", "localhost,evil.example"])
def test_forged_host_is_not_rescued_by_allowed_origin_or_forwarded_headers(make_api, host):
    api, calls = make_api(tunnel_settings())
    headers = {"Host": host, "Origin": "http://localhost:8080", "X-Forwarded-Host": "localhost",
               "X-Forwarded-Proto": "https", "X-Forwarded-Port": "8080", "X-Forwarded-For": "127.0.0.1",
               "Forwarded": 'for=127.0.0.1;host="localhost:8080";proto=https'}
    for method, path in [("GET", "/api/v1/ai/config"), ("POST", "/api/v1/account/login")]:
        response = api.request(method, path, headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "HOST_FORBIDDEN"
    assert not calls


@pytest.mark.parametrize("header", ["Host", "Origin"])
def test_duplicate_security_headers_are_rejected(make_api, header):
    api, calls = make_api(tunnel_settings())
    headers = [("Host", "localhost"), ("Origin", "http://localhost:8080")]
    headers.append((header, headers[0 if header == "Host" else 1][1]))
    assert api.post("/api/v1/account/login", json={}, headers=headers).status_code == 403
    assert not calls


def test_forwarded_host_and_proto_never_add_trusted_origins(make_api):
    api, calls = make_api(tunnel_settings())
    response = api.post("/api/v1/account/login", json={}, headers={
        "Origin": "https://evil.example", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https",
        "Forwarded": "host=evil.example;proto=https",
    })
    assert response.status_code == 403 and not calls


def test_no_origin_preserves_cli_and_same_origin_get_but_not_cross_site_browser(make_api):
    api, calls = make_api()
    assert api.get("/api/v1/ai/config").status_code == 200
    assert api.get("/api/v1/account/config", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert api.post("/api/v1/account/login", json={}).status_code == 200
    assert api.get("/api/v1/account/me").status_code == 200
    assert api.get("/api/v1/ai/config", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    response = api.post("/api/v1/account/login", json={}, headers={"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "ORIGIN_REQUIRED"
    assert api.get("/api/v1/ai/config", headers={"Host": "evil.example"}).status_code == 403
    assert len(calls) == 1


def test_public_https_requires_both_allowlists_and_uses_configured_secure_cookie(make_api):
    settings = {"ALLOWED_ORIGINS": "https://saveany.example", "ACCOUNT_COOKIE_SECURE": "true"}
    api, calls = make_api(settings, "https://saveany.example")
    assert api.get("/api/v1/ai/config", headers={"Origin": "https://saveany.example"}).status_code == 403
    settings["ALLOWED_HOSTS"] = "saveany.example"
    # HTTP upstream behind TLS-terminating Nginx; spoofed proto cannot downgrade the cookie.
    api, calls = make_api(settings, "http://saveany.example")
    headers = {"Origin": "https://saveany.example", "X-Forwarded-Proto": "http"}
    assert api.get("/api/v1/ai/config", headers=headers).status_code == 200
    response = api.post("/api/v1/account/login", json={}, headers=headers)
    cookie = response.headers["set-cookie"]
    assert response.status_code == 200
    assert all(flag in cookie for flag in ["HttpOnly", "SameSite=strict", "Secure", "Path=/"])
    assert "Domain=" not in cookie
    assert api.get("/api/v1/account/me", headers=headers).status_code == 401  # Secure never sent over upstream HTTP by this client.
    assert api.get("/api/v1/account/me", headers={**headers, "Cookie": f"{COOKIE}=local-session"}).status_code == 200  # Nginx forwards the browser's HTTPS cookie.
    assert api.get("/api/v1/ai/config", headers={"Origin": "http://saveany.example"}).status_code == 403
    assert api.get("/api/v1/ai/config", headers={"Host": "localhost", **headers}).status_code == 403
    # Browser sees HTTPS and retains the existing session/logout behaviour.
    api, _ = make_api(settings, "https://saveany.example")
    api.post("/api/v1/account/login", json={}, headers=headers)
    assert api.get("/api/v1/account/me", headers=headers).status_code == 200
    assert "Secure" in api.post("/api/v1/account/logout", headers=headers).headers["set-cookie"]
    assert api.get("/api/v1/account/me", headers=headers).status_code == 401


def test_http_login_cookie_is_not_changed_by_forged_https_proxy_header(make_api):
    api, _ = make_api()
    response = api.post("/api/v1/account/login", json={}, headers={"Origin": "http://localhost:5173", "X-Forwarded-Proto": "https"})
    assert "Secure" not in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_cors_preflight_and_actual_calls_share_explicit_policy(make_api):
    api, _ = make_api(tunnel_settings())
    headers = {"Host": "localhost", "Origin": "http://localhost:8080", "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "Content-Type"}
    response = api.options("/api/v1/account/login", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert api.options("/api/v1/account/login", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    assert api.options("/api/v1/account/login", headers={**headers, "Host": "evil.example"}).status_code == 403
    assert api.options("/api/v1/account/login", headers={**headers, "Origin": "http://localhost:8080/"}).status_code == 403
    response = api.post("/api/v1/account/register", json={}, headers={"Origin": "http://localhost:8080"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"


@pytest.mark.parametrize("settings", [
    {"ALLOWED_ORIGINS": "*"}, {"ALLOWED_ORIGINS": ""}, {"ALLOWED_ORIGINS": "http://localhost:8080,"},
    {"ALLOWED_ORIGINS": "https://example.test/path"}, {"ALLOWED_ORIGINS": "https://user@example.test"},
    {"ALLOWED_ORIGINS": "https://example.test?"}, {"ALLOWED_ORIGINS": "https://example.test#"},
    {"ALLOWED_ORIGINS": "null"}, {"ALLOWED_ORIGINS": "http://localhost:65536"},
    {"ALLOWED_HOSTS": "*"}, {"ALLOWED_HOSTS": "*.example.test"}, {"ALLOWED_HOSTS": "https://example.test"},
    {"ALLOWED_HOSTS": "localhost:8000"}, {"ALLOWED_HOSTS": ""}, {"ALLOWED_HOSTS": "localhost/path"},
    {"ACCOUNT_COOKIE_SECURE": "yes"},
])
def test_invalid_config_fails_closed_without_echoing_values(tmp_path, settings):
    with pytest.raises(ValueError) as failure:
        load_access_policy(settings, tmp_path / "absent.env")
    assert any(name in str(failure.value) for name in settings)
    assert "user@" not in str(failure.value)


def test_root_file_process_override_and_only_explicit_config_is_used(tmp_path):
    settings = tmp_path / ".env"
    settings.write_text("ALLOWED_ORIGINS=https://saveany.example\nALLOWED_HOSTS=saveany.example\nACCOUNT_COOKIE_SECURE=true\nSTRIPE_SECRET_KEY=not-an-access-setting\n", encoding="utf-8")
    policy = load_access_policy({}, settings)
    assert policy.origins == ("https://saveany.example",) and policy.secure_cookies
    assert "STRIPE" not in repr(policy)
    policy = load_access_policy({"ALLOWED_ORIGINS": "http://localhost:8080", "ALLOWED_HOSTS": "localhost", "ACCOUNT_COOKIE_SECURE": "false"}, settings)
    assert policy.origins == ("http://localhost:8080",) and policy.hosts == ("localhost",) and not policy.secure_cookies
