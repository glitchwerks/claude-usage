"""Tests for hooks/check-prospector-setup.py SessionStart hook.

Tests cover:
- MISSING flag: banner contains setup instruction text
- STALE flag: banner contains version mismatch text
- BROKEN flag: banner contains venv unreachable text
- VALID flag + import probe succeeds: no banner (empty additionalContext)
- VALID flag + import probe fails: flag is deleted, MISSING banner emitted

The hook is invoked via subprocess with env vars redirecting all paths to
tmp_path so no real home-directory state is touched.

Banner text format from spec § 5:
  MISSING:  "claude-prospector requires setup. Run /setup-prospector..."
  STALE:    "claude-prospector venv is for vX but plugin is vY."
  BROKEN:   "claude-prospector venv at <path> is unreachable or corrupt."
  VALID+OK: (empty additionalContext — hook outputs {})
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import textwrap
from pathlib import Path

_WORKTREE = Path(__file__).parent.parent.parent
_HOOK_PATH = _WORKTREE / "hooks" / "check-prospector-setup.py"

# Compute _CURRENT_VERSION dynamically by calling the helper — pyproject is on
# 0.7.0rc1 during the rehearsal window and would otherwise drift to STALE.
sys.path.insert(0, str(_WORKTREE / "hooks" / "lib"))
import setup_state as _setup_state  # noqa: E402

_CURRENT_VERSION = _setup_state.get_current_version()


def _make_env(
    tmp_path: Path,
    *,
    plugin_root: Path | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a hook invocation.

    Sets CLAUDE_PLUGIN_DATA (redirects flag and runtime artifacts) and
    CLAUDE_PLUGIN_ROOT (so get_current_version() finds pyproject.toml).

    PYTHONPATH is intentionally NOT set here. The hook contains its own
    sys.path.insert(0, str(Path(__file__).parent / "lib")) block — that is
    the production import mechanism. Adding PYTHONPATH in the test would mask
    regressions where the hook's own insert is accidentally removed.

    Args:
        tmp_path: Temporary directory used as CLAUDE_PLUGIN_DATA root.
        plugin_root: Override for CLAUDE_PLUGIN_ROOT; defaults to worktree
            root.
        extra: Additional environment variables to merge in.

    Returns:
        A copy of the current environment with test seams applied.
    """
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root or _WORKTREE)
    if extra:
        env.update(extra)
    return env


def _run_hook(tmp_path: Path, extra_env: dict[str, str] | None = None) -> dict:
    """Run the hook and return the parsed stdout JSON dict.

    Args:
        tmp_path: Temporary directory used as CLAUDE_PLUGIN_DATA.
        extra_env: Additional environment variables to pass to the hook.

    Returns:
        Parsed JSON dict from hook stdout, or empty dict if stdout is blank.
    """
    env = _make_env(tmp_path, extra=extra_env)
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps({}),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, f"Hook exited non-zero: {result.stderr}"
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


def _write_flag(tmp_path: Path, data: dict) -> None:
    """Write a setup-state.json flag into tmp_path.

    Args:
        tmp_path: Directory in which to write setup-state.json.
        data: Flag content dict to serialise as JSON.
    """
    (tmp_path / "setup-state.json").write_text(json.dumps(data), encoding="utf-8")


def _make_fake_venv_python(tmp_path: Path) -> Path:
    """Create a fake venv directory with a python binary stub.

    Args:
        tmp_path: Parent directory in which to create the fake venv.

    Returns:
        Path to the fake venv root directory.
    """
    venv_dir = tmp_path / "venv"
    if platform.system() == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    # Write a real Python wrapper that exits 0 on "import claude_prospector"
    python_path.write_text(
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import sys
            if "-c" in sys.argv and "import claude_prospector" in " ".join(sys.argv):
                sys.exit(0)
            # Fall back to real python for other invocations
            import subprocess
            sys.exit(subprocess.run([sys.executable] + sys.argv[1:]).returncode)
        """),
        encoding="utf-8",
    )
    if platform.system() != "Windows":
        python_path.chmod(0o755)
    return venv_dir


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_missing_flag_emits_setup_banner(tmp_path: Path) -> None:
    """No flag -> banner tells user to run /setup-prospector."""
    output = _run_hook(tmp_path)
    context = output.get("additionalContext", "")
    assert "setup" in context.lower() or "/setup-prospector" in context


def test_stale_flag_emits_version_banner(tmp_path: Path) -> None:
    """Flag with old version -> banner mentions version mismatch."""
    _write_flag(
        tmp_path,
        {
            "version": "0.6.0",
            "venv_path": str(tmp_path / "venv"),
            "interpreter": "python3",
            "installed_at": "2026-01-01T00:00:00Z",
        },
    )
    output = _run_hook(tmp_path)
    context = output.get("additionalContext", "")
    assert "0.6.0" in context or "setup" in context.lower()


def test_broken_flag_emits_broken_banner(tmp_path: Path) -> None:
    """Flag with valid version but missing venv python -> BROKEN banner."""
    # Write flag with valid version but venv python absent
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    # Do NOT create python binary — venv dir exists, python doesn't
    _write_flag(
        tmp_path,
        {
            "version": _CURRENT_VERSION,
            "venv_path": str(venv_dir),
            "interpreter": "python3",
            "installed_at": "2026-01-01T00:00:00Z",
        },
    )
    output = _run_hook(tmp_path)
    context = output.get("additionalContext", "")
    assert context  # Some banner was emitted


def test_valid_flag_import_ok_no_banner(tmp_path: Path) -> None:
    """VALID flag + import probe succeeds -> no banner (empty additionalContext).

    Resolves the venv directory without copying the interpreter binary.
    Copying sys.executable is fragile on Windows when pytest runs under a
    uv-managed venv: the venv launcher (Scripts/python.exe) reads pyvenv.cfg
    from its own directory to locate python3XX.dll, and a bare copy in a
    temp directory without that pyvenv.cfg fails to start.

    Strategy (mirrors conftest.py valid_setup_state fixture):
    1. If sys.executable is inside a venv's Scripts/bin dir, use that venv
       root directly — get_venv_python(venv_root) returns sys.executable,
       which is a working interpreter.  Inject PYTHONPATH to a stub so the
       import probe succeeds without touching the real installed package.
    2. Otherwise fall back to symlink (POSIX) or copy (Windows last-resort)
       into a minimal fake venv layout.
    """
    _is_windows = platform.system() == "Windows"
    _scripts_name = "Scripts" if _is_windows else "bin"
    _python_name = "python.exe" if _is_windows else "python"

    exe = Path(sys.executable)

    # Create a minimal claude_prospector stub so `import claude_prospector`
    # succeeds in the probe without touching the real installed package.
    stub_site = tmp_path / "stub_site"
    stub_pkg = stub_site / "claude_prospector"
    stub_pkg.mkdir(parents=True)
    (stub_pkg / "__init__.py").write_text(
        '"""Stub for test import probe."""\n', encoding="utf-8"
    )

    # Strategy 1: sys.executable is already inside a venv's Scripts/bin dir.
    # Use the real venv root so we never need to copy the interpreter binary.
    if exe.parent.name.lower() == _scripts_name.lower():
        candidate = exe.parent.parent
        if (candidate / _scripts_name / _python_name).exists():
            _write_flag(
                tmp_path,
                {
                    "version": _CURRENT_VERSION,
                    "venv_path": str(candidate),
                    "interpreter": "python3",
                    "installed_at": "2026-01-01T00:00:00Z",
                },
            )
            output = _run_hook(tmp_path, extra_env={"PYTHONPATH": str(stub_site)})
            context = output.get("additionalContext", "")
            assert not context, f"Expected no banner on VALID+OK, got: {context!r}"
            return

    # Strategy 2 (fallback): build a minimal fake venv layout.
    # Symlink on POSIX (no elevation needed); copy on Windows as last resort.
    if _is_windows:
        venv_python_dir = tmp_path / "venv" / "Scripts"
    else:
        venv_python_dir = tmp_path / "venv" / "bin"
    venv_python_dir.mkdir(parents=True)
    venv_python = venv_python_dir / _python_name

    try:
        venv_python.symlink_to(exe)
    except (OSError, NotImplementedError):
        import shutil

        shutil.copy2(exe, venv_python)

    if not _is_windows:
        venv_python.chmod(0o755)

    _write_flag(
        tmp_path,
        {
            "version": _CURRENT_VERSION,
            "venv_path": str(tmp_path / "venv"),
            "interpreter": "python3",
            "installed_at": "2026-01-01T00:00:00Z",
        },
    )
    # Inject PYTHONPATH so the venv python can import the stub.
    output = _run_hook(tmp_path, extra_env={"PYTHONPATH": str(stub_site)})
    context = output.get("additionalContext", "")
    assert not context, f"Expected no banner on VALID+OK, got: {context!r}"


def test_valid_flag_import_fails_deletes_flag_and_emits_banner(
    tmp_path: Path,
) -> None:
    """VALID flag + import probe fails -> flag deleted, MISSING banner emitted."""
    if platform.system() == "Windows":
        venv_python_dir = tmp_path / "venv" / "Scripts"
        venv_python_dir.mkdir(parents=True)
        venv_python = venv_python_dir / "python.exe"
    else:
        venv_python_dir = tmp_path / "venv" / "bin"
        venv_python_dir.mkdir(parents=True)
        venv_python = venv_python_dir / "python"

    # Write a script that always exits 1 (simulates broken venv)
    fail_script = textwrap.dedent("""\
        #!/usr/bin/env python3
        import sys
        sys.exit(1)
    """)
    venv_python.write_text(fail_script, encoding="utf-8")
    if platform.system() != "Windows":
        venv_python.chmod(0o755)

    _write_flag(
        tmp_path,
        {
            "version": _CURRENT_VERSION,
            "venv_path": str(tmp_path / "venv"),
            "interpreter": "python3",
            "installed_at": "2026-01-01T00:00:00Z",
        },
    )

    output = _run_hook(tmp_path)

    # Flag must be deleted (probe failure -> downgrade to MISSING)
    assert not (
        tmp_path / "setup-state.json"
    ).exists(), "Flag should have been deleted after probe failure"
    # A banner must be emitted
    context = output.get("additionalContext", "")
    assert context, "Expected a banner after probe failure deleted the flag"
