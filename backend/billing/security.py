import hashlib
import hmac
import re
import secrets


def mock_checkout_path(session_id: str) -> str:
    if not isinstance(session_id, str) or not re.fullmatch(r"cs_test_mock_[A-Za-z0-9_-]{32}", session_id):
        raise ValueError("Invalid mock checkout session")
    return "/dev/checkout/" + session_id


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    result = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=3, maxmem=64*1024*1024, dklen=32)
    return f"scrypt${salt}${result.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        method, salt, expected = stored.split("$")
        if method != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=3, maxmem=64*1024*1024, dklen=32).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token() -> str:
    return secrets.token_urlsafe(32)
