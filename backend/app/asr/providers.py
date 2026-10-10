import os
import re
from abc import ABC, abstractmethod

import httpx

from ..analysis_errors import AnalysisError


class RetryableQuery(AnalysisError):
    def __init__(self):
        super().__init__("ASR_QUERY_FAILED", "云端识别状态暂时无法查询，请稍后重试原任务。")


class ASRProvider(ABC):
    @abstractmethod
    def submit(self, audio_url: str, language: str) -> str: ...

    @abstractmethod
    def query(self, task_id: str) -> dict: ...


class AliyunParaformer(ASRProvider):
    def __init__(self, config):
        self.config = config

    def _request(self, method, path, **kwargs):
        with httpx.Client(timeout=httpx.Timeout(30, connect=10), follow_redirects=False,
                          trust_env=False) as client:
            return client.request(method, self.config.base_url + path,
                headers={"Authorization": "Bearer " + os.environ["DASHSCOPE_API_KEY"].strip(),
                         "X-DashScope-Async": "enable"}, **kwargs)

    def submit(self, audio_url, language):
        # No automatic POST retry: timeout/5xx may have accepted a billable task.
        hints = {"zh", "en", "ja", "yue", "ko", "de", "fr", "ru"}
        lang = language.removeprefix("ai-").split("-")[0]
        params = {"channel_id": [0]}
        if lang in hints:
            params["language_hints"] = [lang]
        try:
            response = self._request("POST", "/services/audio/asr/transcription", json={
                "model": self.config.model, "input": {"file_urls": [audio_url]}, "parameters": params})
        except httpx.HTTPError as error:
            raise AnalysisError("ASR_SUBMISSION_UNKNOWN", "识别提交结果不明；已停止自动重提，请管理员先核查百炼任务及账单。") from error
        if response.status_code in {401, 403}:
            raise AnalysisError("ASR_AUTH_FAILED", "百炼拒绝访问，请管理员检查北京地域 API Key 与模型权限。")
        if response.status_code == 429:
            raise AnalysisError("ASR_RATE_LIMITED", "百炼请求过于频繁，请稍后重试。", 429)
        if response.status_code >= 500 or response.status_code in {408, 409} or response.is_redirect:
            raise AnalysisError("ASR_SUBMISSION_UNKNOWN", "识别提交结果不明，已禁止自动重复提交，请先核查云端任务。")
        if response.status_code != 200:
            raise AnalysisError("ASR_SUBMIT_FAILED", "百炼未接受识别任务，请管理员检查模型与音频配置。")
        try:
            task_id = response.json()["output"]["task_id"]
            if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
                raise ValueError()
            return task_id
        except (ValueError, KeyError, TypeError) as error:
            raise AnalysisError("ASR_SUBMISSION_UNKNOWN", "百炼响应缺少任务 ID；已禁止重复提交，请管理员核查云端任务。") from error

    def query(self, task_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
            raise AnalysisError("ASR_TASK_INVALID", "保存的识别任务标识无效。")
        try:
            # Official recorded-file example uses POST for task queries; this is
            # read-only, and never uses the transcription submission endpoint.
            response = self._request("POST", "/tasks/" + task_id)
            if response.status_code == 429 or response.status_code >= 500:
                raise RetryableQuery()
            if response.status_code != 200:
                raise AnalysisError("ASR_QUERY_FAILED", "无法查询原识别任务，可能已过云端保存期限；未重复提交。")
            data = response.json()
            if not isinstance(data.get("output"), dict):
                raise ValueError()
            return data
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise RetryableQuery() from error


class GroqWhisper(ASRProvider):
    def submit(self, audio_url, language):
        raise AnalysisError("ASR_PROVIDER_NOT_IMPLEMENTED", "Groq Whisper 仅预留接口，尚未实现。", 409)

    def query(self, task_id):
        raise AnalysisError("ASR_PROVIDER_NOT_IMPLEMENTED", "Groq Whisper 仅预留接口，尚未实现。", 409)
