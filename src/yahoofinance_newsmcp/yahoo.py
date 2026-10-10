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
from typing import Any, Dict, Iterable, List, Optional
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


_BOILERPLATE_TAGS = (
    "script",
    "style",
    "noscript",
    "header",
    "footer",
    "nav",
    "aside",
    "form",
    "iframe",
    "svg",
    "button",
)

_BOILERPLATE_COMPONENTS = {
    "ad",
    "ads",
    "advert",
    "adverts",
    "advertisement",
    "advertising",
    "sponsor",
    "sponsored",
    "sponsorship",
    "promo",
    "promotion",
    "teaser",
    "newsletter",
    "subscribe",
    "subscription",
    "cookie",
    "cookies",
    "consent",
    "gdpr",
    "banner",
    "widget",
    "sidebar",
    "masthead",
    "breadcrumb",
    "pagination",
    "pager",
    "nav",
    "navigation",
    "menu",
    "footer",
    "header",
    "modal",
    "overlay",
    "popup",
    "paywall",
    "trending",
    "social",
    "sharethis",
    "sharing",
    "comments",
    "comment",
    "related",
    "recirc",
    "recommended",
    "recommendations",
}

_COMPONENT_SPLIT_RE = re.compile(r"[^a-z0-9]+")

_BOILERPLATE_PARAGRAPH_RE = re.compile(
    r"("
    r"read more"
    r"|sign up"
    r"|subscribe"
    r"|advertisement"
    r"|follow us"
    r"|download the .*app"
    r"|click here"
    r"|we use cookies"
    r"|accept cookies"
    r"|all rights reserved"
    r"|terms of (service|use)"
    r"|privacy policy"
    r"|cookie policy"
    r"|share this article"
    r"|this article (was|has been)"
    r")",
    re.IGNORECASE,
)


def _is_boilerplate_element(tag: Any) -> bool:
    """Heuristic: does this element's class/id/marker look like page chrome?

    Component matching (split on any non-alphanumeric run) means tokens like
    ``ad``/``sponsor``/``sidebar`` are caught without false positives such as
    ``market-share`` or ``commentary``.
    """

    values: List[str] = []
    for attr in ("class", "id", "data-testid", "role", "aria-label"):
        value = tag.get(attr)
        if isinstance(value, (list, tuple)):
            values.extend(str(part) for part in value)
        elif value:
            values.append(str(value))
    haystack = " ".join(values).lower()
    if not haystack:
        return False
    return any(
        component in _BOILERPLATE_COMPONENTS
        for component in _COMPONENT_SPLIT_RE.split(haystack)
        if component
    )


def _is_boilerplate_paragraph(text: str) -> bool:
    return bool(_BOILERPLATE_PARAGRAPH_RE.search(text))


def parse_article_text(html: str) -> str:
    """Best-effort extraction of article body text from a full HTML page.

    Strips scripts/styles/navigation and common ad/sponsorship/cookie chrome,
    prefers an ``<article>``/``<main>`` container when present, and drops
    paragraphs that are too short or look like boilerplate ("read more",
    "subscribe", etc.). Never raises for malformed markup.
    """

    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # pragma: no cover - BeautifulSoup is very tolerant
        raise YahooError(f"Could not parse article HTML: {exc}") from exc

    for tag in soup(_BOILERPLATE_TAGS):
        tag.decompose()

    for tag in soup.find_all(_is_boilerplate_element):
        if tag is not None and hasattr(tag, "decompose"):
            tag.decompose()

    container = soup.find("article") or soup.find("main") or soup
    paragraphs: List[str] = []
    for para in container.find_all("p"):
        text = _WHITESPACE_RE.sub(" ", para.get_text(" ")).strip()
        if len(text) <= 40:
            continue
        if _is_boilerplate_paragraph(text):
            continue
        paragraphs.append(text)
    return "\n".join(paragraphs).strip()


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
        # Per-run memo of article bodies (keyed by URL) plus the ETag observed
        # for each so a repeat fetch can send If-None-Match and reuse the body
        # on a 304.
        self._body_cache: Dict[str, str] = {}
        self._etags: Dict[str, str] = {}

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

    def fetch_article_text(self, article: NewsArticle, *, refresh: bool = False) -> str:
        """Fetch and extract the body of a single article, best-effort.

        Bodies are memoized per URL for the life of this client (i.e. one
        digest run), so a repeated call — a retry, or the same link seen under
        two tickers — never refetches. Pass ``refresh=True`` to revalidate
        instead: if an ETag was seen, the request is conditional and a ``304
        Not Modified`` reuses the cached body.
        """

        url = article.link
        if not url:
            return ""
        cached = self._body_cache.get(url)
        if cached is not None and not refresh:
            return cached

        etag = self._etags.get(url)
        headers = {"If-None-Match": etag} if (refresh and etag) else None
        try:
            response = self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("Article fetch failed for %s: %s", url, exc)
            return cached or ""

        if response.status_code == 304:
            return cached or ""

        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Article fetch returned an error for %s: %s", url, exc)
            return cached or ""

        body = parse_article_text(response.text)
        self._body_cache[url] = body
        new_etag = response.headers.get("etag")
        if new_etag:
            self._etags[url] = new_etag.strip('"')
        return body

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
