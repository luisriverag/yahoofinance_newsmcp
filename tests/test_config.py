from yahoofinance_newsmcp.config import (
    Settings,
    _dedupe,
    get_settings,
    parse_company_names,
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


def test_parse_company_names_json_object():
    raw = '{"AAPL": "Apple Inc.", "msft": "Microsoft Corporation"}'
    assert parse_company_names(raw) == {
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corporation",
    }


def test_parse_company_names_pairs_and_newlines():
    raw = "AAPL=Apple Inc.\nMSFT=Microsoft Corp., NVDA = NVIDIA Corp."
    assert parse_company_names(raw) == {
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corp.",
        "NVDA": "NVIDIA Corp.",
    }


def test_parse_company_names_empty_and_invalid():
    assert parse_company_names("") == {}
    assert parse_company_names("garbage without equals") == {}
    assert parse_company_names("AAPL=") == {}


def test_company_name_for_falls_back_to_ticker():
    settings = Settings(company_names={"AAPL": "Apple Inc."})
    assert settings.company_name_for("aapl") == "Apple Inc."
    assert settings.company_name_for("TSLA") == "TSLA"
    assert settings.company_name_for("  ") == ""


def test_get_settings_reads_company_names(monkeypatch):
    monkeypatch.setenv("COMPANY_NAMES", "AAPL=Apple Inc.")
    assert get_settings().company_names == {"AAPL": "Apple Inc."}


def test_overall_llm_config_empty_by_default():
    settings = Settings(
        llm_chat_url="https://base/v1/chat/completions",
        llm_model="base",
        llm_api_key="basekey",
    )
    assert settings.overall_llm_config() == {}


def test_overall_llm_config_overrides_and_fallbacks():
    settings = Settings(
        llm_chat_url="https://base/v1/chat/completions",
        llm_model="base",
        llm_api_key="basekey",
        llm_timeout_seconds=120.0,
        llm_overall_model="big-model",
    )
    config = settings.overall_llm_config()
    assert config["model"] == "big-model"
    assert config["chat_url"] == "https://base/v1/chat/completions"
    assert config["api_key"] == "basekey"
    assert config["timeout"] == 120.0


def test_overall_llm_config_timeout_override():
    settings = Settings(
        llm_chat_url="https://base",
        llm_model="base",
        llm_overall_chat_url="https://overall",
        llm_overall_timeout_seconds=30.0,
    )
    config = settings.overall_llm_config()
    assert config["chat_url"] == "https://overall"
    assert config["timeout"] == 30.0


def test_get_settings_reads_overall_backend_and_tone(monkeypatch):
    monkeypatch.setenv("LLM_OVERALL_MODEL", "big-model")
    monkeypatch.setenv("DIGEST_TONE", "brisk and plain-spoken")
    settings = get_settings()
    assert settings.llm_overall_model == "big-model"
    assert settings.digest_tone == "brisk and plain-spoken"