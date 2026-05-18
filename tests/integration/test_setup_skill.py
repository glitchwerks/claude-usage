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
        [
            str(venv_python),
            "-c",
            "import claude_prospector; print(claude_prospector.__file__)",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"import claude_prospector failed: {result.stderr}"
    )
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


def test_discover_python_finds_real_interpreter(
    fake_plugin_data: Path,
) -> None:
    """discover_python() finds the CI runner's Python >= 3.10."""
    interpreter = setup_pipeline.discover_python()
    assert interpreter, "Should find at least one Python >= 3.10 on CI"
