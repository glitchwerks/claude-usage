"""Pure-function helper for Pattern W setup-state flag I/O.

Mirrors wayfinder's hooks/lib/setup-state.js in Python.
No subprocess. No side effects beyond get_flag_path() -> read_setup_state().

Each hook imports this module via the sys.path.insert idiom:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent / "lib"))
    import setup_state  # noqa: E402

Public API:
    read_setup_state(current_version: str) -> SetupStateResult
    get_venv_python(venv_path: Path) -> Path
    get_current_version() -> str
    get_plugin_data_dir() -> Path
    get_flag_path() -> Path
    delete_flag() -> None
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Literal, NamedTuple


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class SetupStateResult(NamedTuple):
    """Result of read_setup_state().

    Attributes:
        status: One of "VALID", "MISSING", "STALE", "BROKEN".
        flag: The parsed flag dict when status is VALID or STALE;
            None otherwise.
    """

    status: Literal["VALID", "MISSING", "STALE", "BROKEN"]
    flag: dict | None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_plugin_data_dir() -> Path:
    """Return the plugin data directory.

    Honors $CLAUDE_PLUGIN_DATA when set (test seam and Anthropic harness);
    otherwise computes ~/.claude/plugins/data/{slug}/ where slug is the
    plugin ID with every character outside [a-zA-Z0-9_-] replaced by a
    hyphen.

    The prospector plugin ID is "claude-prospector@claude-prospector",
    which yields slug "claude-prospector-claude-prospector".

    Returns:
        Absolute path to the plugin data directory. Not created by this
        call.
    """
    env_override = os.environ.get("CLAUDE_PLUGIN_DATA")
    if env_override:
        return Path(env_override)
    plugin_id = "claude-prospector@claude-prospector"
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "-", plugin_id)
    return Path.home() / ".claude" / "plugins" / "data" / slug


def get_flag_path() -> Path:
    """Return the absolute path to the setup-state.json flag file.

    Always at ${CLAUDE_PLUGIN_DATA}/setup-state.json per spec D11.
    CLAUDE_PROSPECTOR_BASE_DIR does not override this location.

    Returns:
        Absolute path to setup-state.json.
    """
    return get_plugin_data_dir() / "setup-state.json"


def get_venv_python(venv_path: Path) -> Path:
    """Return the path to the venv's Python binary, platform-aware.

    Args:
        venv_path: Root path of the virtual environment.

    Returns:
        Absolute path to Scripts/python.exe on Windows,
        bin/python on POSIX.
    """
    if platform.system() == "Windows":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _get_plugin_root() -> Path:
    """Return the plugin root directory.

    Honors $CLAUDE_PLUGIN_ROOT when set (test seam and Anthropic harness);
    otherwise computes from this file's location (hooks/lib/setup_state.py
    is three levels below the plugin root).

    Returns:
        Absolute path to the plugin root.
    """
    env_override = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_override:
        return Path(env_override)
    # This file: <root>/hooks/lib/setup_state.py
    # Three levels up: setup_state.py -> lib/ -> hooks/ -> <root>/
    return Path(__file__).parent.parent.parent


def get_current_version() -> str:
    """Read the plugin version from pyproject.toml or plugin.json.

    Reads $CLAUDE_PLUGIN_ROOT (or infers root from __file__) and parses:

    1. pyproject.toml [project] version field (preferred)
    2. .claude-plugin/plugin.json version field (fallback)

    Returns:
        Version string (e.g. "0.7.0").

    Raises:
        RuntimeError: If neither file is readable or contains a version.
    """
    root = _get_plugin_root()
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        try:
            content = pyproject_path.read_text(encoding="utf-8")
            # Match version = "X.Y.Z" inside the [project] table
            match = re.search(
                r"^\[project\].*?^version\s*=\s*\"([^\"]+)\"",
                content,
                re.MULTILINE | re.DOTALL,
            )
            if match:
                return match.group(1).strip()
        except OSError:
            pass
    plugin_json_path = root / ".claude-plugin" / "plugin.json"
    if plugin_json_path.exists():
        try:
            data = json.loads(
                plugin_json_path.read_text(encoding="utf-8")
            )
            if data.get("version"):
                return str(data["version"]).strip()
        except (OSError, json.JSONDecodeError):
            pass
    raise RuntimeError(
        "Cannot resolve plugin version: pyproject.toml and plugin.json "
        "both unreadable or version-less"
    )


# ---------------------------------------------------------------------------
# Flag I/O
# ---------------------------------------------------------------------------


def read_setup_state(current_version: str) -> SetupStateResult:
    """Read and classify the setup-state.json flag.

    Classification rules (evaluated in order):

    1. Flag absent -> MISSING
    2. Flag unparseable JSON -> MISSING
    3. Flag missing required fields (version, venv_path) -> MISSING
    4. flag.version != current_version -> STALE (flag returned for banner)
    5. venv_python path does not exist -> BROKEN (flag returned for banner)
    6. All checks pass -> VALID (flag returned for venv_path use)

    Args:
        current_version: The plugin's current version string, used for
            version-match check. Pass the result of get_current_version().

    Returns:
        SetupStateResult with status and parsed flag (None when MISSING).
    """
    flag_path = get_flag_path()
    if not flag_path.exists():
        return SetupStateResult(status="MISSING", flag=None)

    try:
        flag = json.loads(flag_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(
            f"[setup-state] flag file unparseable: {exc}\n"
        )
        return SetupStateResult(status="MISSING", flag=None)

    version = flag.get("version")
    if not isinstance(version, str) or not version.strip():
        if version is not None:
            sys.stderr.write(
                "[setup-state] flag has malformed version field: "
                f"{version!r}\n"
            )
        return SetupStateResult(status="MISSING", flag=None)

    venv_path_str = flag.get("venv_path")
    if not isinstance(venv_path_str, str) or not venv_path_str.strip():
        if venv_path_str is not None:
            sys.stderr.write(
                "[setup-state] flag has malformed venv_path field: "
                f"{venv_path_str!r}\n"
            )
        return SetupStateResult(status="MISSING", flag=None)

    if version != current_version:
        return SetupStateResult(status="STALE", flag=flag)

    venv_python = get_venv_python(Path(venv_path_str))
    if not venv_python.exists():
        return SetupStateResult(status="BROKEN", flag=flag)

    return SetupStateResult(status="VALID", flag=flag)


def delete_flag() -> None:
    """Delete the setup-state.json flag file if it exists.

    Called by check-prospector-setup.py when the import probe fails on a
    previously-VALID flag (scenario D: venv corruption). Silently no-ops
    if the flag is already absent.
    """
    flag_path = get_flag_path()
    try:
        flag_path.unlink(missing_ok=True)
    except OSError as exc:
        sys.stderr.write(
            f"[setup-state] failed to delete flag: {exc}\n"
        )
