import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger("uvicorn.error.ollama")


class OllamaError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


class OllamaClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self.http = http
        self.settings = settings
        # One in-flight generation for the initial single-worker deployment.
        self._generation_lock = asyncio.Lock()

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            response = await self.http.request(method, path, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError("Invalid Ollama response")
            return payload
        except httpx.TimeoutException as exc:
            raise OllamaError(504, "ollama_timeout", "Ollama 응답 시간이 초과되었습니다.") from exc
        except httpx.RequestError as exc:
            raise OllamaError(503, "ollama_unavailable", "Ollama에 연결할 수 없습니다. 실행 상태와 연결 주소를 확인하세요.") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and path == "api/chat":
                raise OllamaError(502, "ollama_model_unavailable", "설정한 모델을 찾을 수 없습니다. ollama list와 .env 모델 이름을 확인하세요.") from exc
            raise OllamaError(502, "ollama_upstream_error", "Ollama 요청이 실패했습니다. 모델·버전·Ollama 로그를 확인하세요.") from exc
        except ValueError as exc:
            raise OllamaError(502, "ollama_invalid_response", "Ollama가 올바르지 않은 응답을 반환했습니다.") from exc

    async def status(self) -> dict[str, Any]:
        version = await self._request("GET", "api/version")
        tags = await self._request("GET", "api/tags")
        models = tags.get("models")
        if not isinstance(version.get("version"), str) or not isinstance(models, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in models
        ):
            raise OllamaError(502, "ollama_invalid_response", "Ollama 버전 또는 모델 목록 형식이 올바르지 않습니다.")
        names = [item["name"] for item in models]
        model = self.settings.ollama_model
        return {
            "connected": True,
            "version": version["version"],
            "configured_model": model,
            "model_available": model in names or (":" not in model and f"{model}:latest" in names),
            "models": names,
        }

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict] | None = None,
                   response_schema: dict | None = None) -> dict[str, Any]:
        if tools is not None and response_schema is not None:
            raise ValueError("Use native tools or a structured plan, not both")
        outgoing = [dict(message) for message in messages]
        if (self.settings.ollama_disable_thinking and self.settings.ollama_model.split(":")[0] == "qwen3"
                and "instruct" not in self.settings.ollama_model.partition(":")[2]):
            # Qwen's prompt-level switch also supports templates that retain a think prefix.
            for message in reversed(outgoing):
                if message.get("role") == "user":
                    message["content"] = str(message.get("content", "")) + "\n/no_think"
                    break
        body = {
            "model": self.settings.ollama_model, "messages": outgoing, "stream": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": {"num_ctx": self.settings.ollama_num_ctx, "num_predict": self.settings.ollama_num_predict},
        }
        if self.settings.ollama_disable_thinking:
            body["think"] = False
        if tools is not None:
            body["tools"] = tools
            body["options"]["temperature"] = 0
        if response_schema is not None:
            body["format"] = response_schema
            body["options"]["temperature"] = 0
        try:
            # Includes queue waiting; requests are not retried automatically.
            started = time.monotonic()
            phase = "queue"
            async with asyncio.timeout(self.settings.ollama_timeout_seconds):
                async with self._generation_lock:
                    logger.info("Ollama acquired model=%s queue_seconds=%.2f", self.settings.ollama_model, time.monotonic() - started)
                    phase = "generation"
                    payload = await self._request("POST", "api/chat", json=body)
                    logger.info("Ollama response model=%s total_seconds=%.2f", self.settings.ollama_model, time.monotonic() - started)
        except TimeoutError as exc:
            logger.warning("Ollama timeout phase=%s elapsed_seconds=%.2f", phase, time.monotonic() - started)
            raise OllamaError(504, "ollama_timeout", "대기 또는 Ollama 응답 시간이 초과되었습니다.") from exc
        except OllamaError as exc:
            logger.warning("Ollama error code=%s phase=%s elapsed_seconds=%.2f", exc.code, phase, time.monotonic() - started)
            raise
        message = payload.get("message")
        if payload.get("done_reason") == "length":
            raise OllamaError(502, "ollama_output_truncated", "응답이 생성 길이 제한으로 잘렸습니다. 완성된 답변으로 처리하지 않습니다.")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = message["content"]
            if "</think>" in content:
                message["content"] = content.rsplit("</think>", 1)[1].strip()
            elif "<think>" in content:
                raise OllamaError(502, "ollama_incomplete_thinking", "최종 답변 없이 사고 과정만 반환되었습니다.")
        if (
            payload.get("done") is not True
            or not isinstance(payload.get("model"), str)
            or not isinstance(message, dict)
            or message.get("role") != "assistant"
            or not isinstance(message.get("content"), str)
            or (not message["content"].strip() and not (tools and message.get("tool_calls")))
            or len(message["content"]) > 16000
            or (message.get("tool_calls") and not tools)
            or (payload.get("done_reason") is not None and not isinstance(payload["done_reason"], str))
        ):
            raise OllamaError(502, "ollama_invalid_response", "Ollama에서 유효한 최종 텍스트 응답을 받지 못했습니다.")
        return payload
