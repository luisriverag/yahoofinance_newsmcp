"""Command-line entry point for on-demand digest generation.

The MCP server is the primary interface, but a short CLI makes it easy to
sanity-check configuration and generate/deliver a digest from cron or a shell
one-liner without an MCP client.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import health
from .config import configure_logging, get_settings
from .digest import generate_digest, persist_digest, render_json, render_markdown
from .services import run_morning_digest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yahoofinance-newsmcp",
        description="Yahoo Finance morning news digests.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Generate the digest (and optionally deliver it).")
    generate.add_argument("--chat-id", default=None, help="Override TELEGRAM_CHAT_ID.")
    generate.add_argument("--json", action="store_true", help="Print the structured digest as JSON.")
    generate.add_argument(
        "--dry-run", action="store_true", help="Generate only; never send to Telegram."
    )
    generate.add_argument(
        "--ticker",
        action="append",
        default=None,
        help="Restrict the digest to specific ticker(s); repeatable. Defaults to the watchlist.",
    )

    fetch = sub.add_parser(
        "fetch",
        help="Fetch recent headlines without calling the LLM (fast dry run / smoke test).",
    )
    fetch.add_argument(
        "--ticker",
        action="append",
        default=None,
        help="Restrict the fetch to specific ticker(s); repeatable. Defaults to the watchlist.",
    )
    fetch.add_argument("--json", action="store_true", help="Print the headlines as JSON.")

    sub.add_parser("list-watchlist", help="Print the configured tickers.")
    sub.add_parser("check-health", help="Run the consolidated health checks.")

    return parser


def _run_fetch(settings, args) -> int:
    """Fetch-only dry run: print recent headlines without the LLM."""

    from .yahoo import YahooFinanceClient

    tickers = args.ticker or settings.resolved_tickers()
    if not tickers:
        print("No tickers configured (WATCHLIST_TICKERS/WATCHLIST_FILE).", file=sys.stderr)
        return 1

    rows = []
    with YahooFinanceClient(settings) as client:
        for ticker in tickers:
            articles = client.enrich(client.fetch_news(ticker))
            for article in articles:
                rows.append(
                    {
                        "ticker": ticker,
                        "title": article.title,
                        "link": article.link,
                        "publisher": article.publisher,
                        "published_at": article.published_at.isoformat()
                        if article.published_at
                        else None,
                        "body": article.body,
                    }
                )

    if args.json:
        import json

        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    for row in rows:
        print(f"{row['ticker']}: {row['title']}")
        print(f"    {row['publisher'] or 'unknown source'}, "
              f"{row['published_at'] or 'time unknown'}")
        if row["body"]:
            print(f"    body: {row['body'][:200]}{'...' if len(row['body']) > 200 else ''}")
        print(f"    {row['link']}")
    if not rows:
        print("No recent news for the requested ticker(s).")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    if args.command == "list-watchlist":
        for ticker in settings.resolved_tickers():
            print(ticker)
        return 0

    if args.command == "check-health":
        report = health.check_health(settings)
        for check in report.checks:
            print(f"[{'OK' if check.ok else 'FAIL'}] {check.name}: {check.detail}")
        return 0 if report.healthy else 1

    if args.command == "fetch":
        return _run_fetch(settings, args)

    if args.command == "generate":
        tickers = args.ticker or None
        if args.dry_run or not (settings.telegram_bot_token and (args.chat_id or settings.telegram_chat_id)):
            digest = generate_digest(settings, tickers=tickers)
            persist_digest(digest, settings.digest_state_dir)
            output = digest
        else:
            run = run_morning_digest(settings, chat_id=args.chat_id, tickers=tickers)
            output = run.digest

        if args.json:
            print(render_json(output))
        else:
            print(render_markdown(output))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())