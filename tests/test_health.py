import pytest

from yahoofinance_newsmcp import health
from yahoofinance_newsmcp.config import Settings
from yahoofinance_newsmcp.yahoo import YahooError


def test_check_health_healthy(monkeypatch, tmp_path):
    monkeypatch.setattr(health.YahooFinanceClient, "probe", lambda self, ticker="AAPL": 3)
    settings = Settings(
        watchlist_tickers=["AAPL"],
        llm_chat_url="https://llm.example/v1/chat/completions",
        llm_model="model",
        telegram_bot_token="t",
        telegram_chat_id="1",
        digest_state_dir=str(tmp_path),
    )
    report = health.check_health(settings)
    assert report.healthy is True


def test_check_health_fails_without_watchlist(monkeypatch):
    report = health.check_health(Settings())
    assert report.healthy is False
    names = {check.name for check in report.checks}
    assert "watchlist" in names


def test_check_health_fails_without_llm(monkeypatch):
    monkeypatch.setattr(health.YahooFinanceClient, "probe", lambda self, ticker="AAPL": 1)
    report = health.check_health(Settings(watchlist_tickers=["AAPL"]))
    assert report.healthy is False
    llm_check = next(check for check in report.checks if check.name == "llm")
    assert llm_check.ok is False


def test_check_health_reports_yahoo_failure(monkeypatch):
    def probe(self, ticker="AAPL"):
        raise YahooError("unreachable")

    monkeypatch.setattr(health.YahooFinanceClient, "probe", probe)
    settings = Settings(
        watchlist_tickers=["AAPL"],
        llm_chat_url="https://llm.example/v1/chat/completions",
        llm_model="m",
    )
    report = health.check_health(settings)
    assert report.healthy is False
    yahoo_check = next(check for check in report.checks if check.name == "yahoo")
    assert "unreachable" in yahoo_check.detail


def test_optional_checks_do_not_fail_health(monkeypatch, tmp_path):
    monkeypatch.setattr(health.YahooFinanceClient, "probe", lambda self, ticker="AAPL": 1)
    settings = Settings(
        watchlist_tickers=["AAPL"],
        llm_chat_url="https://llm.example/v1/chat/completions",
        llm_model="m",
    )
    report = health.check_health(settings)
    assert report.healthy is True
    telegram_check = next(check for check in report.checks if check.name == "telegram")
    assert telegram_check.ok is True and telegram_check.required is False