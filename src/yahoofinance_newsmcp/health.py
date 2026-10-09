"""One consolidated health check across every external dependency.

Reports each dependency separately so a degraded optional piece (Telegram
delivery, digest persistence) is visible without marking the whole service
unusable. Only the things needed to actually produce a digest — a watchlist,
a reachable Yahoo Finance, and a configured summarization model — gate the
top-level ``healthy`` value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from .config import Settings, get_settings
from .yahoo import YahooError, YahooFinanceClient

__all__ = ["HealthCheckItem", "HealthCheckReport", "check_health"]


@dataclass(frozen=True)
class HealthCheckItem:
    name: str
    ok: bool
    detail: str
    required: bool = True


@dataclass(frozen=True)
class HealthCheckReport:
    healthy: bool
    checks: List[HealthCheckItem]


def _check_watchlist(settings: Settings) -> HealthCheckItem:
    tickers = settings.resolved_tickers()
    if not tickers:
        return HealthCheckItem("watchlist", False, "No tickers configured (WATCHLIST_TICKERS/WATCHLIST_FILE).")
    return HealthCheckItem("watchlist", True, f"{len(tickers)} ticker(s): {', '.join(tickers)}.")


def _check_llm(settings: Settings) -> HealthCheckItem:
    if not settings.llm_chat_url:
        return HealthCheckItem("llm", False, "LLM_CHAT_URL is not configured.")
    if not settings.llm_model:
        return HealthCheckItem("llm", False, "LLM_MODEL is not configured.")
    return HealthCheckItem("llm", True, f"Configured ({settings.llm_model} at {settings.llm_chat_url}).")


def _check_yahoo(settings: Settings) -> HealthCheckItem:
    tickers = settings.resolved_tickers()
    probe_ticker = tickers[0] if tickers else "AAPL"
    client = YahooFinanceClient(settings)
    try:
        count = client.probe(probe_ticker)
    except YahooError as exc:
        return HealthCheckItem("yahoo", False, str(exc))
    finally:
        client.close()
    return HealthCheckItem("yahoo", True, f"Reachable (probe {probe_ticker}: {count} item(s)).")


def _check_telegram(settings: Settings) -> HealthCheckItem:
    if not settings.telegram_bot_token:
        return HealthCheckItem("telegram", True, "Not configured (optional delivery).", required=False)
    if not settings.telegram_chat_id:
        return HealthCheckItem(
            "telegram", False, "TELEGRAM_BOT_TOKEN is set but TELEGRAM_CHAT_ID is not."
        )
    return HealthCheckItem("telegram", True, "Token and chat id configured.", required=False)


def _check_persistence(settings: Settings) -> HealthCheckItem:
    if not settings.digest_state_dir:
        return HealthCheckItem(
            "persistence", True, "Not configured (digests are not saved to disk).", required=False
        )
    path = os.path.expanduser(settings.digest_state_dir)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        return HealthCheckItem("persistence", False, f"{path} is not creatable: {exc}")
    if not os.access(path, os.W_OK):
        return HealthCheckItem("persistence", False, f"{path} is not writable.")
    return HealthCheckItem("persistence", True, f"{path} is writable.", required=False)


def check_health(settings: Optional[Settings] = None) -> HealthCheckReport:
    """Run every check in one pass."""

    settings = settings or get_settings()
    checks = [
        _check_watchlist(settings),
        _check_llm(settings),
        _check_yahoo(settings),
        _check_telegram(settings),
        _check_persistence(settings),
    ]
    healthy = all(check.ok for check in checks if check.required)
    return HealthCheckReport(healthy=healthy, checks=checks)
