import hashlib
import hmac
import secrets


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
