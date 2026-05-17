"""Tests for claude_prospector.paths — central path resolution module.

Each path function is tested for:
1. Default: resolves relative to Path.home() / ".claude" / "claude-prospector"
2. Env-var override: returns the env-var value verbatim as a Path.
3. Three-tier resolution: CLAUDE_PROSPECTOR_BASE_DIR > CLAUDE_PLUGIN_DATA >
   legacy ~/.claude/claude-prospector/.
4. One-time migration from legacy dir to CLAUDE_PLUGIN_DATA.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import claude_prospector.paths as paths_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all path-controlling env vars to test defaults."""
    for key in [
        "CLAUDE_PROSPECTOR_BASE_DIR",
        "CLAUDE_PLUGIN_DATA",
        "CLAUDE_PROSPECTOR_CONFIG",
        "CLAUDE_PROSPECTOR_DASHBOARD",
        "CLAUDE_PROSPECTOR_HOOK_LOG",
        "CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# base_dir
# ---------------------------------------------------------------------------


class TestBaseDir:
    """Tests for paths.base_dir()."""

    def test_default_resolves_under_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default base_dir is ~/.claude/claude-prospector/."""
        _clear_env(monkeypatch)
        result = paths_mod.base_dir()
        expected = Path.home() / ".claude" / "claude-prospector"
        assert result == expected

    def test_env_var_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_BASE_DIR overrides the default base dir."""
        _clear_env(monkeypatch)
        custom = tmp_path / "custom-base"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_BASE_DIR", str(custom))
        assert paths_mod.base_dir() == custom


# ---------------------------------------------------------------------------
# config_path
# ---------------------------------------------------------------------------


class TestConfigPath:
    """Tests for paths.config_path()."""

    def test_default_is_base_dir_slash_config_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default config_path is base_dir() / 'config.json'."""
        _clear_env(monkeypatch)
        result = paths_mod.config_path()
        expected = paths_mod.base_dir() / "config.json"
        assert result == expected

    def test_env_var_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_CONFIG overrides the config path."""
        _clear_env(monkeypatch)
        custom = tmp_path / "my-config.json"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_CONFIG", str(custom))
        assert paths_mod.config_path() == custom

    def test_env_var_independent_of_base_dir_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_CONFIG is returned verbatim even if BASE_DIR is set."""
        _clear_env(monkeypatch)
        monkeypatch.setenv("CLAUDE_PROSPECTOR_BASE_DIR", str(tmp_path / "base"))
        custom_config = tmp_path / "cfg.json"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_CONFIG", str(custom_config))
        assert paths_mod.config_path() == custom_config


# ---------------------------------------------------------------------------
# dashboard_path
# ---------------------------------------------------------------------------


class TestDashboardPath:
    """Tests for paths.dashboard_path()."""

    def test_default_is_base_dir_slash_dashboard_html(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default dashboard_path is base_dir() / 'dashboard.html'."""
        _clear_env(monkeypatch)
        result = paths_mod.dashboard_path()
        expected = paths_mod.base_dir() / "dashboard.html"
        assert result == expected

    def test_env_var_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_DASHBOARD overrides the dashboard path."""
        _clear_env(monkeypatch)
        custom = tmp_path / "dash.html"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_DASHBOARD", str(custom))
        assert paths_mod.dashboard_path() == custom


# ---------------------------------------------------------------------------
# hook_log_path
# ---------------------------------------------------------------------------


class TestHookLogPath:
    """Tests for paths.hook_log_path()."""

    def test_default_is_base_dir_slash_hook_log(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default hook_log_path is base_dir() / 'hook.log'."""
        _clear_env(monkeypatch)
        result = paths_mod.hook_log_path()
        expected = paths_mod.base_dir() / "hook.log"
        assert result == expected

    def test_env_var_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_HOOK_LOG overrides the hook log path."""
        _clear_env(monkeypatch)
        custom = tmp_path / "custom.log"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_HOOK_LOG", str(custom))
        assert paths_mod.hook_log_path() == custom


# ---------------------------------------------------------------------------
# skill_tracking_dir
# ---------------------------------------------------------------------------


class TestSkillTrackingDir:
    """Tests for paths.skill_tracking_dir()."""

    def test_default_is_base_dir_slash_skill_tracking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default skill_tracking_dir is base_dir() / 'skill-tracking/'."""
        _clear_env(monkeypatch)
        result = paths_mod.skill_tracking_dir()
        expected = paths_mod.base_dir() / "skill-tracking"
        assert result == expected

    def test_env_var_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR overrides the tracking dir."""
        _clear_env(monkeypatch)
        custom = tmp_path / "tracking"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR", str(custom))
        assert paths_mod.skill_tracking_dir() == custom

    def test_base_dir_override_propagates_to_skill_tracking(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When BASE_DIR is overridden, skill_tracking_dir follows it."""
        _clear_env(monkeypatch)
        custom_base = tmp_path / "mybase"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_BASE_DIR", str(custom_base))
        result = paths_mod.skill_tracking_dir()
        assert result == custom_base / "skill-tracking"


# ---------------------------------------------------------------------------
# Three-tier resolution
# ---------------------------------------------------------------------------


class TestBaseDirThreeTier:
    """Tests for the three-tier base_dir() resolution order."""

    def test_plugin_data_used_when_no_base_dir_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PLUGIN_DATA is used when CLAUDE_PROSPECTOR_BASE_DIR is unset."""
        _clear_env(monkeypatch)
        plugin_data = tmp_path / "plugin-data"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
        result = paths_mod.base_dir()
        assert result == plugin_data

    def test_base_dir_wins_over_plugin_data(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_BASE_DIR takes priority over CLAUDE_PLUGIN_DATA."""
        _clear_env(monkeypatch)
        override = tmp_path / "override"
        plugin_data = tmp_path / "plugin-data"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_BASE_DIR", str(override))
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
        result = paths_mod.base_dir()
        assert result == override

    def test_legacy_fallback_when_neither_env_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Legacy ~/.claude/claude-prospector/ used when no env vars set."""
        _clear_env(monkeypatch)
        result = paths_mod.base_dir()
        expected = Path.home() / ".claude" / "claude-prospector"
        assert result == expected

    def test_plugin_data_does_not_append_subdir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PLUGIN_DATA is used as-is; no subdirectory is appended."""
        _clear_env(monkeypatch)
        plugin_data = tmp_path / "my-plugin-state"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
        result = paths_mod.base_dir()
        assert result == plugin_data
        # Confirm no extra path segment was appended
        assert result.name == "my-plugin-state"


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestLegacyMigration:
    """Tests for one-time migration from legacy dir to CLAUDE_PLUGIN_DATA."""

    def _make_legacy(self, legacy_dir: Path) -> None:
        """Create a legacy dir with some content."""
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "config.json").write_text('{"autoregen": false}')
        (legacy_dir / "hook.log").write_text("old log")
        tracking = legacy_dir / "skill-tracking"
        tracking.mkdir()
        (tracking / "2026-01-01.jsonl").write_text('{"event":"test"}')

    def test_migration_moves_files_and_removes_legacy(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Files are copied to new dir and legacy dir is deleted."""
        _clear_env(monkeypatch)
        legacy = tmp_path / ".claude" / "claude-prospector"
        self._make_legacy(legacy)
        new_base = tmp_path / "plugin-data"
        # new_base does not exist yet (empty target)
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(new_base))
        # Redirect legacy path resolution to our tmp_path version
        monkeypatch.setattr(paths_mod, "_DEFAULT_BASE", legacy)

        result = paths_mod.base_dir()

        assert result == new_base
        # Content should have moved
        assert (new_base / "config.json").exists()
        assert (new_base / "hook.log").exists()
        assert (new_base / "skill-tracking" / "2026-01-01.jsonl").exists()
        # Legacy dir should be gone
        assert not legacy.exists()

    def test_migration_skipped_when_legacy_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """No error when legacy dir doesn't exist."""
        _clear_env(monkeypatch)
        legacy = tmp_path / ".claude" / "claude-prospector"
        # legacy dir intentionally NOT created
        new_base = tmp_path / "plugin-data"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(new_base))
        monkeypatch.setattr(paths_mod, "_DEFAULT_BASE", legacy)

        result = paths_mod.base_dir()

        assert result == new_base
        assert not new_base.exists()  # No files to move, no creation

    def test_migration_skipped_when_new_dir_nonempty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Migration is skipped when the new dir already has content."""
        _clear_env(monkeypatch)
        legacy = tmp_path / ".claude" / "claude-prospector"
        self._make_legacy(legacy)
        new_base = tmp_path / "plugin-data"
        new_base.mkdir(parents=True)
        existing_file = new_base / "existing.txt"
        existing_file.write_text("already here")
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(new_base))
        monkeypatch.setattr(paths_mod, "_DEFAULT_BASE", legacy)

        paths_mod.base_dir()

        # Legacy dir should still exist (migration was skipped)
        assert legacy.exists()
        # Existing content in new dir should be untouched
        assert existing_file.exists()

    def test_migration_skipped_when_legacy_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Migration is skipped when legacy dir exists but has no content."""
        _clear_env(monkeypatch)
        legacy = tmp_path / ".claude" / "claude-prospector"
        legacy.mkdir(parents=True)  # exists but empty
        new_base = tmp_path / "plugin-data"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(new_base))
        monkeypatch.setattr(paths_mod, "_DEFAULT_BASE", legacy)

        paths_mod.base_dir()

        # Legacy dir still there (empty, no migration needed)
        assert legacy.exists()

    def test_migration_idempotent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A second call after successful migration is a no-op."""
        _clear_env(monkeypatch)
        legacy = tmp_path / ".claude" / "claude-prospector"
        self._make_legacy(legacy)
        new_base = tmp_path / "plugin-data"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(new_base))
        monkeypatch.setattr(paths_mod, "_DEFAULT_BASE", legacy)

        # First call — performs migration
        paths_mod.base_dir()
        assert not legacy.exists()
        assert (new_base / "config.json").exists()

        # Second call — legacy gone, new dir non-empty → no error
        result = paths_mod.base_dir()
        assert result == new_base
        assert (new_base / "config.json").exists()

    def test_migration_failure_does_not_raise(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A failed migration logs the error but does not propagate."""
        _clear_env(monkeypatch)
        legacy = tmp_path / ".claude" / "claude-prospector"
        self._make_legacy(legacy)
        new_base = tmp_path / "plugin-data"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(new_base))
        monkeypatch.setattr(paths_mod, "_DEFAULT_BASE", legacy)

        # Make new_base a file so mkdir/move fails
        new_base.write_text("I am a file, not a dir")

        # Should not raise — returns the plugin_data path anyway
        result = paths_mod.base_dir()
        assert result == new_base

    def test_migration_logs_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Successful migration writes a [migration] line to the hook log."""
        _clear_env(monkeypatch)
        legacy = tmp_path / ".claude" / "claude-prospector"
        self._make_legacy(legacy)
        new_base = tmp_path / "plugin-data"
        log_path = tmp_path / "hook.log"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(new_base))
        monkeypatch.setenv("CLAUDE_PROSPECTOR_HOOK_LOG", str(log_path))
        monkeypatch.setattr(paths_mod, "_DEFAULT_BASE", legacy)

        paths_mod.base_dir()

        assert log_path.exists()
        content = log_path.read_text()
        assert "[migration]" in content
