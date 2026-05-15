"""CLI entry point for claude-prospector — subparser dispatcher."""

from __future__ import annotations

import sys

from claude_prospector.cli import dashboard, session_summary


def main() -> None:
    """Parse top-level subcommand and dispatch to the appropriate runner."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="claude-prospector",
        description=(
            "Claude Code token usage tools. "
            "Run 'claude-prospector <subcommand> --help' for details."
        ),
    )
    subparsers = parser.add_subparsers(
        dest="subcommand",
        metavar="subcommand",
    )

    dashboard.build_parser(subparsers)
    session_summary.build_parser(subparsers)

    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    if args.subcommand == "dashboard":
        sys.exit(dashboard.run(args))

    if args.subcommand == "session-summary":
        sys.exit(session_summary.run(args))


if __name__ == "__main__":
    main()
