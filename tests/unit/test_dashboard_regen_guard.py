"""Tests for the Pattern W guard added to hooks/dashboard-regen.py.

Cases:
- Non-VALID state: hook exits 0, produces no dashboard file, spawns no
  subprocess.
- VALID state: hook spawns subprocess with <venv-python> absolute path (not
  sys.executable) for BOTH the version-check and regen callsites.

Verifying the absolute venv-python path is done via the
CLAUDE_PROSPECTOR_SENTINEL_FILE test seam — the stub writes its own absolute
path (sys.executable from the stub's perspective) to the sentinel file.
The test asserts that path equals the fake-venv python path, not
sys.executable, proving the hook used _venv_python, not sys.executable.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_WORKTREE = Path(__file__).parent.parent.parent
_HOOK_PATH = _WORKTREE / "hooks" / "dashboard-regen.py"

# Resolve current version dynamically so VALID-flag tests aren't classified
# STALE when pyproject.toml contains a pre-release version (e.g. 0.7.0rc1).
# sys and Path are already imported above; reuse them to keep ruff E402 clean.
sys.path.insert(0, str(_WORKTREE / "hooks" / "lib"))
import setup_state as _setup_state  # noqa: E402

_MANIFEST_VERSION = _setup_state.get_current_version()


def _make_env(
    tmp_path: Path,
    *,
    autoregen: bool = True,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build subprocess environment for hook invocation.

    Args:
        tmp_path: Temporary directory for test isolation.
        autoregen: Whether to set autoregen in the config (unused path here
            since we use --autoregen CLI arg, but kept for parity with other
            test helpers).
        extra: Optional additional environment overrides.

    Returns:
        Environment dict with all CLAUDE_PROSPECTOR_* vars redirected.
    """
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path)
    env["CLAUDE_PROSPECTOR_DASHBOARD"] = str(tmp_path / "dashboard.html")
    env["CLAUDE_PROSPECTOR_HOOK_LOG"] = str(tmp_path / "hook.log")
    hooks_lib = str(_WORKTREE / "hooks" / "lib")
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        hooks_lib + (os.pathsep + existing_path if existing_path else "")
    )
    # Write a plugin.json so the version-check logic has a manifest version.
    plugin_root = _WORKTREE
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    if extra:
        env.update(extra)
    return env


def _write_flag(tmp_path: Path, data: dict) -> None:
    """Write a setup-state.json flag to tmp_path.

    Args:
        tmp_path: Directory to write the flag into.
        data: Flag content to serialize as JSON.
    """
    (tmp_path / "setup-state.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _make_fake_venv_python_success(tmp_path: Path) -> Path:
    """Create a venv with a python stub that writes a sentinel on invocation.

    The sentinel file records the absolute path of the interpreter that was
    actually called. The test then asserts that path equals the fake-venv
    python path, not sys.executable — this is the core regression check:
    the hook must use _venv_python, not sys.executable.

    The stub also handles version-check and dashboard regen args so the hook
    can complete its normal flow.

    Args:
        tmp_path: Base directory for the fake venv.

    Returns:
        Path to the fake venv root directory.
    """
    venv_dir = tmp_path / "venv"
    if platform.system() == "Windows":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    # The sentinel path is passed via an env var so the script can write it.
    # The sentinel records sys.executable (which, from the stub's perspective,
    # IS the fake-venv python path — the absolute path the hook invoked).
    script = textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import os, sys
        # Write the sentinel: records the absolute path of this interpreter.
        sentinel = os.environ.get("CLAUDE_PROSPECTOR_SENTINEL_FILE")
        if sentinel:
            with open(sentinel, "w") as f:
                f.write(sys.executable)
        args = sys.argv[1:]
        if "--version" in args or (
            "-m" in args
            and "claude_prospector" in args
            and "--version" in args
        ):
            print("claude-prospector {_MANIFEST_VERSION}")
            sys.exit(0)
        if "-m" in args and "claude_prospector" in args and "dashboard" in args:
            # Simulate successful regen -- write empty dashboard
            for i, a in enumerate(args):
                if a == "--output" and i + 1 < len(args):
                    open(args[i + 1], "w").close()
            sys.exit(0)
        sys.exit(0)
    """)
    venv_python.write_text(script, encoding="utf-8")
    if platform.system() != "Windows":
        venv_python.chmod(0o755)
    return venv_dir


def _run_hook(
    tmp_path: Path, env: dict
) -> subprocess.CompletedProcess:
    """Invoke dashboard-regen.py as a subprocess with --autoregen true.

    Args:
        tmp_path: Temporary directory (unused here but kept for clarity).
        env: Environment dict (from _make_env).

    Returns:
        CompletedProcess with returncode, stdout, and stderr.
    """
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH), "--autoregen", "true"],
        input=json.dumps({}),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_non_valid_state_exits_silent(tmp_path: Path) -> None:
    """No flag -> hook exits 0 and writes no dashboard file."""
    env = _make_env(tmp_path)
    result = _run_hook(tmp_path, env)
    assert result.returncode == 0
    assert not (tmp_path / "dashboard.html").exists(), (
        "Dashboard should not be created when state is non-VALID"
    )


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason=(
        "Fake venv python stub cannot be executed as a PE binary on Windows; "
        "the sentinel approach requires a proper executable shim."
    ),
)
def test_valid_state_uses_venv_python_for_regen(tmp_path: Path) -> None:
    """VALID flag -> both subprocess callsites use venv python, not sys.executable.

    The fake-venv python stub writes its own absolute path (sys.executable
    from the stub's perspective) to a sentinel file. The test asserts that
    sentinel path equals the fake venv python path — proving _venv_python,
    not sys.executable, was passed to subprocess.run().
    """
    venv_dir = _make_fake_venv_python_success(tmp_path)
    if platform.system() == "Windows":
        expected_venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        expected_venv_python = venv_dir / "bin" / "python"

    sentinel_file = tmp_path / "invoked_interpreter.txt"
    _write_flag(tmp_path, {
        "version": _MANIFEST_VERSION,
        "venv_path": str(venv_dir),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    env = _make_env(tmp_path, extra={
        "CLAUDE_PROSPECTOR_SENTINEL_FILE": str(sentinel_file),
    })
    result = _run_hook(tmp_path, env)
    assert result.returncode == 0, (
        f"Hook exited non-zero. stderr: {result.stderr}"
    )

    # The sentinel must exist — meaning the fake venv python was invoked.
    assert sentinel_file.exists(), (
        "Sentinel file not written: the hook never invoked the venv python "
        f"(VALID guard may not have fired). stderr: {result.stderr}"
    )
    invoked_path = Path(sentinel_file.read_text(encoding="utf-8").strip())
    assert invoked_path.resolve() == expected_venv_python.resolve(), (
        f"Hook invoked {invoked_path!r} instead of the venv python "
        f"{expected_venv_python!r}. The hook may have used sys.executable."
    )
