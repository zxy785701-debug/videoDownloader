"""Local HTTP proxy fixture reproducing Nginx $host stripping the tunnel port.

Not Nginx or a deployment entrypoint. Only used with isolated mock services.
"""
from contextlib import asynccontextmanager
import os
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
import httpx


UPSTREAM = os.environ["MEMBERSHIP_TEST_UPSTREAM_URL"].rstrip("/")
parsed = urlsplit(UPSTREAM)
if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path or parsed.username or parsed.password:
    raise RuntimeError("Test proxy upstream must be loopback HTTP")


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
        app.state.upstream = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(path: str, request: Request):
    if request.client.host not in {"127.0.0.1", "::1"} or request.url.hostname not in {"localhost", "127.0.0.1"}:
        return Response(status_code=403)
    if path not in {"", "favicon.svg"} and not path.startswith(("assets/", "api/v1/", "dev/checkout/")):
        return Response(status_code=404)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in {
        "host", "connection", "content-length", "authorization", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"}}
    headers["Host"] = request.url.hostname  # Equivalent to proxy_set_header Host $host.
    response = await app.state.upstream.send(httpx.Request(request.method,
        UPSTREAM + request.url.path + ("?" + request.url.query if request.url.query else ""),
        headers=headers, content=await request.body()))
    outgoing = {k: v for k, v in response.headers.items() if k.lower() not in {
        "content-length", "content-encoding", "connection", "transfer-encoding"}}
    return Response(response.content, status_code=response.status_code, headers=outgoing)
