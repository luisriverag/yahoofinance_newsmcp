from yahoofinance_newsmcp.config import (
    Settings,
    _dedupe,
    get_settings,
    parse_tickers,
    parse_watchlist_text,
)


def test_parse_tickers_normalizes_and_dedupes():
    assert parse_tickers(" aapl , MSFT,aapl, ") == ["AAPL", "MSFT"]


def test_parse_tickers_empty():
    assert parse_tickers("") == []
    assert parse_tickers(" ,,, ") == []


def test_parse_watchlist_text_ignores_comments_and_blanks():
    text = "# my watchlist\n\n AAPL \nabc\n# comment\nabc\n\nMSFT\n"
    assert parse_watchlist_text(text) == ["AAPL", "ABC", "MSFT"]


def test_resolved_tickers_merges_env_and_file(tmp_path, monkeypatch):
    watch = tmp_path / "watch.txt"
    watch.write_text("NVDA\n# note\nAMZN\n")
    monkeypatch.setenv("WATCHLIST_TICKERS", "aapl, nvda")

    settings = get_settings()
    settings = Settings(
        watchlist_tickers=settings.watchlist_tickers,
        watchlist_file=str(watch),
    )
    assert settings.resolved_tickers() == ["AAPL", "NVDA", "AMZN"]


def test_resolved_tickers_without_file(tmp_path):
    assert Settings(watchlist_tickers=["AAPL"]).resolved_tickers() == ["AAPL"]


def test_dedupe_preserves_order():
    assert _dedupe(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]