"""Telegram delivery of the morning digest.

Only the single ``sendMessage`` Bot API method is used. Long digests are split
into chunks under Telegram's 4096-character message limit; plain text is sent
(no ``parse_mode``) so arbitrary article titles can never break Markdown/HTML
parsing.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from .config import Settings, get_settings

logger = logging.getLogger("yahoofinance-newsmcp.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096
# Leave headroom so a chunk boundary never lands exactly on the hard limit.
CHUNK_CHARS = 4000


class TelegramError(RuntimeError):
    """Raised when the digest could not be delivered to Telegram."""


def chunk_message(text: str, limit: int = CHUNK_CHARS) -> List[str]:
    """Split text into chunks no longer than ``limit``, preferring line breaks."""

    text = text or ""
    if len(text) <= limit:
        return [text] if text else []

    chunks: List[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip("\n"))
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


class TelegramClient:
    """Thin Telegram Bot API client with an injectable HTTP client."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = http_client or httpx.Client(timeout=self._settings.http_timeout_seconds)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TelegramClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_me(self) -> str:
        """Verify the bot token against the Bot API; returns the bot username.

        Raises TelegramError when the token is missing, rejected, or the Bot
        API is unreachable. Used by health checks to distinguish "delivery not
        configured" from "delivery configured but broken".
        """

        if not self._settings.telegram_bot_token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not configured")

        url = f"{TELEGRAM_API_BASE}/bot{self._settings.telegram_bot_token}/getMe"
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise TelegramError(f"Telegram getMe request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise TelegramError("Telegram rejected the bot token (HTTP {})".format(response.status_code))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TelegramError(
                f"Telegram getMe returned HTTP {exc.response.status_code}"
            ) from exc

        payload = response.json()
        if not payload.get("ok"):
            description = payload.get("description") or "unknown error"
            raise TelegramError(f"Telegram getMe failed: {description}")
        result = payload.get("result")
        username = result.get("username") if isinstance(result, dict) else None
        return username or "unknown bot"

    def send_message(self, text: str, chat_id: Optional[str] = None) -> List[int]:
        """Send text (auto-chunked) to a chat; returns the message ids sent."""

        settings = self._settings
        if not settings.telegram_bot_token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not configured")
        chat_id = chat_id or settings.telegram_chat_id
        if not chat_id:
            raise TelegramError("TELEGRAM_CHAT_ID is not configured")

        url = f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
        message_ids: List[int] = []
        for chunk in chunk_message(text):
            try:
                response = self._client.post(
                    url, json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise TelegramError(
                    f"Telegram rejected the digest with HTTP {exc.response.status_code}"
                ) from exc
            except httpx.HTTPError as exc:
                raise TelegramError(f"Telegram request failed: {exc}") from exc

            payload = response.json()
            result = payload.get("result") if isinstance(payload, dict) else None
            if isinstance(result, dict) and "message_id" in result:
                message_ids.append(int(result["message_id"]))
        return message_ids
