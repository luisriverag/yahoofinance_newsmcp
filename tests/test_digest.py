import pytest

from yahoofinance_newsmcp.cache import JsonCache
from yahoofinance_newsmcp.config import Settings
from yahoofinance_newsmcp.digest import (
    DigestError,
    MorningDigest,
    generate_digest,
    load_latest,
    persist_digest,
    render_json,
    render_markdown,
)
from yahoofinance_newsmcp.yahoo import NewsArticle


class FakeYahoo:
    def __init__(self, articles):
        self._articles = articles
        self.closed = False

    def fetch_news(self, ticker, limit=None, lookback_hours=None):
        return [a for a in self._articles if a.ticker == ticker]

    def enrich(self, articles):
        return list(articles)

    def close(self):
        self.closed = True


class FakeLLM:
    def chat(self, messages):
        content = messages[-1]["content"]
        if "JSON array" in content:
            return '["article one summary", "article two summary", "article three summary"]'
        if "today's news collectively" in content:
            return "Company paragraph."
        if "shared themes" in content:
            return "Overall paragraph."
        return "fallback"


def _articles():
    return [
        NewsArticle(ticker="AAPL", title="Apple news", link="https://a/1", publisher="Reuters", body="long body a"),
        NewsArticle(ticker="AAPL", title="Apple wow", link="https://a/2", publisher="Bloomberg"),
        NewsArticle(ticker="MSFT", title="Microsoft news", link="https://m/1", publisher="Reuters"),
    ]


def test_generate_digest_end_to_end():
    settings = Settings(watchlist_tickers=["AAPL", "MSFT"], news_fetch_article_text=False)
    digest = generate_digest(
        settings, yahoo=FakeYahoo(_articles()), llm=FakeLLM(), tickers=["AAPL", "MSFT"]
    )

    assert digest.lookback_hours == 24
    assert [c.ticker for c in digest.companies] == ["AAPL", "MSFT"]
    aapl = digest.companies[0]
    assert aapl.article_count == 2
    assert aapl.overall_summary == "Company paragraph."
    assert aapl.articles[0].summary == "article one summary"
    assert digest.overall_summary == "Overall paragraph."
    assert digest.total_articles == 3


class RecordingLLM:
    def __init__(self, reply="Recorded."):
        self.reply = reply
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages[-1]["content"])
        return self.reply

    def close(self):
        pass


def test_generate_digest_uses_injected_overall_llm():
    settings = Settings(watchlist_tickers=["AAPL"], news_fetch_article_text=False)
    overall = RecordingLLM("Overall via second backend.")
    digest = generate_digest(
        settings,
        yahoo=FakeYahoo(_articles()),
        llm=FakeLLM(),
        llm_overall=overall,
        tickers=["AAPL"],
    )
    assert digest.overall_summary == "Overall via second backend."
    assert any("shared themes" in call for call in overall.calls)


def test_generate_digest_applies_tone_to_overall():
    settings = Settings(
        watchlist_tickers=["AAPL"],
        news_fetch_article_text=False,
        digest_tone="brisk and plain-spoken",
    )
    overall = RecordingLLM()
    generate_digest(
        settings,
        yahoo=FakeYahoo(_articles()),
        llm=FakeLLM(),
        llm_overall=overall,
        tickers=["AAPL"],
    )
    assert any("brisk and plain-spoken" in call for call in overall.calls)


def test_generate_digest_reuses_summary_cache_across_calls(tmp_path):
    """A second generate_digest call against the same unchanged watchlist
    should skip the summarization model entirely (both per-article and
    per-company calls), the whole point of passing a persistent cache."""

    settings = Settings(watchlist_tickers=["AAPL"], news_fetch_article_text=False)
    llm = RecordingLLM('["s1", "s2"]')
    cache = JsonCache(str(tmp_path / "summaries.json"), ttl_seconds=3600)

    generate_digest(
        settings,
        yahoo=FakeYahoo(_articles()),
        llm=llm,
        llm_overall=RecordingLLM("Overall."),
        tickers=["AAPL"],
        summary_cache=cache,
    )
    calls_after_first_run = len(llm.calls)
    assert calls_after_first_run > 0

    generate_digest(
        settings,
        yahoo=FakeYahoo(_articles()),
        llm=llm,
        llm_overall=RecordingLLM("Overall."),
        tickers=["AAPL"],
        summary_cache=cache,
    )

    assert len(llm.calls) == calls_after_first_run


def test_generate_digest_handles_ticker_with_no_news():
    settings = Settings(watchlist_tickers=["AAPL"], news_fetch_article_text=False)
    digest = generate_digest(settings, yahoo=FakeYahoo([]), llm=FakeLLM(), tickers=["AAPL"])
    assert digest.companies[0].overall_summary == "No recent news."
    assert digest.companies[0].article_count == 0


def test_generate_digest_requires_tickers():
    settings = Settings(watchlist_tickers=[], news_fetch_article_text=False)
    with pytest.raises(DigestError, match="tickers"):
        generate_digest(settings, yahoo=FakeYahoo([]), llm=FakeLLM(), tickers=[])


def test_render_markdown_contains_sections():
    digest = _sample_digest()
    md = render_markdown(digest)
    assert "# Morning News Digest" in md
    assert "## Overall" in md
    assert "## AAPL (2 article(s))" in md
    assert "Apple news" in md
    assert "https://a/1" in md


def test_generate_digest_includes_company_name():
    settings = Settings(
        watchlist_tickers=["AAPL"],
        company_names={"AAPL": "Apple Inc."},
        news_fetch_article_text=False,
    )
    digest = generate_digest(settings, yahoo=FakeYahoo(_articles()), llm=FakeLLM(), tickers=["AAPL"])
    aapl = digest.companies[0]
    assert aapl.name == "Apple Inc."
    assert aapl.display_name == "Apple Inc."
    assert "## AAPL — Apple Inc. (2 article(s))" in render_markdown(digest)


def test_render_markdown_company_name_round_trips(tmp_path):
    from yahoofinance_newsmcp.digest import ArticleDigest, CompanyDigest

    digest = MorningDigest(
        generated_at="2026-01-01T07:00:00+00:00",
        lookback_hours=24,
        overall_summary="Overall paragraph.",
        companies=[
            CompanyDigest(
                ticker="AAPL",
                name="Apple Inc.",
                overall_summary="Company paragraph.",
                articles=[ArticleDigest(title="Apple news", link="https://a/1")],
            )
        ],
    )
    persist_digest(digest, str(tmp_path))
    loaded = load_latest(str(tmp_path))
    assert loaded is not None
    assert loaded.companies[0].name == "Apple Inc."


def test_render_json_round_trips_via_load_latest(tmp_path):
    digest = _sample_digest()
    paths = persist_digest(digest, str(tmp_path))
    assert len(paths) == 4
    loaded = load_latest(str(tmp_path))
    assert loaded is not None
    assert loaded.overall_summary == "Overall paragraph."
    assert loaded.companies[0].overall_summary == "Company paragraph."
    assert loaded.companies[0].articles[0].title == "Apple news"
    json_text = render_json(digest)
    assert "overall_summary" in json_text


def test_persist_returns_empty_without_state_dir():
    assert persist_digest(_sample_digest(), None) == []


def test_load_latest_returns_none_when_missing(tmp_path):
    assert load_latest(str(tmp_path)) is None


def _sample_digest():
    from yahoofinance_newsmcp.digest import ArticleDigest, CompanyDigest

    return MorningDigest(
        generated_at="2026-01-01T07:00:00+00:00",
        lookback_hours=24,
        overall_summary="Overall paragraph.",
        companies=[
            CompanyDigest(
                ticker="AAPL",
                overall_summary="Company paragraph.",
                articles=[
                    ArticleDigest(title="Apple news", link="https://a/1", publisher="Reuters", summary="s1"),
                    ArticleDigest(title="Apple wow", link="https://a/2", publisher="Bloomberg", summary="s2"),
                ],
            ),
            CompanyDigest(ticker="MSFT", overall_summary="No recent news.", articles=[]),
        ],
    )