"""LLM summarization: per-article, per-company, and overall.

The three levels are deliberately separate prompts so each can be tested and
tuned independently:

* per-article: a one-to-two sentence neutral summary of each headline.
* per-company: a short paragraph synthesizing all of one ticker's articles.
* overall: a short paragraph synthesizing the company paragraphs into a
  watchlist-wide morning briefing.

Prompt *building* and response *parsing* are pure functions; only the
``summarize_*`` helpers touch the LLM client.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Sequence

from .cache import JsonCache, article_fingerprint
from .llm import LlmClient, parse_json_block
from .yahoo import NewsArticle

OVERALL_PROMPT = (
    "You are a financial-news editor writing a concise morning briefing. Be "
    "neutral and factual. Do not give investment advice or price predictions. "
    "If the news is thin or uneventful, say so plainly rather than inventing "
    "significance."
)


def _subject(ticker: str, company_name: str = "") -> str:
    """Reference a ticker in prompts, adding its display name when available."""

    name = (company_name or "").strip()
    if name and name.upper() != ticker.upper():
        return f"{ticker} ({name})"
    return ticker


def _article_context(article: NewsArticle) -> str:
    parts = [f"Title: {article.title}"]
    if article.publisher:
        parts.append(f"Publisher: {article.publisher}")
    if article.published_at:
        parts.append(f"Published: {article.published_at.isoformat()}")
    if article.body:
        parts.append(f"Article text: {article.body}")
    elif article.snippet:
        parts.append(f"Snippet: {article.snippet}")
    return "\n".join(parts)


def build_article_prompt(
    ticker: str, articles: Sequence[NewsArticle], company_name: str = ""
) -> List[Dict[str, str]]:
    """Prompt the model for one short summary per article, returned as JSON."""

    blocks = "\n\n".join(
        f"[{index + 1}] {_article_context(article)}" for index, article in enumerate(articles)
    )
    return [
        {"role": "system", "content": OVERALL_PROMPT},
        {
            "role": "user",
            "content": (
                f"Summarize each of the following {len(articles)} news item(s) about "
                f"{_subject(ticker, company_name)} in one or two sentences. Return a "
                "JSON array of strings, one summary per item, in the same order, "
                "with no extra text.\n\n" + blocks
            ),
        },
    ]


def parse_article_summaries(text: str, expected: int) -> List[str]:
    """Parse a JSON array of summaries, falling back to line splitting.

    Always returns exactly ``expected`` entries; missing ones become an empty
    string so the caller can fall back to the headline.
    """

    summaries: List[str] = []
    try:
        parsed = parse_json_block(text)
    except Exception:
        parsed = None

    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, str):
                summaries.append(item.strip())
            elif isinstance(item, dict):
                value = item.get("summary") or item.get("text") or item.get("content")
                summaries.append(str(value).strip() if value else "")
    else:
        summaries = _split_summary_lines(text)

    if len(summaries) < expected:
        summaries.extend([""] * (expected - len(summaries)))
    return summaries[:expected]


def _split_summary_lines(text: str) -> List[str]:
    lines: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*").strip()
        # Drop a leading "1." / "1)" / "[1]" enumeration if present.
        for prefix in ("[",):
            if line.startswith(prefix):
                closing = line.find("]")
                if closing != -1:
                    line = line[closing + 1 :].strip()
        if len(line) > 1 and line[0].isdigit():
            head, sep, rest = line.partition(". ")
            if sep and head.isdigit():
                line = rest.strip()
            else:
                head, sep, rest = line.partition(") ")
                if sep and head.isdigit():
                    line = rest.strip()
        if line:
            lines.append(line)
    return lines


def summarize_articles(
    llm: LlmClient,
    ticker: str,
    articles: Sequence[NewsArticle],
    company_name: str = "",
    cache: Optional[JsonCache] = None,
) -> List[str]:
    """Summarize every article for one ticker; one LLM call per *uncached*
    article (same call shape as before when nothing is cached). A cache hit
    is keyed on the article's link/title/body, so a changed or newly-fetched
    body is summarized fresh rather than served a stale cached summary.
    """

    if not articles:
        return []
    if cache is None:
        response = llm.chat(build_article_prompt(ticker, articles, company_name))
        return parse_article_summaries(response, expected=len(articles))

    fingerprints = [article_fingerprint(article) for article in articles]
    summaries: List[Optional[str]] = []
    missing_indices: List[int] = []
    for index, fingerprint in enumerate(fingerprints):
        entry = cache.get(f"article:{ticker}:{fingerprint}")
        summaries.append(entry.get("summary", "") if entry is not None else None)
        if entry is None:
            missing_indices.append(index)

    if missing_indices:
        missing_articles = [articles[index] for index in missing_indices]
        response = llm.chat(build_article_prompt(ticker, missing_articles, company_name))
        fresh = parse_article_summaries(response, expected=len(missing_articles))
        for index, summary in zip(missing_indices, fresh):
            summaries[index] = summary
            cache.set(f"article:{ticker}:{fingerprints[index]}", {"summary": summary})

    return [summary or "" for summary in summaries]


def build_company_prompt(
    ticker: str, articles: Sequence[NewsArticle], company_name: str = ""
) -> List[Dict[str, str]]:
    blocks = "\n\n".join(_article_context(article) for article in articles)
    return [
        {"role": "system", "content": OVERALL_PROMPT},
        {
            "role": "user",
            "content": (
                f"Write a single short paragraph (3-6 sentences) summarizing what "
                f"today's news collectively says about {_subject(ticker, company_name)}. "
                "Note the main themes and any clearly positive or negative tone, but "
                "do not give investment advice.\n\nNews items:\n\n" + blocks
            ),
        },
    ]


def _company_fingerprint(articles: Sequence[NewsArticle]) -> str:
    """Identity for one ticker's exact article set -- changes (a new article
    appeared, or one's fetched body changed) naturally miss the cache."""

    combined = "|".join(sorted(article_fingerprint(article) for article in articles))
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def summarize_company(
    llm: LlmClient,
    ticker: str,
    articles: Sequence[NewsArticle],
    company_name: str = "",
    cache: Optional[JsonCache] = None,
) -> str:
    if not articles:
        return "No recent news."
    if cache is None:
        return llm.chat(build_company_prompt(ticker, articles, company_name)).strip()

    key = f"company:{ticker}:{_company_fingerprint(articles)}"
    entry = cache.get(key)
    if entry is not None:
        return entry.get("summary", "")

    summary = llm.chat(build_company_prompt(ticker, articles, company_name)).strip()
    cache.set(key, {"summary": summary})
    return summary


def build_overall_prompt(
    company_summaries: Sequence[tuple[str, str]], tone: str = ""
) -> List[Dict[str, str]]:
    blocks = "\n\n".join(f"{ticker}: {summary}" for ticker, summary in company_summaries)
    tone_line = (
        f"\n\nTone/style: {tone.strip()}." if tone.strip() else ""
    )
    return [
        {"role": "system", "content": OVERALL_PROMPT},
        {
            "role": "user",
            "content": (
                "Below are per-company summaries of this morning's news for a "
                "watchlist. Write one short overall paragraph (3-6 sentences) "
                "highlighting the most important shared themes and any notable "
                "divergences across companies. Do not give investment advice."
                + tone_line
                + "\n\n"
                + blocks
            ),
        },
    ]


def summarize_overall(
    llm: LlmClient, company_summaries: Sequence[tuple[str, str]], tone: str = ""
) -> str:
    if not company_summaries:
        return "No companies were covered."
    return llm.chat(build_overall_prompt(company_summaries, tone)).strip()
