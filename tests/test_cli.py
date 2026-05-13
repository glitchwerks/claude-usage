"""Tests for CLI --format flag."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Helper: run `python -m claude_usage` with the given args."""
    return subprocess.run(
        [sys.executable, "-m", "claude_usage", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


WORKTREE_ROOT = Path(__file__).parent.parent

EXPECTED_TOP_LEVEL_KEYS = {
    "generated_at",
    "total_tokens",
    "total_messages",
    "total_sessions",
    "by_model",
    "by_agent",
    "by_skill",
    "by_project",
    "by_day",
    "sessions",
    "limits",
}


class TestFormatJson:
    def test_outputs_valid_json(self, sample_session_dir: Path):
        """dashboard --format json must write parseable JSON to stdout."""
        result = run_cli(
            [
                "dashboard",
                "--format",
                "json",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
            ],
            cwd=WORKTREE_ROOT,
        )
        assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_has_expected_top_level_keys(self, sample_session_dir: Path):
        """JSON output must contain all expected top-level keys."""
        result = run_cli(
            [
                "dashboard",
                "--format",
                "json",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
            ],
            cwd=WORKTREE_ROOT,
        )
        data = json.loads(result.stdout)
        assert EXPECTED_TOP_LEVEL_KEYS == set(data.keys())

    def test_contains_aggregated_data(self, sample_session_dir: Path):
        """JSON output must reflect the parsed session data."""
        result = run_cli(
            [
                "dashboard",
                "--format",
                "json",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
            ],
            cwd=WORKTREE_ROOT,
        )
        data = json.loads(result.stdout)
        assert data["total_tokens"] > 0
        assert data["total_sessions"] == 1
        assert "opus" in data["by_model"]
        assert "general-purpose" in data["by_agent"]
        assert len(data["sessions"]) == 1

    def test_generated_at_is_iso8601(self, sample_session_dir: Path):
        """generated_at must be a valid ISO-8601 datetime string."""
        from datetime import datetime

        result = run_cli(
            [
                "dashboard",
                "--format",
                "json",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
            ],
            cwd=WORKTREE_ROOT,
        )
        data = json.loads(result.stdout)
        # datetime.fromisoformat raises ValueError if the string is invalid
        dt = datetime.fromisoformat(data["generated_at"])
        assert dt.tzinfo is not None, "generated_at must be timezone-aware"

    def test_limits_included_when_set(self, sample_session_dir: Path):
        """When limit flags are passed, they appear in the JSON output."""
        result = run_cli(
            [
                "dashboard",
                "--format",
                "json",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
                "--limit-5h",
                "600000",
                "--limit-7d",
                "4000000",
            ],
            cwd=WORKTREE_ROOT,
        )
        data = json.loads(result.stdout)
        assert data["limits"] == {
            "limit_5h": 600000,
            "limit_7d": 4000000,
            "limit_sonnet_7d": None,
        }

    def test_limits_null_when_not_set(self, sample_session_dir: Path):
        """When no limit flags are passed, limits key is null."""
        result = run_cli(
            [
                "dashboard",
                "--format",
                "json",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
            ],
            cwd=WORKTREE_ROOT,
        )
        data = json.loads(result.stdout)
        assert data["limits"] is None

    def test_empty_data_dir_still_valid_json(self, tmp_path: Path):
        """dashboard --format json with an empty data dir must still produce valid JSON."""
        result = run_cli(
            ["dashboard", "--format", "json", "--no-open", "--data-dir", str(tmp_path)],
            cwd=WORKTREE_ROOT,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_tokens"] == 0
        assert data["total_sessions"] == 0
        assert data["sessions"] == []

    def test_does_not_write_html_file(self, sample_session_dir: Path, tmp_path: Path):
        """dashboard --format json must not write any HTML file."""
        result = run_cli(
            [
                "dashboard",
                "--format",
                "json",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
                "--output",
                str(tmp_path / "out.html"),
            ],
            cwd=WORKTREE_ROOT,
        )
        assert result.returncode == 0
        assert not (
            tmp_path / "out.html"
        ).exists(), "HTML file should not be written in json mode"


class TestFormatHtmlDefault:
    def test_default_format_is_html(self, sample_session_dir: Path, tmp_path: Path):
        """Omitting --format must produce an HTML file (original behavior)."""
        output_path = tmp_path / "dashboard.html"
        result = run_cli(
            [
                "dashboard",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
                "--output",
                str(output_path),
            ],
            cwd=WORKTREE_ROOT,
        )
        assert result.returncode == 0
        assert output_path.exists(), "HTML output file must be created"

    def test_explicit_html_format(self, sample_session_dir: Path, tmp_path: Path):
        """--format html must produce an HTML file."""
        output_path = tmp_path / "dashboard.html"
        result = run_cli(
            [
                "dashboard",
                "--format",
                "html",
                "--no-open",
                "--data-dir",
                str(sample_session_dir),
                "--output",
                str(output_path),
            ],
            cwd=WORKTREE_ROOT,
        )
        assert result.returncode == 0
        assert output_path.exists()
