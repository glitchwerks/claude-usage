"""Central path resolution for all claude-prospector persistent state.

All paths under the base directory are resolved through this module so
hook scripts, the CLI, and reader code all agree on locations without
duplicating defaults.

Each function checks its own environment variable first; if set, returns
that path verbatim. Otherwise it builds from :func:`base_dir`.

``base_dir()`` uses a three-tier resolution (highest priority first):

1. ``CLAUDE_PROSPECTOR_BASE_DIR`` — explicit override for tests and
   non-plugin invocations.
2. ``CLAUDE_PLUGIN_DATA`` — the Anthropic-documented plugin state
   directory, populated by Claude Code when the plugin is loaded.
   Used as-is (no subdirectory appended). When this tier fires and the
   legacy directory exists with content, a one-time migration runs to
   move the legacy files into the new location.
3. Legacy ``~/.claude/claude-prospector/`` — fallback for non-plugin
   invocations and users who have not yet migrated.

Environment variable overrides (useful for testing):

- ``CLAUDE_PROSPECTOR_BASE_DIR`` — overrides the base directory (tier 1).
- ``CLAUDE_PLUGIN_DATA`` — plugin-managed state dir used as base (tier 2).
- ``CLAUDE_PROSPECTOR_CONFIG`` — overrides :func:`config_path`.
- ``CLAUDE_PROSPECTOR_DASHBOARD`` — overrides :func:`dashboard_path`.
- ``CLAUDE_PROSPECTOR_HOOK_LOG`` — overrides :func:`hook_log_path`.
- ``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` — overrides
  :func:`skill_tracking_dir`.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT_BASE = Path.home() / ".claude" / "claude-prospector"


def base_dir() -> Path:
    """Return the base directory for all claude-prospector persistent state.

    Resolves using a three-tier priority (highest first):

    1. ``CLAUDE_PROSPECTOR_BASE_DIR`` env var — explicit test/override
       path; returned verbatim with no migration side-effects.
    2. ``CLAUDE_PLUGIN_DATA`` env var — the Anthropic plugin state
       directory. Used as-is (no subdirectory appended). Triggers a
       one-time migration from the legacy directory if applicable.
    3. Legacy ``~/.claude/claude-prospector/`` — fallback for non-plugin
       invocations and pre-migration users.

    Returns:
        Path to the base directory (not guaranteed to exist).
    """
    # Tier 1: explicit override — no migration.
    env_override = os.environ.get("CLAUDE_PROSPECTOR_BASE_DIR")
    if env_override:
        return Path(env_override)

    # Tier 2: Anthropic plugin data dir.
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        new_base = Path(plugin_data)
        _migrate_legacy_if_needed(new_base)
        return new_base

    # Tier 3: legacy fallback.
    return _DEFAULT_BASE


# ---------------------------------------------------------------------------
# Derived path helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _migrate_legacy_if_needed(new_base: Path) -> None:
    """Perform a one-time migration from the legacy dir to *new_base*.

    Migration runs only when all three conditions hold:

    - The legacy directory (``_DEFAULT_BASE``) exists and is non-empty.
    - *new_base* does not exist or is empty (so we never clobber data).

    On success the legacy directory is removed. If the migration raises
    for any reason the error is swallowed and logged — hook execution
    continues using *new_base* regardless.

    Idempotency: once the legacy dir is gone (or the new dir is
    non-empty), subsequent calls are no-ops.

    Args:
        new_base: The ``CLAUDE_PLUGIN_DATA`` path that will receive the
            migrated files.
    """
    legacy = _DEFAULT_BASE

    # Guard: legacy must exist and have content.
    if not legacy.is_dir():
        return
    legacy_contents = list(legacy.iterdir())
    if not legacy_contents:
        return

    # Guard: new dir must be absent or empty (and actually a directory).
    if new_base.is_dir() and any(True for _ in new_base.iterdir()):
        return

    try:
        new_base.mkdir(parents=True, exist_ok=True)
        for item in legacy_contents:
            dest = new_base / item.name
            shutil.move(str(item), str(dest))
        # Remove the now-empty legacy dir.
        legacy.rmdir()
        _log_migration(f"migrated from {legacy} to {new_base}")
    except Exception as exc:  # noqa: BLE001
        _log_migration(f"migration failed ({exc}); continuing with {new_base}")


def _log_migration(message: str) -> None:
    """Append a ``[migration]`` line to the hook log.

    Uses the ``CLAUDE_PROSPECTOR_HOOK_LOG`` env var for the log path
    (same resolution as :func:`hook_log_path` but inlined to avoid a
    circular call through :func:`base_dir`).

    Errors are silently swallowed so a log failure never crashes a hook.

    Args:
        message: Diagnostic text to record after the ``[migration]``
            prefix.
    """
    try:
        env_val = os.environ.get("CLAUDE_PROSPECTOR_HOOK_LOG")
        if env_val:
            log = Path(env_val)
        else:
            # Resolve log path without calling base_dir() again.
            plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
            if plugin_data:
                log = Path(plugin_data) / "hook.log"
            else:
                log = _DEFAULT_BASE / "hook.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"[migration] {message}\n")
    except Exception:  # noqa: BLE001
        pass
