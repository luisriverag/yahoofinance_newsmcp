# Roadmap

## Near-term improvements
- [x] Add tests around the scheduler's behavior under different timezones (America/New_York, Europe/London, Asia/Tokyo) to catch DST edge cases.
- [ ] Tighten article body extraction to avoid noisy boilerplate (ads, cookie banners, "read more", social embeds). Consider adding simple heuristics or configurable selectors.
- [ ] Add optional company name mapping in config (e.g. `COMPANY_NAMES={"AAPL": "Apple Inc."}`) for nicer digest titles and overall summaries.
- [ ] Add integration tests for the Telegram chunking edge case (exactly at 4000-char boundaries) and RSS with dateless items.

## Longer-term
- [ ] Support multiple LLM backends (separate summarization vs. optional tone/style) with per-call timeouts.
- [ ] Add a "dry run" mode that only fetches headlines without calling the LLM (fast smoke test).
- [ ] Cache article bodies per run to avoid re-fetching on retries; add simple ETag support.
- [ ] Expose digest format presets (concise vs. detailed) via config/CLI.
- [ ] Add health check probe against Telegram Bot API (`getMe`) when delivery is configured.
- [ ] Consider a small TUI (inspired by torrent_mcp's `tui.py`) to preview the digest before sending.
