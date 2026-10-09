from datetime import datetime, timedelta, timezone

import httpx
import pytest

from yahoofinance_newsmcp.config import Settings
from yahoofinance_newsmcp.yahoo import (
    NewsArticle,
    YahooError,
    YahooFinanceClient,
    dedupe_articles,
    filter_recent,
    parse_article_text,
    parse_rss_payload,
    parse_search_payload,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _search_payload(published=None):
    timestamp = NOW.timestamp() if published is None else published
    return {
        "news": [
            {
                "uuid": "u1",
                "title": "Headline",
                "publisher": "Reuters",
                "link": "https://example.com/1",
                "providerPublishTime": timestamp,
                "summary": "A recent summary.",
            },
            {"uuid": "u2", "title": "", "link": ""},
        ]
    }


def test_parse_search_payload_normalizes():
    articles = parse_search_payload(_search_payload(), "aapl")
    assert len(articles) == 1
    article = articles[0]
    assert article.ticker == "AAPL"
    assert article.title == "Headline"
    assert article.published_at == NOW
    assert article.uuid == "u1"


def test_parse_search_payload_non_object_raises():
    with pytest.raises(YahooError):
        parse_search_payload([], "AAPL")


def _rss(pub_date="Wed, 01 Jan 2026 12:00:00 +0000"):
    return (
        '<?xml version="1.0"?>\n'
        '<rss version="2.0"><channel><title>T</title>\n'
        "<item>\n"
        "  <title>MSFT cloud growth</title>\n"
        "  <link>https://example.com/msft1</link>\n"
        f"  <pubDate>{pub_date}</pubDate>\n"
        "  <description>&lt;p&gt;Winning &amp;amp; growing.&lt;/p&gt;</description>\n"
        "  <guid>msft-guid</guid>\n"
        "  <source>Bloomberg</source>\n"
        "</item>\n"
        "</channel></rss>"
    )


RSS = _rss()


def test_parse_rss_payload():
    articles = parse_rss_payload(RSS, "msft")
    assert len(articles) == 1
    article = articles[0]
    assert article.ticker == "MSFT"
    assert article.title == "MSFT cloud growth"
    assert article.published_at == NOW
    assert "Winning & growing." in article.snippet
    assert article.publisher == "Bloomberg"


def test_parse_rss_payload_invalid_xml_raises():
    with pytest.raises(YahooError):
        parse_rss_payload("<rss><unclosed>", "AAPL")


def test_parse_article_text_extracts_paragraphs():
    html = (
        "<html><body><article>"
        "<h1>Headline</h1>"
        "<p>First real paragraph with enough words to be worth keeping around here.</p>"
        "<script>var x = 1;</script>"
        "<p>Short.</p>"
        "<p>Second real paragraph, definitely long enough to survive the filter honestly.</p>"
        "</article></body></html>"
    )
    body = parse_article_text(html)
    assert "First real paragraph" in body
    assert "Second real paragraph" in body
    assert "var x" not in body
    assert "Short." not in body


def test_filter_recent_keeps_recent_and_dateless():
    old = _article("old", NOW - timedelta(hours=48))
    fresh = _article("fresh", NOW - timedelta(hours=2))
    dateless = _article("dateless", None)
    kept = filter_recent([old, fresh, dateless], lookback_hours=24, now=NOW)
    assert [a.title for a in kept] == ["fresh", "dateless"]


def test_dedupe_articles_by_link():
    a = _article("same", NOW, link="https://example.com/x")
    b = _article("same", NOW, link="https://example.com/x")
    c = _article("other", NOW, link="https://example.com/y")
    assert [x.title for x in dedupe_articles([a, b, c])] == ["same", "other"]


def _article(title, published_at, link="https://example.com/a"):
    return NewsArticle(ticker="AAPL", title=title, link=link, published_at=published_at)


class TestClient:
    def test_fetch_news_uses_search(self):
        recent = datetime.now(timezone.utc).timestamp()

        def handler(request):
            assert "search" in str(request.url)
            return httpx.Response(200, json=_search_payload(published=recent))

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = YahooFinanceClient(Settings(), http_client=http)
            articles = client.fetch_news("aapl", limit=5, lookback_hours=24)
        assert len(articles) == 1
        assert articles[0].ticker == "AAPL"

    def test_fetch_news_falls_back_to_rss(self):
        from email.utils import format_datetime

        recent_date = format_datetime(datetime.now(timezone.utc))

        def handler(request):
            if "search" in str(request.url):
                return httpx.Response(200, json={"news": []})
            return httpx.Response(200, text=_rss(recent_date))

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = YahooFinanceClient(Settings(), http_client=http)
            articles = client.fetch_news("msft", limit=5, lookback_hours=24)
        assert articles[0].title == "MSFT cloud growth"

    def test_fetch_news_returns_empty_on_network_error(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = YahooFinanceClient(Settings(), http_client=http)
            assert client.fetch_news("aapl") == []

    def test_enrich_attaches_truncated_body(self):
        settings = Settings(news_fetch_article_text=True, news_max_article_chars=40)

        def handler(request):
            return httpx.Response(200, text="<html><body><p>" + "x" * 100 + "</p></body></html>")

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = YahooFinanceClient(settings, http_client=http)
            enriched = client.enrich([_article("t", NOW)])
        assert len(enriched[0].body) <= 40

    def test_probe_raises_on_network_error(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = YahooFinanceClient(Settings(), http_client=http)
            with pytest.raises(YahooError):
                client.probe("AAPL")

    def test_fetch_news_requires_ticker(self):
        with httpx.Client() as http:
            client = YahooFinanceClient(Settings(), http_client=http)
            with pytest.raises(YahooError):
                client.fetch_news("  ")