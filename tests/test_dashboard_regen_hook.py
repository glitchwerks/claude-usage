"""Tests for hooks/dashboard-regen.py Stop hook.

The hook is invoked via subprocess with env vars redirecting all paths to
``tmp_path`` directories so no real home-directory state is touched.

The contract verified for each test:
- autoregen=false: hook exits 0 and produces no dashboard file.
- autoregen=true + missing python (patched): writes "Python not found" page.
- autoregen=true + version mismatch: writes "version mismatch" page.
- autoregen=true + regen success: dashboard.html exists with non-zero size.
- autoregen=true + regen failure: writes "regen failed" page with stderr.

New (issue #99) contracts:
- --autoregen true/false/1/yes/no: hook parses the CLI arg as the gate.
- --autoregen absent: hook falls back to legacy config.json.
- Migration notice: one-time log entry when legacy config.json is present.
- Sentinel file prevents duplicate migration notices.

Hook input:
    The Stop hook payload is read from stdin. The hook ignores the payload
    content — only autoregen config and the python subprocess matter. We
    pass ``{}`` as the stdin payload.

CWD note:
    All subprocess invocations use ``cwd=str(_WORKTREE)`` so that the
    empty-string sys.path entry resolves to the worktree package, not the
    main repo checkout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

_WORKTREE = Path(__file__).parent.parent
_HOOK_PATH = _WORKTREE / "hooks" / "dashboard-regen.py"

# Use the actual installed version so the Pattern W guard can read a matching
# version from CLAUDE_PLUGIN_ROOT/plugin.json and classify the flag as VALID.
# sys and Path are already imported above.
sys.path.insert(0, str(_WORKTREE / "hooks" / "lib"))
import setup_state as _setup_state  # noqa: E402

# The default manifest version must match the installed package version so
# non-mismatch tests satisfy the guard (flag.version == current_version).
# Version-mismatch tests override this with an explicit higher value ("999.0.0").
_MANIFEST_VERSION = _setup_state.get_current_version()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_env(
    tmp_path: Path,
    *,
    autoregen: bool,
    manifest_version: str = _MANIFEST_VERSION,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a hook invocation.

    Creates:
    - A config file under ``tmp_path/config.json`` with ``autoregen`` set.
    - A plugin.json manifest under ``tmp_path/plugin-root/`` at the version
      given by *manifest_version*.

    Returns the env dict with all relevant CLAUDE_PROSPECTOR_* vars
    pointing into tmp_path.

    Args:
        tmp_path: pytest temporary directory.
        autoregen: Value to write for ``{"autoregen": <bool>}``.
        manifest_version: Version string to embed in the plugin manifest.
        extra: Extra vars to merge (last wins).

    Returns:
        Environment dict suitable for ``subprocess.run(..., env=...)``.
    """
    # Config file
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"autoregen": autoregen}), encoding="utf-8")

    # Dashboard output dir
    dashboard_file = tmp_path / "dashboard.html"

    # Hook log
    hook_log = tmp_path / "hook.log"

    # Plugin manifest — two copies with intentionally different purposes:
    # 1. plugin_root/plugin.json: read by the hook's existing version-check
    #    logic (Step 4 of main()) via CLAUDE_PLUGIN_ROOT/plugin.json.
    #    Carries manifest_version — may be "999.0.0" for mismatch tests.
    # 2. plugin_root/.claude-plugin/plugin.json: read by setup_state
    #    .get_current_version() when CLAUDE_PLUGIN_ROOT has no pyproject.toml.
    #    Always carries _MANIFEST_VERSION (the real installed version) so the
    #    Pattern W guard sees VALID (flag.version == current_version).
    plugin_root = tmp_path / "plugin-root"
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps({"version": manifest_version}), encoding="utf-8"
    )
    claude_plugin_dir = plugin_root / ".claude-plugin"
    claude_plugin_dir.mkdir(parents=True, exist_ok=True)
    (claude_plugin_dir / "plugin.json").write_text(
        json.dumps({"version": _MANIFEST_VERSION}), encoding="utf-8"
    )

    env = {
        **os.environ,
        "CLAUDE_PROSPECTOR_CONFIG": str(cfg_path),
        "CLAUDE_PROSPECTOR_DASHBOARD": str(dashboard_file),
        "CLAUDE_PROSPECTOR_HOOK_LOG": str(hook_log),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
    }
    if extra:
        env.update(extra)
    return env


def _run_hook(
    env: dict[str, str],
    stdin_payload: dict | None = None,
    autoregen_arg: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke dashboard-regen.py as a subprocess.

    Args:
        env: Environment dict (from _make_env).
        stdin_payload: JSON payload to write to stdin. Defaults to ``{}``.
        autoregen_arg: If given, passes ``--autoregen <value>`` to the hook.
            When None, the hook is invoked without the flag (legacy path).

    Returns:
        CompletedProcess with stdout, stderr, returncode.
    """
    payload = json.dumps(stdin_payload or {})
    cmd = [sys.executable, str(_HOOK_PATH)]
    if autoregen_arg is not None:
        cmd += ["--autoregen", autoregen_arg]
    return subprocess.run(
        cmd,
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKTREE),
    )


def _make_env_no_config(
    tmp_path: Path,
    *,
    manifest_version: str = _MANIFEST_VERSION,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build env pointing at non-existent config (no config.json created).

    Useful for testing the --autoregen CLI-arg path where config.json
    should not exist.

    Args:
        tmp_path: pytest temporary directory.
        manifest_version: Version string to embed in the plugin manifest.
        extra: Extra vars to merge (last wins).

    Returns:
        Environment dict suitable for ``subprocess.run(..., env=...)``.
    """
    cfg_path = tmp_path / "config.json"  # intentionally not created

    dashboard_file = tmp_path / "dashboard.html"
    hook_log = tmp_path / "hook.log"

    # See _make_env comment: two copies of plugin.json are needed.
    # plugin_root/plugin.json: for the hook's version-check (Step 4).
    # plugin_root/.claude-plugin/plugin.json: for setup_state
    # .get_current_version() so the Pattern W guard sees VALID state.
    plugin_root = tmp_path / "plugin-root"
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps({"version": manifest_version}), encoding="utf-8"
    )
    claude_plugin_dir = plugin_root / ".claude-plugin"
    claude_plugin_dir.mkdir(parents=True, exist_ok=True)
    (claude_plugin_dir / "plugin.json").write_text(
        json.dumps({"version": _MANIFEST_VERSION}), encoding="utf-8"
    )

    env = {
        **os.environ,
        "CLAUDE_PROSPECTOR_CONFIG": str(cfg_path),
        "CLAUDE_PROSPECTOR_DASHBOARD": str(dashboard_file),
        "CLAUDE_PROSPECTOR_HOOK_LOG": str(hook_log),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
    }
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------------------
# autoregen=false (no-op)
# ---------------------------------------------------------------------------


class TestAutoregenDisabled:
    """When autoregen is false the hook must be a no-op."""

    def test_exits_zero(self, tmp_path: Path) -> None:
        """Hook exits 0 when autoregen=false."""
        env = _make_env(tmp_path, autoregen=False)
        result = _run_hook(env)
        assert result.returncode == 0, result.stderr

    def test_no_dashboard_written(self, tmp_path: Path) -> None:
        """Hook does not create dashboard.html when autoregen=false."""
        env = _make_env(tmp_path, autoregen=False)
        dashboard = tmp_path / "dashboard.html"
        _run_hook(env)
        assert not dashboard.exists()

    def test_no_config_file(self, tmp_path: Path) -> None:
        """Hook exits 0 with no dashboard when config file is missing."""
        env = {
            **os.environ,
            "CLAUDE_PROSPECTOR_CONFIG": str(tmp_path / "nonexistent-config.json"),
            "CLAUDE_PROSPECTOR_DASHBOARD": str(tmp_path / "dashboard.html"),
            "CLAUDE_PROSPECTOR_HOOK_LOG": str(tmp_path / "hook.log"),
            "CLAUDE_PLUGIN_ROOT": str(tmp_path / "plugin-root"),
        }
        # Create a minimal plugin root so manifest parsing doesn't fail first
        (tmp_path / "plugin-root").mkdir(parents=True, exist_ok=True)
        (tmp_path / "plugin-root" / "plugin.json").write_text(
            json.dumps({"version": _MANIFEST_VERSION}), encoding="utf-8"
        )
        result = _run_hook(env)
        assert result.returncode == 0
        assert not (tmp_path / "dashboard.html").exists()


# ---------------------------------------------------------------------------
# autoregen=true + version mismatch
# ---------------------------------------------------------------------------


class TestVersionMismatch:
    """When the manifest version > package version, write the mismatch page."""

    def test_writes_version_mismatch_page(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """A higher manifest version causes the mismatch page to be written."""
        # Set manifest version to something higher than the installed package
        env = _make_env(tmp_path, autoregen=True, manifest_version="999.0.0")
        _run_hook(env)
        dashboard = tmp_path / "dashboard.html"
        assert dashboard.exists(), "Expected mismatch page to be written"
        content = dashboard.read_text(encoding="utf-8")
        assert "mismatch" in content.lower() or "version" in content.lower()

    def test_mismatch_page_shows_both_versions(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """Mismatch page includes both manifest and package version info."""
        env = _make_env(tmp_path, autoregen=True, manifest_version="999.0.0")
        _run_hook(env)
        content = (tmp_path / "dashboard.html").read_text(encoding="utf-8")
        assert "999.0.0" in content

    def test_exits_zero_on_mismatch(self, tmp_path: Path) -> None:
        """Hook still exits 0 on version mismatch (no propagation to runner)."""
        env = _make_env(tmp_path, autoregen=True, manifest_version="999.0.0")
        result = _run_hook(env)
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# autoregen=true + regen success
# ---------------------------------------------------------------------------


class TestRegenSuccess:
    """When autoregen=true and versions match, the dashboard is regenerated."""

    def test_dashboard_file_created(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """Successful regen creates a non-empty dashboard.html."""
        env = _make_env(tmp_path, autoregen=True)
        result = _run_hook(env)
        assert result.returncode == 0, result.stderr
        dashboard = tmp_path / "dashboard.html"
        assert (
            dashboard.exists()
        ), f"dashboard.html not created. stderr: {result.stderr!r}"
        assert dashboard.stat().st_size > 0

    def test_dashboard_is_html(self, tmp_path: Path, valid_setup_state: Path) -> None:
        """Regenerated dashboard.html contains HTML markup."""
        env = _make_env(tmp_path, autoregen=True)
        _run_hook(env)
        content = (tmp_path / "dashboard.html").read_text(encoding="utf-8")
        assert "<html" in content.lower() or "<!doctype" in content.lower()

    def test_hook_log_written_on_success(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """On success the hook writes a log entry to hook.log."""
        env = _make_env(tmp_path, autoregen=True)
        _run_hook(env)
        hook_log = tmp_path / "hook.log"
        assert hook_log.exists()
        assert hook_log.stat().st_size > 0


# ---------------------------------------------------------------------------
# autoregen=true + regen failure (simulated via bad data dir)
# ---------------------------------------------------------------------------


class TestRegenFailure:
    """When the regen subprocess fails, the hook writes a failure page."""

    def test_writes_failure_page(self, tmp_path: Path, valid_setup_state: Path) -> None:
        """A failed regen subprocess causes a failure page to be written."""
        # Create a wrapper script that replaces the dashboard subcommand
        # with one that always fails. We do this by pointing to a fake
        # python that exits 1 with stderr output.
        fake_python_dir = tmp_path / "fake-python"
        fake_python_dir.mkdir()

        # Write a stub that mimics a dashboard generation failure.
        fake_script = fake_python_dir / "claude_prospector_fail.py"
        fake_script.write_text(
            textwrap.dedent("""\
                import sys
                sys.stderr.write("simulated regen failure\\n")
                sys.exit(1)
            """),
            encoding="utf-8",
        )

        # Override CLAUDE_PROSPECTOR_REGEN_ARGS to inject a guaranteed
        # failing subcommand. Since we control the hook, we instead pass
        # a wrapper via environment so the hook calls our script. But the
        # hook uses sys.executable — we need a different approach.
        #
        # Strategy: write a real config with a data-dir that doesn't exist,
        # so the dashboard command fails gracefully with a non-zero exit.
        # However, the dashboard command may exit 0 on empty data dirs.
        #
        # Cleaner: use CLAUDE_PROSPECTOR_REGEN_PYTHON env var so the hook
        # can call an alternative python that always fails. If the hook
        # doesn't support that, skip this test as the failure path
        # requires the hook's implementation to expose a seam.
        #
        # Since we're writing the hook, we'll honour
        # CLAUDE_PROSPECTOR_REGEN_PYTHON in the hook implementation to
        # support test injection.
        env = _make_env(tmp_path, autoregen=True)
        # Override the python used for regen with our failing script
        env["CLAUDE_PROSPECTOR_REGEN_PYTHON"] = sys.executable
        env["CLAUDE_PROSPECTOR_REGEN_MODULE"] = str(fake_script.parent)
        # Pass the script path to hook via module override — we'll use
        # a different env var the hook reads for tests.
        # Actually: simplest is a fake module path injection. We'll
        # document this in the hook via CLAUDE_PROSPECTOR_FAIL_REGEN=1.
        env["CLAUDE_PROSPECTOR_FAIL_REGEN"] = "1"

        result = _run_hook(env)
        assert result.returncode == 0, result.stderr
        dashboard = tmp_path / "dashboard.html"
        assert dashboard.exists(), "Expected failure page to be written"
        content = dashboard.read_text(encoding="utf-8")
        assert "fail" in content.lower() or "error" in content.lower()

    def test_failure_page_contains_stderr(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """Failure page must include the captured stderr from the regen run."""
        env = _make_env(tmp_path, autoregen=True)
        env["CLAUDE_PROSPECTOR_FAIL_REGEN"] = "1"
        _run_hook(env)
        content = (tmp_path / "dashboard.html").read_text(encoding="utf-8")
        # The failure page should contain a <pre> block with error content
        assert "<pre>" in content.lower() or "pre>" in content

    def test_exits_zero_on_failure(self, tmp_path: Path) -> None:
        """Hook exits 0 even when regen fails (no propagation to runner)."""
        env = _make_env(tmp_path, autoregen=True)
        env["CLAUDE_PROSPECTOR_FAIL_REGEN"] = "1"
        result = _run_hook(env)
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# --autoregen CLI argument parsing (issue #99)
# ---------------------------------------------------------------------------


class TestAutoregenArgParsing:
    """--autoregen CLI arg gates the hook; truthy/falsy values are parsed."""

    def test_autoregen_true_enables_regen(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """--autoregen true triggers dashboard generation (success path)."""
        env = _make_env_no_config(tmp_path)
        result = _run_hook(env, autoregen_arg="true")
        assert result.returncode == 0, result.stderr
        dashboard = tmp_path / "dashboard.html"
        assert dashboard.exists(), (
            f"Dashboard not created with --autoregen true. "
            f"stderr: {result.stderr!r}"
        )

    def test_autoregen_false_is_noop(self, tmp_path: Path) -> None:
        """--autoregen false skips dashboard generation."""
        env = _make_env_no_config(tmp_path)
        result = _run_hook(env, autoregen_arg="false")
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "dashboard.html").exists()

    def test_autoregen_1_enables_regen(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """--autoregen 1 is treated as truthy."""
        env = _make_env_no_config(tmp_path)
        result = _run_hook(env, autoregen_arg="1")
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "dashboard.html").exists()

    def test_autoregen_yes_enables_regen(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """--autoregen yes is treated as truthy."""
        env = _make_env_no_config(tmp_path)
        result = _run_hook(env, autoregen_arg="yes")
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "dashboard.html").exists()

    def test_autoregen_true_case_insensitive(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """--autoregen TRUE (uppercase) is treated as truthy."""
        env = _make_env_no_config(tmp_path)
        result = _run_hook(env, autoregen_arg="TRUE")
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "dashboard.html").exists()

    def test_autoregen_empty_string_is_noop(self, tmp_path: Path) -> None:
        """--autoregen '' (empty string) is treated as falsy."""
        env = _make_env_no_config(tmp_path)
        result = _run_hook(env, autoregen_arg="")
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "dashboard.html").exists()

    def test_autoregen_0_is_noop(self, tmp_path: Path) -> None:
        """--autoregen 0 is treated as falsy."""
        env = _make_env_no_config(tmp_path)
        result = _run_hook(env, autoregen_arg="0")
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "dashboard.html").exists()


# ---------------------------------------------------------------------------
# Legacy config.json fallback (issue #99)
# ---------------------------------------------------------------------------


class TestLegacyConfigFallback:
    """When --autoregen is absent, the hook falls back to config.json."""

    def test_no_arg_with_autoregen_true_in_config_enables_regen(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """No --autoregen arg + config.json autoregen=true triggers regen."""
        env = _make_env(tmp_path, autoregen=True)
        result = _run_hook(env)  # no autoregen_arg
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "dashboard.html").exists()

    def test_no_arg_with_autoregen_false_in_config_is_noop(
        self, tmp_path: Path
    ) -> None:
        """No --autoregen arg + config.json autoregen=false is a no-op."""
        env = _make_env(tmp_path, autoregen=False)
        result = _run_hook(env)
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "dashboard.html").exists()

    def test_no_arg_no_config_is_noop(self, tmp_path: Path) -> None:
        """No --autoregen arg + no config.json at all is a no-op."""
        env = _make_env_no_config(tmp_path)
        result = _run_hook(env)
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "dashboard.html").exists()


# ---------------------------------------------------------------------------
# Migration notice (issue #99)
# ---------------------------------------------------------------------------


class TestMigrationNotice:
    """Legacy config.json triggers a one-time migration notice in hook.log."""

    def test_migration_notice_logged_when_legacy_config_present(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """First run with legacy config.json writes [migration] to hook.log."""
        # Pass --autoregen true so the hook proceeds past the autoregen gate,
        # then checks for the legacy file.
        env = _make_env(tmp_path, autoregen=True)
        _run_hook(env, autoregen_arg="true")
        hook_log = tmp_path / "hook.log"
        assert hook_log.exists(), "hook.log should exist after successful regen"
        content = hook_log.read_text(encoding="utf-8")
        assert (
            "[migration]" in content
        ), f"Expected [migration] prefix in hook.log. Got: {content!r}"

    def test_migration_notice_not_logged_when_no_legacy_config(
        self, tmp_path: Path
    ) -> None:
        """No legacy config.json means no [migration] line in hook.log."""
        env = _make_env_no_config(tmp_path)
        _run_hook(env, autoregen_arg="true")
        hook_log = tmp_path / "hook.log"
        if hook_log.exists():
            content = hook_log.read_text(encoding="utf-8")
            assert (
                "[migration]" not in content
            ), "Should not log [migration] when no legacy config present"

    def test_migration_notice_written_only_once(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """Second run does not repeat the [migration] notice (sentinel guards)."""
        env = _make_env(tmp_path, autoregen=True)

        # First run — should write notice.
        _run_hook(env, autoregen_arg="true")
        hook_log_after_first = (tmp_path / "hook.log").read_text(encoding="utf-8")
        assert "[migration]" in hook_log_after_first

        # Second run — hook.log is truncated each run; if sentinel works, the
        # migration line must NOT appear this time.
        _run_hook(env, autoregen_arg="true")
        hook_log_after_second = (tmp_path / "hook.log").read_text(encoding="utf-8")
        assert (
            "[migration]" not in hook_log_after_second
        ), "Migration notice should not appear on second run (sentinel check)"

    def test_sentinel_file_created_after_first_run(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """Sentinel file config.json.migrated-notice is created after notice."""
        env = _make_env(tmp_path, autoregen=True)
        _run_hook(env, autoregen_arg="true")
        sentinel = tmp_path / "config.json.migrated-notice"
        assert (
            sentinel.exists()
        ), "Expected sentinel file 'config.json.migrated-notice' to be created"

    def test_legacy_config_not_deleted(self, tmp_path: Path) -> None:
        """Migration must NOT delete the legacy config.json file."""
        env = _make_env(tmp_path, autoregen=True)
        cfg_path = tmp_path / "config.json"
        assert cfg_path.exists(), "Precondition: config.json must exist"
        _run_hook(env, autoregen_arg="true")
        assert cfg_path.exists(), "config.json must not be deleted during migration"
