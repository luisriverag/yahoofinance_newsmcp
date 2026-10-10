# Yahoo Finance News MCP

A Yahoo Finance morning news digest service: fetch recent headlines per ticker, summarize them into per-article, per-company, and overall summaries via an OpenAI-compatible LLM, render a clean Markdown digest, optionally persist it to disk, and deliver it to Telegram. Exposes an MCP server (stdio or Streamable HTTP) with tools to generate digests on demand, and an optional built-in morning scheduler for automatic delivery.

## Features
- Config-driven watchlist (`WATCHLIST_TICKERS` or `WATCHLIST_FILE`) covering any Yahoo Finance symbols.
- Fetches from Yahoo Finance search API with RSS fallback.
- Optional full-article body extraction for richer summaries, with per-run body caching and ETag revalidation.
- Persistent disk cache (article bodies and LLM summaries) across separate calls, not just within one run -- a repeat `generate_digest`/`summarize_ticker` call within `CACHE_TTL_HOURS` skips re-fetching and re-summarizing unchanged articles entirely.
- Server-side LLM summarization (per-article, per-company, overall) using any OpenAI-compatible `/v1/chat/completions` endpoint; an optional separate backend/tone can run the overall summary.
- Clean Markdown rendering; JSON output available for automation.
- Persistence: writes `latest.md`, `latest.json`, and dated files to `DIGEST_STATE_DIR`.
- Telegram delivery with automatic message chunking; token verified via `getMe` in health checks.
- MCP server with tools: `list_watchlist`, `fetch_news`, `summarize_ticker`, `generate_digest`, `send_digest`, `get_last_digest`, `check_health`.
- Built-in daily scheduler (`DIGEST_SCHEDULER_ENABLED`, `DIGEST_TIME`, `DIGEST_TIMEZONE`) for always-on HTTP mode.
- Health checks covering watchlist, LLM, Yahoo, Telegram (optional), persistence (optional).
- CLI for one-off generation, headline-only dry runs (`fetch`), and health checks.
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

# Fast headline-only smoke test (no LLM call)
yahoofinance-newsmcp fetch

# Or run MCP server over stdio
yahoofinance-newsmcp-server
```

## Configuration
See [`.env.sample`](./.env.sample) for all variables. Key ones:
- `WATCHLIST_TICKERS`: comma-separated symbols (e.g. `AAPL,MSFT,NVDA`)
- `WATCHLIST_FILE`: optional file with one ticker per line
- `COMPANY_NAMES`: optional ticker→display-name map (`AAPL=Apple Inc.` or JSON)
- `NEWS_LOOKBACK_HOURS`: how far back to pull news (default 24)
- `NEWS_PER_TICKER`: max articles per ticker (default 10)
- `NEWS_FETCH_ARTICLE_TEXT`: fetch full article bodies (default true)
- `LLM_CHAT_URL`, `LLM_MODEL`, `LLM_API_KEY`: OpenAI-compatible endpoint
- `LLM_OVERALL_*`, `DIGEST_TONE`: optional separate backend/tone for the overall summary
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: for delivery
- `DIGEST_SCHEDULER_ENABLED`, `DIGEST_TIME`, `DIGEST_TIMEZONE`: for automatic runs
- `CACHE_DIR` (defaults to `DIGEST_STATE_DIR`), `CACHE_TTL_HOURS` (default 24): persistent cache for fetched article bodies and LLM summaries, so a repeat call within the TTL skips re-fetching/re-summarizing unchanged articles; leave both empty to disable caching
- `YF_MCP_TRANSPORT`: `http` (default) or `stdio`
- `YF_MCP_HTTP_HOST`, `YF_MCP_HTTP_PORT` (default `3654`), `YF_MCP_HTTP_PATH`: HTTP bind
- `YF_MCP_AUTH_TOKEN`: required for HTTP in untrusted networks

## Docker
```bash
cp .env .env
cp docker-compose.yml.sample docker-compose.yml
# Mount data volume and any watchlist file as needed
docker compose up -d --build
```

## MCP integration with ocabra_telegram
This server is designed to be wired into [ocabra_telegram](https://github.com/luisriverag/ocabra_telegram) as an MCP backend. By default it serves MCP over Streamable HTTP on port **3654** (`/mcp`), which is the recommended path for a client on another host/container:

```env
# In ocabra_telegram's .env
YF_MCP_HTTP_PORT=3654
YAHOO_NEWS_MCP_ENABLED=true
YAHOO_NEWS_MCP_URL=http://<host>:3654/mcp
YAHOO_NEWS_MCP_AUTH_TOKEN=<same value as YF_MCP_AUTH_TOKEN>
YAHOO_NEWS_ADMIN_TELEGRAM_ID=<your Telegram user id>
```

For a same-host stdio install (no HTTP service), set `YF_MCP_TRANSPORT=stdio` here and configure ocabra_telegram's generic stdio backend:
```env
EXTRA_MCP_SERVERS=yahoo_news
MCP_YAHOO_NEWS_ENABLED=true
MCP_YAHOO_NEWS_COMMAND=yahoofinance-newsmcp-server  # add YF_MCP_TRANSPORT=stdio to its env
```

See ocabra_telegram's README for the full branch-and-pull-request workflow and the HTTP backend conventions (`homebox_tools.py`/`torrent_tools.py`).

## Development
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## License
MIT
