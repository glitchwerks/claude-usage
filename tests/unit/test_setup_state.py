"""Unit tests for hooks/lib/setup_state.py.

12 cases mirroring WAYFINDER-SPEC § 7 helper-unit-tests.
$CLAUDE_PLUGIN_DATA is always set to a fresh tmp_path — this redirects
BOTH the flag path and all runtime artifacts (via the three-tier _base_dir()
resolver). Do not fight this; it is the intended test isolation mechanism.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import pytest

# Allow import from hooks/lib without installing.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks" / "lib"))
import setup_state  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def plugin_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh temp dir as $CLAUDE_PLUGIN_DATA for one test."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    return tmp_path


@pytest.fixture()
def plugin_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set $CLAUDE_PLUGIN_ROOT to the repo root so get_current_version() finds pyproject.toml."""
    root = Path(__file__).parent.parent.parent
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    return root


def _write_flag(plugin_data: Path, data: dict) -> None:
    """Write setup-state.json into plugin_data."""
    flag_path = plugin_data / "setup-state.json"
    flag_path.write_text(json.dumps(data), encoding="utf-8")


def _make_fake_venv(plugin_data: Path) -> Path:
    """Create a fake venv dir with the platform-appropriate python binary."""
    venv_dir = plugin_data / "venv"
    if platform.system() == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.touch()
    return venv_dir


# ---------------------------------------------------------------------------
# Case 1: Flag missing
# ---------------------------------------------------------------------------


def test_flag_missing(plugin_data: Path) -> None:
    result = setup_state.read_setup_state("0.7.0")
    assert result.status == "MISSING"
    assert result.flag is None


# ---------------------------------------------------------------------------
# Case 2: Flag exists but unparseable JSON
# ---------------------------------------------------------------------------


def test_flag_unparseable(plugin_data: Path) -> None:
    (plugin_data / "setup-state.json").write_text("not json {{", encoding="utf-8")
    result = setup_state.read_setup_state("0.7.0")
    assert result.status == "MISSING"


# ---------------------------------------------------------------------------
# Case 3: Flag parseable but version field missing
# ---------------------------------------------------------------------------


def test_flag_missing_version_field(plugin_data: Path) -> None:
    _write_flag(plugin_data, {"venv_path": "/some/venv", "interpreter": "python3", "installed_at": "2026-01-01T00:00:00Z"})
    result = setup_state.read_setup_state("0.7.0")
    assert result.status == "MISSING"


# ---------------------------------------------------------------------------
# Case 4: Flag valid, version matches, venv path exists, venv-python exists
# ---------------------------------------------------------------------------


def test_flag_valid(plugin_data: Path) -> None:
    venv_dir = _make_fake_venv(plugin_data)
    _write_flag(plugin_data, {
        "version": "0.7.0",
        "venv_path": str(venv_dir),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    result = setup_state.read_setup_state("0.7.0")
    assert result.status == "VALID"
    assert result.flag is not None
    assert result.flag["version"] == "0.7.0"


# ---------------------------------------------------------------------------
# Case 5: Flag valid, version mismatch -> STALE
# ---------------------------------------------------------------------------


def test_flag_stale_version(plugin_data: Path) -> None:
    venv_dir = _make_fake_venv(plugin_data)
    _write_flag(plugin_data, {
        "version": "0.6.0",
        "venv_path": str(venv_dir),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    result = setup_state.read_setup_state("0.7.0")
    assert result.status == "STALE"
    assert result.flag is not None


# ---------------------------------------------------------------------------
# Case 6: Flag valid, version matches, venv path doesn't exist -> BROKEN
# ---------------------------------------------------------------------------


def test_flag_broken_venv_path_missing(plugin_data: Path) -> None:
    _write_flag(plugin_data, {
        "version": "0.7.0",
        "venv_path": str(plugin_data / "nonexistent_venv"),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    result = setup_state.read_setup_state("0.7.0")
    assert result.status == "BROKEN"


# ---------------------------------------------------------------------------
# Case 7: Flag valid, version matches, venv dir exists but python binary missing -> BROKEN
# ---------------------------------------------------------------------------


def test_flag_broken_venv_python_missing(plugin_data: Path) -> None:
    venv_dir = plugin_data / "venv"
    venv_dir.mkdir()
    # Do NOT create the python binary — venv dir exists, python doesn't
    _write_flag(plugin_data, {
        "version": "0.7.0",
        "venv_path": str(venv_dir),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    result = setup_state.read_setup_state("0.7.0")
    assert result.status == "BROKEN"


# ---------------------------------------------------------------------------
# Case 8: get_current_version() reads pyproject.toml correctly
# ---------------------------------------------------------------------------


def test_get_current_version_from_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "claude-prospector"\nversion = "0.7.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    version = setup_state.get_current_version()
    assert version == "0.7.0"


# ---------------------------------------------------------------------------
# Case 9: get_current_version() falls back to plugin.json
# ---------------------------------------------------------------------------


def test_get_current_version_fallback_to_plugin_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No pyproject.toml at all
    claude_plugin = tmp_path / ".claude-plugin"
    claude_plugin.mkdir()
    (claude_plugin / "plugin.json").write_text(
        json.dumps({"version": "0.7.0"}), encoding="utf-8"
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    version = setup_state.get_current_version()
    assert version == "0.7.0"


# ---------------------------------------------------------------------------
# Case 10: get_plugin_data_dir() honors $CLAUDE_PLUGIN_DATA
# ---------------------------------------------------------------------------


def test_get_plugin_data_dir_env_override(plugin_data: Path) -> None:
    result = setup_state.get_plugin_data_dir()
    assert result == plugin_data


# ---------------------------------------------------------------------------
# Case 11: get_venv_python() returns Scripts/python.exe on Windows
# ---------------------------------------------------------------------------


def test_get_venv_python_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    venv_dir = Path("/fake/venv")
    result = setup_state.get_venv_python(venv_dir)
    assert result == venv_dir / "Scripts" / "python.exe"


# ---------------------------------------------------------------------------
# Case 12: get_venv_python() returns bin/python on POSIX
# ---------------------------------------------------------------------------


def test_get_venv_python_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    venv_dir = Path("/fake/venv")
    result = setup_state.get_venv_python(venv_dir)
    assert result == venv_dir / "bin" / "python"
