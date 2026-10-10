"""Bounded public downloads with DNS pinning, including every redirect.

The media/result client never forwards API keys or platform Cookie headers.
TLS still verifies the original hostname while connecting to the validated IP.
"""
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from ..analysis_errors import AnalysisError


def public_addresses(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = [item[4][0] for item in addresses]
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise AnalysisError("ASR_URL_UNSAFE", "音频或识别结果地址未通过公网安全校验。")
    return ips


class PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        ips = public_addresses(self.host, self.port)
        self.sock = socket.create_connection((ips[0], self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def download(url, destination, limit, check=lambda: None, headers=None, result_only=False):
    safe_headers = {k: v for k, v in (headers or {}).items()
                    if k.lower() in {"user-agent", "referer", "accept-language"}
                    and isinstance(v, str) and "\r" not in v and "\n" not in v}
    safe_headers["Accept-Encoding"] = "identity"
    for _ in range(9):
        check()
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in {None, 443}):
            raise AnalysisError("ASR_URL_UNSAFE", "音频与识别结果必须使用公开 HTTPS 地址。")
        if result_only and not parsed.hostname.endswith(".oss-cn-beijing.aliyuncs.com"):
            raise AnalysisError("ASR_URL_UNSAFE", "识别结果未使用北京地域 OSS 地址。")
        connection = PinnedHTTPS(parsed.hostname, timeout=20, context=ssl.create_default_context())
        try:
            connection.request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""), headers=safe_headers)
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.getheader("Location", ""))
                continue
            if response.status != 200:
                raise AnalysisError("ASR_RESOURCE_FAILED", "音频或识别结果无法下载，请检查平台权限或稍后重试。")
            length = response.getheader("Content-Length")
            if length and int(length) > limit:
                raise AnalysisError("ASR_FILE_TOO_LARGE", "音频或识别结果超过服务端文件大小上限。")
            size = 0
            with destination.open("wb") as output:
                while True:
                    check()
                    block = response.read(64 * 1024)
                    if not block:
                        break
                    size += len(block)
                    if size > limit:
                        raise AnalysisError("ASR_FILE_TOO_LARGE", "音频或识别结果超过服务端文件大小上限。")
                    output.write(block)
            return
        finally:
            connection.close()
    raise AnalysisError("ASR_RESOURCE_FAILED", "音频或识别结果跳转次数过多。")


def result_json(url, directory, check):
    path = directory / "result.json"
    try:
        download(url, path, 5 * 1024 * 1024, check, result_only=True)
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise AnalysisError("ASR_RESULT_INVALID", "无法读取语音识别结果。") from error


def resolve_short_link(url):
    """Resolve B23 without letting yt-dlp follow arbitrary redirect targets."""
    for _ in range(9):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.port not in {None, 443} or parsed.username or parsed.password
                or parsed.hostname not in {"b23.tv", "www.bilibili.com", "bilibili.com"}):
            raise AnalysisError("ASR_URL_UNSAFE", "B站短链接跳转到了不允许的地址。")
        if parsed.hostname != "b23.tv":
            return url
        connection = PinnedHTTPS(parsed.hostname, timeout=20, context=ssl.create_default_context())
        try:
            connection.request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""))
            response = connection.getresponse()
            if response.status not in {301, 302, 303, 307, 308}:
                raise AnalysisError("ASR_AUDIO_UNAVAILABLE", "B站短链接未返回视频地址，请使用完整 BV/AV 链接。")
            url = urljoin(url, response.getheader("Location", ""))
        finally:
            connection.close()
    raise AnalysisError("ASR_URL_UNSAFE", "B站短链接跳转次数过多。")
