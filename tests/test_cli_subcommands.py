"""Tests for top-level CLI subparser routing."""

from __future__ import annotations

import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run claude_prospector as a module and capture output.

    Args:
        *args: Command-line arguments to pass after the module name.

    Returns:
        CompletedProcess with stdout, stderr, and returncode populated.
    """
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", *args],
        capture_output=True,
        text=True,
    )


def test_bare_invocation_exits_0_and_shows_subcommands() -> None:
    """Bare 'claude-prospector' with no args must exit 0 and list subcommands."""
    result = _run()
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "dashboard" in combined
    assert "session-summary" in combined


def test_dashboard_help_exits_0() -> None:
    """'claude-prospector dashboard --help' must exit 0."""
    result = _run("dashboard", "--help")
    assert result.returncode == 0


def test_old_flag_only_form_exits_nonzero() -> None:
    """'claude-prospector --format json' (old form) must exit non-zero post-refactor.

    The top-level parser no longer accepts --format; callers must migrate
    to 'claude-prospector dashboard --format json'.
    """
    result = _run("--format", "json")
    assert result.returncode != 0
