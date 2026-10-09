"""Yahoo Finance news fetching.

Two public Yahoo Finance sources are supported, in fallback order:

1. The Finance search JSON endpoint (``/v1/finance/search``) — richer metadata
   (uuid, publisher, timestamp) and the primary source.
2. The legacy RSS headline feed (``feeds.finance.yahoo.com/rss/2.0/headline``)
   — used when the search endpoint is unavailable or returns nothing.

Only the parsing/normalization helpers are pure and unit-testable; the client
itself takes an injectable ``httpx.Client`` so tests can drive it with a mock
transport and never touch the network.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, List, Optional
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .config import Settings, get_settings

logger = logging.getLogger("yahoofinance-newsmcp.yahoo")

USER_AGENT = (
    "Mozilla/5.0 (compatible; yahoofinance-newsmcp/0.1; +https://github.com/luisriverag/yahoofinance_newsmcp)"
)

_WHITESPACE_RE = re.compile(r"\s+")


class YahooError(RuntimeError):
    """Raised when Yahoo Finance news could not be fetched or parsed."""


@dataclass(frozen=True)
class NewsArticle:
    """One news item for one ticker, normalized across both sources."""

    ticker: str
    title: str
    link: str
    publisher: str = ""
    published_at: Optional[datetime] = None
    uuid: str = ""
    snippet: str = ""
    body: str = ""


def _as_utc(timestamp: Optional[float]) -> Optional[datetime]:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _parse_pub_date(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_search_payload(payload: Any, ticker: str) -> List[NewsArticle]:
    """Normalize a ``/v1/finance/search`` JSON payload into NewsArticle objects."""

    if not isinstance(payload, dict):
        raise YahooError("Yahoo search payload was not a JSON object")
    items = payload.get("news")
    if not isinstance(items, list):
        return []

    articles: List[NewsArticle] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        link = str(item.get("link") or "").strip()
        if not title or not link:
            continue
        articles.append(
            NewsArticle(
                ticker=ticker.upper(),
                title=title,
                link=link,
                publisher=str(item.get("publisher") or "").strip(),
                published_at=_as_utc(item.get("providerPublishTime")),
                uuid=str(item.get("uuid") or "").strip(),
                snippet=str(item.get("summary") or item.get("description") or "").strip(),
            )
        )
    return articles


def parse_rss_payload(xml_text: str, ticker: str) -> List[NewsArticle]:
    """Normalize a Yahoo RSS headline feed into NewsArticle objects."""

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise YahooError(f"Yahoo RSS feed was not valid XML: {exc}") from exc

    articles: List[NewsArticle] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        description = (item.findtext("description") or "").strip()
        articles.append(
            NewsArticle(
                ticker=ticker.upper(),
                title=title,
                link=link,
                publisher=(item.findtext("source") or "").strip(),
                published_at=_parse_pub_date(item.findtext("pubDate") or ""),
                uuid=(item.findtext("guid") or "").strip(),
                snippet=_html_to_text(description),
            )
        )
    return articles


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def parse_article_text(html: str) -> str:
    """Best-effort extraction of article body text from a full HTML page."""

    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # pragma: no cover - BeautifulSoup is very tolerant
        raise YahooError(f"Could not parse article HTML: {exc}") from exc

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    container = soup.find("article") or soup
    paragraphs = [
        _WHITESPACE_RE.sub(" ", para.get_text(" ")).strip()
        for para in container.find_all("p")
    ]
    body = "\n".join(para for para in paragraphs if len(para) > 40)
    return body.strip()


def filter_recent(
    articles: Iterable[NewsArticle],
    lookback_hours: float,
    now: Optional[datetime] = None,
) -> List[NewsArticle]:
    """Keep only articles published within ``lookback_hours`` of ``now``.

    Articles with no timestamp are kept (they are more useful than dropping
    them, and the caller requested them from Yahoo in the first place).
    """

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)
    kept: List[NewsArticle] = []
    for article in articles:
        if article.published_at is None or article.published_at >= cutoff:
            kept.append(article)
    return kept


def _article_key(article: NewsArticle) -> str:
    return article.link or article.uuid or article.title.lower()


def dedupe_articles(articles: Iterable[NewsArticle]) -> List[NewsArticle]:
    """Drop duplicate articles (same link/uuid/title), preserving order."""

    seen: set[str] = set()
    unique: List[NewsArticle] = []
    for article in articles:
        key = _article_key(article)
        if key and key not in seen:
            seen.add(key)
            unique.append(article)
    return unique


class YahooFinanceClient:
    """Small Yahoo Finance news client with an injectable HTTP client."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = http_client or httpx.Client(
            timeout=self._settings.http_timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            follow_redirects=True,
        )
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "YahooFinanceClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _search_url(self, ticker: str, limit: int) -> str:
        return f"{self._settings.yahoo_news_base_url}/v1/finance/search"

    def _rss_url(self, ticker: str) -> str:
        return self._settings.yahoo_rss_base_url

    def probe(self, ticker: str = "AAPL") -> int:
        """Reachability check: fetch the search endpoint and count items.

        Unlike ``fetch_news`` this raises ``YahooError`` on a network/HTTP
        failure so health checks can distinguish "reachable but no news" from
        "unreachable".
        """

        params = {"q": ticker, "newsCount": "1", "quotesCount": "0", "enableFuzzyQuery": "false"}
        try:
            response = self._client.get(self._search_url(ticker, 1), params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise YahooError(f"Yahoo Finance is unreachable: {exc}") from exc
        try:
            return len(parse_search_payload(response.json(), ticker))
        except (ValueError, YahooError) as exc:
            raise YahooError(f"Yahoo Finance returned an unusable payload: {exc}") from exc

    def fetch_news(
        self,
        ticker: str,
        limit: Optional[int] = None,
        lookback_hours: Optional[float] = None,
    ) -> List[NewsArticle]:
        """Return recent articles for one ticker, search first then RSS."""

        ticker = ticker.strip().upper()
        if not ticker:
            raise YahooError("ticker is required")

        settings = self._settings
        limit = limit if limit is not None else settings.news_per_ticker
        lookback = lookback_hours if lookback_hours is not None else settings.news_lookback_hours

        articles = self._fetch_search(ticker, limit)
        if not articles:
            articles = self._fetch_rss(ticker, limit)

        articles = filter_recent(articles, lookback)
        return dedupe_articles(articles)[:limit]

    def _fetch_search(self, ticker: str, limit: int) -> List[NewsArticle]:
        params = {
            "q": ticker,
            "newsCount": str(limit),
            "quotesCount": "0",
            "enableFuzzyQuery": "false",
        }
        try:
            response = self._client.get(self._search_url(ticker, limit), params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Yahoo search fetch failed for %s: %s", ticker, exc)
            return []
        try:
            return parse_search_payload(response.json(), ticker)
        except (ValueError, YahooError) as exc:
            logger.warning("Yahoo search payload for %s was unusable: %s", ticker, exc)
            return []

    def _fetch_rss(self, ticker: str, limit: int) -> List[NewsArticle]:
        params = {"s": ticker, "region": "US", "lang": "en-US"}
        try:
            response = self._client.get(self._rss_url(ticker), params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Yahoo RSS fetch failed for %s: %s", ticker, exc)
            return []
        try:
            return parse_rss_payload(response.text, ticker)
        except YahooError as exc:
            logger.warning("Yahoo RSS payload for %s was unusable: %s", ticker, exc)
            return []

    def fetch_article_text(self, article: NewsArticle) -> str:
        """Fetch and extract the body of a single article, best-effort."""

        try:
            response = self._client.get(article.link)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Article fetch failed for %s: %s", article.link, exc)
            return ""
        return parse_article_text(response.text)

    def enrich(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """Attach article body text to each item when configured, capped in length."""

        if not self._settings.news_fetch_article_text:
            return list(articles)

        cap = self._settings.news_max_article_chars
        enriched: List[NewsArticle] = []
        for article in articles:
            body = self.fetch_article_text(article) if article.link else ""
            if cap > 0 and len(body) > cap:
                body = body[:cap]
            enriched.append(replace(article, body=body))
        return enriched
