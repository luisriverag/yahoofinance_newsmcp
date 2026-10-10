# Roadmap

## Near-term improvements
- [x] Add tests around the scheduler's behavior under different timezones (America/New_York, Europe/London, Asia/Tokyo) to catch DST edge cases.
- [x] Tighten article body extraction to avoid noisy boilerplate (ads, cookie banners, "read more", social embeds). Consider adding simple heuristics or configurable selectors.
- [x] Add optional company name mapping in config (e.g. `COMPANY_NAMES={"AAPL": "Apple Inc."}`) for nicer digest titles and overall summaries.
- [x] Add integration tests for the Telegram chunking edge case (exactly at 4000-char boundaries) and RSS with dateless items.

## Longer-term
- [x] Support multiple LLM backends (separate summarization vs. optional tone/style) with per-call timeouts.
- [x] Add a "dry run" mode that only fetches headlines without calling the LLM (fast smoke test).
- [x] Cache article bodies per run to avoid re-fetching on retries; add simple ETag support.
- [x] Persist the article-body and summary caches to disk (CACHE_DIR/CACHE_TTL_HOURS) so a repeat call across separate runs, not just within one, skips re-fetching and re-summarizing unchanged articles -- the summarization model call is the dominant cost of a digest run.
- [ ] Expose digest format presets (concise vs. detailed) via config/CLI.
- [x] Add health check probe against Telegram Bot API (`getMe`) when delivery is configured.
- [ ] Consider a small TUI (inspired by torrent_mcp's `tui.py`) to preview the digest before sending.
