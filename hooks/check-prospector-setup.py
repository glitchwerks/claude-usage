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
    {"additionalContext": "<banner text>"}   -- when setup required
    {}                                       -- when setup is valid and probe passes
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
    """Print an additionalContext JSON object to stdout.

    Args:
        banner: The banner text to include in the additionalContext field.
    """
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
        flag_version = (
            result.flag.get("version", "unknown") if result.flag else "unknown"
        )
        _emit(
            _BANNER_STALE_TMPL.format(
                flag_version=flag_version,
                current_version=current_version,
            )
        )
        return 0

    if result.status == "BROKEN":
        venv_path = (
            result.flag.get("venv_path", "<unknown>") if result.flag else "<unknown>"
        )
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
