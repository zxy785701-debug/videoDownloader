import os
import logging
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from .analysis_errors import AnalysisError


def read_local_settings(path: Path) -> dict[str, str]:
    allowed = {
        "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_TIMEOUT_SECONDS",
        "VIDEO_LEARNING_MAX_SECONDS", "VIDEO_LEARNING_MAX_CHARACTERS",
        "VIDEO_LEARNING_SUMMARY_TIMEOUT", "VIDEO_LEARNING_DB",
        "VIDEO_LEARNING_FIREFOX_SESSION", "VIDEO_LEARNING_FIREFOX_PROFILE",
    }
    try:
        values = dotenv_values(path, interpolate=False) if path.is_file() else {}
    except OSError as error:
        logging.getLogger(__name__).warning("Learning config unavailable type=%s", type(error).__name__)
        return {}
    return {name: value for name, value in values.items() if name in allowed and isinstance(value, str)}


_LOCAL_CONFIG = read_local_settings(Path(__file__).resolve().parents[2] / ".env")


def setting(name: str, default: str = "") -> str:
    # Local AI settings only; do not load download settings or mutate process env.
    return os.environ.get(name, _LOCAL_CONFIG.get(name, default))


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(setting(name, str(default)))))
    except ValueError:
        return default


@dataclass(frozen=True)
class AIConfig:
    model: str
    api_key: str = field(repr=False)
    max_duration: int
    max_characters: int
    request_timeout: int
    summary_timeout: int
    max_resource_bytes: int = 5 * 1024 * 1024
    max_request_bytes: int = 700 * 1024
    chunk_characters: int = 12000
    firefox_subtitle_session: bool = False
    firefox_subtitle_profile: str | None = field(default=None, repr=False)

    def require_key(self):
        if not self.api_key:
            raise AnalysisError("AI_NOT_CONFIGURED", "请先在本机后端配置 DeepSeek API 密钥。", 409)
        if self.model not in {"deepseek-flash", "deepseek-v4-pro"}:
            raise AnalysisError("AI_MODEL_INVALID", "DEEPSEEK_MODEL 需设置为 deepseek-flash 或 deepseek-v4-pro。", 409)

    def public(self) -> dict:
        return {
            "configured": bool(self.api_key),
            "model": self.model,
            "max_duration": self.max_duration,
            "max_characters": self.max_characters,
            "request_timeout": self.request_timeout,
            "summary_timeout": self.summary_timeout,
            "firefox_subtitle_session": self.firefox_subtitle_session,
            "summary_stream_version": 2,
            "auto_summary_version": 1,
        }


def get_config() -> AIConfig:
    return AIConfig(
        model=setting("DEEPSEEK_MODEL", "deepseek-flash").strip(),
        api_key=setting("DEEPSEEK_API_KEY").strip(),
        max_duration=_integer("VIDEO_LEARNING_MAX_SECONDS", 7200, 60, 7200),
        max_characters=_integer("VIDEO_LEARNING_MAX_CHARACTERS", 120000, 1000, 120000),
        request_timeout=_integer("DEEPSEEK_TIMEOUT_SECONDS", 180, 10, 180),
        summary_timeout=_integer("VIDEO_LEARNING_SUMMARY_TIMEOUT", 900, 30, 900),
        firefox_subtitle_session=setting("VIDEO_LEARNING_FIREFOX_SESSION").strip().lower() in {"1", "true"},
        firefox_subtitle_profile=setting("VIDEO_LEARNING_FIREFOX_PROFILE").strip() or None,
    )
