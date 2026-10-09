"""Configuration loaded entirely from environment variables / .env.

Nothing here is a real endpoint, key, or chat id: every credential and
operational knob lives in the environment so the code can be published without
leaking anyone's tokens or watchlist. Values are read once and cached; changing
`.env` requires restarting the process (or calling ``reset_settings_cache`` in
tests).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def _float_env(name: str, default: float) -> float:
    raw = _clean(os.getenv(name))
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = _clean(os.getenv(name))
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = _clean(os.getenv(name)).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y"}


def _log_level_env(name: str, default: str) -> str:
    raw = _clean(os.getenv(name)).upper()
    return raw if raw in _VALID_LOG_LEVELS else default


def parse_tickers(raw: str) -> List[str]:
    """Split a comma-separated ticker list into normalized, de-duplicated symbols."""

    return _dedupe(_clean(item).upper() for item in (raw or "").split(",") if _clean(item))


def parse_watchlist_text(text: str) -> List[str]:
    """One ticker per line; blank lines and ``#`` comments are ignored."""

    tickers: List[str] = []
    for line in (text or "").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            tickers.append(stripped.upper())
    return _dedupe(tickers)


def _dedupe(items) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


@dataclass(frozen=True)
class Settings:
    watchlist_tickers: List[str] = field(default_factory=list)
    watchlist_file: str = ""

    news_lookback_hours: float = 24.0
    news_per_ticker: int = 10
    news_fetch_article_text: bool = True
    news_max_article_chars: int = 6000

    yahoo_news_base_url: str = "https://query1.finance.yahoo.com"
    yahoo_rss_base_url: str = "https://feeds.finance.yahoo.com/rss/2.0/headline"

    llm_chat_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 120.0

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    digest_scheduler_enabled: bool = False
    digest_time: str = "07:00"
    digest_timezone: str = "UTC"
    digest_state_dir: str = ""

    http_timeout_seconds: float = 30.0
    log_level: str = "INFO"

    def resolved_tickers(self) -> List[str]:
        """Configured watchlist: env tickers merged with an optional file."""

        return _dedupe([*self.watchlist_tickers, *load_watchlist_file(self.watchlist_file)])


def load_watchlist_file(path: str) -> List[str]:
    """Read a watchlist file, returning an empty list when unset or unreadable."""

    if not path:
        return []
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as handle:
            return parse_watchlist_text(handle.read())
    except OSError:
        logging.getLogger("yahoofinance-newsmcp").warning(
            "Could not read WATCHLIST_FILE=%s; continuing with WATCHLIST_TICKERS only.", path
        )
        return []


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        watchlist_tickers=parse_tickers(_clean(os.getenv("WATCHLIST_TICKERS"))),
        watchlist_file=_clean(os.getenv("WATCHLIST_FILE")),
        news_lookback_hours=_float_env("NEWS_LOOKBACK_HOURS", 24.0),
        news_per_ticker=_int_env("NEWS_PER_TICKER", 10),
        news_fetch_article_text=_bool_env("NEWS_FETCH_ARTICLE_TEXT", True),
        news_max_article_chars=_int_env("NEWS_MAX_ARTICLE_CHARS", 6000),
        yahoo_news_base_url=(
            _clean(os.getenv("YAHOO_NEWS_BASE_URL")) or "https://query1.finance.yahoo.com"
        ).rstrip("/"),
        yahoo_rss_base_url=(
            _clean(os.getenv("YAHOO_RSS_BASE_URL"))
            or "https://feeds.finance.yahoo.com/rss/2.0/headline"
        ).rstrip("/"),
        llm_chat_url=_clean(os.getenv("LLM_CHAT_URL")),
        llm_api_key=_clean(os.getenv("LLM_API_KEY")),
        llm_model=_clean(os.getenv("LLM_MODEL")),
        llm_timeout_seconds=_float_env("LLM_TIMEOUT_SECONDS", 120.0),
        telegram_bot_token=_clean(os.getenv("TELEGRAM_BOT_TOKEN")),
        telegram_chat_id=_clean(os.getenv("TELEGRAM_CHAT_ID")),
        digest_scheduler_enabled=_bool_env("DIGEST_SCHEDULER_ENABLED", False),
        digest_time=_clean(os.getenv("DIGEST_TIME")) or "07:00",
        digest_timezone=_clean(os.getenv("DIGEST_TIMEZONE")) or "UTC",
        digest_state_dir=_clean(os.getenv("DIGEST_STATE_DIR")),
        http_timeout_seconds=_float_env("HTTP_TIMEOUT_SECONDS", 30.0),
        log_level=_log_level_env("LOG_LEVEL", "INFO"),
    )


def configure_logging(settings: Optional[Settings] = None) -> None:
    """Wire up console logging per LOG_LEVEL.

    A no-op if the root logger already has handlers (e.g. a test harness, or a
    second call), matching ``logging.basicConfig``'s own behavior.
    """

    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def reset_settings_cache() -> None:
    """Test helper: drop the cached Settings so the next get_settings() re-reads env."""

    get_settings.cache_clear()
