"""Digest orchestration: fetch -> summarize -> assemble -> render/persist.

`generate_digest` is the one function that ties the Yahoo client and the LLM
summarizer together. It is deliberately tolerant of a single ticker failing
(a fetch error yields an empty article list, not a crashed digest) while still
surfacing LLM misconfiguration, since without a working model there is no
digest to produce.

Rendering and persistence are pure/independent of the network so they can be
tested directly.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from .config import Settings, get_settings
from .summarize import summarize_articles, summarize_company, summarize_overall
from .yahoo import NewsArticle, YahooFinanceClient


class DigestError(RuntimeError):
    """Raised when a digest cannot be generated."""


@dataclass(frozen=True)
class ArticleDigest:
    title: str
    link: str
    publisher: str = ""
    published_at: Optional[str] = None
    summary: str = ""


@dataclass(frozen=True)
class CompanyDigest:
    ticker: str
    overall_summary: str
    articles: List[ArticleDigest] = field(default_factory=list)

    @property
    def article_count(self) -> int:
        return len(self.articles)


@dataclass(frozen=True)
class MorningDigest:
    generated_at: str
    lookback_hours: float
    overall_summary: str
    companies: List[CompanyDigest] = field(default_factory=list)

    @property
    def total_articles(self) -> int:
        return sum(company.article_count for company in self.companies)


def _article_digest(article: NewsArticle, summary: str) -> ArticleDigest:
    return ArticleDigest(
        title=article.title,
        link=article.link,
        publisher=article.publisher,
        published_at=article.published_at.isoformat() if article.published_at else None,
        summary=summary.strip() or article.snippet or article.title,
    )


def generate_digest(
    settings: Optional[Settings] = None,
    *,
    yahoo: Optional[YahooFinanceClient] = None,
    llm=None,
    tickers: Optional[Sequence[str]] = None,
    now: Optional[datetime] = None,
) -> MorningDigest:
    """Fetch and summarize news for every configured ticker into one digest."""

    settings = settings or get_settings()
    tickers = list(tickers) if tickers is not None else settings.resolved_tickers()
    if not tickers:
        raise DigestError("no tickers configured (set WATCHLIST_TICKERS and/or WATCHLIST_FILE)")

    if llm is None:
        from .llm import LlmClient

        llm = LlmClient(settings)
    owns_yahoo = yahoo is None
    yahoo = yahoo or YahooFinanceClient(settings)

    now = now or datetime.now(timezone.utc)
    companies: List[CompanyDigest] = []
    try:
        for ticker in tickers:
            articles = yahoo.enrich(yahoo.fetch_news(ticker))
            if not articles:
                companies.append(
                    CompanyDigest(ticker=ticker, overall_summary="No recent news.", articles=[])
                )
                continue

            summaries = summarize_articles(llm, ticker, articles)
            company_summary = summarize_company(llm, ticker, articles)
            article_digests = [
                _article_digest(article, summaries[index] if index < len(summaries) else "")
                for index, article in enumerate(articles)
            ]
            companies.append(
                CompanyDigest(
                    ticker=ticker,
                    overall_summary=company_summary,
                    articles=article_digests,
                )
            )

        overall = summarize_overall(
            llm, [(company.ticker, company.overall_summary) for company in companies]
        )
    finally:
        if owns_yahoo:
            yahoo.close()

    return MorningDigest(
        generated_at=now.isoformat(),
        lookback_hours=settings.news_lookback_hours,
        overall_summary=overall,
        companies=companies,
    )


def digest_to_dict(digest: MorningDigest) -> dict:
    return asdict(digest)


def render_json(digest: MorningDigest) -> str:
    return json.dumps(digest_to_dict(digest), indent=2, ensure_ascii=False)


def _format_published(published_at: Optional[str]) -> str:
    if not published_at:
        return "time unknown"
    return published_at.replace("+00:00", " UTC")


def render_markdown(digest: MorningDigest) -> str:
    """Human-readable morning briefing in Markdown."""

    lines: List[str] = [
        f"# Morning News Digest — {digest.generated_at}",
        "",
        f"_Covering {len(digest.companies)} ticker(s), last {digest.lookback_hours:g}h, "
        f"{digest.total_articles} article(s)._",
        "",
        "## Overall",
        "",
        digest.overall_summary or "No summary available.",
        "",
    ]

    for company in digest.companies:
        lines.append(f"## {company.ticker} ({company.article_count} article(s))")
        lines.append("")
        lines.append(company.overall_summary or "No summary available.")
        lines.append("")
        for article in company.articles:
            lines.append(f"- [{article.title}]({article.link})")
            lines.append(
                f"  - {article.publisher or 'unknown source'}, "
                f"{_format_published(article.published_at)}"
            )
            if article.summary:
                lines.append(f"  - {article.summary}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def persist_digest(digest: MorningDigest, state_dir: Optional[str] = None) -> List[str]:
    """Write latest and dated Markdown/JSON files; returns the paths written.

    Persistence is skipped (returning an empty list) when no state directory is
    configured.
    """

    state_dir = state_dir if state_dir is not None else get_settings().digest_state_dir
    if not state_dir:
        return []

    os.makedirs(state_dir, exist_ok=True)
    date = (digest.generated_at or datetime.now(timezone.utc).isoformat())[:10]
    markdown = render_markdown(digest)
    as_json = render_json(digest)

    written: List[str] = []
    for name, content in (
        ("latest.md", markdown),
        ("latest.json", as_json),
        (f"{date}.md", markdown),
        (f"{date}.json", as_json),
    ):
        path = os.path.join(state_dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        written.append(path)
    return written


def load_latest(state_dir: Optional[str] = None) -> Optional[MorningDigest]:
    """Load the persisted ``latest.json`` digest, if present."""

    state_dir = state_dir if state_dir is not None else get_settings().digest_state_dir
    if not state_dir:
        return None
    path = os.path.join(state_dir, "latest.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return _digest_from_dict(data)


def _digest_from_dict(data: dict) -> MorningDigest:
    companies = [
        CompanyDigest(
            ticker=company.get("ticker", ""),
            overall_summary=company.get("overall_summary", ""),
            articles=[
                ArticleDigest(
                    title=article.get("title", ""),
                    link=article.get("link", ""),
                    publisher=article.get("publisher", ""),
                    published_at=article.get("published_at"),
                    summary=article.get("summary", ""),
                )
                for article in company.get("articles", [])
            ],
        )
        for company in data.get("companies", [])
    ]
    return MorningDigest(
        generated_at=data.get("generated_at", ""),
        lookback_hours=float(data.get("lookback_hours", 0.0)),
        overall_summary=data.get("overall_summary", ""),
        companies=companies,
    )
