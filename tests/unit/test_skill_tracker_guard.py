"""Tests for the Pattern W guard added to hooks/skill-tracker.py.

Two cases:
- Non-VALID state (no flag): hook exits 0 and produces no tracking output.
- VALID state (flag + fake venv python): hook proceeds to main() logic
  (emits tracking events when given a proper Skill payload).

The hook is invoked as a subprocess. CLAUDE_PLUGIN_DATA is redirected to
a fresh tmp_path. CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR is redirected to
a separate tmp_path subdirectory so tracking files don't land in real dirs.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

_WORKTREE = Path(__file__).parent.parent.parent
_HOOK_PATH = _WORKTREE / "hooks" / "skill-tracker.py"

# Resolve current version dynamically so VALID-flag tests aren't classified
# STALE when pyproject.toml contains a pre-release version (e.g. 0.7.0rc1).
sys.path.insert(0, str(_WORKTREE / "hooks" / "lib"))
import setup_state as _setup_state  # noqa: E402

_CURRENT_VERSION = _setup_state.get_current_version()


def _make_env(tmp_path: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build subprocess environment for hook invocation.

    Args:
        tmp_path: Temporary directory for test isolation.
        extra: Optional additional environment variables.

    Returns:
        Environment dict with all CLAUDE_PROSPECTOR_* vars redirected to
        tmp_path.
    """
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(_WORKTREE)
    env["CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR"] = str(tmp_path / "skill-tracking")
    env["CLAUDE_PROSPECTOR_HOOK_LOG"] = str(tmp_path / "hook.log")
    hooks_lib = str(_WORKTREE / "hooks" / "lib")
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = hooks_lib + (
        os.pathsep + existing_path if existing_path else ""
    )
    if extra:
        env.update(extra)
    return env


def _write_flag(tmp_path: Path, data: dict) -> None:
    """Write a setup-state.json flag to tmp_path.

    Args:
        tmp_path: Directory to write the flag into.
        data: Flag content to serialize as JSON.
    """
    (tmp_path / "setup-state.json").write_text(json.dumps(data), encoding="utf-8")


def _make_fake_venv(tmp_path: Path) -> Path:
    """Create a venv dir with a stub python binary that passes exists() check.

    Args:
        tmp_path: Base directory for the fake venv.

    Returns:
        Path to the fake venv root directory.
    """
    venv_dir = tmp_path / "venv"
    if platform.system() == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.touch()
    return venv_dir


def _run_hook(
    tmp_path: Path,
    payload: dict,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Invoke skill-tracker.py as a subprocess.

    Args:
        tmp_path: Temporary directory for env isolation.
        payload: JSON payload dict to write to stdin.
        extra_env: Optional additional environment overrides.

    Returns:
        CompletedProcess with returncode, stdout, and stderr.
    """
    env = _make_env(tmp_path, extra=extra_env)
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def test_non_valid_state_exits_silent(tmp_path: Path) -> None:
    """No flag -> hook exits 0 and writes no tracking file."""
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "some-skill"},
        "session_id": "test-session",
    }
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0
    tracking_dir = tmp_path / "skill-tracking"
    if tracking_dir.exists():
        jsonl_files = list(tracking_dir.glob("*.jsonl"))
        assert (
            not jsonl_files
        ), "No tracking files should be written when state is non-VALID"


def test_valid_state_allows_tracking(tmp_path: Path) -> None:
    """VALID flag -> hook proceeds and writes a tracking event for Skill call.

    Using tool_name="Skill" is deliberate: the Skill path in main() records
    the event directly without consulting _get_allowlist() — allowlist
    filtering only applies to Agent dispatch. This means "some-skill" does
    not need to be in the filesystem allowlist; the test is not brittle
    against the allowlist content.
    """
    venv_dir = _make_fake_venv(tmp_path)
    _write_flag(
        tmp_path,
        {
            "version": _CURRENT_VERSION,
            "venv_path": str(venv_dir),
            "interpreter": "python3",
            "installed_at": "2026-01-01T00:00:00Z",
        },
    )
    # CLAUDE_PLUGIN_ROOT is set in _make_env to _WORKTREE so
    # get_current_version() reads pyproject.toml and returns the same version
    # as _CURRENT_VERSION (matching the flag version -> VALID).
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "some-skill"},
        "session_id": "test-session",
    }
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0
    tracking_dir = tmp_path / "skill-tracking"
    jsonl_files = list(tracking_dir.glob("*.jsonl")) if tracking_dir.exists() else []
    assert jsonl_files, "Tracking file should be written when state is VALID"
    events = [
        json.loads(line)
        for line in jsonl_files[0].read_text().splitlines()
        if line.strip()
    ]
    assert any(
        e.get("event") == "skill_invoked" and e.get("skill") == "some-skill"
        for e in events
    )
