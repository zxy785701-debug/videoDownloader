import json
import threading
import time
from contextlib import contextmanager
from typing import Callable

import httpx

from .ai_config import AIConfig
from .analysis_errors import AnalysisError, OutputLimitError


class DeepSeekHTTPPool:
    """Share verified connections, never a job's credentials or callbacks."""

    def __init__(self, transport=None):
        self.transport = transport
        self.lock = threading.Lock()
        self.http = None
        self.closed = False

    def client(self):
        with self.lock:
            if self.closed:
                raise AnalysisError("SERVICE_STOPPING", "服务正在停止，请稍后重试。", 503)
            if self.http is None:
                self.http = httpx.Client(transport=self.transport, verify=True,
                                         follow_redirects=False, trust_env=False)
            return self.http

    @contextmanager
    def stream(self, payload, api_key, deadline, check):
        client = self.client()
        # TLS initialization/pool acquisition count towards the original deadline.
        check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AnalysisError("AI_TIMEOUT", "模型请求超时，可能已产生用量，请手动重试。")
        timeout = httpx.Timeout(remaining, connect=min(10, remaining))
        # Explicit requests cannot inherit another task's cookies or credentials.
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions",
                                headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
                                content=payload, extensions={"timeout": timeout.as_dict()})
        response = client.send(request, stream=True)
        try:
            yield response
        finally:
            response.close()

    def close(self):
        with self.lock:
            self.closed = True
            if self.http is not None:
                self.http.close()


class DeepSeekClient:
    def __init__(self, config: AIConfig, check: Callable, on_usage: Callable, transport=None, *, pool=None):
        self.config, self.check, self.on_usage, self.transport = config, check, on_usage, transport
        self.pool = pool if pool is not None else DeepSeekHTTPPool(transport)
        self.owns_pool = pool is None

    def close(self):
        if self.owns_pool:
            self.pool.close()

    def complete_stream(self, messages: list[dict], max_tokens: int, deadline: float, on_content: Callable) -> dict:
        return self.complete(messages, max_tokens, deadline, on_content=on_content)

    def complete(self, messages: list[dict], max_tokens: int, deadline: float, *, on_content=None) -> dict:
        self.config.require_key()
        request = {
            "model": self.config.model, "messages": messages,
            "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
            "max_tokens": max_tokens, "stream": on_content is not None,
        }
        if on_content is not None:
            request["stream_options"] = {"include_usage": True}
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
        if len(payload) > self.config.max_request_bytes:
            raise AnalysisError("AI_CONTEXT_TOO_LARGE", "字幕与对话超过单次请求上限，未截断原文；可清空对话后重试。")
        call_deadline = min(deadline, time.monotonic() + self.config.request_timeout)
        for attempt in range(3):
            self.check()
            remaining = call_deadline - time.monotonic()
            if remaining <= 0:
                raise AnalysisError("AI_TIMEOUT", "模型请求超时，可能已产生用量，请手动重试。")
            try:
                with self.pool.stream(payload, self.config.api_key, call_deadline, self.check) as response:
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
                    if on_content is not None:
                        data = self._read_stream(response, call_deadline, on_content)
                    else:
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
                if on_content is None:
                    self._usage(data.get("usage") or {})
                self.check()
                choice = data.get("choices", [])[0]
                if choice.get("finish_reason") == "length":
                    raise OutputLimitError()
                if choice.get("finish_reason") != "stop":
                    raise AnalysisError("AI_OUTPUT_INVALID", "模型输出不完整或被中断，未保存为成功结果。")
                content = choice.get("message", {}).get("content")
                if not isinstance(content, str) or not content.strip():
                    raise AnalysisError("AI_OUTPUT_INVALID", "DeepSeek 返回空内容，请重试。")
                output = json.loads(content)
                if not isinstance(output, dict):
                    raise ValueError()
                if on_content is not None:
                    json.dumps(output, ensure_ascii=False).encode("utf-8")
                return output
            except AnalysisError:
                raise
            except httpx.TimeoutException as error:
                raise AnalysisError("AI_TIMEOUT", "DeepSeek 响应超时，可能已产生用量，请手动重试。") from error
            except httpx.HTTPError as error:
                raise AnalysisError("AI_NETWORK_FAILED", "无法连接 DeepSeek 官方 API，请检查本机网络后重试。") from error
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError, UnicodeError) as error:
                raise AnalysisError("AI_OUTPUT_INVALID", "DeepSeek 返回无效内容，未保存为成功结果。") from error
        raise AnalysisError("AI_UPSTREAM_FAILED", "DeepSeek 暂时不可用。")

    def _usage(self, usage):
        if not isinstance(usage, dict):
            raise ValueError()
        self.on_usage({k: usage[k] for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
                       if isinstance(usage.get(k), int) and not isinstance(usage[k], bool) and usage[k] >= 0})

    def _read_stream(self, response, deadline, on_content):
        content, data_lines, finish, done, recorded = "", [], None, False, False
        received = 0
        next_check = 0
        for line in response.iter_lines():
            stamp = time.monotonic()
            if stamp >= next_check:
                self.check()
                next_check = time.monotonic() + 0.1
            if time.monotonic() >= deadline:
                raise AnalysisError("AI_TIMEOUT", "流式回答超时，可能已产生用量，请手动重试。")
            received += len(line.encode("utf-8")) + 1
            if received > 2 * 1024 * 1024:
                raise AnalysisError("AI_OUTPUT_INVALID", "模型返回内容过大，未保存为成功结果。")
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            elif not line and data_lines:
                event = "\n".join(data_lines); data_lines = []
                if event == "[DONE]":
                    done = True; break
                chunk = json.loads(event)
                if not isinstance(chunk, dict) or "error" in chunk:
                    raise AnalysisError("AI_UPSTREAM_FAILED", "DeepSeek 流式回答异常，未保存为成功结果。")
                if isinstance(chunk.get("usage"), dict) and not recorded:
                    self._usage(chunk["usage"]); recorded = True
                choices = chunk.get("choices")
                if not isinstance(choices, list):
                    raise ValueError()
                if not choices:
                    continue  # Compatibility with earlier usage-only chunks.
                choice = choices[0]
                delta = choice.get("delta", {}).get("content")
                if delta is not None:
                    if not isinstance(delta, str):
                        raise ValueError()
                    content += delta
                    if delta:
                        on_content(content)
                if choice.get("finish_reason") is not None:
                    finish = choice["finish_reason"]
        if not done:
            raise AnalysisError("AI_NETWORK_FAILED", "流式回答连接中断，可能已产生用量，请手动重试。")
        return {"choices": [{"finish_reason": finish, "message": {"content": content}}]}
