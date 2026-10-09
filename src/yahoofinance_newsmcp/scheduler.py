"""Built-in morning scheduler.

A tiny dependency-free daily scheduler: a daemon thread sleeps until the next
occurrence of a configured ``HH:MM`` in a configured timezone, runs the digest
callback, then recomputes the next day's run. This is intentionally simpler
than pulling in APScheduler — one daily job needs no cron expression engine.

The next-run calculation is a pure function so it can be tested with fixed
datetimes. The scheduler only runs when the server runs as an always-on HTTP
service; a stdio subprocess is spawned per client request and never schedules.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("yahoofinance-newsmcp.scheduler")


def parse_hhmm(raw: str) -> time:
    """Parse ``HH:MM`` (24-hour) into a ``datetime.time``; raises ValueError."""

    text = (raw or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"DIGEST_TIME must be HH:MM (24-hour), got {raw!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"DIGEST_TIME out of range: {raw!r}")
    return time(hour=hour, minute=minute)


def resolve_timezone(name: str) -> ZoneInfo:
    """Resolve an IANA timezone name, falling back to UTC with a warning."""

    try:
        return ZoneInfo((name or "UTC").strip() or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown DIGEST_TIMEZONE=%r; falling back to UTC.", name)
        return ZoneInfo("UTC")


def next_run_after(now: datetime, at: time) -> datetime:
    """The next strictly-future occurrence of ``at`` at or after ``now``.

    ``now`` may be naive or aware; the result keeps the same tzinfo. The result
    is strictly greater than ``now`` so a sleep is always positive.
    """

    candidate = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


class MorningScheduler:
    """Runs ``callback`` once per day at the configured local time."""

    def __init__(
        self,
        digest_time: str,
        timezone_name: str,
        callback: Callable[[], None],
    ) -> None:
        self._at = parse_hhmm(digest_time)
        self._tz = resolve_timezone(timezone_name)
        self._callback = callback
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def digest_time(self) -> time:
        return self._at

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    def next_run(self, now: Optional[datetime] = None) -> datetime:
        return next_run_after(now or datetime.now(self._tz), self._at)

    def run_once(self) -> None:
        """Invoke the callback now; exceptions are logged, never propagated."""

        try:
            self._callback()
        except Exception:  # noqa: BLE001 - a failed run must not kill the scheduler
            logger.exception("Morning digest run failed")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="morning-scheduler", daemon=True)
        self._thread.start()
        logger.info(
            "Morning scheduler started: daily at %s %s",
            self._at.strftime("%H:%M"),
            self._tz.key,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            wait_seconds = (self.next_run() - datetime.now(self._tz)).total_seconds()
            if wait_seconds < 0:
                wait_seconds = 0
            if self._stop.wait(wait_seconds):
                break
            if self._stop.is_set():
                break
            self.run_once()
