"""Minimal OpenAI-compatible chat-completions client.

Works against any backend exposing ``POST /v1/chat/completions`` (Ocabra,
OpenAI, a local vLLM/Ollama gateway, ...). The URL is used verbatim, so point
``LLM_CHAT_URL`` at the full endpoint, e.g.
``http://ocabra:8080/v1/chat/completions``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from .config import Settings, get_settings

logger = logging.getLogger("yahoofinance-newsmcp.llm")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class LlmError(RuntimeError):
    """Raised when the summarization model could not be reached or parsed."""


def extract_chat_text(payload: Any) -> str:
    """Pull the assistant text out of a chat-completions response."""

    try:
        choices = payload["choices"]
        message = choices[0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError("chat-completions response is missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise LlmError("chat-completions response content was empty")
    return content.strip()


def parse_json_block(text: str) -> Any:
    """Extract a JSON value from an LLM reply that may wrap it in prose or fences.

    Tries, in order: the whole string, a fenced ```json block, then the widest
    ``{...}`` / ``[...]`` span. Raises LlmError if none parse.
    """

    candidates: List[str] = [text.strip()]
    candidates.extend(match.strip() for match in _JSON_FENCE_RE.findall(text))
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise LlmError("could not parse JSON from the model response")


class LlmClient:
    """OpenAI-compatible chat client with an injectable HTTP client."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = http_client or httpx.Client(timeout=self._settings.llm_timeout_seconds)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "LlmClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> str:
        settings = self._settings
        if not settings.llm_chat_url:
            raise LlmError("LLM_CHAT_URL is not configured")
        if not settings.llm_model:
            raise LlmError("LLM_MODEL is not configured")

        body: Dict[str, Any] = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"

        try:
            response = self._client.post(settings.llm_chat_url, json=body, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LlmError(
                f"summarization model returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"summarization model request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise LlmError("summarization model returned non-JSON") from exc
        return extract_chat_text(payload)
