"""Small OpenAI-compatible LLM client used by optional agent helpers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMClientConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 30


class LLMClientError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, config: LLMClientConfig) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")

    def list_models(self) -> list[str]:
        payload = self._request("GET", "/models")
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        models = [str(row.get("id")) for row in rows if isinstance(row, dict) and row.get("id")]
        return sorted(set(models))

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        data = self._request("POST", "/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("invalid_chat_completion_response") from exc
        try:
            parsed = json.loads(str(content))
        except json.JSONDecodeError as exc:
            raise LLMClientError("llm_response_not_json") from exc
        if not isinstance(parsed, dict):
            raise LLMClientError("llm_json_response_must_be_object")
        return parsed

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "crypto-quant-bot/1.0 (+llm)",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise LLMClientError(detail or f"HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise LLMClientError(f"network_error: {exc.reason}") from exc
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise LLMClientError("invalid_json_response") from exc
        if not isinstance(data, dict):
            raise LLMClientError("response_must_be_object")
        return data