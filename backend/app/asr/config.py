import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..analysis_errors import AnalysisError
from .settings import setting


def integer(name, default, low, high):
    try:
        return max(low, min(high, int(setting(name, str(default)))))
    except ValueError:
        return default


def number(name, default):
    import math
    try:
        value = float(setting(name, str(default)))
        return value if math.isfinite(value) and value >= 0 else default
    except ValueError:
        return default


@dataclass(frozen=True)
class ASRUser:
    """Internal identity resolved by the backend, never from a request body."""
    key: str
    member: bool = False


@dataclass(frozen=True)
class ASRConfig:
    enabled: bool
    provider: str
    model: str
    max_duration: int
    concurrency: int
    budget: float
    stop_over_budget: bool
    price_per_second: float
    job_timeout: int
    audio_timeout: int
    poll_interval: int
    retries: int
    max_audio_bytes: int
    max_download_bytes: int
    url_ttl: int
    per_user_hour: int
    member_per_user_hour: int
    threads: int
    base_url: str
    temp_root: Path

    def fingerprint(self, language):
        # Conversion and output schema versions are part of cache identity.
        return hashlib.sha256(json.dumps([self.provider, self.model, language,
            "mono-16000-flac-v1", "sentences-v1", [0]], sort_keys=True).encode()).hexdigest()

    def require(self):
        if not self.enabled:
            raise AnalysisError("ASR_DISABLED", "没有可用原生字幕，服务端尚未开启语音转录。", 409)
        if self.provider == "groq_whisper":
            raise AnalysisError("ASR_PROVIDER_NOT_IMPLEMENTED", "Groq Whisper 接口已预留，暂未启用真实识别。", 409)
        if self.provider != "aliyun_paraformer" or self.model != "paraformer-v2":
            raise AnalysisError("ASR_CONFIG_INVALID", "请配置 aliyun_paraformer 和 paraformer-v2。", 409)
        if not setting("DASHSCOPE_API_KEY").strip():
            raise AnalysisError("ASR_NOT_CONFIGURED", "原生字幕不可用；请管理员在服务端环境变量或项目根目录 .env 配置 DASHSCOPE_API_KEY 后重试。", 409)
        if not re.fullmatch(r"https://(?:dashscope\.aliyuncs\.com|[A-Za-z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com)/api/v1", self.base_url):
            raise AnalysisError("ASR_CONFIG_INVALID", "ASR_API_BASE 必须是百炼北京地域 HTTPS API 地址。", 409)


def get_config(runtime_root: Path) -> ASRConfig:
    timeout = integer("ASR_JOB_TIMEOUT_SECONDS", 1800, 60, 7200)
    return ASRConfig(
        enabled=setting("ASR_ENABLED", "true").lower() in {"1", "true"},
        provider=setting("ASR_PROVIDER", "aliyun_paraformer").strip(),
        model=setting("ASR_MODEL", "paraformer-v2").strip(),
        max_duration=integer("ASR_MAX_DURATION_SECONDS", 3600, 1, 7200),
        concurrency=integer("ASR_MAX_CONCURRENT_JOBS", 1, 1, 2),
        budget=number("ASR_MONTHLY_BUDGET_CNY", 10),
        stop_over_budget=setting("ASR_STOP_ON_BUDGET", "true").lower() in {"1", "true"},
        price_per_second=number("ASR_PRICE_CNY_PER_SECOND", 0.00008),
        job_timeout=timeout, audio_timeout=integer("ASR_AUDIO_TIMEOUT_SECONDS", 900, 10, timeout),
        poll_interval=integer("ASR_POLL_INTERVAL_SECONDS", 5, 1, 60),
        retries=integer("ASR_MAX_RETRIES", 2, 0, 3),
        max_audio_bytes=integer("ASR_MAX_AUDIO_MB", 120, 1, 256) * 1024 * 1024,
        max_download_bytes=integer("ASR_MAX_DOWNLOAD_MB", 256, 1, 512) * 1024 * 1024,
        url_ttl=integer("ASR_SIGNED_URL_TTL_SECONDS", max(7200, timeout + 300), timeout + 300, 86400),
        per_user_hour=integer("ASR_USER_HOURLY_LIMIT", 3, 1, 100),
        member_per_user_hour=integer("ASR_MEMBER_HOURLY_LIMIT", 10, 1, 100),
        threads=integer("ASR_FFMPEG_THREADS", 1, 1, 2),
        base_url=setting("ASR_API_BASE", "https://dashscope.aliyuncs.com/api/v1").rstrip("/"),
        temp_root=Path(setting("ASR_TEMP_DIR", str(runtime_root / "asr-tmp"))),
    )
