"""Tests for 'python -m claude_prospector config' subcommand.

All subprocess invocations redirect the config file path via the
``CLAUDE_PROSPECTOR_CONFIG`` environment variable so tests never touch
the real home directory.

Covers:
- ``--enable-autoregen`` creates the config file with autoregen=true.
- ``--disable-autoregen`` sets autoregen=false (and creates file if absent).
- ``--show`` prints the current config; reports "(no config file yet)" when
  absent.
- Mutual exclusion: combining two flags exits non-zero.
- No flags: prints usage hint, exits 0.
- ``--show`` preserves extra keys in the config file.
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
# --enable-autoregen
# ---------------------------------------------------------------------------


class TestEnableAutoregen:
    """Tests for the --enable-autoregen flag."""

    def test_creates_config_file_when_absent(self, tmp_path: Path) -> None:
        """--enable-autoregen creates config.json when it doesn't exist."""
        cfg_path = tmp_path / "config.json"
        assert not cfg_path.exists()
        result = _run_config("--enable-autoregen", config_path=cfg_path)
        assert result.returncode == 0, result.stderr
        assert cfg_path.exists()

    def test_sets_autoregen_true(self, tmp_path: Path) -> None:
        """--enable-autoregen writes autoregen=true to the config file."""
        cfg_path = tmp_path / "config.json"
        result = _run_config("--enable-autoregen", config_path=cfg_path)
        assert result.returncode == 0, result.stderr
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["autoregen"] is True

    def test_preserves_other_keys(self, tmp_path: Path) -> None:
        """--enable-autoregen preserves existing keys in the config file."""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"some_other_key": 42}), encoding="utf-8")
        _run_config("--enable-autoregen", config_path=cfg_path)
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["some_other_key"] == 42
        assert cfg["autoregen"] is True

    def test_overwrites_false_to_true(self, tmp_path: Path) -> None:
        """--enable-autoregen flips autoregen from false to true."""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"autoregen": False}), encoding="utf-8")
        _run_config("--enable-autoregen", config_path=cfg_path)
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["autoregen"] is True


# ---------------------------------------------------------------------------
# --disable-autoregen
# ---------------------------------------------------------------------------


class TestDisableAutoregen:
    """Tests for the --disable-autoregen flag."""

    def test_creates_config_file_when_absent(self, tmp_path: Path) -> None:
        """--disable-autoregen creates config.json when it doesn't exist."""
        cfg_path = tmp_path / "config.json"
        result = _run_config("--disable-autoregen", config_path=cfg_path)
        assert result.returncode == 0, result.stderr
        assert cfg_path.exists()

    def test_sets_autoregen_false(self, tmp_path: Path) -> None:
        """--disable-autoregen writes autoregen=false."""
        cfg_path = tmp_path / "config.json"
        result = _run_config("--disable-autoregen", config_path=cfg_path)
        assert result.returncode == 0, result.stderr
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["autoregen"] is False

    def test_flips_true_to_false(self, tmp_path: Path) -> None:
        """--disable-autoregen flips autoregen from true to false."""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"autoregen": True}), encoding="utf-8")
        _run_config("--disable-autoregen", config_path=cfg_path)
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["autoregen"] is False


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


# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------


class TestMutualExclusion:
    """Tests for the mutually-exclusive flag group."""

    def test_enable_and_disable_together_exits_nonzero(self, tmp_path: Path) -> None:
        """--enable-autoregen and --disable-autoregen together must fail."""
        cfg_path = tmp_path / "config.json"
        result = _run_config(
            "--enable-autoregen",
            "--disable-autoregen",
            config_path=cfg_path,
        )
        assert result.returncode != 0

    def test_enable_and_show_together_exits_nonzero(self, tmp_path: Path) -> None:
        """--enable-autoregen and --show together must fail."""
        cfg_path = tmp_path / "config.json"
        result = _run_config("--enable-autoregen", "--show", config_path=cfg_path)
        assert result.returncode != 0


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

    def test_no_flags_mentions_flags(self, tmp_path: Path) -> None:
        """'config' with no flags must mention the available flags."""
        cfg_path = tmp_path / "config.json"
        result = _run_config(config_path=cfg_path)
        combined = result.stdout + result.stderr
        assert "autoregen" in combined
