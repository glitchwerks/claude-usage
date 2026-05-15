"""Dashboard subcommand for claude-prospector."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from claude_prospector.aggregator import aggregate
from claude_prospector.parser import parse_sessions
from claude_prospector.renderer import render
from claude_prospector.skill_tracking import parse_skill_tracking


def _parse_window(window_str: str) -> float:
    """Parse a window string like '5h' or '7d' into hours.

    Args:
        window_str: A string of the form '<number>h' or '<number>d'.

    Returns:
        The window duration expressed as a float number of hours.

    Raises:
        argparse.ArgumentTypeError: If the format is not recognised.
    """
    match = re.match(r"^(\d+(?:\.\d+)?)(h|d)$", window_str.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(
            f"Invalid window format: '{window_str}'. Use e.g. '5h' or '7d'."
        )
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "d":
        value *= 24
    return value


def _parse_date(date_str: str) -> datetime:
    """Parse a date string (YYYY-MM-DD) into a timezone-aware datetime.

    Args:
        date_str: A date string in YYYY-MM-DD format.

    Returns:
        A UTC-aware datetime set to midnight on the given date.

    Raises:
        argparse.ArgumentTypeError: If the string is not YYYY-MM-DD.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: '{date_str}'. Use YYYY-MM-DD."
        )


def build_parser(parent: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the 'dashboard' subparser and return it.

    Args:
        parent: The subparsers action from the top-level parser.

    Returns:
        The configured dashboard ArgumentParser.
    """
    p = parent.add_parser(
        "dashboard",
        help="Generate an HTML or JSON dashboard of Claude Code token usage.",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".claude",
        help=("Path to Claude Code data directory (default: ~/.claude)"),
    )
    p.add_argument(
        "--from",
        dest="from_date",
        type=_parse_date,
        help=("Start date (YYYY-MM-DD). Only include data on or after this date."),
    )
    p.add_argument(
        "--to",
        dest="to_date",
        type=_parse_date,
        help=("End date (YYYY-MM-DD). Only include data before this date."),
    )
    p.add_argument(
        "--window",
        type=_parse_window,
        help="Rolling window (e.g. '5h', '7d'). Overrides --from.",
    )
    p.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output file path. If omitted, writes to a temp file.",
    )
    p.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open the dashboard in a browser.",
    )
    p.add_argument(
        "--limit-5h",
        type=int,
        default=None,
        help="Token budget for 5-hour rolling window.",
    )
    p.add_argument(
        "--limit-7d",
        type=int,
        default=None,
        help="Token budget for 7-day rolling window.",
    )
    p.add_argument(
        "--limit-sonnet-7d",
        type=int,
        default=None,
        help="Token budget for Sonnet-only 7-day window.",
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["html", "json"],
        default="html",
        help=(
            "Output format: 'html' (default) opens a dashboard; "
            "'json' writes structured data to stdout."
        ),
    )
    return p


def run(args: argparse.Namespace) -> int:
    """Execute the dashboard subcommand.

    Args:
        args: Parsed argument namespace from the dashboard subparser.

    Returns:
        Integer exit code (0 on success).
    """
    # In json mode, status messages go to stderr so stdout carries only the JSON payload.
    status_file = sys.stderr if args.output_format == "json" else sys.stdout

    print(f"Scanning sessions in {args.data_dir}...", file=status_file)
    sessions = parse_sessions(args.data_dir)
    print(f"Found {len(sessions)} sessions.", file=status_file)

    result = aggregate(
        sessions,
        from_date=args.from_date,
        to_date=args.to_date,
        window_hours=args.window,
    )
    print(
        f"Aggregated: {result.total_tokens:,} tokens across {result.total_sessions} sessions.",
        file=status_file,
    )

    # Skill adoption tracking (from PreToolUse hook log)
    passed_events, invoked_events = parse_skill_tracking(args.data_dir)
    if passed_events or invoked_events:
        from claude_prospector.aggregator import compute_skill_adoption

        result.by_skill_adoption = compute_skill_adoption(
            passed_events,
            invoked_events,
            from_date=args.from_date,
            to_date=args.to_date,
        )

    limits = None
    if any([args.limit_5h, args.limit_7d, args.limit_sonnet_7d]):
        limits = {
            "limit_5h": args.limit_5h,
            "limit_7d": args.limit_7d,
            "limit_sonnet_7d": args.limit_sonnet_7d,
        }

    if args.output_format == "json":
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_tokens": result.total_tokens,
            "total_messages": result.total_messages,
            "total_sessions": result.total_sessions,
            "by_model": result.by_model,
            "by_agent": result.by_agent,
            "by_skill": result.by_skill,
            "by_project": result.by_project,
            "by_day": result.by_day,
            "sessions": result.sessions,
            "limits": limits,
        }
        print(json.dumps(payload, indent=2))
        return 0

    output = render(
        result,
        output_path=args.output,
        open_browser=not args.no_open,
        limits=limits,
    )
    print(f"Dashboard written to {output}")
    return 0
