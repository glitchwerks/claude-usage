"""Regression test: dashboard JSON output is byte-identical after refactor.

Compares 'claude-usage dashboard --format json' output against the
snapshot captured on main before the subparser refactor (Phase 0).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "session_summaries"
    / "dashboard_baseline_input"
)
SNAPSHOT_FILE = (
    Path(__file__).parent / "fixtures" / "dashboard_snapshot_pre_refactor.json"
)


def test_existing_dashboard_unchanged() -> None:
    """dashboard --format json output must be byte-identical to pre-refactor.

    Runs the dashboard subcommand against the committed minimal fixture
    tree and compares stdout to the snapshot captured on main before the
    refactor. Any diff indicates a behavior regression in the refactor.

    Note: generated_at will differ between runs (it is the current
    timestamp). The comparison therefore normalises that field to a
    fixed sentinel before comparing, so only structural/data differences
    trigger a failure.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "claude_usage",
            "dashboard",
            "--from",
            "2026-01-01",
            "--to",
            "2026-12-31",
            "--format",
            "json",
            "--data-dir",
            str(FIXTURE_DIR),
        ],
        capture_output=True,
        text=True,
    )
    assert (
        result.returncode == 0
    ), f"dashboard exited {result.returncode}.\nstderr: {result.stderr}"

    actual = json.loads(result.stdout)
    expected = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))

    # Normalise the timestamp field — it will differ between runs.
    actual["generated_at"] = "__normalised__"
    expected["generated_at"] = "__normalised__"

    assert actual == expected, (
        "Dashboard JSON output differs from pre-refactor snapshot.\n"
        "If this is intentional, re-capture the snapshot (Phase 0 Task 0 "
        "Step 2) and commit the updated file."
    )
