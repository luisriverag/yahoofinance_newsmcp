"""Service-level orchestration shared by the MCP tools and the scheduler.

Keeps the three-step morning flow in one place: generate -> persist -> deliver.
The MCP tools and the scheduler both call these, so behavior can never drift
between an on-demand digest and the automatic one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .config import Settings, get_settings
from .digest import MorningDigest, generate_digest, persist_digest, render_markdown
from .telegram import TelegramClient

logger = logging.getLogger("yahoofinance-newsmcp.services")


@dataclass(frozen=True)
class DigestRun:
    digest: MorningDigest
    markdown: str
    persisted_paths: list
    message_ids: list


def generate_and_persist(
    settings: Optional[Settings] = None,
    *,
    yahoo=None,
    llm=None,
    tickers=None,
) -> MorningDigest:
    """Generate a digest and write it to the configured state directory."""

    settings = settings or get_settings()
    digest = generate_digest(settings, yahoo=yahoo, llm=llm, tickers=tickers)
    persist_digest(digest, settings.digest_state_dir)
    return digest


def deliver_digest(
    digest: MorningDigest,
    settings: Optional[Settings] = None,
    *,
    chat_id: Optional[str] = None,
) -> list:
    """Send a rendered digest to Telegram if delivery is configured."""

    settings = settings or get_settings()
    if not (settings.telegram_bot_token and (chat_id or settings.telegram_chat_id)):
        logger.info("Telegram delivery not configured; skipping send.")
        return []
    with TelegramClient(settings) as telegram:
        return telegram.send_message(render_markdown(digest), chat_id)


def run_morning_digest(
    settings: Optional[Settings] = None,
    *,
    chat_id: Optional[str] = None,
    yahoo=None,
    llm=None,
    tickers=None,
) -> DigestRun:
    """The full morning flow: generate, persist, and deliver."""

    settings = settings or get_settings()
    digest = generate_and_persist(settings, yahoo=yahoo, llm=llm, tickers=tickers)
    message_ids = deliver_digest(digest, settings, chat_id=chat_id)
    return DigestRun(
        digest=digest,
        markdown=render_markdown(digest),
        persisted_paths=[],
        message_ids=message_ids,
    )
