import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import HTTPException


def validate_public_http_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only absolute HTTP and HTTPS URLs are supported")
        if parsed.username or parsed.password:
            raise ValueError("URLs containing credentials are not supported")

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        resolved = {ipaddress.ip_address(item[4][0]) for item in addresses}
        if not resolved or any(not address.is_global for address in resolved):
            raise ValueError("The URL host must resolve to a public IP address")
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return value