"""Central path resolution for all claude-prospector persistent state.

All paths under ``~/.claude/claude-prospector/`` are resolved through
this module so hook scripts, the CLI, and reader code all agree on
locations without duplicating defaults.

Each function checks its own environment variable first; if set, returns
that path verbatim. Otherwise it builds from :func:`base_dir`.

Environment variable overrides (useful for testing):

- ``CLAUDE_PROSPECTOR_BASE_DIR`` — overrides the base directory.
- ``CLAUDE_PROSPECTOR_CONFIG`` — overrides :func:`config_path`.
- ``CLAUDE_PROSPECTOR_DASHBOARD`` — overrides :func:`dashboard_path`.
- ``CLAUDE_PROSPECTOR_HOOK_LOG`` — overrides :func:`hook_log_path`.
- ``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` — overrides
  :func:`skill_tracking_dir`.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT_BASE = Path.home() / ".claude" / "claude-prospector"


def base_dir() -> Path:
    """Return the base directory for all claude-prospector persistent state.

    Defaults to ``~/.claude/claude-prospector/``. Override via the
    ``CLAUDE_PROSPECTOR_BASE_DIR`` environment variable.

    Returns:
        Path to the base directory (not guaranteed to exist).
    """
    env_val = os.environ.get("CLAUDE_PROSPECTOR_BASE_DIR")
    if env_val:
        return Path(env_val)
    return _DEFAULT_BASE


def config_path() -> Path:
    """Return the path to the settings JSON file.

    Defaults to ``base_dir() / "config.json"``. Override via the
    ``CLAUDE_PROSPECTOR_CONFIG`` environment variable.

    Returns:
        Path to the config file (not guaranteed to exist).
    """
    env_val = os.environ.get("CLAUDE_PROSPECTOR_CONFIG")
    if env_val:
        return Path(env_val)
    return base_dir() / "config.json"


def dashboard_path() -> Path:
    """Return the path to the generated dashboard HTML file.

    Defaults to ``base_dir() / "dashboard.html"``. Override via the
    ``CLAUDE_PROSPECTOR_DASHBOARD`` environment variable.

    Returns:
        Path to the dashboard file (not guaranteed to exist).
    """
    env_val = os.environ.get("CLAUDE_PROSPECTOR_DASHBOARD")
    if env_val:
        return Path(env_val)
    return base_dir() / "dashboard.html"


def hook_log_path() -> Path:
    """Return the path to the hook diagnostic log file.

    Defaults to ``base_dir() / "hook.log"``. Override via the
    ``CLAUDE_PROSPECTOR_HOOK_LOG`` environment variable.

    The log is truncated on each hook run (last-run-wins), so it never
    grows unbounded.

    Returns:
        Path to the hook log file (not guaranteed to exist).
    """
    env_val = os.environ.get("CLAUDE_PROSPECTOR_HOOK_LOG")
    if env_val:
        return Path(env_val)
    return base_dir() / "hook.log"


def skill_tracking_dir() -> Path:
    """Return the directory used for per-day skill-tracking JSONL files.

    Defaults to ``base_dir() / "skill-tracking"``. Override via the
    ``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` environment variable.

    Returns:
        Path to the skill-tracking directory (not guaranteed to exist).
    """
    env_val = os.environ.get("CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR")
    if env_val:
        return Path(env_val)
    return base_dir() / "skill-tracking"
