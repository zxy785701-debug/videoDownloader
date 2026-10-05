import json
import time
from typing import Callable

import httpx

from .ai_config import AIConfig
from .analysis_errors import AnalysisError


class DeepSeekClient:
    def __init__(self, config: AIConfig, check: Callable, on_usage: Callable, transport=None):
        self.config, self.check, self.on_usage, self.transport = config, check, on_usage, transport

    def complete(self, messages: list[dict], max_tokens: int, deadline: float) -> dict:
        self.config.require_key()
        payload = json.dumps({
            "model": self.config.model, "messages": messages,
            "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
            "max_tokens": max_tokens, "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        if len(payload) > self.config.max_request_bytes:
            raise AnalysisError("AI_CONTEXT_TOO_LARGE", "字幕与对话超过单次请求上限，未截断原文；可清空对话后重试。")
        call_deadline = min(deadline, time.monotonic() + self.config.request_timeout)
        for attempt in range(3):
            self.check()
            remaining = call_deadline - time.monotonic()
            if remaining <= 0:
                raise AnalysisError("AI_TIMEOUT", "模型请求超时，可能已产生用量，请手动重试。")
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(remaining, connect=min(10, remaining)),
                    transport=self.transport, follow_redirects=False, trust_env=False,
                ) as client:
                    with client.stream(
                        "POST", "https://api.deepseek.com/chat/completions",
                        headers={"Authorization": "Bearer " + self.config.api_key, "Content-Type": "application/json"},
                        content=payload,
                    ) as response:
                        status = response.status_code
                        if status == 429 or status in {500, 502, 503, 504}:
                            if attempt < 2:
                                wait = min(2 ** attempt, max(0, call_deadline - time.monotonic()))
                                time.sleep(wait)
                                continue
                            code, message = ("AI_RATE_LIMITED", "DeepSeek 请求受限，请稍后重试。") if status == 429 else ("AI_UPSTREAM_FAILED", "DeepSeek 暂时不可用，请稍后重试。")
                            raise AnalysisError(code, message)
                        failures = {
                            400: ("AI_REQUEST_INVALID", "DeepSeek 不接受当前请求格式，请检查模型配置。"),
                            401: ("AI_KEY_INVALID", "DeepSeek 密钥无效，请在本机检查后端配置。"),
                            402: ("AI_BALANCE_INSUFFICIENT", "DeepSeek 账户余额不足，请在官方平台检查。"),
                            422: ("AI_REQUEST_INVALID", "DeepSeek 请求参数无效，请检查模型配置。"),
                        }
                        if status in failures:
                            raise AnalysisError(*failures[status])
                        if status != 200:
                            raise AnalysisError("AI_UPSTREAM_FAILED", "DeepSeek 返回异常响应，请稍后重试。")
                        body = bytearray()
                        for part in response.iter_bytes(65536):
                            self.check()
                            if time.monotonic() >= call_deadline:
                                raise AnalysisError("AI_TIMEOUT", "模型请求超时，可能已产生用量，请手动重试。")
                            body.extend(part)
                            if len(body) > 2 * 1024 * 1024:
                                raise AnalysisError("AI_OUTPUT_INVALID", "模型返回内容过大，未保存为成功结果。")
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError()
                usage = data.get("usage") or {}
                usage = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens") if isinstance(usage.get(k), int) and not isinstance(usage[k], bool) and usage[k] >= 0}
                self.on_usage(usage)
                self.check()
                choice = data.get("choices", [])[0]
                if choice.get("finish_reason") != "stop":
                    raise AnalysisError("AI_OUTPUT_INVALID", "模型输出不完整或被中断，未保存为成功结果。")
                content = choice.get("message", {}).get("content")
                if not isinstance(content, str) or not content.strip():
                    raise AnalysisError("AI_OUTPUT_INVALID", "DeepSeek 返回空内容，请重试。")
                output = json.loads(content)
                if not isinstance(output, dict):
                    raise ValueError()
                return output
            except AnalysisError:
                raise
            except httpx.TimeoutException as error:
                raise AnalysisError("AI_TIMEOUT", "DeepSeek 响应超时，可能已产生用量，请手动重试。") from error
            except httpx.HTTPError as error:
                raise AnalysisError("AI_NETWORK_FAILED", "无法连接 DeepSeek 官方 API，请检查本机网络后重试。") from error
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError) as error:
                raise AnalysisError("AI_OUTPUT_INVALID", "DeepSeek 返回无效内容，未保存为成功结果。") from error
        raise AnalysisError("AI_UPSTREAM_FAILED", "DeepSeek 暂时不可用。")
