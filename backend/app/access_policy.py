"""Explicit browser-origin and Host policy, independent of proxy-supplied URLs."""
import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping

from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .analysis_errors import AnalysisError


DEFAULT_ORIGINS = (
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:8000", "http://127.0.0.1:8000",
)
DEFAULT_HOSTS = ("localhost", "127.0.0.1")
CONFIG_PATH = Path(__file__).resolve().parents[2] / ".env"
_AUTHORITY = re.compile(r"(\[[0-9a-fA-F:.]+\]|[a-zA-Z0-9.-]+)(?::([1-9][0-9]{0,4}))?")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def parse_authority(value: str) -> tuple[str, int | None]:
    """No userinfo, whitespace, URL paths, escaping, wildcards or ambiguous ports."""
    match = _AUTHORITY.fullmatch(value)
    if not match:
        raise ValueError("Invalid authority")
    raw_host, raw_port = match.groups()
    port = int(raw_port) if raw_port else None
    if port is not None and port > 65535:
        raise ValueError("Invalid port")
    host = raw_host.lower()
    if host.startswith("["):
        host = str(ipaddress.IPv6Address(host[1:-1]))
    else:
        if len(host) > 253 or not all(_LABEL.fullmatch(label) for label in host.split(".")):
            raise ValueError("Invalid hostname")
        if re.fullmatch(r"[0-9.]+", host):
            host = str(ipaddress.IPv4Address(host))
    return host, port


def parse_origin(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"(http|https)://([^/?#\\]+)", value)
    if not match:
        raise ValueError("Origin must contain only an HTTP(S) scheme and authority")
    scheme, authority = match.groups()
    host, port = parse_authority(authority)
    serialized_host = f"[{host}]" if ":" in host else host
    suffix = f":{port}" if port is not None and port != (443 if scheme == "https" else 80) else ""
    return f"{scheme}://{serialized_host}{suffix}", host


@dataclass(frozen=True)
class AccessPolicy:
    origins: tuple[str, ...] = DEFAULT_ORIGINS
    hosts: tuple[str, ...] = DEFAULT_HOSTS
    secure_cookies: bool = False

    def check(self, request: Request):
        # Read the actual Host header, not a URL reconstructed from forwarded headers.
        hosts = request.headers.getlist("host")
        try:
            if len(hosts) != 1 or parse_authority(hosts[0])[0] not in self.hosts:
                raise ValueError("Untrusted Host")
        except ValueError:
            raise AnalysisError("HOST_FORBIDDEN", "请求 Host 不在后端配置的可信主机中。", 403) from None

        origins = request.headers.getlist("origin")
        if origins:
            try:
                if len(origins) != 1:
                    raise ValueError("Multiple Origin headers")
                canonical, _ = parse_origin(origins[0])
                # Browser origins use canonical serialization. Reject alternative spellings.
                if origins[0] != canonical or canonical not in self.origins:
                    raise ValueError("Untrusted Origin")
            except ValueError:
                raise AnalysisError("ORIGIN_FORBIDDEN", "不允许该网页访问学习记录或触发账号、模型操作。", 403) from None
        elif (request.headers.get("sec-fetch-site") == "cross-site" or
              (request.method not in {"GET", "HEAD", "OPTIONS"} and
               any(name.startswith("sec-fetch-") for name in request.headers))):
            # Preserve curl/service clients and same-origin GET/SSE without Origin, while
            # rejecting browser cross-site reads and browser writes missing their Origin.
            raise AnalysisError("ORIGIN_REQUIRED", "该浏览器请求缺少可信 Origin。", 403)


def load_access_policy(environ: Mapping[str, str] | None = None, path: Path = CONFIG_PATH) -> AccessPolicy:
    environment = os.environ if environ is None else environ
    local = dotenv_values(path, interpolate=False) if path.is_file() else {}

    def value(name: str, default: str) -> str:
        return environment.get(name, local.get(name, default))

    def items(name: str, defaults: tuple[str, ...]) -> list[str]:
        raw = value(name, ",".join(defaults))
        if not isinstance(raw, str):
            raise ValueError(f"{name} must be a non-empty comma-separated allowlist")
        result = [part.strip() for part in raw.split(",")]
        if not result or any(not part for part in result):
            raise ValueError(f"{name} must be a non-empty comma-separated allowlist")
        return result

    try:
        origins = tuple(dict.fromkeys(parse_origin(origin)[0] for origin in items("ALLOWED_ORIGINS", DEFAULT_ORIGINS)))
    except ValueError:
        raise ValueError("ALLOWED_ORIGINS contains an invalid HTTP(S) origin (no paths, wildcards or credentials)") from None
    try:
        hosts = []
        for entry in items("ALLOWED_HOSTS", DEFAULT_HOSTS):
            host, port = parse_authority(entry)
            if port is not None:
                raise ValueError("Host allowlist must not contain ports")
            hosts.append(host)
    except ValueError:
        raise ValueError("ALLOWED_HOSTS must contain exact hostnames/IPs, without ports or wildcards") from None
    secure = value("ACCOUNT_COOKIE_SECURE", "false")
    if not isinstance(secure, str) or secure.lower() not in {"true", "false"}:
        raise ValueError("ACCOUNT_COOKIE_SECURE must be true or false")
    return AccessPolicy(origins, tuple(dict.fromkeys(hosts)), secure.lower() == "true")


class AccessCORSMiddleware(CORSMiddleware):
    """Preflight ends before router dependencies, so validate it explicitly too."""
    def __init__(self, app, *, policy: AccessPolicy, **kwargs):
        super().__init__(app, **kwargs)
        self.policy = policy

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "OPTIONS" and scope["path"].startswith("/api/"):
            try:
                self.policy.check(Request(scope))
            except AnalysisError as error:
                response = JSONResponse({"detail": {"code": error.code, "message": error.message}}, status_code=error.status_code)
                await response(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


def install_access_policy(app: FastAPI, policy: AccessPolicy):
    app.state.access_policy = policy
    app.add_middleware(
        AccessCORSMiddleware,
        policy=policy,
        allow_origins=list(policy.origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
