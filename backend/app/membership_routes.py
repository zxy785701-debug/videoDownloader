from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .analysis_errors import AnalysisError
from .analysis_routes import local_access
from .membership_client import COOKIE, get_membership_client


router = APIRouter(prefix="/api/v1/account", dependencies=[Depends(local_access)], tags=["本机账号代理"])


class AccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(default="", max_length=254)
    password: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=100)


def client():
    value = get_membership_client()
    if not value:
        raise AnalysisError("MEMBERSHIP_DISABLED", "当前为个人本机模式，会员服务尚未配置。", 503)
    return value


def actor(request: Request):
    return request.cookies.get(COOKIE)


@router.get("/config")
def config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    # The navigation entry depends on local setup, never on a remote service round trip.
    return {"enabled": get_membership_client() is not None}


@router.get("/settings")
def settings(response: Response):
    response.headers["Cache-Control"] = "no-store"
    bridge = get_membership_client()
    if not bridge:
        return {"enabled": False}
    try:
        return {"enabled": True, **bridge.call("/config")}
    except AnalysisError:
        # Keep the account entry available to explain an outage; core downloads still work.
        return {"enabled": True, "configuration_available": False}


@router.get("/me")
def me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return client().me(actor(request))


@router.post("/refresh")
def refresh(request: Request):
    return client().me(actor(request), refresh=True)


@router.post("/checkout")
def checkout(request: Request):
    bridge = client()
    return bridge.call("/checkout", {}, bridge.session(actor(request))["access"])


@router.post("/login")
def login(body: AccountBody, request: Request, response: Response):
    bridge = client()
    old = actor(request)
    session_id, expires = bridge.login(body.email, body.password)
    if old:
        # Remove old local session without affecting work already reserved by that account.
        with bridge.db() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (old,))
    response.set_cookie(COOKIE, session_id, max_age=7*86400, httponly=True, samesite="strict", secure=False, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"message": "已登录。"}


@router.post("/logout")
def logout(request: Request, response: Response):
    response.delete_cookie(COOKIE, path="/")
    client().logout(actor(request))
    return {"message": "已退出登录。"}


@router.post("/{operation}")
def account_operation(operation: Literal["register", "verify-email", "reset-password", "resend-verification", "forgot-password"], body: AccountBody):
    bridge = client()
    if operation == "register":
        return bridge.call("/register", {"email": body.email, "password": body.password})
    if operation == "verify-email":
        return bridge.call("/verify-email", {"code": body.code})
    if operation == "reset-password":
        return bridge.call("/reset-password", {"code": body.code, "password": body.password})
    return bridge.call("/email-code/" + ("verify" if operation == "resend-verification" else "reset"), {"email": body.email})
