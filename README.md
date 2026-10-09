# Yahoo Finance News MCP

A Yahoo Finance morning news digest service: fetch recent headlines per ticker, summarize them into per-article, per-company, and overall summaries via an OpenAI-compatible LLM, render a clean Markdown digest, optionally persist it to disk, and deliver it to Telegram. Exposes an MCP server (stdio or Streamable HTTP) with tools to generate digests on demand, and an optional built-in morning scheduler for automatic delivery.

## Features
- Config-driven watchlist (`WATCHLIST_TICKERS` or `WATCHLIST_FILE`) covering any Yahoo Finance symbols.
- Fetches from Yahoo Finance search API with RSS fallback.
- Optional full-article body extraction for richer summaries.
- Server-side LLM summarization (per-article, per-company, overall) using any OpenAI-compatible `/v1/chat/completions` endpoint.
- Clean Markdown rendering; JSON output available for automation.
- Persistence: writes `latest.md`, `latest.json`, and dated files to `DIGEST_STATE_DIR`.
- Telegram delivery with automatic message chunking.
- MCP server with tools: `list_watchlist`, `fetch_news`, `summarize_ticker`, `generate_digest`, `send_digest`, `get_last_digest`, `check_health`.
- Built-in daily scheduler (`DIGEST_SCHEDULER_ENABLED`, `DIGEST_TIME`, `DIGEST_TIMEZONE`) for always-on HTTP mode.
- Health checks covering watchlist, LLM, Yahoo, Telegram (optional), persistence (optional).
- CLI for one-off generation and health checks.
- Docker image and docker-compose sample.

## Quick start
```bash
# Clone and set up
cd yahoofinance_newsmcp
cp .env.sample .env
# Edit .env with at least WATCHLIST_TICKERS, LLM_CHAT_URL, LLM_MODEL

# Run with venv
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Generate a digest (dry-run by default if Telegram not configured)
yahoofinance-newsmcp generate --dry-run

# Or run MCP server over stdio
yahoofinance-newsmcp-server
```

## Configuration
See [`.env.sample`](./.env.sample) for all variables. Key ones:
- `WATCHLIST_TICKERS`: comma-separated symbols (e.g. `AAPL,MSFT,NVDA`)
- `WATCHLIST_FILE`: optional file with one ticker per line
- `NEWS_LOOKBACK_HOURS`: how far back to pull news (default 24)
- `NEWS_PER_TICKER`: max articles per ticker (default 10)
- `NEWS_FETCH_ARTICLE_TEXT`: fetch full article bodies (default true)
- `LLM_CHAT_URL`, `LLM_MODEL`, `LLM_API_KEY`: OpenAI-compatible endpoint
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: for delivery
- `DIGEST_SCHEDULER_ENABLED`, `DIGEST_TIME`, `DIGEST_TIMEZONE`: for automatic runs
- `YF_MCP_TRANSPORT`: `stdio` (default) or `http`
- `YF_MCP_AUTH_TOKEN`: required for HTTP in untrusted networks

## Docker
```bash
cp .env .env
cp docker-compose.yml.sample docker-compose.yml
# Mount data volume and any watchlist file as needed
docker compose up -d --build
```

## MCP integration with ocabra_telegram
This server is designed to be wired into [ocabra_telegram](https://github.com/luisriverag/ocabra_telegram) as an MCP backend (Streamable HTTP). Configure:
```env
EXTRA_MCP_SERVERS=yahoo_news
MCP_YAHOO_NEWS_ENABLED=true
MCP_YAHOO_NEWS_COMMAND=yahoofinance-newsmcp-server  # or ssh bridge
# For HTTP backend, use the generic Streamable HTTP pattern in ocabra_telegram
```
Or run this server as HTTP (`YF_MCP_TRANSPORT=http`) and add a small HTTP MCP backend module in ocabra_telegram following `homebox_tools.py`/`torrent_tools.py` conventions (Streamable HTTP, admin allowlist). See ocabra_telegram's `docs/SPEC.md` and `generic_mcp_tools.py` for the stdio path; for HTTP, mirror the existing HTTP backends.

## Development
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## License
MIT
