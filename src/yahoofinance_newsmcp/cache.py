"""Persistent on-disk cache for fetched article bodies and LLM summaries.

Without this, every call to generate_digest/summarize_ticker re-fetches each
article's full body and re-runs the summarization model from scratch, even
when called again moments later against the same watchlist -- wasteful
against publisher sites, and slow against the summarization model, which is
the dominant cost of a digest run and the part most likely to be a local,
single-request-at-a-time backend.

Stored as one JSON file per cache "kind" (article bodies, per-article
summaries, per-company summaries) under Settings.cache_dir, with entries
expiring after Settings.cache_ttl_hours. A cache is never load-bearing for
correctness -- a missing, corrupt, or unwritable cache file degrades to the
same "always fetch/summarize fresh" behavior as if caching were disabled,
never an error.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from .config import Settings
    from .yahoo import NewsArticle

logger = logging.getLogger("yahoofinance-newsmcp.cache")


class JsonCache:
    """A single JSON-file-backed string-key -> dict cache with a TTL.

    ``path=None`` makes every get() a miss and every save() a no-op, so
    callers can always construct and use a JsonCache without a None-check at
    every call site -- caching being disabled is just an empty, inert cache.
    """

    def __init__(self, path: Optional[str], ttl_seconds: float) -> None:
        self._path = path
        self._ttl = max(ttl_seconds, 0.0)
        self._data: Dict[str, dict] = self._load()
        self._dirty = False

    def _load(self) -> Dict[str, dict]:
        if not self._path or not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError) as exc:
            logger.warning("Could not read cache %s; starting empty: %s", self._path, exc)
            return {}
        return raw if isinstance(raw, dict) else {}

    def get(self, key: str) -> Optional[dict]:
        entry = self._data.get(key)
        if entry is None:
            return None
        cached_at = entry.get("_cached_at", 0)
        if time.time() - cached_at > self._ttl:
            return None
        return entry

    def set(self, key: str, value: dict) -> None:
        if not self._path:
            return
        self._data[key] = {**value, "_cached_at": time.time()}
        self._dirty = True

    def save(self) -> None:
        """Prune expired entries and write to disk, if anything changed.

        Safe to call even when nothing was ever set (a no-op) or when the
        directory can't be created/written (logs a warning, doesn't raise --
        a dropped cache write is never worse than caching being disabled).
        """

        if not self._path or not self._dirty:
            return
        now = time.time()
        self._data = {
            key: entry
            for key, entry in self._data.items()
            if now - entry.get("_cached_at", 0) <= self._ttl
        }
        try:
            directory = os.path.dirname(self._path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp_path = f"{self._path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle)
            os.replace(tmp_path, self._path)
        except OSError as exc:
            logger.warning("Could not write cache %s: %s", self._path, exc)
        else:
            self._dirty = False


def build_cache(settings: "Settings", name: str) -> JsonCache:
    """Build the named cache (e.g. "article_bodies", "summaries") for these
    settings. Returns an inert (always-miss) JsonCache when CACHE_DIR/
    DIGEST_STATE_DIR aren't configured, so callers never need a None-check.
    """

    path = os.path.join(settings.cache_dir, "cache", f"{name}.json") if settings.cache_dir else None
    return JsonCache(path, settings.cache_ttl_hours * 3600)


def article_fingerprint(article: "NewsArticle") -> str:
    """A short, stable identity for one article's cached content.

    Keyed on link/title plus whatever text was actually used to summarize it
    (body if fetched, else snippet) -- not just the link -- so a cached
    summary is invalidated automatically if the article's available text
    changes (e.g. a body successfully fetched on a later run where it
    previously failed), without any explicit invalidation logic.
    """

    basis = f"{article.link}|{article.title}|{article.body or article.snippet}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
