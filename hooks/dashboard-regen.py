#!/usr/bin/env python3
"""Stop hook: regenerate the claude-prospector dashboard on session end.

This script is registered as a Claude Code Stop hook in hooks/hooks.json.
It fires at the end of every session. Whether it actually does work is
controlled by the ``autoregen`` key in the plugin config file — when
``autoregen`` is false (or the config file is absent) the hook exits
immediately as a no-op so users who haven't opted in are unaffected.

The Stop hook is registered unconditionally in hooks.json rather than
conditionally based on config because:
- If registration were conditional on config, users would have to
  reinstall the plugin to toggle autoregen.
- A fast no-op on every session end is cheaper than re-install friction.

Path resolution:
    All paths are resolved via env-var overrides first, then default to
    ``~/.claude/claude-prospector/``. The env vars are:

    - ``CLAUDE_PROSPECTOR_CONFIG``      — config file path.
    - ``CLAUDE_PROSPECTOR_DASHBOARD``   — output dashboard file path.
    - ``CLAUDE_PROSPECTOR_HOOK_LOG``    — hook diagnostic log path.
    - ``CLAUDE_PLUGIN_ROOT``            — plugin install directory
      (set by the hook runner; used to locate plugin.json).

Test seam:
    When ``CLAUDE_PROSPECTOR_FAIL_REGEN=1`` is set, the regen subprocess
    is skipped and a synthetic failure is simulated so the failure-page
    code path can be tested without a real crash.

Exit codes:
    Always 0. Hook failures must never propagate to the Claude Code
    session runner — that would disrupt the user's workflow.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path resolution (mirrors claude_prospector.paths without importing it)
# ---------------------------------------------------------------------------
# The hook script is invoked as a standalone Python file by the harness.
# It cannot safely import claude_prospector without knowing the project
# root is on sys.path. Rather than risk import failures, we replicate
# the env-var path resolution inline (env var names are identical to
# paths.py, so defaults are byte-for-byte compatible).


def _base_dir() -> Path:
    """Return the claude-prospector base directory.

    Three-tier resolution (highest priority first):

    1. ``CLAUDE_PROSPECTOR_BASE_DIR`` — explicit test/override path.
    2. ``CLAUDE_PLUGIN_DATA`` — Anthropic plugin state dir (used as-is).
    3. Legacy ``~/.claude/claude-prospector/`` — pre-migration fallback.

    Migration logic is intentionally omitted here; it runs only from
    ``claude_prospector.paths.base_dir()`` so it happens exactly once.

    Returns:
        Resolved base directory path.
    """
    env_override = os.environ.get("CLAUDE_PROSPECTOR_BASE_DIR")
    if env_override:
        return Path(env_override)
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data)
    return Path.home() / ".claude" / "claude-prospector"


def _config_path() -> Path:
    """Return the config file path.

    Returns:
        Path from CLAUDE_PROSPECTOR_CONFIG env var, or the default.
    """
    env = os.environ.get("CLAUDE_PROSPECTOR_CONFIG")
    if env:
        return Path(env)
    return _base_dir() / "config.json"


def _dashboard_path() -> Path:
    """Return the dashboard HTML output path.

    Returns:
        Path from CLAUDE_PROSPECTOR_DASHBOARD env var, or the default.
    """
    env = os.environ.get("CLAUDE_PROSPECTOR_DASHBOARD")
    if env:
        return Path(env)
    return _base_dir() / "dashboard.html"


def _hook_log_path() -> Path:
    """Return the hook diagnostic log path.

    Returns:
        Path from CLAUDE_PROSPECTOR_HOOK_LOG env var, or the default.
    """
    env = os.environ.get("CLAUDE_PROSPECTOR_HOOK_LOG")
    if env:
        return Path(env)
    return _base_dir() / "hook.log"


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------


def _version_tuple(version_str: str) -> tuple[int, ...]:
    """Parse a dotted version string into a tuple of integers.

    Handles simple dotted-numeric versions like "0.4.0". Non-numeric
    segments are treated as 0 to stay robust against pre-release tags.

    Args:
        version_str: A version string such as "0.4.0" or "1.2.3+local".

    Returns:
        Tuple of ints, e.g. ``(0, 4, 0)``.
    """
    # Strip any local/build suffix (e.g. "0.0.0+local" → "0.0.0")
    base = version_str.split("+")[0].split("-")[0]
    parts = []
    for seg in base.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _compare_versions(pkg_ver: str, manifest_ver: str) -> int:
    """Compare two version strings.

    Args:
        pkg_ver: Package version string.
        manifest_ver: Manifest (plugin.json) version string.

    Returns:
        Negative if pkg_ver < manifest_ver, 0 if equal, positive if
        pkg_ver > manifest_ver.
    """
    try:
        from packaging.version import Version

        pv = Version(pkg_ver)
        mv = Version(manifest_ver)
        if pv < mv:
            return -1
        if pv > mv:
            return 1
        return 0
    except Exception:
        # Fall back to tuple comparison on dotted ints.
        pt = _version_tuple(pkg_ver)
        mt = _version_tuple(manifest_ver)
        if pt < mt:
            return -1
        if pt > mt:
            return 1
        return 0


# ---------------------------------------------------------------------------
# HTML page builders
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns:
        ISO 8601 timestamp string with UTC timezone.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _html_page(title: str, heading: str, body_html: str) -> str:
    """Build a minimal static HTML page.

    Args:
        title: Browser tab title.
        heading: H1 heading text.
        body_html: Raw HTML to insert in the page body after the heading.

    Returns:
        Complete HTML document as a string.
    """
    ts = _timestamp()
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: sans-serif; max-width: 800px; margin: 2rem auto;
            padding: 0 1rem; }}
    pre {{ background: #f4f4f4; padding: 1rem; overflow: auto;
           white-space: pre-wrap; word-break: break-all; }}
    footer {{ margin-top: 2rem; color: #888; font-size: 0.85em; }}
  </style>
</head>
<body>
  <h1>{heading}</h1>
  {body_html}
  <footer>Generated at {ts}</footer>
</body>
</html>
"""


def _write_page(path: Path, html: str) -> None:
    """Write *html* to *path*, creating parent directories as needed.

    Args:
        path: Destination file path.
        html: HTML content to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _python_not_found_page() -> str:
    """Build the 'Python not found' error page HTML.

    Returns:
        HTML page informing the user that the python executable failed.
    """
    body = """\
<p>The dashboard could not be regenerated because the
<code>python -m claude_prospector</code> command failed to start.</p>
<p>Make sure the <code>claude-prospector</code> Python package is
installed in the Python environment used by this plugin.</p>
<p>See the plugin README for installation instructions:
<code>~/.claude/plugins/cache/.../README.md#install-as-a-claude-code-plugin
</code></p>
"""
    return _html_page(
        "Python not found — claude-prospector",
        "Python not found",
        body,
    )


def _version_mismatch_page(pkg_ver: str, manifest_ver: str) -> str:
    """Build the version-mismatch error page HTML.

    Args:
        pkg_ver: The installed Python package version.
        manifest_ver: The plugin manifest version.

    Returns:
        HTML page explaining the version mismatch and how to upgrade.
    """
    body = f"""\
<dl>
  <dt>Plugin (manifest) version</dt><dd><code>{manifest_ver}</code></dd>
  <dt>Python package version</dt><dd><code>{pkg_ver}</code></dd>
  <dt>Required</dt>
  <dd>package version &ge; {manifest_ver}</dd>
</dl>
<p>To upgrade the Python package, run:</p>
<pre>uv pip install --upgrade \
"git+https://github.com/glitchwerks/claude-prospector.git"</pre>
<p>Then restart Claude Code to pick up the new version.</p>
"""
    return _html_page(
        "claude-prospector version mismatch",
        "claude-prospector version mismatch",
        body,
    )


def _regen_failed_page(stderr_output: str) -> str:
    """Build the 'regen failed' error page HTML.

    Args:
        stderr_output: Captured stderr from the failed regen subprocess.

    Returns:
        HTML page with the captured error output.
    """
    import html as _html_mod

    escaped = _html_mod.escape(stderr_output)
    body = f"""\
<p>The dashboard regeneration command exited with a non-zero status.</p>
<p>Captured error output:</p>
<pre>{escaped}</pre>
<p>To diagnose, run manually:</p>
<pre>python -m claude_prospector dashboard --window 7d</pre>
"""
    return _html_page(
        "Dashboard regeneration failed — claude-prospector",
        "Dashboard regeneration failed",
        body,
    )


# ---------------------------------------------------------------------------
# Hook log
# ---------------------------------------------------------------------------


def _log(message: str) -> None:
    """Truncate-on-each-run log write. Silently swallows IO errors.

    Args:
        message: Diagnostic text to record.
    """
    try:
        log_path = _hook_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"[{_timestamp()}] {message}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point for the Stop hook. Returns process exit code.

    Steps:
    1. Consume stdin (Stop hook payload — content not needed).
    2. Load config. If autoregen != true, exit 0 as a no-op.
    3. Check manifest version vs. package version; write mismatch page on
       downgrade.
    4. Run regen subprocess. Write failure page on non-zero exit.
    5. Log success and exit 0.

    Returns:
        Always 0 — hook failures must not propagate to the session runner.
    """
    try:
        # Step 1: consume stdin so the process closes cleanly.
        _stdin = sys.stdin.read()

        # Step 2: load config.
        cfg_path = _config_path()
        if not cfg_path.exists():
            return 0  # No config → autoregen not enabled.

        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return 0  # Malformed config → no-op.

        if not cfg.get("autoregen"):
            return 0  # autoregen disabled.

        dashboard = _dashboard_path()

        # Step 3: version-pin check.
        plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
        manifest_ver: str | None = None
        if plugin_root_env:
            manifest_path = Path(plugin_root_env) / "plugin.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest_ver = manifest.get("version")
            except Exception:
                manifest_ver = None

        # Get package version via subprocess.
        try:
            ver_result = subprocess.run(
                [sys.executable, "-m", "claude_prospector", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path(sys.executable).parent.parent.parent),
            )
            if ver_result.returncode != 0:
                _write_page(dashboard, _python_not_found_page())
                return 0
            # Output is like "claude-prospector 0.4.0"
            raw_ver = ver_result.stdout.strip() + ver_result.stderr.strip()
            # Extract the version token (last whitespace-separated segment)
            pkg_ver = raw_ver.split()[-1] if raw_ver.split() else "0.0.0"
        except FileNotFoundError:
            _write_page(dashboard, _python_not_found_page())
            return 0
        except Exception:
            _write_page(dashboard, _python_not_found_page())
            return 0

        if manifest_ver and _compare_versions(pkg_ver, manifest_ver) < 0:
            _write_page(dashboard, _version_mismatch_page(pkg_ver, manifest_ver))
            return 0

        # Test seam: CLAUDE_PROSPECTOR_FAIL_REGEN=1 simulates a failure.
        if os.environ.get("CLAUDE_PROSPECTOR_FAIL_REGEN") == "1":
            _write_page(
                dashboard,
                _regen_failed_page(
                    "Simulated regen failure (CLAUDE_PROSPECTOR_FAIL_REGEN=1)"
                ),
            )
            return 0

        # Step 4: run the regen.
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

        if regen_result.returncode != 0:
            _write_page(dashboard, _regen_failed_page(regen_result.stderr))
            return 0

        # Step 5: log success.
        _log(f"Dashboard regenerated successfully → {dashboard}")

    except Exception as exc:
        sys.stderr.write(f"[dashboard-regen] unexpected error: {exc}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
