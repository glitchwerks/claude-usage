"""Tests for --version flag and __version__ attribute.

Covers:
- ``python -m claude_prospector --version`` exits 0 and prints a version
  string.
- The version string matches the expected format (digits or sentinel).
- ``claude_prospector.__version__`` is importable and non-empty.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import claude_prospector

# Resolve worktree root so subprocess CWD is correct — prevents the
# shell's CWD (main repo) from shadowing the worktree package via the
# empty-string entry in sys.path.
_WORKTREE = Path(__file__).parent.parent

# Pattern for a real version (e.g. "0.4.0") or the local sentinel.
# Uses search (not match) so "claude-prospector 0.4.0" is accepted.
_VERSION_RE = re.compile(r"[\d]+\.[\d]+\.[\d]|0\.0\.0\+local")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run claude_prospector from the worktree, capturing output.

    Args:
        *args: Arguments to pass after ``-m claude_prospector``.

    Returns:
        CompletedProcess with stdout, stderr, and returncode.
    """
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", *args],
        capture_output=True,
        text=True,
        cwd=str(_WORKTREE),
    )


def test_version_flag_exits_zero() -> None:
    """``python -m claude_prospector --version`` must exit 0."""
    result = _run_cli("--version")
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}. " f"stderr: {result.stderr!r}"
    )


def test_version_flag_prints_version_string() -> None:
    """``--version`` output must match the version pattern."""
    result = _run_cli("--version")
    combined = (result.stdout + result.stderr).strip()
    assert _VERSION_RE.search(
        combined
    ), f"Version output did not match pattern: {combined!r}"


def test_dunder_version_is_non_empty() -> None:
    """claude_prospector.__version__ must be a non-empty string."""
    assert isinstance(claude_prospector.__version__, str)
    assert claude_prospector.__version__
