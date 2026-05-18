# Pattern W Adoption for claude-prospector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Pattern W to claude-prospector so every hook gates subprocess work behind a `setup-state.json` flag that records the plugin-owned venv path, eliminating the brittle `Path(sys.executable).parent.parent.parent` CWD inference and ensuring hooks never spawn Python without a verified install.

**Architecture:** A new `hooks/lib/setup_state.py` helper provides pure-function flag I/O; a new `SessionStart` hook (`hooks/check-prospector-setup.py`) runs the per-session import probe and emits banners; the two existing hooks gain a cheap `read_setup_state()` guard at the top of `main()`; a user-invoked `/setup-prospector` skill materialises the plugin-owned venv and writes the flag. Tests cover the helper (12 unit cases), the hooks (guard + banner behaviour), the full pipeline (integration smoke), and skill/pipeline drift (sync check).

**Tech Stack:** Python 3.10+, pytest, `python -m venv`, `python -m pip`, GitHub Actions, SKILL.md frontmatter format.

---

## File Map

| File | Action | Task |
|------|--------|------|
| `hooks/lib/__init__.py` | Create (empty, makes `lib/` a package for import) | AC3 |
| `hooks/lib/setup_state.py` | Create — pure-function helper, ~150 LOC | AC3 |
| `tests/__init__.py` | Already exists | — |
| `tests/unit/__init__.py` | Create (empty) | AC3 |
| `tests/unit/test_setup_state.py` | Create — 12 unit cases | AC3 |
| `skills/setup-prospector/SKILL.md` | Create — 8-step skill body | AC2 |
| `tests/integration/__init__.py` | Create (empty) | AC2 |
| `tests/integration/setup_pipeline.py` | Create — executable mirror of 8 steps | AC2 |
| `tests/integration/test_setup_skill.py` | Create — e2e smoke | AC2 |
| `tests/test_skill_pipeline_sync.py` | Create — drift guard | AC2 |
| `hooks/check-prospector-setup.py` | Create — SessionStart hook | AC4 |
| `tests/unit/test_check_prospector_setup.py` | Create — banner + probe-fail tests | AC4 |
| `hooks/hooks.json` | Modify — add SessionStart entry | AC4 |
| `hooks/skill-tracker.py` | Modify — add guard at top of `main()` | AC5 |
| `hooks/dashboard-regen.py` | Modify — add guard, rewire both subprocess callsites | AC5 |
| `tests/unit/test_skill_tracker_guard.py` | Create | AC5 |
| `tests/unit/test_dashboard_regen_guard.py` | Create | AC5 |
| `.github/workflows/ci.yml` | Modify — add `skill-smoke-{ubuntu,windows}` jobs | AC6 |
| `README.md` | Modify — add "First-run setup" section | AC6 |
| `CHANGELOG.md` | Modify — add v0.7.0 entry | AC6 |
| `pyproject.toml` | Modify — bump version to `0.7.0` | AC6 |
| `.claude-plugin/plugin.json` | Modify — bump version to `0.7.0` | AC6 |

---

## Key Invariants (read before implementing any task)

1. **`$CLAUDE_PLUGIN_DATA`** is always the flag root. `setup-state.json` lives at `$CLAUDE_PLUGIN_DATA/setup-state.json`. The three-tier `_base_dir()` in existing hooks governs **runtime artifacts** only and is left untouched.
2. **Setting `$CLAUDE_PLUGIN_DATA` in tests** redirects both the flag path AND runtime artifacts (via the existing three-tier resolver). Always set it to a fresh `tmp_path` and expect all state files there.
3. **`sys.path.insert` idiom** — every hook that imports `setup_state` starts with these three lines (before all other imports, `# noqa: E402` on the import line):
   ```python
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(__file__).parent / "lib"))
   import setup_state  # noqa: E402
   ```
4. **The `_get_allowlist()` ImportError fallback** in `skill-tracker.py` (lines 107–119) stays. Even with a VALID flag, `sys.executable` is the harness Python, not the venv Python — the import may still fail. Do not remove it.
5. **Both subprocess callsites** in `dashboard-regen.py` must be rewired: the version-check subprocess at lines 506–514 AND the regen subprocess at lines 543–560. Both drop the `cwd=` arg and replace `sys.executable` with `get_venv_python(flag.venv_path)`.
6. **Python ≥ 3.10** for the probe (prospector stays at 3.10; wayfinder uses 3.11 — do not copy the 3.11 version check).
7. **`python -m pip install`** not `uv pip install` in the setup pipeline (D13).
8. **`ensurepip` defensive step** before `pip install` in `setup_pipeline.py` (covers Windows runners where ensurepip may be disabled).
9. **F10 mid-session venv corruption** is already handled by `_regen_failed_page()` and `_get_allowlist()` fallback — do NOT add a separate recovery mechanism.

---

## Task 1 (AC3): `hooks/lib/setup_state.py` — Pure-Function Helper

**Files:**
- Create: `hooks/lib/__init__.py`
- Create: `hooks/lib/setup_state.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_setup_state.py`

### Step 1: Write the failing tests

Create `tests/unit/__init__.py` (empty):

```python
```

Create `tests/unit/test_setup_state.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/unit/test_setup_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'setup_state'` (or `ImportError`) — the helper does not exist yet.

- [ ] **Step 3: Create the empty `hooks/lib/__init__.py`**

Create `hooks/lib/__init__.py` as a truly empty file (zero bytes). This makes `hooks/lib/` a Python package. No content needed.

- [ ] **Step 4: Create `hooks/lib/setup_state.py`**

```python
"""Pure-function helper for Pattern W setup-state flag I/O.

Mirrors wayfinder's hooks/lib/setup-state.js in Python.
No subprocess. No side effects beyond get_flag_path() → read_setup_state().

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
        flag: The parsed flag dict when status is VALID or STALE; None otherwise.
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
    plugin ID with every character outside [a-zA-Z0-9_-] replaced by a hyphen.

    The prospector plugin ID is "claude-prospector@claude-prospector", which
    yields slug "claude-prospector-claude-prospector".

    Returns:
        Absolute path to the plugin data directory. Not created by this call.
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
        Absolute path to Scripts/python.exe on Windows, bin/python on POSIX.
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
    # Three levels up: setup_state.py → lib/ → hooks/ → <root>/
    return Path(__file__).parent.parent.parent


def get_current_version() -> str:
    """Read the plugin version from pyproject.toml, falling back to plugin.json.

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
            data = json.loads(plugin_json_path.read_text(encoding="utf-8"))
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
    1. Flag absent → MISSING
    2. Flag unparseable JSON → MISSING
    3. Flag missing required fields (version, venv_path) → MISSING
    4. flag.version != current_version → STALE (flag returned for banner)
    5. venv_python path does not exist → BROKEN (flag returned for banner)
    6. All checks pass → VALID (flag returned for venv_path use)

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
        sys.stderr.write(f"[setup-state] flag file unparseable: {exc}\n")
        return SetupStateResult(status="MISSING", flag=None)

    version = flag.get("version")
    if not isinstance(version, str) or not version.strip():
        if version is not None:
            sys.stderr.write(
                f"[setup-state] flag has malformed version field: {version!r}\n"
            )
        return SetupStateResult(status="MISSING", flag=None)

    venv_path_str = flag.get("venv_path")
    if not isinstance(venv_path_str, str) or not venv_path_str.strip():
        if venv_path_str is not None:
            sys.stderr.write(
                f"[setup-state] flag has malformed venv_path field: {venv_path_str!r}\n"
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
        sys.stderr.write(f"[setup-state] failed to delete flag: {exc}\n")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/unit/test_setup_state.py -v
```

Expected: 12 tests pass. Confirm each test name appears in the output.

- [ ] **Step 6: Commit**

```bash
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" add hooks/lib/__init__.py hooks/lib/setup_state.py tests/unit/__init__.py tests/unit/test_setup_state.py
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" commit -m "feat: add setup_state.py helper and unit tests (refs #107)"
```

---

## Task 2 (AC2): `/setup-prospector` Skill, Pipeline, and Sync Test

**Files:**
- Create: `skills/setup-prospector/SKILL.md`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/setup_pipeline.py`
- Create: `tests/integration/test_setup_skill.py`
- Create: `tests/test_skill_pipeline_sync.py`

- [ ] **Step 1: Write the sync test first (it will immediately fail)**

Create `tests/test_skill_pipeline_sync.py`:

```python
"""Drift guard: skill body's numbered steps must match setup_pipeline.py functions.

Fails CI if the SKILL.md steps and the executable mirror diverge.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILL_BODY = Path(__file__).parent.parent / "skills" / "setup-prospector" / "SKILL.md"
PIPELINE = Path(__file__).parent / "integration" / "setup_pipeline.py"

# Maps the human-readable step heading in the skill body to the function name
# in setup_pipeline.py. Update this map when adding/removing steps.
STEP_FUNCTION_MAP = {
    "Resolve `${CLAUDE_PLUGIN_DATA}`": "compute_plugin_data_dir",
    "Discover Python": "discover_python",
    "Wipe the existing venv": "wipe_venv",
    "Create the venv": "create_venv",
    "Install claude-prospector from PyPI": "pip_install",
    "Verify import": "verify_import",
    "Write the setup-state flag": "write_flag",
    # Step 8 (tell user) is intentionally not mirrored in the pipeline module.
}


def test_skill_body_lists_expected_step_count() -> None:
    """Skill body must contain exactly 8 sequential step headings."""
    body = SKILL_BODY.read_text(encoding="utf-8")
    step_headings = re.findall(r"^##\s+Step\s+(\d+):", body, re.MULTILINE)
    assert len(step_headings) == 8, (
        f"Expected 8 steps in skill body, found {len(step_headings)}"
    )
    assert step_headings == ["1", "2", "3", "4", "5", "6", "7", "8"], (
        "Steps should be numbered 1-8 consecutively"
    )


@pytest.mark.parametrize("step_heading,function_name", STEP_FUNCTION_MAP.items())
def test_skill_step_has_matching_function(step_heading: str, function_name: str) -> None:
    """Each skill body step heading corresponds to a function in setup_pipeline.py."""
    body = SKILL_BODY.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")
    heading_pattern = rf"^##\s+Step\s+\d+:\s+.*{re.escape(step_heading)}"
    assert re.search(heading_pattern, body, re.MULTILINE), (
        f"Step heading not found as a '## Step N:' heading in skill body: {step_heading!r}"
    )
    pattern = rf"^def\s+{re.escape(function_name)}\s*\("
    assert re.search(pattern, pipeline, re.MULTILINE), (
        f"Function {function_name}() not found in setup_pipeline.py"
    )


def test_pipeline_has_run_full_pipeline_entrypoint() -> None:
    """The executable mirror exposes run_full_pipeline() that runs all steps."""
    pipeline = PIPELINE.read_text(encoding="utf-8")
    assert re.search(r"^def\s+run_full_pipeline\s*\(", pipeline, re.MULTILINE), (
        "setup_pipeline.py should expose run_full_pipeline()"
    )
```

- [ ] **Step 2: Run sync test to verify it fails**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/test_skill_pipeline_sync.py -v
```

Expected: `FileNotFoundError` or `AssertionError` — neither `SKILL.md` nor `setup_pipeline.py` exist yet.

- [ ] **Step 3: Create `skills/setup-prospector/SKILL.md`**

```markdown
---
name: setup-prospector
description: >
  Set up claude-prospector's plugin-owned Python venv. Invoked via /setup-prospector
  or natural-language triggers: "set up claude-prospector", "install prospector
  dependencies", "prospector isn't working", "fix prospector", "repair prospector".
  Do not trigger on "dashboard", "usage analysis", or "skill adoption" — those
  are distinct skills.
triggers:
  - /setup-prospector
  - set up claude-prospector
  - install prospector dependencies
  - prospector isn't working
  - fix prospector
  - repair prospector
---

# Setup claude-prospector

This skill materialises the plugin-owned Python venv that the plugin's hooks
need to run `claude-prospector` as a subprocess. Run it once after first install
and after any plugin version update.

## Step 1: Resolve `${CLAUDE_PLUGIN_DATA}`

Read the `CLAUDE_PLUGIN_DATA` environment variable. If unset, compute the default:

```
~/.claude/plugins/data/claude-prospector-claude-prospector/
```

The slug is the plugin ID `claude-prospector@claude-prospector` with every
character outside `[a-zA-Z0-9_-]` replaced by a hyphen.

Create the directory if it does not exist.

## Step 2: Discover Python

Find a Python ≥ 3.10 interpreter using this probe chain (stop at first success):

1. `flag.interpreter` from the prior `setup-state.json` (if a flag exists from a
   previous run, try that interpreter first).
2. `$CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON` environment variable (absolute path).
3. `py -3` (Windows only).
4. `python3`
5. `python`

Probe each candidate with:
```
<candidate> -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
```

If all candidates fail, ask the user:
> "No Python ≥ 3.10 interpreter found. Please provide an absolute path to
> a Python 3.10+ executable, or set CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON."

## Step 3: Wipe the existing venv

If `${CLAUDE_PLUGIN_DATA}/venv/` exists, remove it entirely:
```
shutil.rmtree(<plugin_data>/venv)
```
This is always-wipe-first (spec D4). A partial venv from a failed previous run
is handled correctly by this unconditional removal.

## Step 4: Create the venv

```
<python_cmd> -m venv <plugin_data>/venv
```

Where `<python_cmd>` is the interpreter found in Step 2. If this fails, surface
the stderr to the user and do NOT proceed to Step 5.

## Step 5: Install claude-prospector from PyPI

First, ensure pip is available in the new venv:
```
<venv_python> -m ensurepip --upgrade
```

Then install:
```
<venv_python> -m pip install claude-prospector==<version>
```

Where `<version>` is the current plugin version (read from `pyproject.toml`
`[project].version`, falling back to `.claude-plugin/plugin.json` `version`).

If `$CLAUDE_PROSPECTOR_PIP_SPEC` is set, use its value as the entire package
spec instead of `claude-prospector==<version>` (test/dev override only).

If pip fails, surface the stderr verbatim, wipe the partial venv, and do NOT
proceed to Step 6.

## Step 6: Verify import

```
<venv_python> -c "import claude_prospector"
```

If this fails, wipe the venv and report the import error. Suggest
`pip cache purge` and retry if the error looks like a wheel issue.

## Step 7: Write the setup-state flag

Write `${CLAUDE_PLUGIN_DATA}/setup-state.json` with this shape:

```json
{
  "version": "<current_version>",
  "venv_path": "<absolute_path_to_venv_dir>",
  "interpreter": "<probe_string_from_step_2>",
  "installed_at": "<UTC_ISO_8601_timestamp>"
}
```

The `venv_path` is the absolute path to the venv root (e.g.
`C:/Users/alice/.claude/plugins/data/claude-prospector-claude-prospector/venv`).
The `interpreter` is the raw command string from Step 2 (e.g. `py -3` or
`python3`), not an absolute path, so re-setup can reuse it.

## Step 8: Tell the user

Report success:
> "Setup complete. Open a new Claude Code session to activate claude-prospector.
> The dashboard, skill-tracking, and usage-analysis features will work normally
> after the next session starts."
```

- [ ] **Step 4: Create `tests/integration/__init__.py`** (empty file)

- [ ] **Step 5: Create `tests/integration/setup_pipeline.py`**

```python
"""Executable mirror of the setup-prospector skill body.

The skill body at skills/setup-prospector/SKILL.md describes 8 numbered
steps that the LLM follows when /setup-prospector is invoked. This module
exposes each step as an importable function so CI can run the full pipeline
end-to-end on a real Python interpreter.

The skill body and this module must stay in sync — see
tests/test_skill_pipeline_sync.py for the drift check.

Test seams:
    $CLAUDE_PLUGIN_DATA     — redirects plugin_data_dir (and runtime artifacts)
    $CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON — override discovery probe
    $CLAUDE_PROSPECTOR_PIP_SPEC — replace install spec (pre-PyPI CI)
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


class SetupError(Exception):
    """Raised when a setup pipeline step cannot complete."""


def compute_plugin_data_dir(
    plugin_id: str = "claude-prospector@claude-prospector",
) -> Path:
    """Step 1: Resolve ${CLAUDE_PLUGIN_DATA} deterministically.

    Honors $CLAUDE_PLUGIN_DATA when set (test seam); otherwise computes
    ~/.claude/plugins/data/{slug}/ per spec § 4.2. The slug is derived
    by replacing every character outside [a-zA-Z0-9_-] with a hyphen.

    Args:
        plugin_id: Plugin identifier used to compute the data directory
            slug. Defaults to the canonical prospector plugin ID.

    Returns:
        Absolute path to the plugin data directory. Not created here —
        callers that need it to exist call mkdir(parents=True, exist_ok=True).
    """
    env_override = os.environ.get("CLAUDE_PLUGIN_DATA")
    if env_override:
        return Path(env_override)
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "-", plugin_id)
    return Path.home() / ".claude" / "plugins" / "data" / slug


def discover_python(prior_interpreter: str | None = None) -> str:
    """Step 2: Find a Python interpreter >= 3.10.

    Try, in order: prior_interpreter (from previous run's flag),
    $CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON, `py -3` (Windows),
    `python3`, `python`. Probe each with:
      -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"

    Args:
        prior_interpreter: Command string from a previous setup run's
            flag file (interpreter field). Tried first when provided.

    Returns:
        The first candidate command string that passes the version probe.

    Raises:
        SetupError: When all candidates fail. Set
            CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON in CI to avoid this.
    """
    candidates: list[str] = []
    if prior_interpreter:
        candidates.append(prior_interpreter)
    env_override = os.environ.get("CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON")
    if env_override:
        candidates.append(env_override)
    if platform.system() == "Windows":
        candidates.append("py -3")
    candidates.extend(["python3", "python"])

    probe = "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
    for candidate in candidates:
        try:
            args = candidate.split() + ["-c", probe]
            result = subprocess.run(args, capture_output=True, check=False, timeout=10)
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise SetupError(
        f"No Python >= 3.10 found. Tried: {candidates}. "
        "Set CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON to an absolute path."
    )


def wipe_venv(venv_dir: Path) -> None:
    """Step 3: Delete the venv directory if it exists.

    Always-wipe per spec D4. Missing directory is silently ignored.

    Args:
        venv_dir: Absolute path to the venv directory to remove.
    """
    if venv_dir.exists():
        shutil.rmtree(venv_dir)


def create_venv(python_cmd: str, venv_dir: Path) -> None:
    """Step 4: Create a fresh virtual environment.

    Runs `<python_cmd> -m venv <venv_dir>`. The command string is split
    on whitespace so multi-word forms like "py -3" work correctly.

    Args:
        python_cmd: Interpreter command string from discover_python().
        venv_dir: Destination path for the new venv. Should not already
            exist — call wipe_venv() first.

    Raises:
        SetupError: If `python -m venv` exits nonzero. Stderr and stdout
            are included so callers can surface them verbatim.
    """
    args = python_cmd.split() + ["-m", "venv", str(venv_dir)]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=60
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(venv_dir, ignore_errors=True)
        raise SetupError(f"python -m venv timed out after {exc.timeout}s") from exc
    if result.returncode != 0:
        raise SetupError(
            f"python -m venv failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def get_venv_python(venv_dir: Path) -> Path:
    """Return the path to the venv's Python binary, platform-aware.

    Args:
        venv_dir: Root path of the virtual environment.

    Returns:
        Absolute path to Scripts/python.exe on Windows, bin/python on POSIX.
    """
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def pip_install(venv_dir: Path, version: str) -> None:
    """Step 5: Install claude-prospector from PyPI into the venv.

    Runs ensurepip first (defensive step for Windows runners where the
    venv pip may be absent), then installs with `python -m pip install`
    per spec D13 (pip, not uv, for end-user portability).

    Honors $CLAUDE_PROSPECTOR_PIP_SPEC to replace the default install
    spec for pre-PyPI CI. Production always uses `claude-prospector==<version>`.

    Args:
        venv_dir: Root path of the venv created by create_venv().
        version: Exact package version string (e.g. "0.7.0").

    Raises:
        SetupError: If pip exits nonzero. Partial venv is wiped first.
    """
    venv_python = get_venv_python(venv_dir)

    # Defensive ensurepip for Windows runners (spec § 9.5)
    try:
        subprocess.run(
            [str(venv_python), "-m", "ensurepip", "--upgrade"],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # Best-effort; pip install below will surface any real failure

    pip_spec = os.environ.get(
        "CLAUDE_PROSPECTOR_PIP_SPEC",
        f"claude-prospector=={version}",
    )
    # shlex.split handles both plain specs and path/editable forms (-e /path)
    args = [str(venv_python), "-m", "pip", "install", *shlex.split(pip_spec)]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=180
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(venv_dir, ignore_errors=True)
        raise SetupError(
            f"pip install timed out after {exc.timeout}s — check network"
        ) from exc
    if result.returncode != 0:
        shutil.rmtree(venv_dir, ignore_errors=True)
        raise SetupError(
            f"pip install {pip_spec!r} failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def verify_import(venv_dir: Path) -> None:
    """Step 6: Confirm `import claude_prospector` works inside the venv.

    Args:
        venv_dir: Root path of the venv populated by pip_install().

    Raises:
        SetupError: If import fails. Venv is wiped before raising.
    """
    venv_python = get_venv_python(venv_dir)
    args = [str(venv_python), "-c", "import claude_prospector"]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=15
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(venv_dir, ignore_errors=True)
        raise SetupError(f"import check timed out after {exc.timeout}s") from exc
    if result.returncode != 0:
        shutil.rmtree(venv_dir, ignore_errors=True)
        raise SetupError(
            f"import claude_prospector failed after install:\nstderr: {result.stderr}"
        )


def write_flag(
    plugin_data_dir: Path,
    version: str,
    venv_dir: Path,
    interpreter: str,
) -> Path:
    """Step 7: Write the setup-state.json flag file.

    Creates $PLUGIN_DATA/setup-state.json with the canonical shape required
    by hooks/lib/setup_state.py's read_setup_state().

    Args:
        plugin_data_dir: Plugin data directory from compute_plugin_data_dir().
        version: Installed package version (e.g. "0.7.0").
        venv_dir: Absolute path to the created venv.
        interpreter: Command string from discover_python() (stored so
            re-setup skips discovery on the next run).

    Returns:
        Absolute path to the written flag file.
    """
    flag = {
        "version": version,
        "venv_path": str(venv_dir),
        "interpreter": interpreter,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    flag_path = plugin_data_dir / "setup-state.json"
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text(json.dumps(flag, indent=2), encoding="utf-8")
    return flag_path


def _read_plugin_version() -> str:
    """Read the plugin version from pyproject.toml in the repo root.

    Returns:
        Version string (e.g. "0.7.0").

    Raises:
        AssertionError: If the version field cannot be found.
    """
    pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(
        r"^\[project\].*?^version\s*=\s*\"([^\"]+)\"",
        content,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "Could not find version in pyproject.toml"
    return match.group(1)


def run_full_pipeline(
    version: str | None = None,
    prior_interpreter: str | None = None,
) -> Path:
    """Run all 8 steps in order.

    Step 8 (tell user) is excluded — this function is for CI; the caller
    handles success reporting.

    Args:
        version: Package version to install. If None, reads from pyproject.toml.
        prior_interpreter: Optional interpreter command from a previous flag.

    Returns:
        Absolute path to the written setup-state.json flag file.

    Raises:
        SetupError: Propagated from any step that fails.
    """
    if version is None:
        version = _read_plugin_version()
    plugin_data_dir = compute_plugin_data_dir()
    plugin_data_dir.mkdir(parents=True, exist_ok=True)
    interpreter = discover_python(prior_interpreter=prior_interpreter)
    venv_dir = plugin_data_dir / "venv"
    wipe_venv(venv_dir)
    create_venv(interpreter, venv_dir)
    pip_install(venv_dir, version)
    verify_import(venv_dir)
    return write_flag(plugin_data_dir, version, venv_dir, interpreter)
```

- [ ] **Step 6: Create `tests/integration/test_setup_skill.py`**

```python
"""End-to-end smoke test for the setup pipeline.

Runs the full 8 steps against a real Python >= 3.10 and a real PyPI
(or a local install via $CLAUDE_PROSPECTOR_PIP_SPEC). Asserts that the
venv materialises, the import works, and the flag file is shaped correctly.

Set $CLAUDE_PROSPECTOR_PIP_SPEC to the repo root path to install from a
local checkout instead of PyPI (required in CI before the package is
published to PyPI).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Use the same sys.path.insert pattern as sibling tests so pytest can collect
# this file regardless of whether the project is installed as a package.
sys.path.insert(0, str(Path(__file__).parent.parent))
from integration import setup_pipeline  # noqa: E402


@pytest.fixture()
def fake_plugin_data(monkeypatch: pytest.MonkeyPatch):
    """Provide a temp dir as $CLAUDE_PLUGIN_DATA for the duration of one test.

    Setting $CLAUDE_PLUGIN_DATA here redirects BOTH the flag path and all
    runtime artifacts (via the three-tier _base_dir() resolver). All state
    files will land under this temp dir; cleanup is automatic.

    Yields:
        Path to the temporary directory.
    """
    with tempfile.TemporaryDirectory(prefix="prospector-smoke-") as tmp:
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", tmp)
        yield Path(tmp)


def test_full_pipeline_smoke(fake_plugin_data: Path) -> None:
    """The 8-step pipeline produces a working venv with claude-prospector importable."""
    flag_path = setup_pipeline.run_full_pipeline()

    # Step 7 wrote the flag — verify shape
    assert flag_path.exists()
    flag = json.loads(flag_path.read_text(encoding="utf-8"))
    assert "version" in flag
    assert "venv_path" in flag
    assert "interpreter" in flag
    assert "installed_at" in flag

    # The venv exists at the recorded path
    venv_dir = Path(flag["venv_path"])
    assert venv_dir.exists()
    assert venv_dir.is_dir()

    # The venv Python is accessible
    venv_python = setup_pipeline.get_venv_python(venv_dir)
    assert venv_python.exists()

    # claude_prospector imports from inside the venv, not system Python
    result = subprocess.run(
        [str(venv_python), "-c", "import claude_prospector; print(claude_prospector.__file__)"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"import claude_prospector failed: {result.stderr}"
    assert str(venv_dir) in result.stdout, (
        f"Imported claude_prospector from outside the venv: {result.stdout!r}"
    )


def test_wipe_idempotent(fake_plugin_data: Path) -> None:
    """wipe_venv() is a no-op when no venv exists; removes it when it does."""
    venv_dir = fake_plugin_data / "venv"
    # No-op: directory does not exist
    setup_pipeline.wipe_venv(venv_dir)
    assert not venv_dir.exists()
    # Create then wipe
    venv_dir.mkdir()
    (venv_dir / "marker").write_text("hello", encoding="utf-8")
    setup_pipeline.wipe_venv(venv_dir)
    assert not venv_dir.exists()


def test_discover_python_finds_real_interpreter(fake_plugin_data: Path) -> None:
    """discover_python() finds the CI runner's Python >= 3.10."""
    interpreter = setup_pipeline.discover_python()
    assert interpreter, "Should find at least one Python >= 3.10 on CI"
```

- [ ] **Step 7: Run the sync test to verify it passes now**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/test_skill_pipeline_sync.py -v
```

Expected: all 9 tests pass (1 count test + 7 step-function parametrised + 1 entrypoint test).

- [ ] **Step 8: Run the integration test (skip if slow — verify it is collected)**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/integration/test_setup_skill.py --collect-only
```

Expected: 3 test items collected. (The actual `test_full_pipeline_smoke` run takes minutes; full execution is reserved for CI.)

- [ ] **Step 9: Commit**

```bash
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" add skills/setup-prospector/SKILL.md tests/integration/__init__.py tests/integration/setup_pipeline.py tests/integration/test_setup_skill.py tests/test_skill_pipeline_sync.py
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" commit -m "feat: add setup-prospector skill, pipeline, and sync test (refs #107)"
```

---

## Task 3 (AC4): `hooks/check-prospector-setup.py` — SessionStart Hook

**Files:**
- Create: `hooks/check-prospector-setup.py`
- Create: `tests/unit/test_check_prospector_setup.py`
- Modify: `hooks/hooks.json` (add SessionStart entry)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_check_prospector_setup.py`:

```python
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

import pytest

_WORKTREE = Path(__file__).parent.parent.parent
_HOOK_PATH = _WORKTREE / "hooks" / "check-prospector-setup.py"
_CURRENT_VERSION = "0.7.0"


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
    """
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root or _WORKTREE)
    if extra:
        env.update(extra)
    return env


def _run_hook(tmp_path: Path, extra_env: dict[str, str] | None = None) -> dict:
    """Run the hook and return the parsed stdout JSON dict."""
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
    (tmp_path / "setup-state.json").write_text(json.dumps(data), encoding="utf-8")


def _make_fake_venv_python(tmp_path: Path) -> Path:
    """Create a fake venv directory with a python binary stub."""
    venv_dir = tmp_path / "venv"
    if platform.system() == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    # Write a real Python wrapper that exits 0 on "import claude_prospector"
    python_path.write_text(
        textwrap.dedent(f"""\
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
    """No flag → banner tells user to run /setup-prospector."""
    output = _run_hook(tmp_path)
    context = output.get("additionalContext", "")
    assert "setup" in context.lower() or "/setup-prospector" in context


def test_stale_flag_emits_version_banner(tmp_path: Path) -> None:
    """Flag with old version → banner mentions version mismatch."""
    _write_flag(tmp_path, {
        "version": "0.6.0",
        "venv_path": str(tmp_path / "venv"),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    output = _run_hook(tmp_path)
    context = output.get("additionalContext", "")
    assert "0.6.0" in context or "setup" in context.lower()


def test_broken_flag_emits_broken_banner(tmp_path: Path) -> None:
    """Flag with valid version but missing venv python → BROKEN banner."""
    # Write flag with valid version but venv python absent
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    # Do NOT create python binary — venv dir exists, python doesn't
    _write_flag(tmp_path, {
        "version": _CURRENT_VERSION,
        "venv_path": str(venv_dir),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    output = _run_hook(tmp_path)
    context = output.get("additionalContext", "")
    assert context  # Some banner was emitted


def test_valid_flag_import_ok_no_banner(tmp_path: Path) -> None:
    """VALID flag + import probe succeeds → no banner (empty or absent additionalContext)."""
    # Use the real system python as the venv python stub
    if platform.system() == "Windows":
        venv_python_dir = tmp_path / "venv" / "Scripts"
        venv_python_dir.mkdir(parents=True)
        venv_python = venv_python_dir / "python.exe"
    else:
        venv_python_dir = tmp_path / "venv" / "bin"
        venv_python_dir.mkdir(parents=True)
        venv_python = venv_python_dir / "python"

    # Write a script that succeeds when asked to import claude_prospector
    script = textwrap.dedent("""\
        #!/usr/bin/env python3
        import sys
        args = " ".join(sys.argv)
        if "-c" in sys.argv:
            # Succeed on import probe
            sys.exit(0)
        import subprocess
        sys.exit(subprocess.run([sys.executable] + sys.argv[1:]).returncode)
    """)
    venv_python.write_text(script, encoding="utf-8")
    if platform.system() != "Windows":
        venv_python.chmod(0o755)

    _write_flag(tmp_path, {
        "version": _CURRENT_VERSION,
        "venv_path": str(tmp_path / "venv"),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    output = _run_hook(tmp_path)
    context = output.get("additionalContext", "")
    assert not context, f"Expected no banner on VALID+OK, got: {context!r}"


def test_valid_flag_import_fails_deletes_flag_and_emits_banner(tmp_path: Path) -> None:
    """VALID flag + import probe fails → flag deleted, MISSING banner emitted."""
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

    _write_flag(tmp_path, {
        "version": _CURRENT_VERSION,
        "venv_path": str(tmp_path / "venv"),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })

    output = _run_hook(tmp_path)

    # Flag must be deleted (probe failure → downgrade to MISSING)
    assert not (tmp_path / "setup-state.json").exists(), (
        "Flag should have been deleted after probe failure"
    )
    # A banner must be emitted
    context = output.get("additionalContext", "")
    assert context, "Expected a banner after probe failure deleted the flag"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/unit/test_check_prospector_setup.py -v
```

Expected: All 5 tests fail with `FileNotFoundError` (hook script does not exist yet).

- [ ] **Step 3: Create `hooks/check-prospector-setup.py`**

```python
#!/usr/bin/env python3
"""SessionStart hook: check Pattern W setup state and emit banners.

Registered as a SessionStart hook in hooks/hooks.json. Fires once at
the beginning of every session. Responsibilities:

1. Read the setup-state.json flag (MISSING / STALE / BROKEN / VALID).
2. If VALID: spawn <venv-python> -c 'import claude_prospector' as the
   per-session import probe. If the probe fails, delete the flag (downgrade
   to MISSING) then emit a MISSING banner.
3. If NOT VALID: emit an additionalContext banner describing the problem.
4. If VALID and probe passes: emit nothing (silent session).

The hook never blocks the session — all exceptions are caught and the hook
exits 0. Banners are emitted via the additionalContext output key.

Output format (printed to stdout):
    {"additionalContext": "<banner text>"}   — when setup required
    {}                                       — when setup is valid and probe passes
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import setup_state helper from hooks/lib/
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import setup_state  # noqa: E402

# ---------------------------------------------------------------------------
# Banner text
# ---------------------------------------------------------------------------

_BANNER_MISSING = (
    "claude-prospector requires setup. Run /setup-prospector to materialise "
    "the Python venv. After setup completes, open a new session to activate "
    "the dashboard, skill-tracking, and usage-analysis features."
)

_BANNER_STALE_TMPL = (
    "claude-prospector venv is for v{flag_version} but plugin is v{current_version}. "
    "Run /setup-prospector to refresh the venv."
)

_BANNER_BROKEN_TMPL = (
    "claude-prospector venv at {venv_path} is unreachable or corrupt. "
    "Run /setup-prospector to recreate it."
)


def _emit(banner: str) -> None:
    """Print an additionalContext JSON object to stdout."""
    print(json.dumps({"additionalContext": banner}))


def _emit_silent() -> None:
    """Print an empty object to stdout (no banner)."""
    print(json.dumps({}))


def main() -> int:
    """Run the SessionStart setup-state check.

    Returns:
        Always 0. Hooks must never propagate errors to the session runner.
    """
    try:
        current_version = setup_state.get_current_version()
    except Exception:
        # Cannot determine version — be silent rather than crashing the session
        _emit_silent()
        return 0

    try:
        result = setup_state.read_setup_state(current_version)
    except Exception:
        _emit_silent()
        return 0

    if result.status == "MISSING":
        _emit(_BANNER_MISSING)
        return 0

    if result.status == "STALE":
        flag_version = result.flag.get("version", "unknown") if result.flag else "unknown"
        _emit(_BANNER_STALE_TMPL.format(
            flag_version=flag_version,
            current_version=current_version,
        ))
        return 0

    if result.status == "BROKEN":
        venv_path = result.flag.get("venv_path", "<unknown>") if result.flag else "<unknown>"
        _emit(_BANNER_BROKEN_TMPL.format(venv_path=venv_path))
        return 0

    # VALID: run the per-session import probe
    assert result.status == "VALID"
    assert result.flag is not None

    venv_path = Path(result.flag["venv_path"])
    venv_python = setup_state.get_venv_python(venv_path)

    try:
        probe = subprocess.run(
            [str(venv_python), "-c", "import claude_prospector"],
            capture_output=True,
            timeout=15,
        )
        probe_ok = probe.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        probe_ok = False

    if not probe_ok:
        # Downgrade to MISSING: delete the flag and emit the MISSING banner
        setup_state.delete_flag()
        _emit(_BANNER_MISSING)
        return 0

    # All good — silent session
    _emit_silent()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Last-resort: never crash the session
        sys.exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/unit/test_check_prospector_setup.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Modify `hooks/hooks.json` to add the SessionStart entry**

The current content of `hooks/hooks.json` is:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Skill|Agent",
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/skill-tracker.py\""
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/dashboard-regen.py\" --autoregen \"${user_config.autoregen}\""
          }
        ]
      }
    ]
  }
}
```

Replace the entire file with this content (adds the SessionStart block; PreToolUse and Stop are unchanged):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/check-prospector-setup.py\""
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Skill|Agent",
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/skill-tracker.py\""
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/dashboard-regen.py\" --autoregen \"${user_config.autoregen}\""
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 6: Commit**

```bash
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" add hooks/check-prospector-setup.py hooks/hooks.json tests/unit/test_check_prospector_setup.py
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" commit -m "feat: add SessionStart hook and banner tests (refs #107)"
```

---

## Task 4 (AC5): Guard Existing Hooks — `skill-tracker.py` and `dashboard-regen.py`

**Files:**
- Modify: `hooks/skill-tracker.py` (add guard at top of `main()`, add `sys.path.insert` block)
- Modify: `hooks/dashboard-regen.py` (add guard, rewire both subprocess callsites)
- Create: `tests/unit/test_skill_tracker_guard.py`
- Create: `tests/unit/test_dashboard_regen_guard.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_skill_tracker_guard.py`:

```python
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
import textwrap
from pathlib import Path

import pytest

_WORKTREE = Path(__file__).parent.parent.parent
_HOOK_PATH = _WORKTREE / "hooks" / "skill-tracker.py"


def _make_env(tmp_path: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(_WORKTREE)
    env["CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR"] = str(tmp_path / "skill-tracking")
    env["CLAUDE_PROSPECTOR_HOOK_LOG"] = str(tmp_path / "hook.log")
    hooks_lib = str(_WORKTREE / "hooks" / "lib")
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = hooks_lib + (os.pathsep + existing_path if existing_path else "")
    if extra:
        env.update(extra)
    return env


def _write_flag(tmp_path: Path, data: dict) -> None:
    (tmp_path / "setup-state.json").write_text(json.dumps(data), encoding="utf-8")


def _make_fake_venv(tmp_path: Path) -> Path:
    """Create a venv dir with a stub python binary that passes the exists() check."""
    venv_dir = tmp_path / "venv"
    if platform.system() == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.touch()
    return venv_dir


def _run_hook(tmp_path: Path, payload: dict, extra_env: dict | None = None) -> subprocess.CompletedProcess:
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
    """No flag → hook exits 0 and writes no tracking file."""
    payload = {"tool_name": "Skill", "tool_input": {"skill": "some-skill"}, "session_id": "test-session"}
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0
    tracking_dir = tmp_path / "skill-tracking"
    if tracking_dir.exists():
        jsonl_files = list(tracking_dir.glob("*.jsonl"))
        assert not jsonl_files, "No tracking files should be written when state is non-VALID"


def test_valid_state_allows_tracking(tmp_path: Path) -> None:
    """VALID flag → hook proceeds and writes a tracking event for a Skill invocation.

    Using tool_name="Skill" is deliberate: the Skill path in main() records the
    event directly without consulting _get_allowlist() — allowlist filtering only
    applies to Agent dispatch. This means "some-skill" does not need to be in the
    filesystem allowlist; the test is not brittle against the allowlist content.
    """
    venv_dir = _make_fake_venv(tmp_path)
    _write_flag(tmp_path, {
        "version": "0.7.0",
        "venv_path": str(venv_dir),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    # CLAUDE_PLUGIN_ROOT is set in _make_env to _WORKTREE so get_current_version()
    # reads pyproject.toml and returns "0.7.0" (matching the flag version → VALID).
    payload = {"tool_name": "Skill", "tool_input": {"skill": "some-skill"}, "session_id": "test-session"}
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0
    tracking_dir = tmp_path / "skill-tracking"
    jsonl_files = list(tracking_dir.glob("*.jsonl")) if tracking_dir.exists() else []
    assert jsonl_files, "Tracking file should be written when state is VALID"
    events = [json.loads(line) for line in jsonl_files[0].read_text().splitlines() if line.strip()]
    assert any(e.get("event") == "skill_invoked" and e.get("skill") == "some-skill" for e in events)
```

Create `tests/unit/test_dashboard_regen_guard.py`:

```python
"""Tests for the Pattern W guard added to hooks/dashboard-regen.py.

Cases:
- Non-VALID state: hook exits 0, produces no dashboard file, spawns no subprocess.
- VALID state: hook spawns subprocess with <venv-python> absolute path (not
  sys.executable) for BOTH the version-check and regen callsites.

Verifying the absolute venv-python path is done via the CLAUDE_PROSPECTOR_FAIL_REGEN
test seam — the hook writes a failure page when FAIL_REGEN=1, which proves it
reached the regen callsite. We then inspect the regen output to confirm the process
was intended to be called (not short-circuited by the guard).
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
_MANIFEST_VERSION = "0.7.0"


def _make_env(
    tmp_path: Path,
    *,
    autoregen: bool = True,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(_WORKTREE)
    env["CLAUDE_PROSPECTOR_DASHBOARD"] = str(tmp_path / "dashboard.html")
    env["CLAUDE_PROSPECTOR_HOOK_LOG"] = str(tmp_path / "hook.log")
    hooks_lib = str(_WORKTREE / "hooks" / "lib")
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = hooks_lib + (os.pathsep + existing_path if existing_path else "")
    # Write a fake plugin.json so the version-check logic has a manifest version
    plugin_root = _WORKTREE
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    if extra:
        env.update(extra)
    return env


def _write_flag(tmp_path: Path, data: dict) -> None:
    (tmp_path / "setup-state.json").write_text(json.dumps(data), encoding="utf-8")


def _make_fake_venv_python_success(tmp_path: Path) -> Path:
    """Create a venv with a python stub that writes a sentinel on invocation.

    The sentinel file records the absolute path of the interpreter that was
    actually called. The test then asserts that path equals the fake-venv
    python path, not sys.executable — this is the core regression check for
    BLOCKING-1: the hook must use _venv_python, not sys.executable.

    The stub also handles version-check and dashboard regen args so the hook
    can complete its normal flow.
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
        if "--version" in args or ("-m" in args and "claude_prospector" in args and "--version" in args):
            print("claude-prospector {_MANIFEST_VERSION}")
            sys.exit(0)
        if "-m" in args and "claude_prospector" in args and "dashboard" in args:
            # Simulate successful regen — write empty dashboard
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


def _run_hook(tmp_path: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH), "--autoregen", "true"],
        input=json.dumps({}),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_non_valid_state_exits_silent(tmp_path: Path) -> None:
    """No flag → hook exits 0 and writes no dashboard file."""
    env = _make_env(tmp_path)
    result = _run_hook(tmp_path, env)
    assert result.returncode == 0
    assert not (tmp_path / "dashboard.html").exists(), (
        "Dashboard should not be created when state is non-VALID"
    )


def test_valid_state_uses_venv_python_for_regen(tmp_path: Path) -> None:
    """VALID flag → both subprocess callsites use the venv python, not sys.executable.

    The fake-venv python stub writes its own absolute path (sys.executable from
    the stub's perspective) to a sentinel file. The test asserts that sentinel
    path equals the fake venv python path — proving _venv_python, not
    sys.executable, was passed to subprocess.run().
    """
    venv_dir = _make_fake_venv_python_success(tmp_path)
    if platform.system() == "Windows":
        expected_venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        expected_venv_python = venv_dir / "bin" / "python"

    sentinel_file = tmp_path / "invoked_interpreter.txt"
    _write_flag(tmp_path, {
        "version": "0.7.0",
        "venv_path": str(venv_dir),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    })
    env = _make_env(tmp_path, extra={
        "CLAUDE_PROSPECTOR_SENTINEL_FILE": str(sentinel_file),
    })
    result = _run_hook(tmp_path, env)
    assert result.returncode == 0, f"Hook exited non-zero. stderr: {result.stderr}"

    # The sentinel must exist — meaning the fake venv python was actually invoked.
    assert sentinel_file.exists(), (
        "Sentinel file not written: the hook never invoked the venv python "
        f"(VALID guard may not have fired). stderr: {result.stderr}"
    )
    invoked_path = Path(sentinel_file.read_text(encoding="utf-8").strip())
    assert invoked_path.resolve() == expected_venv_python.resolve(), (
        f"Hook invoked {invoked_path!r} instead of the venv python "
        f"{expected_venv_python!r}. The hook may have used sys.executable."
    )
```

- [ ] **Step 2: Run failing tests**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/unit/test_skill_tracker_guard.py tests/unit/test_dashboard_regen_guard.py -v
```

Expected: Both test files import and collect, but `test_non_valid_state_exits_silent` in `test_skill_tracker_guard.py` will PASS already (the hook exits 0 for non-Skill tool names). The `test_valid_state_allows_tracking` will likely FAIL because the guard doesn't exist yet and the version mismatch will cause it to emit differently. The dashboard guard tests will also fail because there's no guard.

**Verify that the VALID-state test in skill-tracker fails** — if all tests somehow pass without the guard, confirm by reading `test_non_valid_state_exits_silent`: without the guard, a non-VALID state should still attempt tracking and write a file. If the non-VALID test passes for the wrong reason (the hook exits silently on an already-silent path), the implementer must add a temporary assertion to confirm the guard is actually needed.

- [ ] **Step 3: Modify `hooks/skill-tracker.py` — add `sys.path.insert` block and guard**

Add these lines at the top of the file, after the existing `from __future__ import annotations` and standard library imports (after line 27, before the first blank line between imports and the `_base_dir()` function definition). The `# noqa: E402` suppresses ruff's non-top-level import warning:

```python
# ---------------------------------------------------------------------------
# Pattern W: import setup_state helper from hooks/lib/
# ---------------------------------------------------------------------------
import sys  # already imported above
from pathlib import Path  # already imported above
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import setup_state  # noqa: E402
```

Then, at the top of the `main()` function (line 222, immediately after `def main() -> None:` and before the `try: data = json.load(sys.stdin)` block), add the Pattern W guard:

```python
    # Pattern W guard: only proceed if setup state is VALID.
    # This check is cheap (flag read + path exists) — no subprocess.
    # Runs on every PreToolUse(Skill|Agent) fire, so it must stay minimal.
    try:
        _current_ver = setup_state.get_current_version()
        _state = setup_state.read_setup_state(_current_ver)
        if _state.status != "VALID":
            return  # Banner already shown by SessionStart hook; silent exit here
    except Exception:
        return  # Defensive: never crash the session on a guard error
```

The full `main()` function beginning after this guard:

```python
def main() -> None:
    """Parse a PreToolUse JSON payload from stdin and emit tracking events. ..."""
    # Pattern W guard: only proceed if setup state is VALID.
    try:
        _current_ver = setup_state.get_current_version()
        _state = setup_state.read_setup_state(_current_ver)
        if _state.status != "VALID":
            return
    except Exception:
        return

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    # ... rest of existing main() body unchanged ...
```

**Important**: Do NOT remove the `_get_allowlist()` ImportError fallback at lines 107–119. It stays. Even when state is VALID, `sys.executable` is the harness Python, not the venv Python — the import of `claude_prospector.skill_tracking` may still fail, and the filesystem fallback is correct behaviour.

- [ ] **Step 4: Modify `hooks/dashboard-regen.py` — add `sys.path.insert` block and guard, rewire both subprocess callsites**

**4a. Add sys.path.insert block** at the top of the file, after existing imports (after the `from pathlib import Path` line near the top of the file), before the `# Path resolution` comment block:

```python
# ---------------------------------------------------------------------------
# Pattern W: import setup_state helper from hooks/lib/
# ---------------------------------------------------------------------------
# sys and Path are already imported above.
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import setup_state  # noqa: E402
```

**4b. Add the Pattern W guard** at the very top of the `main()` function (or equivalent entry function). Locate where the hook's `main()` begins (the function that reads `--autoregen`, reads the config, and dispatches to regen). Add this block before any other logic:

```python
    # Pattern W guard: only proceed if setup state is VALID.
    try:
        _current_ver = setup_state.get_current_version()
        _state = setup_state.read_setup_state(_current_ver)
        if _state.status != "VALID":
            return 0  # Banner already shown by SessionStart hook
        # Pre-compute venv python here so both subprocess callsites below
        # can use _venv_python directly without re-accessing _state.flag.
        _venv_python = str(setup_state.get_venv_python(Path(_state.flag["venv_path"])))
    except Exception:
        return 0  # Defensive: never crash the session
```

**4c. Rewire the version-check subprocess callsite (lines 506–514).**

Current code (lines 506–514):
```python
        try:
            ver_result = subprocess.run(
                [sys.executable, "-m", "claude_prospector", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path(sys.executable).parent.parent.parent),
            )
```

Replace with (uses `_venv_python` already bound by the guard at 4b, no `cwd=`):
```python
        try:
            ver_result = subprocess.run(
                [_venv_python, "-m", "claude_prospector", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
```

**4d. Rewire the dashboard regen subprocess callsite (lines 543–560).**

Current code (lines 543–560):
```python
        regen_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "dashboard",
                "--window",
                "7d",
                "--output",
                str(dashboard),
                "--no-open",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path(sys.executable).parent.parent.parent),
        )
```

Replace with (uses `_venv_python` bound in the guard at 4b, no `cwd=`):
```python
        regen_result = subprocess.run(
            [
                _venv_python,
                "-m",
                "claude_prospector",
                "dashboard",
                "--window",
                "7d",
                "--output",
                str(dashboard),
                "--no-open",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
```

Note: `_venv_python` is resolved once in the guard block at step 4b. Both 4c and 4d use the already-bound name — no re-access of `_state.flag` at either callsite.

- [ ] **Step 5: Run the guard tests**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/unit/test_skill_tracker_guard.py tests/unit/test_dashboard_regen_guard.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 6: Run the full unit test suite to catch regressions**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/unit/ -v
```

Expected: All tests pass (12 from test_setup_state + 5 from test_check_prospector_setup + 2 from test_skill_tracker_guard + 2 from test_dashboard_regen_guard = 21 tests).

- [ ] **Step 7: Run the existing hook regression tests**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/test_skill_tracker_hook.py tests/test_dashboard_regen_hook.py -v
```

Expected: All existing tests still pass. If any fail, the guard is interfering with existing test fixtures — check that the test fixtures set `CLAUDE_PLUGIN_DATA` to a directory that either (a) has no `setup-state.json` (non-VALID → guard exits silently before the old path, which may break existing tests that expect the old path to run) or (b) has a VALID flag with a fake venv python stub. If existing tests break, continue to Step 8.

- [ ] **Step 8: Patch existing hook tests to satisfy the new guard**

The existing `tests/test_dashboard_regen_hook.py::_make_env` and `tests/test_skill_tracker_hook.py::_run_hook` do not set `CLAUDE_PLUGIN_DATA`. After Task 4 adds the guard, both hooks will read `read_setup_state()` → get MISSING (no flag file in the real home dir, or a real home-dir flag) → return 0 silently. The tests that assert regen/tracking logic was reached will then fail because the guard short-circuits them.

**Fix: extract a shared VALID-flag fixture into `tests/conftest.py`** (which pytest auto-discovers for both test files), then apply it to the affected tests in each file.

**Add to `tests/conftest.py`** (this file already exists — add the fixture below the existing content):

```python
# ---------------------------------------------------------------------------
# Pattern W: shared fixture for hook tests that require a VALID setup state
# ---------------------------------------------------------------------------

import json
import os
import platform
import textwrap
from pathlib import Path

import pytest


@pytest.fixture()
def valid_setup_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CLAUDE_PLUGIN_DATA to tmp_path and write a VALID setup-state flag.

    The fake venv python is a real Python script that exits 0 for all
    invocations — it is not a zero-byte stub, because Windows cannot
    execute zero-byte .exe files via subprocess.

    Returns the venv directory so callers can further configure it if needed.
    """
    # Point CLAUDE_PLUGIN_DATA at our temp dir — this is the Pattern W seam.
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))

    # Build a fake venv python that the exists() check will pass and that
    # subprocess.run() can actually execute (exits 0 for any args).
    venv_dir = tmp_path / "venv"
    if platform.system() == "Windows":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text(
        textwrap.dedent("""\
            #!/usr/bin/env python3
            # Fake venv python for Pattern W tests — exits 0 for all invocations.
            import sys
            sys.exit(0)
        """),
        encoding="utf-8",
    )
    if platform.system() != "Windows":
        venv_python.chmod(0o755)

    # Write the VALID flag.
    flag = {
        "version": "0.7.0",
        "venv_path": str(venv_dir),
        "interpreter": "python3",
        "installed_at": "2026-01-01T00:00:00Z",
    }
    (tmp_path / "setup-state.json").write_text(
        json.dumps(flag), encoding="utf-8"
    )
    return venv_dir
```

**Apply the fixture in `tests/test_dashboard_regen_hook.py`**: every test that invokes `_run_hook` with `autoregen=True` and expects regen logic to run must add `valid_setup_state` to its parameter list. The fixture's `monkeypatch.setenv("CLAUDE_PLUGIN_DATA", ...)` runs automatically.

Example patch for the tests in that file that exercise the regen path (version-check, regen success, regen failure):

```python
# Before (no Pattern W awareness):
def test_autoregen_regen_success(tmp_path: Path) -> None:
    env = _make_env(tmp_path, autoregen=True)
    result = _run_hook(env, autoregen_arg="true")
    ...

# After (VALID guard satisfied):
def test_autoregen_regen_success(tmp_path: Path, valid_setup_state: Path) -> None:
    # valid_setup_state already set CLAUDE_PLUGIN_DATA; _make_env picks it up.
    env = _make_env(tmp_path, autoregen=True)
    result = _run_hook(env, autoregen_arg="true")
    ...
```

**Apply the same pattern in `tests/test_skill_tracker_hook.py`**: the subprocess-based tests that assert tracking files are written need `valid_setup_state` in their parameter list. The `CLAUDE_PLUGIN_DATA` env var is already forwarded through `os.environ.copy()` inside `_run_hook`, so no other change is required.

Tests that exercise non-regen or non-tracking paths (e.g., `autoregen=False` exit-0 check, `_get_allowlist` unit tests via `_load_module()`) do not need the fixture — the guard short-circuiting is the correct behaviour for those scenarios.

- [ ] **Step 9: Re-run the existing tests to confirm they pass**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/test_skill_tracker_hook.py tests/test_dashboard_regen_hook.py -v
```

Expected: All tests pass.

- [ ] **Step 11: Commit**

```bash
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" add hooks/skill-tracker.py hooks/dashboard-regen.py tests/unit/test_skill_tracker_guard.py tests/unit/test_dashboard_regen_guard.py tests/conftest.py tests/test_skill_tracker_hook.py tests/test_dashboard_regen_hook.py
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" commit -m "feat: add Pattern W guards to skill-tracker and dashboard-regen hooks (refs #107)"
```

---

## Task 5 (AC6): CI Jobs, README, CHANGELOG, Version Bumps

**Files:**
- Modify: `.github/workflows/ci.yml` (add `skill-smoke-{ubuntu,windows}` jobs)
- Modify: `README.md` (add "First-run setup" section)
- Modify: `CHANGELOG.md` (add v0.7.0 entry)
- Modify: `pyproject.toml` (bump `0.7.0rc1` → `0.7.0`)
- Modify: `.claude-plugin/plugin.json` (bump `0.7.0rc1` → `0.7.0`)

There are no TDD test steps for this task — it is configuration and documentation. Each step is verified by review or dry-run.

- [ ] **Step 1: Add `skill-smoke-{ubuntu,windows}` jobs to `.github/workflows/ci.yml`**

Append these two jobs to the existing `ci.yml` (after the `test:` job, before the closing of the YAML document). The new jobs do not depend on `test:` — they are independent parallel jobs.

**Install step:** the `uv pip install --system -e ".[dev]"` line below mirrors the existing `test:` job in `ci.yml` exactly (verified against `.github/workflows/ci.yml` at commit `3caf9a4`). Use the same form — do not substitute `pip install` or `uv sync`.

```yaml
  skill-smoke-ubuntu:
    name: Skill Smoke (Ubuntu)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install dev extras
        run: uv pip install --system -e ".[dev]"
      - name: Skill smoke test
        env:
          CLAUDE_PROSPECTOR_PIP_SPEC: ${{ github.workspace }}
        run: pytest tests/integration/test_setup_skill.py -v

  skill-smoke-windows:
    name: Skill Smoke (Windows)
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install dev extras
        run: uv pip install --system -e ".[dev]"
      - name: Skill smoke test
        env:
          CLAUDE_PROSPECTOR_PIP_SPEC: ${{ github.workspace }}
        run: pytest tests/integration/test_setup_skill.py -v
```

- [ ] **Step 2: Add "First-run setup" section to `README.md`**

Find the README's main content (after the badges/title, before the first major feature section or installation section). Insert this new section before "Installation" or as a top-level section immediately after the introduction paragraph:

```markdown
## First-run setup

After installing claude-prospector for the first time (or after a plugin
update), open a new Claude Code session. You'll see a banner:

> claude-prospector requires setup. Run /setup-prospector to materialise
> the Python venv.

Run `/setup-prospector` once. The skill will:

1. Discover a Python 3.10+ interpreter on your system.
2. Create a plugin-owned venv at `${CLAUDE_PLUGIN_DATA}/venv/`.
3. Install `claude-prospector` from PyPI into that venv.
4. Verify the install and record a setup-state flag.

After setup completes, open a new session — the banner will be gone and
the dashboard, skill-tracking, and usage-analysis features will work
normally.

You'll need to re-run `/setup-prospector` only when:

- The plugin updates to a new version (banner: "venv is for vX but
  plugin is vY").
- The venv is corrupted or deleted (banner: "venv at <path> is
  unreachable or corrupt").
- You move to a new machine (per-machine setup; flag is not portable
  across machines).

**Note:** The plugin's hook scripts still run under the harness-provided
`python` and require a working harness-environment Python interpreter.
The venv created by `/setup-prospector` is used by the hooks for
subprocess spawning only.

### Migration from v0.6.0

After upgrading to v0.7.0, open a new Claude Code session. A banner will
prompt you to run `/setup-prospector`. This is a one-time action per
machine.

If you previously installed `claude-prospector` into `~/.claude/.venv`,
you can leave that install in place — Pattern W hooks always use the
plugin-owned venv via an absolute path. To reclaim disk you may
`uv pip uninstall claude-prospector` from `~/.claude/.venv` after setup;
this is optional.
```

- [ ] **Step 3: Add v0.7.0 entry to `CHANGELOG.md`**

Insert this block at the top of the changelog (after the `# Changelog` heading and before the previous version entry):

```markdown
## [0.7.0] - 2026-MM-DD

### Added

- `/setup-prospector` skill: materialises a plugin-owned Python venv at
  `${CLAUDE_PLUGIN_DATA}/venv/` and writes a setup-state flag. Required
  once after install or after a plugin update.
- `SessionStart` hook (`hooks/check-prospector-setup.py`): surfaces a
  banner when setup is required and runs a per-session import probe to
  detect venv corruption.
- `hooks/lib/setup_state.py`: shared deterministic helper for flag I/O,
  version comparison, and venv-python path resolution.
- CI: `skill-smoke-{ubuntu,windows}` jobs validate the full setup
  pipeline on every PR against real Python 3.10 and real pip.

### Changed

- `hooks/dashboard-regen.py` no longer guesses the venv root via
  `Path(sys.executable).parent.parent.parent`. Both the version-check
  subprocess (`:506-514`) and the dashboard regen subprocess (`:543-560`)
  now use the absolute path recorded in the setup-state flag.
- `hooks/skill-tracker.py` now short-circuits silently when the
  setup-state flag is not VALID, deferring to the SessionStart banner
  for user guidance.
- `claude-prospector` is now published to PyPI. The setup skill installs
  from PyPI by default; `CLAUDE_PROSPECTOR_PIP_SPEC` allows installing
  from a local checkout for development.

### Migration from v0.6.0

After upgrading to v0.7.0, open a new Claude Code session. A
SessionStart banner will prompt you to run `/setup-prospector`. This is
a one-time action per machine per major version.

If you previously installed `claude-prospector` into `~/.claude/.venv`
(the user-managed venv approach), you can leave that install in place —
Pattern W's hooks always spawn the plugin-owned venv via an absolute
path and will not pick up the legacy install. To reclaim disk, you may
`uv pip uninstall claude-prospector` from `~/.claude/.venv` after
Pattern W is working; this is optional and unrelated to plugin operation.

The `${user_config.autoregen}` setting is preserved across the upgrade.
The legacy `config.json` migration mechanism added in v0.6.0 continues
to function unchanged.
```

Replace `2026-MM-DD` with the actual date when committing.

- [ ] **Step 4: Bump version in `pyproject.toml`**

In `pyproject.toml`, change line 7:

```toml
version = "0.7.0rc1"
```

to:

```toml
version = "0.7.0"
```

- [ ] **Step 5: Bump version in `.claude-plugin/plugin.json`**

In `.claude-plugin/plugin.json`, change:

```json
"version": "0.7.0rc1",
```

to:

```json
"version": "0.7.0",
```

- [ ] **Step 6: Run the full test suite to verify no regressions from version bump**

The version bump changes what `get_current_version()` returns. Any test that wrote a flag with `"version": "0.7.0rc1"` will now get STALE rather than VALID. Check:

```bash
"./.venv/Scripts/python.exe" -m pytest tests/unit/ -v
```

Expected: All 21 unit tests pass. If any test_setup_state case fails due to the version bump, update that test's flag fixture from `0.7.0rc1` to `0.7.0`.

- [ ] **Step 7: Run sync test to confirm drift guard still passes**

```bash
"./.venv/Scripts/python.exe" -m pytest tests/test_skill_pipeline_sync.py -v
```

Expected: All 9 tests pass.

- [ ] **Step 8: Commit**

Fill in the actual date in CHANGELOG.md, then:

```bash
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" add .github/workflows/ci.yml README.md CHANGELOG.md pyproject.toml .claude-plugin/plugin.json
git -C "I:/other/claude-prospector/.worktrees/pattern-w-implementation" commit -m "feat: CI smoke jobs, README setup docs, CHANGELOG, version bump to 0.7.0 (refs #107)"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Item | Covered in Task |
|-----------|----------------|
| AC1 — PyPI publish | Out of scope (existing release.yml PR #109) |
| AC2 — `/setup-prospector` skill | Task 2 |
| AC3 — `hooks/lib/setup_state.py` + 12 unit tests | Task 1 |
| AC4 — `check-prospector-setup.py` + `hooks.json` + `test_check_prospector_setup.py` | Task 3 |
| AC5 — `skill-tracker.py` guard + `dashboard-regen.py` guard/rewire (both callsites) | Task 4 |
| AC6 — CI smoke + README + CHANGELOG + version bumps | Task 5 |
| `tests/unit/test_skill_tracker_guard.py` | Task 4 |
| `tests/unit/test_dashboard_regen_guard.py` | Task 4 |
| `tests/integration/setup_pipeline.py` | Task 2 |
| `tests/integration/test_setup_skill.py` | Task 2 |
| `tests/test_skill_pipeline_sync.py` | Task 2 |
| D11 — flag at `$CLAUDE_PLUGIN_DATA/setup-state.json` always | `get_flag_path()` in Task 1 |
| D13 — `python -m pip install` not `uv` | `pip_install()` in Task 2 |
| `ensurepip` defensive step | `pip_install()` Step 5 in Task 2 |
| `sys.path.insert` idiom in all three hooks | Tasks 3, 4 |
| F10 — no new recovery mechanism | Documented in Task 4 Step 3 |
| `_get_allowlist()` fallback retained | Task 4 Step 3 |
| Both subprocess callsites in dashboard-regen rewired | Task 4 Step 4c+4d |
| BLOCKING-1: probe failure deletes flag | `test_valid_flag_import_fails_deletes_flag_and_emits_banner` in Task 3 |
| `$CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON` env var | `discover_python()` in Task 2 |
| `$CLAUDE_PROSPECTOR_PIP_SPEC` env var | `pip_install()` in Task 2, CI jobs in Task 5 |
| `$CLAUDE_PLUGIN_DATA` dual-effect in tests | Documented in Task 1 fixtures |

All 17 `touches:` files are mapped:

| File | Task |
|------|------|
| `.claude-plugin/plugin.json` | Task 5 |
| `pyproject.toml` | Task 5 |
| `hooks/hooks.json` | Task 3 |
| `hooks/skill-tracker.py` | Task 4 |
| `hooks/dashboard-regen.py` | Task 4 |
| `hooks/check-prospector-setup.py` | Task 3 |
| `hooks/lib/setup_state.py` | Task 1 |
| `skills/setup-prospector/SKILL.md` | Task 2 |
| `tests/integration/setup_pipeline.py` | Task 2 |
| `tests/integration/test_setup_skill.py` | Task 2 |
| `tests/unit/test_check_prospector_setup.py` | Task 3 |
| `tests/unit/test_dashboard_regen_guard.py` | Task 4 |
| `tests/unit/test_setup_state.py` | Task 1 |
| `tests/unit/test_skill_tracker_guard.py` | Task 4 |
| `tests/test_skill_pipeline_sync.py` | Task 2 |
| `.github/workflows/ci.yml` | Task 5 |
| `README.md` | Task 5 |

CHANGELOG.md is not in the `touches:` frontmatter but is required by spec § 11.3 and the CLAUDE.md README-maintenance rule.

### 2. Placeholder Scan

No "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling", or "similar to Task N" phrases remain in this plan.

### 3. Type Consistency

Function names used across tasks:

| Name | Defined in | Used in |
|------|-----------|---------|
| `setup_state.read_setup_state()` | Task 1 (`setup_state.py`) | Tasks 3, 4 |
| `setup_state.get_venv_python()` | Task 1 (`setup_state.py`) | Tasks 3, 4 |
| `setup_state.get_current_version()` | Task 1 (`setup_state.py`) | Tasks 3, 4 |
| `setup_state.get_plugin_data_dir()` | Task 1 (`setup_state.py`) | Task 1 tests |
| `setup_state.get_flag_path()` | Task 1 (`setup_state.py`) | Task 1 (internal) |
| `setup_state.delete_flag()` | Task 1 (`setup_state.py`) | Task 3 |
| `SetupStateResult.status` | Task 1 (NamedTuple) | Tasks 1, 3, 4 |
| `SetupStateResult.flag` | Task 1 (NamedTuple) | Tasks 1, 3, 4 |
| `compute_plugin_data_dir()` | Task 2 (`setup_pipeline.py`) | Tasks 2, sync test |
| `discover_python()` | Task 2 (`setup_pipeline.py`) | Tasks 2, sync test |
| `wipe_venv()` | Task 2 (`setup_pipeline.py`) | Tasks 2, sync test |
| `create_venv()` | Task 2 (`setup_pipeline.py`) | Tasks 2, sync test |
| `pip_install()` | Task 2 (`setup_pipeline.py`) | Tasks 2, sync test |
| `verify_import()` | Task 2 (`setup_pipeline.py`) | Tasks 2, sync test |
| `write_flag()` | Task 2 (`setup_pipeline.py`) | Tasks 2, sync test |
| `run_full_pipeline()` | Task 2 (`setup_pipeline.py`) | Tasks 2, sync test |
| `get_venv_python()` (pipeline) | Task 2 (`setup_pipeline.py`) | Task 2 tests |

All consistent. The sync test's `STEP_FUNCTION_MAP` keys match the SKILL.md `## Step N:` headings exactly.

---

## Reviewer Findings Applied (2026-05-18)

The following findings from project-review were applied as targeted edits. Original plan structure and task ordering are preserved.

| Finding | Location Patched | Resolution |
|---------|-----------------|------------|
| BLOCKING-1: venv-python assertion missing in `test_valid_state_uses_venv_python_for_regen` | Task 4, `test_dashboard_regen_guard.py` block | `_make_fake_venv_python_success` shim now writes `sys.executable` to a sentinel file via `CLAUDE_PROSPECTOR_SENTINEL_FILE` env var; test asserts sentinel path equals expected fake-venv python absolute path |
| BLOCKING-2: `_venv_python` scope ambiguous across 4b/4c/4d | Task 4, steps 4b–4d | `_venv_python` is now pre-computed in step 4b immediately after the guard; steps 4c and 4d reference the already-bound name with no re-access of `_state.flag` |
| CONCERN-3: existing hook tests lose coverage silently | Task 4, new steps 8–10 | Added step 8 (shared `valid_setup_state` fixture extracted to `tests/conftest.py`) and step 9 (re-run existing tests); step numbering shifted, commit is now step 11 |
| CONCERN-4: `test_setup_skill.py` import style inconsistency | Task 2, step 6 import block | Changed `from tests.integration import setup_pipeline` to `sys.path.insert` + `from integration import setup_pipeline` pattern, matching sibling tests |
| CONCERN-5: `test_valid_state_allows_tracking` brittle vs allowlist | Task 4, `test_skill_tracker_guard.py` block | Added docstring clarifying that `tool_name="Skill"` path never consults `_get_allowlist()` — the allowlist concern does not apply here; test is not brittle |
| CONCERN-6: `_get_plugin_root()` docstring off-by-one | Task 1, `setup_state.py` block | Docstring updated to "three levels up" with explicit chain: `setup_state.py → lib/ → hooks/ → <root>/` |
| CONCERN-7: `PYTHONPATH` redundancy in `test_check_prospector_setup.py::_make_env` | Task 3, `test_check_prospector_setup.py` block | Removed `PYTHONPATH` manipulation; added comment explaining why (hook's own `sys.path.insert` is the production mechanism and should be tested as such) |
| NIT-8: `status` field should be `Literal[...]` not bare `str` | Task 1, `SetupStateResult` dataclass | Changed `status: str` to `status: Literal["VALID", "MISSING", "STALE", "BROKEN"]`; added `Literal` to `from typing import` line |
| NIT-9: CI smoke jobs `--system` flag inconsistency | Task 5, step 1 | Verified against `ci.yml` at `3caf9a4`: existing `test:` job uses `uv pip install --system -e ".[dev]"` — plan already matches; added inline note confirming the match |
