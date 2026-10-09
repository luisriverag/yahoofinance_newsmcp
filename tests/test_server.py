import pytest

from yahoofinance_newsmcp import server
from yahoofinance_newsmcp.config import Settings
from yahoofinance_newsmcp.digest import MorningDigest
from yahoofinance_newsmcp.server import mcp
from yahoofinance_newsmcp.yahoo import YahooError


def _digest():
    from yahoofinance_newsmcp.digest import ArticleDigest, CompanyDigest

    return MorningDigest(
        generated_at="2026-01-01T07:00:00+00:00",
        lookback_hours=24,
        overall_summary="Overall.",
        companies=[CompanyDigest(ticker="AAPL", overall_summary="Company.", articles=[])],
    )


def test_instructions_mention_watchlist():
    assert "watchlist" in mcp.instructions


def test_tool_list_watchlist(monkeypatch):
    monkeypatch.setattr(server, "get_settings", lambda: Settings(watchlist_tickers=["AAPL", "MSFT"]))
    assert server.list_watchlist() == ["AAPL", "MSFT"]


def _stub_yahoo(monkeypatch, *, articles=None, enriched=None):
    from yahoofinance_newsmcp.yahoo import NewsArticle

    class FakeClient:
        def __init__(self, settings=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def fetch_news(self, ticker, limit=None):
            return list(articles or [])

        def enrich(self, items):
            return list(enriched if enriched is not None else items)

    monkeypatch.setattr(server, "YahooFinanceClient", FakeClient)
    return FakeClient


def test_tool_fetch_news(monkeypatch):
    from yahoofinance_newsmcp.yahoo import NewsArticle

    monkeypatch.setattr(server, "get_settings", lambda: Settings())
    _stub_yahoo(
        monkeypatch,
        articles=[NewsArticle(ticker="AAPL", title="Headline", link="https://x/1")],
    )
    result = server.fetch_news("AAPL")
    assert result[0]["title"] == "Headline"
    assert result[0]["ticker"] == "AAPL"


def test_tool_summarize_ticker_empty_news(monkeypatch):
    monkeypatch.setattr(server, "get_settings", lambda: Settings())
    _stub_yahoo(monkeypatch, articles=[], enriched=[])
    assert server.summarize_ticker("AAPL") == {
        "ticker": "AAPL",
        "overall_summary": "No recent news.",
        "articles": [],
    }


def test_tool_generate_digest(monkeypatch):
    monkeypatch.setattr(server, "get_settings", lambda: Settings())
    monkeypatch.setattr(server, "generate_and_persist", lambda settings: _digest())
    monkeypatch.setattr(server, "render_markdown", lambda digest: "# digest")
    result = server.generate_digest()
    assert result["digest"]["overall_summary"] == "Overall."
    assert result["markdown"] == "# digest"


def test_tool_send_digest(monkeypatch):
    monkeypatch.setattr(server, "get_settings", lambda: Settings())
    monkeypatch.setattr(server, "generate_and_persist", lambda settings: _digest())
    monkeypatch.setattr(server, "deliver_digest", lambda digest, settings, chat_id=None: [1, 2])
    result = server.send_digest()
    assert result["message_ids"] == [1, 2]


def test_tool_get_last_digest(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "get_settings", lambda: Settings())
    monkeypatch.setattr(server, "load_latest", lambda state_dir: _digest())
    result = server.get_last_digest()
    assert result["available"] is True
    assert result["digest"]["companies"][0]["ticker"] == "AAPL"


def test_tool_check_health(monkeypatch):
    from types import SimpleNamespace

    class FakeReport:
        healthy = True
        checks = [
            SimpleNamespace(name="watchlist", ok=True, detail="ok", required=True),
        ]

    monkeypatch.setattr(server, "get_settings", lambda: Settings())
    monkeypatch.setattr(server.health, "check_health", lambda settings: FakeReport())
    result = server.check_health()
    assert result["healthy"] is True
    assert result["checks"][0]["name"] == "watchlist"


def test_tool_wrapper_converts_expected_errors():
    @server._tool
    def boom():
        raise YahooError("something failed")

    with pytest.raises(Exception) as exc:
        boom()
    from mcp.server.mcpserver.exceptions import ToolError

    assert isinstance(exc.value, ToolError)
    assert "something failed" in str(exc.value)


# --- transport selection, mirroring the sibling byte-for-byte shape ---


def test_main_defaults_to_stdio(monkeypatch):
    monkeypatch.delenv("YF_MCP_TRANSPORT", raising=False)

    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda: calls.append("stdio"))

    server.main()

    assert calls == ["stdio"]


def test_main_stdio_explicit(monkeypatch):
    monkeypatch.setenv("YF_MCP_TRANSPORT", "stdio")

    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda: calls.append("stdio"))

    server.main()

    assert calls == ["stdio"]


def test_main_rejects_unknown_transport(monkeypatch):
    monkeypatch.setenv("YF_MCP_TRANSPORT", "carrier-pigeon")

    with pytest.raises(ValueError, match="carrier-pigeon"):
        server.main()


def test_main_http_wraps_app_with_auth_when_token_set(monkeypatch):
    monkeypatch.setenv("YF_MCP_TRANSPORT", "http")
    monkeypatch.setenv("YF_MCP_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("YF_MCP_HTTP_PORT", "9911")
    monkeypatch.setenv("YF_MCP_AUTH_TOKEN", "s3cret")

    sentinel_app = object()
    monkeypatch.setattr(server.mcp, "streamable_http_app", lambda **kwargs: sentinel_app)

    captured = {}

    def fake_uvicorn_run(app, *, host, port, log_level):
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    server.main()

    assert isinstance(captured["app"], server._BearerAuthMiddleware)
    assert captured["app"]._app is sentinel_app
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9911


def test_main_http_without_token_runs_unwrapped(monkeypatch, capsys):
    monkeypatch.setenv("YF_MCP_TRANSPORT", "http")
    monkeypatch.delenv("YF_MCP_AUTH_TOKEN", raising=False)

    sentinel_app = object()
    monkeypatch.setattr(server.mcp, "streamable_http_app", lambda **kwargs: sentinel_app)

    captured = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update(app=app))

    server.main()

    assert captured["app"] is sentinel_app
    assert "no authentication" in capsys.readouterr().err


def test_bearer_middleware_requires_auth_header():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse

    async def app(scope, receive, send):
        response = JSONResponse({"ok": True})
        await response(scope, receive, send)

    import httpx

    wrapped = server._BearerAuthMiddleware(app, "topsecret")

    async def call(headers):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/mcp",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            "http_version": "1.1",
            "scheme": "http",
            "query_string": b"",
            "client": None,
            "server": None,
            "state": {},
            "app": None,
        }

        sent_messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await wrapped(scope, receive, send)
        return sent_messages

    import asyncio

    unauth = asyncio.run(call({}))
    assert unauth and unauth[0]["type"] == "http.response.start"
    assert unauth[0]["status"] == 401

    authed = asyncio.run(call({"authorization": "Bearer topsecret"}))
    assert authed and authed[0]["status"] == 200