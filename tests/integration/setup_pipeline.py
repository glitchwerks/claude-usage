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
            result = subprocess.run(
                args, capture_output=True, check=False, timeout=10
            )
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
        raise SetupError(
            f"python -m venv timed out after {exc.timeout}s"
        ) from exc
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
    spec for pre-PyPI CI. Production always uses
    `claude-prospector==<version>`.

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
        raise SetupError(
            f"import check timed out after {exc.timeout}s"
        ) from exc
    if result.returncode != 0:
        shutil.rmtree(venv_dir, ignore_errors=True)
        raise SetupError(
            "import claude_prospector failed after install:\n"
            f"stderr: {result.stderr}"
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
        r"^\[project\][^\[]*?^version\s*=\s*\"([^\"]+)\"",
        content,
        re.MULTILINE,
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
        version: Package version to install. If None, reads from
            pyproject.toml.
        prior_interpreter: Optional interpreter command from a previous
            flag.

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
