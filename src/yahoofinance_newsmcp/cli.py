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

    sub.add_parser("list-watchlist", help="Print the configured tickers.")
    sub.add_parser("check-health", help="Run the consolidated health checks.")

    return parser


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