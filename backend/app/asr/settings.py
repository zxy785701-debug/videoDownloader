"""Allowlisted server-only ASR settings; never export .env into process env."""
import logging
import os
from pathlib import Path

from dotenv import dotenv_values


NAMES = frozenset({
    "ASR_ENABLED", "ASR_PROVIDER", "ASR_MODEL", "ASR_MAX_DURATION_SECONDS",
    "ASR_MAX_CONCURRENT_JOBS", "ASR_MONTHLY_BUDGET_CNY", "ASR_STOP_ON_BUDGET",
    "ASR_PRICE_CNY_PER_SECOND", "ASR_USER_HOURLY_LIMIT", "ASR_MEMBER_HOURLY_LIMIT", "ASR_JOB_TIMEOUT_SECONDS",
    "ASR_AUDIO_TIMEOUT_SECONDS", "ASR_POLL_INTERVAL_SECONDS", "ASR_MAX_RETRIES",
    "ASR_MAX_AUDIO_MB", "ASR_MAX_DOWNLOAD_MB", "ASR_SIGNED_URL_TTL_SECONDS",
    "ASR_FFMPEG_THREADS", "ASR_API_BASE", "ASR_TEMP_DIR", "DASHSCOPE_API_KEY",
    "ALIYUN_OSS_BUCKET", "ALIYUN_OSS_ENDPOINT", "ALIYUN_OSS_ACCESS_KEY_ID",
    "ALIYUN_OSS_ACCESS_KEY_SECRET", "ALIYUN_OSS_SECURITY_TOKEN",
})


def read_local_settings(path: Path) -> dict[str, str]:
    try:
        values = dotenv_values(path, interpolate=False, encoding="utf-8-sig") if path.is_file() else {}
    except (OSError, UnicodeError) as error:
        logging.getLogger(__name__).warning("ASR local config unavailable type=%s", type(error).__name__)
        return {}
    return {name: value for name, value in values.items() if name in NAMES and isinstance(value, str)}


_LOCAL_CONFIG = read_local_settings(Path(__file__).resolve().parents[3] / ".env")


def setting(name: str, default: str = "") -> str:
    # An explicitly empty process variable also overrides the file. This lets
    # an operator disable a saved key or opt into the SDK role credential chain.
    return os.environ.get(name, _LOCAL_CONFIG.get(name, default))


def missing_configuration() -> list[str]:
    """Presence only: no network, secrets returned or role credentials fetched."""
    missing = [name for name in ("DASHSCOPE_API_KEY", "ALIYUN_OSS_BUCKET") if not setting(name).strip()]
    fixed_id = bool(setting("ALIYUN_OSS_ACCESS_KEY_ID").strip())
    fixed_secret = bool(setting("ALIYUN_OSS_ACCESS_KEY_SECRET").strip())
    if fixed_id != fixed_secret:
        missing.append("ALIYUN_OSS_ACCESS_KEY_SECRET" if fixed_id else "ALIYUN_OSS_ACCESS_KEY_ID")
    return missing


def main() -> int:
    missing = missing_configuration()
    if missing:
        print("Missing server configuration names (process environment or project-root .env): " + ", ".join(missing))
        return 1
    print("ASR configuration inputs found (not cloud-validated); secret values are never printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
