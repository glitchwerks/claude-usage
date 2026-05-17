"""Config subcommand for claude-prospector (read-only after issue #99).

Provides inspection of the plugin configuration. As of v0.5.x, autoregen
is managed via Anthropic's ``userConfig`` plugin-manager UX rather than
by writing to ``config.json`` directly. This subcommand is therefore
read-only: it shows the current state but does not mutate anything.

Subcommand flags:

- ``--show``  Pretty-prints the current ``config.json`` to stdout.
  When no config file exists, prints ``{}`` to stdout and a note to
  stderr directing the user to the plugin manager. Exits 0 in all cases.

Running ``python -m claude_prospector config`` with no flags prints
subcommand help and exits 0.

To toggle autoregen, use the plugin manager:

    /plugin reconfigure claude-prospector

or enable it at install time when prompted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from claude_prospector.paths import config_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_config(path: Path) -> dict:
    """Read and parse the config file.

    Returns an empty dict when the file does not exist; propagates
    :class:`json.JSONDecodeError` on malformed content so the caller can
    surface a useful error.

    Args:
        path: Path to the config JSON file.

    Returns:
        Parsed config dict, or ``{}`` if the file is absent.

    Raises:
        json.JSONDecodeError: If the file exists but is not valid JSON.
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def build_parser(
    parent: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    """Register the 'config' subparser and return it.

    Args:
        parent: The subparsers action from the top-level parser.

    Returns:
        The configured config ArgumentParser.
    """
    p = parent.add_parser(
        "config",
        help=(
            "Inspect the claude-prospector configuration. "
            "Use --show to print current settings. "
            "Toggle autoregen via the plugin manager "
            "(/plugin reconfigure claude-prospector)."
        ),
    )
    p.add_argument(
        "--show",
        action="store_true",
        default=False,
        dest="show",
        help="Print the current config as pretty-printed JSON and exit.",
    )
    return p


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    """Execute the config subcommand.

    Args:
        args: Parsed argument namespace. Expected attribute:
            ``args.show`` (bool).

    Returns:
        Integer exit code (0 on success).
    """
    path = config_path()

    # ── --show ───────────────────────────────────────────────────────────
    if args.show:
        if not path.exists():
            print("(no config file yet)", file=sys.stderr)
            print(
                "autoregen is managed via plugin user-config;"
                " toggle with /plugin reconfigure claude-prospector",
                file=sys.stderr,
            )
            print("{}")
            return 0
        try:
            cfg = _read_config(path)
        except json.JSONDecodeError as exc:
            print(
                f"config: malformed JSON in '{path}': {exc}",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(cfg, indent=2))
        return 0

    # ── No flags — print help ─────────────────────────────────────────────
    print(
        "Usage: claude-prospector config [--show]\n"
        "\n"
        "To toggle autoregen, use the plugin manager:\n"
        "    /plugin reconfigure claude-prospector\n"
        "\n"
        "Run 'claude-prospector config --help' for full help."
    )
    return 0
