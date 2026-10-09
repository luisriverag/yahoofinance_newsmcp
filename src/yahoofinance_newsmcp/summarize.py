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

from typing import Dict, List, Sequence

from .llm import LlmClient, parse_json_block
from .yahoo import NewsArticle

OVERALL_PROMPT = (
    "You are a financial-news editor writing a concise morning briefing. Be "
    "neutral and factual. Do not give investment advice or price predictions. "
    "If the news is thin or uneventful, say so plainly rather than inventing "
    "significance."
)


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


def build_article_prompt(ticker: str, articles: Sequence[NewsArticle]) -> List[Dict[str, str]]:
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
                f"{ticker} in one or two sentences. Return a JSON array of "
                "strings, one summary per item, in the same order, with no extra "
                "text.\n\n" + blocks
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


def summarize_articles(llm: LlmClient, ticker: str, articles: Sequence[NewsArticle]) -> List[str]:
    """Summarize every article for one ticker; one LLM call, ordered output."""

    if not articles:
        return []
    response = llm.chat(build_article_prompt(ticker, articles))
    return parse_article_summaries(response, expected=len(articles))


def build_company_prompt(ticker: str, articles: Sequence[NewsArticle]) -> List[Dict[str, str]]:
    blocks = "\n\n".join(_article_context(article) for article in articles)
    return [
        {"role": "system", "content": OVERALL_PROMPT},
        {
            "role": "user",
            "content": (
                f"Write a single short paragraph (3-6 sentences) summarizing what "
                f"today's news collectively says about {ticker}. Note the main "
                "themes and any clearly positive or negative tone, but do not "
                "give investment advice.\n\nNews items:\n\n" + blocks
            ),
        },
    ]


def summarize_company(llm: LlmClient, ticker: str, articles: Sequence[NewsArticle]) -> str:
    if not articles:
        return "No recent news."
    return llm.chat(build_company_prompt(ticker, articles)).strip()


def build_overall_prompt(company_summaries: Sequence[tuple[str, str]]) -> List[Dict[str, str]]:
    blocks = "\n\n".join(f"{ticker}: {summary}" for ticker, summary in company_summaries)
    return [
        {"role": "system", "content": OVERALL_PROMPT},
        {
            "role": "user",
            "content": (
                "Below are per-company summaries of this morning's news for a "
                "watchlist. Write one short overall paragraph (3-6 sentences) "
                "highlighting the most important shared themes and any notable "
                "divergences across companies. Do not give investment advice.\n\n"
                + blocks
            ),
        },
    ]


def summarize_overall(llm: LlmClient, company_summaries: Sequence[tuple[str, str]]) -> str:
    if not company_summaries:
        return "No companies were covered."
    return llm.chat(build_overall_prompt(company_summaries)).strip()
