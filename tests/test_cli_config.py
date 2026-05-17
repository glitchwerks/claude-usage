"""Tests for 'python -m claude_prospector config' subcommand.

All subprocess invocations redirect the config file path via the
``CLAUDE_PROSPECTOR_CONFIG`` environment variable so tests never touch
the real home directory.

After issue #99, the config subcommand is read-only (--show only).
The --enable-autoregen and --disable-autoregen flags are removed; autoregen
is now managed via the plugin manager user-config (userConfig.autoregen).

Covers:
- ``--show`` prints the current config; reports "(no config file yet)" when
  absent.
- ``--show`` prints user-config guidance when no config file exists.
- ``--enable-autoregen`` and ``--disable-autoregen`` are rejected (unknown).
- No flags: prints usage hint, exits 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Worktree root — keeps subprocess CWD off the main repo so the empty-
# string sys.path entry resolves to the worktree package.
_WORKTREE = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_config(
    *args: str,
    config_path: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the config subcommand with config redirected to *config_path*.

    Args:
        *args: Additional flags to pass after ``config``.
        config_path: Path to use as the config file (via env var override).
        extra_env: Extra environment variables to merge in.

    Returns:
        CompletedProcess with stdout, stderr, and returncode.
    """
    env = {**os.environ, "CLAUDE_PROSPECTOR_CONFIG": str(config_path)}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", "config", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKTREE),
    )


# ---------------------------------------------------------------------------
# Removed flags (issue #99 — now rejected as unknown)
# ---------------------------------------------------------------------------


class TestRemovedFlags:
    """--enable-autoregen and --disable-autoregen are removed in v0.5.x."""

    def test_enable_autoregen_exits_nonzero(self, tmp_path: Path) -> None:
        """--enable-autoregen is no longer a valid flag; must exit non-zero."""
        cfg_path = tmp_path / "config.json"
        result = _run_config("--enable-autoregen", config_path=cfg_path)
        assert (
            result.returncode != 0
        ), "--enable-autoregen should be rejected after demotion to read-only"

    def test_disable_autoregen_exits_nonzero(self, tmp_path: Path) -> None:
        """--disable-autoregen is no longer a valid flag; must exit non-zero."""
        cfg_path = tmp_path / "config.json"
        result = _run_config("--disable-autoregen", config_path=cfg_path)
        assert (
            result.returncode != 0
        ), "--disable-autoregen should be rejected after demotion to read-only"

    def test_enable_autoregen_does_not_write_config(self, tmp_path: Path) -> None:
        """--enable-autoregen must not create or modify config.json."""
        cfg_path = tmp_path / "config.json"
        _run_config("--enable-autoregen", config_path=cfg_path)
        assert not cfg_path.exists(), "Removed flag must not side-effect config.json"


# ---------------------------------------------------------------------------
# --show
# ---------------------------------------------------------------------------


class TestShow:
    """Tests for the --show flag."""

    def test_exits_zero_when_file_present(self, tmp_path: Path) -> None:
        """--show exits 0 when the config file exists."""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"autoregen": True}), encoding="utf-8")
        result = _run_config("--show", config_path=cfg_path)
        assert result.returncode == 0

    def test_prints_config_as_json(self, tmp_path: Path) -> None:
        """--show prints the config as valid JSON to stdout."""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"autoregen": True}), encoding="utf-8")
        result = _run_config("--show", config_path=cfg_path)
        parsed = json.loads(result.stdout)
        assert parsed["autoregen"] is True

    def test_exits_zero_when_file_absent(self, tmp_path: Path) -> None:
        """--show exits 0 even when the config file does not exist."""
        cfg_path = tmp_path / "nonexistent-config.json"
        result = _run_config("--show", config_path=cfg_path)
        assert result.returncode == 0

    def test_reports_no_config_on_stderr_when_absent(self, tmp_path: Path) -> None:
        """--show writes a '(no config file yet)' note to stderr when absent."""
        cfg_path = tmp_path / "nonexistent-config.json"
        result = _run_config("--show", config_path=cfg_path)
        assert "(no config file yet)" in result.stderr

    def test_prints_empty_braces_to_stdout_when_absent(self, tmp_path: Path) -> None:
        """--show prints '{}' to stdout when the config file is absent."""
        cfg_path = tmp_path / "nonexistent-config.json"
        result = _run_config("--show", config_path=cfg_path)
        assert result.stdout.strip() == "{}"

    def test_show_mentions_plugin_manager_when_config_absent(
        self, tmp_path: Path
    ) -> None:
        """--show with no config mentions plugin manager for configuration."""
        cfg_path = tmp_path / "nonexistent-config.json"
        result = _run_config("--show", config_path=cfg_path)
        combined = result.stdout + result.stderr
        assert "plugin" in combined.lower() or "reconfigure" in combined.lower()


# ---------------------------------------------------------------------------
# No flags
# ---------------------------------------------------------------------------


class TestNoFlags:
    """Tests for bare 'config' subcommand with no flags."""

    def test_no_flags_exits_zero(self, tmp_path: Path) -> None:
        """'config' with no flags must exit 0 and print usage hint."""
        cfg_path = tmp_path / "config.json"
        result = _run_config(config_path=cfg_path)
        assert result.returncode == 0

    def test_no_flags_mentions_show(self, tmp_path: Path) -> None:
        """'config' with no flags must mention --show."""
        cfg_path = tmp_path / "config.json"
        result = _run_config(config_path=cfg_path)
        combined = result.stdout + result.stderr
        assert "--show" in combined
