"""Config subcommand for claude-prospector.

Manages the plugin configuration file at the path returned by
:func:`claude_prospector.paths.config_path` (default:
``~/.claude/claude-prospector/config.json``).

The config file is a JSON object. Currently the only supported key is
``autoregen`` (bool) which controls whether the Stop hook regenerates
the dashboard at the end of every session.

Subcommand flags (mutually exclusive):

- ``--enable-autoregen``  Sets ``{"autoregen": true}`` (creates file if
  absent; preserves other keys).
- ``--disable-autoregen`` Sets ``{"autoregen": false}``.
- ``--show``              Pretty-prints the current config to stdout.
  Exits 0 whether or not the file exists.

Running ``python -m claude_prospector config`` with no flags prints
subcommand help and exits 0.
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


def _write_config(path: Path, cfg: dict) -> None:
    """Write a config dict to *path* as pretty-printed JSON.

    Creates parent directories as needed.

    Args:
        path: Destination path.
        cfg: Config mapping to serialise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


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
        help=("Read or update the claude-prospector configuration file."),
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--enable-autoregen",
        action="store_true",
        default=False,
        dest="enable_autoregen",
        help=(
            "Enable automatic dashboard regeneration on session end "
            "(sets autoregen=true in config.json)."
        ),
    )
    group.add_argument(
        "--disable-autoregen",
        action="store_true",
        default=False,
        dest="disable_autoregen",
        help=(
            "Disable automatic dashboard regeneration "
            "(sets autoregen=false in config.json)."
        ),
    )
    group.add_argument(
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
        args: Parsed argument namespace. Expected attributes:
            ``args.enable_autoregen`` (bool),
            ``args.disable_autoregen`` (bool),
            ``args.show`` (bool).

    Returns:
        Integer exit code (0 on success).
    """
    path = config_path()

    # ── --show ───────────────────────────────────────────────────────────
    if args.show:
        if not path.exists():
            print("(no config file yet)", file=sys.stderr)
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

    # ── --enable-autoregen / --disable-autoregen ─────────────────────────
    if args.enable_autoregen or args.disable_autoregen:
        try:
            cfg = _read_config(path)
        except json.JSONDecodeError as exc:
            print(
                f"config: malformed JSON in '{path}': {exc}",
                file=sys.stderr,
            )
            return 1
        cfg["autoregen"] = args.enable_autoregen
        _write_config(path, cfg)
        state = "enabled" if args.enable_autoregen else "disabled"
        print(f"autoregen {state} (config: {path})")
        return 0

    # ── No flags — print help ─────────────────────────────────────────────
    # Re-parse with --help to get consistent help output via argparse.
    # We can't easily reach the subparser from here without plumbing, so
    # print a minimal usage note instead.
    print(
        "Usage: claude-prospector config "
        "[--enable-autoregen | --disable-autoregen | --show]"
    )
    print("Run 'claude-prospector config --help' for full help.")
    return 0
