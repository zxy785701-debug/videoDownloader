import html
import hashlib
import hmac
import logging
import re
import secrets
from typing import Literal
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .config import load_config
from .mail import delivery_mode
from .provider import MockProvider, StripeProvider
from .service import BillingError, MembershipService
from .security import mock_checkout_path
from .store import Store


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Body):
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)


class EmailRequest(Body):
    email: str = Field(max_length=254)


class CodeRequest(Body):
    code: str = Field(min_length=32, max_length=100)


class ResetRequest(CodeRequest):
    password: str = Field(min_length=12, max_length=128)


class ReserveRequest(Body):
    task_id: str = Field(min_length=16, max_length=100)
    receipt: str = Field(min_length=32, max_length=100)


class SettleRequest(Body):
    success: bool
    completed_at: float | None = Field(default=None, allow_inf_nan=False)


class RecoverRequest(Body):
    task_id: str = Field(min_length=16, max_length=100)


def create_app(config=None, provider=None, clock=None):
    config = config or load_config()
    config.validate()
    store = Store(config.database)
    provider = provider or (MockProvider(config, store) if config.provider == "mock" else StripeProvider(config))
    service = MembershipService(config, store, provider, **({"clock": clock} if clock else {}))
    if isinstance(provider, MockProvider):
        provider.clock = lambda: service.clock()
    app = FastAPI(title="SaveAny Membership", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service

    @app.exception_handler(BillingError)
    async def billing_error(request, error):
        return JSONResponse({"detail": {"code": error.code, "message": error.message}}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return JSONResponse({"detail": {"code": "INPUT_INVALID", "message": "输入不符合要求，请检查邮箱、密码长度或操作标识。"}}, status_code=422)

    @app.exception_handler(Exception)
    async def service_error(request, error):
        # Exceptions can contain request credentials; log only the exception class.
        logging.warning("Membership request unavailable type=%s", type(error).__name__)
        return JSONResponse({"detail": {"code": "SERVICE_UNAVAILABLE", "message": "会员服务暂不可用，请稍后重试；若已付款请勿重复购买。"}}, status_code=503)

    @app.middleware("http")
    async def private_headers(request, call_next):
        if config.provider == "mock" and (request.url.hostname not in {"localhost", "127.0.0.1", "testserver"} or request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}):
            return JSONResponse({"detail": "Mock service is local-only"}, status_code=403)
        try:
            length = int(request.headers.get("content-length", "0") or "0")
        except ValueError:
            return JSONResponse({"detail": "Invalid request length"}, status_code=400)
        if length < 0 or length > 65536:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # no-referrer makes browser form POST Origin opaque ('null'). The loopback mock
        # has an actual form with strict same-origin validation; keep that origin intact.
        response.headers["Referrer-Policy"] = "same-origin" if config.provider == "mock" else "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        if config.live:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def bearer(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise BillingError("LOGIN_REQUIRED", "请先登录账号。", 401)
        return authorization[7:]

    def user(access=Depends(bearer)):
        return service.authenticate(access)

    def public_rate(request: Request):
        service.throttle("ip", request.client.host if request.client else "unknown", 60, 60)

    prefix = "/api/membership/v1"

    @app.get(prefix + "/config", dependencies=[Depends(public_rate)])
    def public_config():
        # Only public behavior flags; never expose SMTP credentials, paths or payment keys.
        return {"verification_required": config.require_email_verification,
                "mail_delivery": delivery_mode(config), "simulated": config.provider == "mock"}

    @app.get("/health")
    def health():
        return {"status": "ok", "simulated": config.provider == "mock"}

    @app.get("/robots.txt")
    def robots():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.post(prefix + "/register", dependencies=[Depends(public_rate)])
    def register(body: Credentials):
        return service.register(body.email, body.password)

    @app.post(prefix + "/login", dependencies=[Depends(public_rate)])
    def login(body: Credentials):
        return service.login(body.email, body.password)

    @app.post(prefix + "/email-code/{kind}", dependencies=[Depends(public_rate)])
    def email_code(kind: Literal["verify", "reset"], body: EmailRequest):
        return service.send_code(body.email, kind)

    @app.post(prefix + "/verify-email", dependencies=[Depends(public_rate)])
    def verify_email(body: CodeRequest):
        return service.verify_email(body.code)

    @app.post(prefix + "/reset-password", dependencies=[Depends(public_rate)])
    def reset_password(body: ResetRequest):
        return service.reset_password(body.code, body.password)

    @app.post(prefix + "/logout")
    def logout(access=Depends(bearer)):
        service.logout(access)
        return {"message": "已退出登录。"}

    @app.get(prefix + "/me")
    def me(account=Depends(user)):
        return service.me(account)

    @app.post(prefix + "/refresh", dependencies=[Depends(public_rate)])
    def refresh(account=Depends(user)):
        return service.refresh(account)

    @app.post(prefix + "/checkout", dependencies=[Depends(public_rate)])
    def checkout(account=Depends(user)):
        return service.checkout(account)

    @app.post(prefix + "/quota/reserve", dependencies=[Depends(public_rate)])
    def reserve(body: ReserveRequest, account=Depends(user)):
        return service.reserve(account, body.task_id, body.receipt)

    @app.post(prefix + "/quota/{reservation_id}/settle", dependencies=[Depends(public_rate)])
    def settle(reservation_id: str, body: SettleRequest, receipt=Depends(bearer)):
        return service.settle(reservation_id, receipt, body.success, body.completed_at)

    @app.post(prefix + "/quota/recover", dependencies=[Depends(public_rate)])
    def recover(body: RecoverRequest, receipt=Depends(bearer)):
        return service.recover_reservation(body.task_id, receipt)

    @app.post(prefix + "/webhook")
    async def webhook(request: Request):
        payload = await request.body()
        if len(payload) > 65536:
            raise BillingError("PAYLOAD_TOO_LARGE", "通知过大。", 413)
        return await run_in_threadpool(service.webhook, payload, request.headers.get("stripe-signature", ""))

    @app.get("/checkout-return", response_class=HTMLResponse)
    def checkout_return():
        return "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='robots' content='noindex,nofollow'><title>返回 SaveAny</title><body><h1>请返回本机 SaveAny</h1><p>在会员窗口点击“刷新会员状态”核实结果。返回此页不代表付款成功，会员以服务端确认结果为准。</p><p>若取消或付款失败，可继续打开原支付页；已付款时请勿再次购买。</p></body></html>"

    if config.provider == "mock":
        form_secret = secrets.token_bytes(32)

        def owned_mock_session(session_id, account):
            try:
                mock_checkout_path(session_id)
            except ValueError:
                raise BillingError("ORDER_NOT_FOUND", "模拟订单不存在。", 404) from None
            with store.connection() as db:
                order = db.execute("SELECT id FROM orders WHERE session_id=? AND user_id=?", (session_id, account["id"])).fetchone()
            if not order:
                raise BillingError("ORDER_NOT_FOUND", "模拟订单不存在。", 404)
            return provider.session(session_id)

        def form_token(session_id):
            return hmac.new(form_secret, session_id.encode(), hashlib.sha256).hexdigest()

        def mock_page(heading, message, extra=""):
            return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>模拟支付 · 无真实扣款</title>"
                    f"<body><h1>{heading}</h1><p>{message}</p>{extra}<p><a href='/'>返回 SaveAny</a>"
                    "，在会员窗口点击“刷新会员状态”核实订单。不会产生真实扣款。</p></body></html>")

        @app.get("/dev/checkout/{session_id}", response_class=HTMLResponse)
        def mock_checkout(session_id: str, account=Depends(user)):
            value = owned_mock_session(session_id, account)
            safe_id = html.escape(session_id, quote=True)
            if value["status"] != "open":
                return mock_page("模拟订单已处理或已过期", "付款与会员权益以服务端核实结果为准。")
            return mock_page("仅限本机模拟，不会扣款", "SaveAny 30 天会员 · ¥19.90 · 不自动续费",
                f"<form method='post' action='/dev/checkout/{safe_id}'><input type='hidden' name='csrf' value='{form_token(session_id)}'>"
                "<button name='outcome' value='paid'>模拟付款成功</button><button name='outcome' value='declined'>模拟银行卡拒付</button>"
                "<button name='outcome' value='cancelled'>取消并返回</button></form>")

        @app.post("/dev/checkout/{session_id}", response_class=HTMLResponse)
        async def mock_pay(session_id: str, request: Request, account=Depends(user)):
            if request.headers.getlist("origin") != [config.public_url] or request.headers.get("sec-fetch-site") == "cross-site":
                raise BillingError("ORIGIN_FORBIDDEN", "不允许该网页触发模拟付款。", 403)
            await run_in_threadpool(owned_mock_session, session_id, account)
            if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
                raise BillingError("OUTCOME_INVALID", "模拟结果不合法。")
            try:
                fields = parse_qs((await request.body()).decode("utf-8"), strict_parsing=True, max_num_fields=3)
            except (ValueError, UnicodeError):
                raise BillingError("OUTCOME_INVALID", "模拟结果不合法。") from None
            if set(fields) != {"csrf", "outcome"} or any(len(value) != 1 for value in fields.values()):
                raise BillingError("OUTCOME_INVALID", "模拟结果不合法。")
            if not re.fullmatch(r"[0-9a-f]{64}", fields["csrf"][0]) or not hmac.compare_digest(fields["csrf"][0], form_token(session_id)):
                raise BillingError("CSRF_FORBIDDEN", "模拟支付页已失效，请重新打开原订单。", 403)
            outcome = fields["outcome"][0]
            if outcome in {"declined", "cancelled"}:
                return mock_page("模拟拒付" if outcome == "declined" else "已取消本次模拟付款",
                    "此操作不会开通会员或撤销已有权益。原订单保留，可从会员窗口继续。")
            if outcome != "paid":
                raise BillingError("OUTCOME_INVALID", "模拟结果不合法。")
            value = await run_in_threadpool(provider.pay, session_id)
            payload, signature = provider.signed_event("checkout.session.completed", value)
            await run_in_threadpool(service.webhook, payload, signature)
            return mock_page("模拟付款已处理", "没有真实扣款，会员以服务端核实结果为准。")

    return app


def app_factory():
    return create_app()
