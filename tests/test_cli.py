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