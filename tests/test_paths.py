"""Tests for claude_prospector.paths — central path resolution module.

Each path function is tested for:
1. Default: resolves relative to Path.home() / ".claude" / "claude-prospector"
2. Env-var override: returns the env-var value verbatim as a Path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import claude_prospector.paths as paths_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all CLAUDE_PROSPECTOR_* env vars to test defaults."""
    for key in [
        "CLAUDE_PROSPECTOR_BASE_DIR",
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
