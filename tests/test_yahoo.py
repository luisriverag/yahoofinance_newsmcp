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


def test_parse_article_text_drops_ad_and_sponsor_chrome():
    html = (
        "<html><body><article>"
        '<div class="ad-container"><p>Buy this product now, it is truly amazing and cheap.</p></div>'
        '<div class="sponsored-content"><p>Sponsored story that should not show up in the body.</p></div>'
        "<p>A genuine paragraph that is long enough to be kept in the extracted body.</p>"
        "</article></body></html>"
    )
    body = parse_article_text(html)
    assert "A genuine paragraph" in body
    assert "Buy this product" not in body
    assert "Sponsored story" not in body


def test_parse_article_text_drops_boilerplate_paragraphs():
    html = (
        "<html><body><article>"
        "<p>Read more: the full story continues on our website after this point.</p>"
        "<p>Subscribe to our newsletter for daily updates delivered to your inbox.</p>"
        "<p>Actual reporting content that is clearly long enough to be kept here.</p>"
        "</article></body></html>"
    )
    body = parse_article_text(html)
    assert "Actual reporting content" in body
    assert "Read more" not in body
    assert "Subscribe to our newsletter" not in body


def test_parse_article_text_keeps_word_containing_ad():
    html = (
        "<html><body><article>"
        "<p>The newly adapted strategy was rolled out across the whole company.</p>"
        "</article></body></html>"
    )
    body = parse_article_text(html)
    assert "newly adapted strategy" in body


def test_parse_article_text_keeps_hyphenated_component():
    html = (
        "<html><body><article>"
        '<div class="market-share"><p>Our market share grew enough to be a real paragraph here.</p></div>'
        '<div class="commentary"><p>Expert commentary that is long enough to be kept in the body.</p></div>'
        "</article></body></html>"
    )
    body = parse_article_text(html)
    assert "market share grew" in body
    assert "Expert commentary" in body


def test_parse_article_text_prefers_main_container():
    html = (
        "<html><body>"
        '<div id="sidebar"><p>Sidebar text that is long enough but should be removed entirely.</p></div>'
        "<main><p>Main content paragraph long enough to be considered real article text.</p></main>"
        "</body></html>"
    )
    body = parse_article_text(html)
    assert "Main content paragraph" in body
    assert "Sidebar text" not in body


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

    def test_fetch_article_text_memoizes_per_url(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(
                200,
                text="<html><body><article><p>Body text that is long enough to be kept here in full.</p></article></body></html>",
                headers={"ETag": "v1"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = YahooFinanceClient(Settings(), http_client=http)
            article = _article("t", NOW)
            first = client.fetch_article_text(article)
            second = client.fetch_article_text(article)
        assert "Body text" in first
        assert second == first
        assert calls["n"] == 1

    def test_fetch_article_text_uses_etag_and_handles_304(self):
        seen = []

        def handler(request):
            seen.append(request.headers.get("if-none-match"))
            if request.headers.get("if-none-match"):
                return httpx.Response(304)
            return httpx.Response(
                200,
                text="<html><body><article><p>Cached body text that is long enough to survive here.</p></article></body></html>",
                headers={"ETag": "abc"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = YahooFinanceClient(Settings(), http_client=http)
            article = _article("t", NOW)
            first = client.fetch_article_text(article)
            second = client.fetch_article_text(article, refresh=True)
        assert "Cached body text" in first
        assert second == first
        assert seen[0] is None
        assert seen[1] == "abc"

    def test_fetch_article_text_returns_cached_on_error(self):
        state = {"fail": False}

        def handler(request):
            if state["fail"]:
                raise httpx.ConnectError("boom")
            return httpx.Response(
                200,
                text="<html><body><article><p>Good body text that is long enough to keep here in full.</p></article></body></html>",
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = YahooFinanceClient(Settings(), http_client=http)
            article = _article("t", NOW)
            good = client.fetch_article_text(article)
            state["fail"] = True
            assert client.fetch_article_text(article, refresh=True) == good

    def test_fetch_article_text_persists_body_across_client_instances(self, tmp_path):
        settings = Settings(cache_dir=str(tmp_path), cache_ttl_hours=1)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(
                200,
                text="<html><body><article><p>Persisted body text that is long enough to be kept here.</p></article></body></html>",
            )

        article = _article("t", NOW)
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            first_client = YahooFinanceClient(settings, http_client=http)
            first = first_client.fetch_article_text(article)
            first_client.close()

        # A fresh client instance (as a separate process/run would construct)
        # reuses the persisted body instead of hitting the network again.
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            second_client = YahooFinanceClient(settings, http_client=http)
            second = second_client.fetch_article_text(article)

        assert second == first
        assert calls["n"] == 1

    def test_fetch_article_text_refresh_bypasses_persisted_body(self, tmp_path):
        settings = Settings(cache_dir=str(tmp_path), cache_ttl_hours=1)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(
                200,
                text="<html><body><article><p>Fresh body text that is long enough to be kept here.</p></article></body></html>",
            )

        article = _article("t", NOW)
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            first_client = YahooFinanceClient(settings, http_client=http)
            first_client.fetch_article_text(article)
            first_client.close()

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            second_client = YahooFinanceClient(settings, http_client=http)
            second_client.fetch_article_text(article, refresh=True)

        assert calls["n"] == 2