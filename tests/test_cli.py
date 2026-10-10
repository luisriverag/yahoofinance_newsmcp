import pytest

from yahoofinance_newsmcp import cli
from yahoofinance_newsmcp.digest import DigestError


def test_main_list_watchlist(monkeypatch, capsys):
    from yahoofinance_newsmcp.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(watchlist_tickers=["AAPL", "MSFT"]))
    assert cli.main(["list-watchlist"]) == 0
    assert capsys.readouterr().out.strip().splitlines() == ["AAPL", "MSFT"]


def test_main_check_health_returncode(monkeypatch, tmp_path):
    from yahoofinance_newsmcp.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    assert cli.main(["check-health"]) == 1


def test_main_generate_dry_run(monkeypatch, capsys):
    from yahoofinance_newsmcp.config import Settings

    called = {}

    def fake_generate(settings, tickers=None):
        called["tickers"] = tickers
        from yahoofinance_newsmcp.digest import MorningDigest

        return MorningDigest(
            generated_at="2026-01-01T07:00:00+00:00",
            lookback_hours=24,
            overall_summary="Overall.",
            companies=[],
        )

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli, "generate_digest", fake_generate)
    monkeypatch.setattr(cli, "persist_digest", lambda digest, state_dir: [])

    assert cli.main(["generate", "--dry-run", "--ticker", "AAPL"]) == 0
    assert called["tickers"] == ["AAPL"]
    assert "Morning News Digest" in capsys.readouterr().out


def test_main_missing_command(monkeypatch, capsys):
    from yahoofinance_newsmcp.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    with pytest.raises(SystemExit):
        cli.main([])


def test_main_fetch_dry_run(monkeypatch, capsys):
    from datetime import datetime, timezone

    from yahoofinance_newsmcp.config import Settings
    from yahoofinance_newsmcp.yahoo import NewsArticle, YahooFinanceClient

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(watchlist_tickers=["AAPL"]))

    def fake_fetch_news(self, ticker, limit=None, lookback_hours=None):
        return [
            NewsArticle(
                ticker="AAPL",
                title="Apple ships something",
                link="https://example.com/1",
                publisher="Reuters",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        ]

    monkeypatch.setattr(YahooFinanceClient, "fetch_news", fake_fetch_news)
    monkeypatch.setattr(YahooFinanceClient, "enrich", lambda self, articles: list(articles))

    assert cli.main(["fetch"]) == 0
    out = capsys.readouterr().out
    assert "AAPL: Apple ships something" in out
    assert "https://example.com/1" in out


def test_main_fetch_json(monkeypatch, capsys):
    from yahoofinance_newsmcp.config import Settings
    from yahoofinance_newsmcp.yahoo import NewsArticle, YahooFinanceClient

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(watchlist_tickers=["AAPL"]))
    monkeypatch.setattr(
        YahooFinanceClient,
        "fetch_news",
        lambda self, ticker, limit=None, lookback_hours=None: [
            NewsArticle(ticker="AAPL", title="T", link="https://example.com/1")
        ],
    )
    monkeypatch.setattr(YahooFinanceClient, "enrich", lambda self, articles: list(articles))

    assert cli.main(["fetch", "--json"]) == 0
    assert '"title": "T"' in capsys.readouterr().out


def test_main_fetch_without_tickers(monkeypatch, capsys):
    from yahoofinance_newsmcp.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    assert cli.main(["fetch"]) == 1
    assert "No tickers configured" in capsys.readouterr().err