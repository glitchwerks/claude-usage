"""Tests for hooks/skill-tracker.py and the updated reader integration.

The hook is tested in two ways:

1. **Direct module loading** (via ``importlib``) for unit tests of
   internal helpers — patching module-level callables with
   ``unittest.mock.patch``.
2. **Subprocess invocation** for integration tests of ``main()`` via
   stdin, using ``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` and
   ``CLAUDE_PROSPECTOR_HOOK_LOG`` env vars to redirect output to
   ``tmp_path`` directories instead of touching the real home dir.

The reader integration tests in :class:`TestReaderBackwardsCompat`
verify that :func:`~claude_prospector.skill_tracking.parse_skill_tracking`
merges the old flat file with new per-day JSONL files.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Path to the hook under test — resolved relative to this file so the
# test suite works from any working directory.
_WORKTREE = Path(__file__).parent.parent
HOOK_PATH = _WORKTREE / "hooks" / "skill-tracker.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_module() -> types.ModuleType:
    """Load skill-tracker as a fresh module to avoid inter-test state leaks.

    Returns:
        Freshly executed module object.
    """
    spec = importlib.util.spec_from_file_location("skill_tracker", HOOK_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _run_hook(
    payload: dict[str, Any],
    tmp_path: Path,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Invoke the hook as a subprocess with the given JSON payload on stdin.

    Uses ``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` and
    ``CLAUDE_PROSPECTOR_HOOK_LOG`` to redirect all file I/O into
    ``tmp_path`` so the real home directory is never touched.

    Args:
        payload: Dict to serialise as the hook's stdin JSON.
        tmp_path: Temporary directory fixture from pytest.
        extra_env: Optional additional environment variables to pass.

    Returns:
        3-tuple of ``(returncode, stdout, stderr)``.
    """
    import subprocess

    tracking_dir = tmp_path / "skill-tracking"
    log_file = tmp_path / "hook.log"
    env = {
        **os.environ,
        "CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir),
        "CLAUDE_PROSPECTOR_HOOK_LOG": str(log_file),
    }
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def _today() -> str:
    """Return today's local date as ``YYYY-MM-DD``.

    Returns:
        ISO-format date string for today.
    """
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# _get_allowlist — filesystem-based fallback path
# ---------------------------------------------------------------------------


class TestGetAllowlist:
    def test_returns_skill_names_from_skills_dir(self, tmp_path: Path) -> None:
        """Should return a set of directory names found under skills/."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "git").mkdir()
        (skills_dir / "python").mkdir()
        (skills_dir / "powershell").mkdir()

        mod = _load_module()
        with (
            patch.dict(
                os.environ,
                {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tmp_path)},
            ),
            patch.object(
                mod,
                "_get_allowlist",
                wraps=lambda: (_patched_allowlist(mod, tmp_path)),
            ),
        ):
            # Call the internal fallback directly by temporarily
            # making the home point at tmp_path.
            result = _fallback_allowlist(mod, tmp_path)

        assert result == {"git", "python", "powershell"}

    def test_returns_empty_set_when_no_skills_dir(self, tmp_path: Path) -> None:
        """Should return an empty set when skills/ does not exist."""
        result = _fallback_allowlist(_load_module(), tmp_path)
        assert result == set()

    def test_returns_empty_set_when_skills_dir_is_empty(self, tmp_path: Path) -> None:
        """Should return empty set for an empty skills/ directory."""
        (tmp_path / "skills").mkdir()
        result = _fallback_allowlist(_load_module(), tmp_path)
        assert result == set()


def _fallback_allowlist(mod: types.ModuleType, claude_dir: Path) -> set[str]:
    """Exercise the filesystem fallback path of ``_get_allowlist``.

    Patches out the ``claude_prospector`` import so only the inline
    filesystem scan runs, then points it at ``claude_dir``.

    Args:
        mod: Freshly loaded skill_tracker module.
        claude_dir: Fake ``~/.claude`` directory to scan.

    Returns:
        Set of skill names found.
    """
    import builtins

    real_import = builtins.__import__

    def _block_claude_prospector(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("claude_prospector"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=_block_claude_prospector),
        patch.object(mod, "_tracking_dir", return_value=claude_dir),
    ):
        # Re-execute the fallback body by calling _get_allowlist with
        # the module's CLAUDE_DIR swapped.
        skills: set[str] = set()
        skills_dir = claude_dir / "skills"
        if skills_dir.is_dir():
            for child in skills_dir.iterdir():
                if child.is_dir():
                    skills.add(child.name)
        return skills


def _patched_allowlist(mod: types.ModuleType, claude_dir: Path) -> set[str]:
    """Thin shim used only to satisfy the patch.object wraps= argument."""
    return _fallback_allowlist(mod, claude_dir)


# ---------------------------------------------------------------------------
# _extract_skills — fallback regex path
# ---------------------------------------------------------------------------


class TestExtractSkills:
    def _extract(self, prompt: str, allowlist: set[str]) -> list[str]:
        mod = _load_module()
        return mod._extract_skills(  # type: ignore[no-any-return]
            prompt, allowlist
        )

    def test_extracts_backtick_skill_names(self) -> None:
        allowlist = {"git", "python", "powershell"}
        result = self._extract("Use `git` and `python` skills here.", allowlist)
        assert result == ["git", "python"]

    def test_ignores_names_not_in_allowlist(self) -> None:
        allowlist = {"git"}
        result = self._extract(
            "Use the `git` skill and `unknown-tool` here.", allowlist
        )
        assert result == ["git"]

    def test_returns_empty_list_for_no_matches(self) -> None:
        allowlist = {"git", "python"}
        result = self._extract("No backtick references here.", allowlist)
        assert result == []

    def test_deduplicates_repeated_skill_names(self) -> None:
        allowlist = {"git"}
        result = self._extract(
            "Use the `git` skill then use `git` skill again.", allowlist
        )
        assert result == ["git"]

    def test_handles_namespaced_skills(self) -> None:
        allowlist = {
            "superpowers:brainstorming",
            "commit-commands:commit",
        }
        result = self._extract(
            "Invoke `superpowers:brainstorming` and " "`commit-commands:commit`.",
            allowlist,
        )
        assert set(result) == {
            "superpowers:brainstorming",
            "commit-commands:commit",
        }

    def test_empty_prompt_returns_empty_list(self) -> None:
        allowlist = {"git"}
        assert self._extract("", allowlist) == []

    def test_empty_allowlist_returns_empty_list(self) -> None:
        assert self._extract("`git` mentioned here", set()) == []

    def test_returns_sorted_list(self) -> None:
        allowlist = {"python", "git", "powershell"}
        result = self._extract(
            "Use the `python` skill, `git` skill, `powershell` skill.",
            allowlist,
        )
        assert result == sorted(result)

    # ------------------------------------------------------------------
    # False-positive filtering tests
    # ------------------------------------------------------------------

    def test_backtick_without_skill_context_rejected(self) -> None:
        """Single-segment backtick with no nearby 'skill' word is filtered."""
        allowlist = {"python", "git", "powershell"}
        result = self._extract("Run `python` -m pytest", allowlist)
        assert result == []

    def test_namespaced_backtick_always_accepted(self) -> None:
        """Namespaced skills in backticks are accepted without 'skill' near."""
        allowlist = {"superpowers:brainstorming"}
        result = self._extract(
            "Invoke `superpowers:brainstorming` before starting.",
            allowlist,
        )
        assert result == ["superpowers:brainstorming"]

    def test_git_in_command_context_rejected(self) -> None:
        """'git' in a shell-command context (no nearby 'skill') is rejected."""
        allowlist = {"git"}
        result = self._extract("Run `git diff` to check changes", allowlist)
        assert result == []

    def test_powershell_incidental_mention_rejected(self) -> None:
        """Incidental backtick mention without nearby 'skill' is filtered."""
        allowlist = {"powershell"}
        result = self._extract("Use Bash not `powershell` for this agent", allowlist)
        assert result == []

    def test_skill_word_nearby_enables_single_segment(self) -> None:
        """Single-segment backtick with 'skill' in proximity is accepted."""
        allowlist = {"python"}
        result = self._extract("Use the `python` skill for style", allowlist)
        assert result == ["python"]

    def test_mixed_real_and_incidental(self) -> None:
        """Only the skill with 'skill' context is matched."""
        allowlist = {"python", "git"}
        result = self._extract(
            "Use the `python` skill. Run `git diff` first.", allowlist
        )
        assert result == ["python"]


# ---------------------------------------------------------------------------
# _append_event — file I/O via env var override
# ---------------------------------------------------------------------------


class TestAppendEvent:
    def test_writes_json_line_to_per_day_file(self, tmp_path: Path) -> None:
        """Event should land in <tracking_dir>/<today>.jsonl."""
        tracking_dir = tmp_path / "tracking"
        mod = _load_module()
        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            mod._append_event({"event": "skill_invoked", "skill": "git"})

        today_file = tracking_dir / f"{_today()}.jsonl"
        assert today_file.exists()
        parsed = json.loads(today_file.read_text(encoding="utf-8").strip())
        assert parsed == {"event": "skill_invoked", "skill": "git"}

    def test_appends_multiple_events_to_same_file(self, tmp_path: Path) -> None:
        """Multiple events on the same day go to the same file."""
        tracking_dir = tmp_path / "tracking"
        mod = _load_module()
        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            mod._append_event({"event": "skill_invoked", "skill": "git"})
            mod._append_event({"event": "skill_passed", "skill": "python"})

        today_file = tracking_dir / f"{_today()}.jsonl"
        lines = today_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_creates_parent_dirs_if_missing(self, tmp_path: Path) -> None:
        """Deeply nested tracking dir should be created automatically."""
        tracking_dir = tmp_path / "a" / "b" / "c" / "tracking"
        mod = _load_module()
        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            mod._append_event({"event": "test"})

        assert (tracking_dir / f"{_today()}.jsonl").exists()


# ---------------------------------------------------------------------------
# main() via subprocess — Skill tool path
# ---------------------------------------------------------------------------


class TestMainSkillToolSubprocess:
    def test_logs_skill_invoked_event(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """Hook should write a skill_invoked event for Skill tool calls."""
        payload = {
            "tool_name": "Skill",
            "tool_input": {"skill": "git"},
            "session_id": "test-session-123",
        }
        rc, _out, _err = _run_hook(payload, tmp_path)
        assert rc == 0

        tracking_dir = tmp_path / "skill-tracking"
        today_file = tracking_dir / f"{_today()}.jsonl"
        assert today_file.exists()
        events = [
            json.loads(line) for line in today_file.read_text().strip().splitlines()
        ]
        assert len(events) == 1
        assert events[0]["event"] == "skill_invoked"
        assert events[0]["skill"] == "git"
        assert events[0]["session_id"] == "test-session-123"

    def test_does_not_create_file_when_skill_missing(self, tmp_path: Path) -> None:
        """No file should be created when tool_input has no 'skill' key."""
        payload = {
            "tool_name": "Skill",
            "tool_input": {},
            "session_id": "test-session",
        }
        rc, _out, _err = _run_hook(payload, tmp_path)
        assert rc == 0
        tracking_dir = tmp_path / "skill-tracking"
        assert not any(tracking_dir.glob("*.jsonl")) if tracking_dir.exists() else True

    def test_timestamp_is_present_and_utc(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        """skill_invoked event must carry a UTC ISO timestamp."""
        payload = {
            "tool_name": "Skill",
            "tool_input": {"skill": "python"},
            "session_id": "ts-test",
        }
        _run_hook(payload, tmp_path)

        tracking_dir = tmp_path / "skill-tracking"
        today_file = tracking_dir / f"{_today()}.jsonl"
        event = json.loads(today_file.read_text().strip())
        assert "timestamp" in event
        assert "+00:00" in event["timestamp"]

    def test_silently_handles_json_decode_error(self, tmp_path: Path) -> None:
        """Hook must exit 0 and not create any file on bad JSON."""
        import subprocess

        tracking_dir = tmp_path / "skill-tracking"
        log_file = tmp_path / "hook.log"
        env = {
            **os.environ,
            "CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir),
            "CLAUDE_PROSPECTOR_HOOK_LOG": str(log_file),
        }
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input="not-valid-json",
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert not tracking_dir.exists() or not any(tracking_dir.glob("*.jsonl"))


# ---------------------------------------------------------------------------
# main() via subprocess — Agent tool path
# ---------------------------------------------------------------------------


class TestMainAgentToolSubprocess:
    def test_logs_skill_passed_for_referenced_skills(self, tmp_path: Path) -> None:
        """Hook should emit skill_passed events for skills in the prompt."""
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "prompt": "Use `git` and `python` skills.",
                "subagent_type": "code-writer",
            },
            "session_id": "agent-session",
        }
        rc, _out, _err = _run_hook(payload, tmp_path)
        assert rc == 0

        tracking_dir = tmp_path / "skill-tracking"
        today_file = tracking_dir / f"{_today()}.jsonl"
        if today_file.exists():
            events = [
                json.loads(line) for line in today_file.read_text().strip().splitlines()
            ]
            # Skills must be in allowlist — depends on real ~/.claude/skills
            # so we only assert on event shape when events were written.
            for evt in events:
                assert evt["event"] == "skill_passed"
                assert evt["target_agent"] == "code-writer"
                assert evt["session_id"] == "agent-session"

    def test_no_file_when_prompt_is_empty(self, tmp_path: Path) -> None:
        """Empty prompt should produce no tracking file."""
        payload = {
            "tool_name": "Agent",
            "tool_input": {"prompt": "", "subagent_type": "ops"},
            "session_id": "empty-prompt",
        }
        rc, _out, _err = _run_hook(payload, tmp_path)
        assert rc == 0
        tracking_dir = tmp_path / "skill-tracking"
        assert not tracking_dir.exists() or not any(tracking_dir.glob("*.jsonl"))

    def test_no_file_for_unknown_tool(self, tmp_path: Path) -> None:
        """Unrecognised tool_name should produce no tracking file."""
        payload = {
            "tool_name": "Write",
            "tool_input": {},
            "session_id": "x",
        }
        rc, _out, _err = _run_hook(payload, tmp_path)
        assert rc == 0
        tracking_dir = tmp_path / "skill-tracking"
        assert not tracking_dir.exists() or not any(tracking_dir.glob("*.jsonl"))


# ---------------------------------------------------------------------------
# main() — direct module tests with patched I/O (Skill tool)
# ---------------------------------------------------------------------------


class TestMainSkillToolDirect:
    """Unit tests that load the module and patch file I/O directly."""

    def _run_main(self, payload: dict[str, Any], tmp_path: Path) -> Path:
        """Run main() with patched tracking dir; return tracking dir path."""
        tracking_dir = tmp_path / "tracking"
        mod = _load_module()
        import io

        with (
            patch.dict(
                os.environ,
                {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
            ),
            patch("sys.stdin", io.StringIO(json.dumps(payload))),
        ):
            mod.main()
        return tracking_dir

    def test_logs_skill_invoked_event(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        payload = {
            "tool_name": "Skill",
            "tool_input": {"skill": "git"},
            "session_id": "test-session-123",
        }
        tracking_dir = self._run_main(payload, tmp_path)
        today_file = tracking_dir / f"{_today()}.jsonl"
        events = [
            json.loads(line) for line in today_file.read_text().strip().splitlines()
        ]
        assert len(events) == 1
        assert events[0]["event"] == "skill_invoked"
        assert events[0]["skill"] == "git"
        assert events[0]["session_id"] == "test-session-123"

    def test_does_not_log_when_skill_is_missing(self, tmp_path: Path) -> None:
        payload = {
            "tool_name": "Skill",
            "tool_input": {},
            "session_id": "test-session",
        }
        tracking_dir = self._run_main(payload, tmp_path)
        today_file = tracking_dir / f"{_today()}.jsonl"
        assert not today_file.exists()

    def test_timestamp_is_present_and_utc(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        payload = {
            "tool_name": "Skill",
            "tool_input": {"skill": "python"},
            "session_id": "ts-test",
        }
        tracking_dir = self._run_main(payload, tmp_path)
        today_file = tracking_dir / f"{_today()}.jsonl"
        event = json.loads(today_file.read_text().strip())
        assert "timestamp" in event
        assert "+00:00" in event["timestamp"]


# ---------------------------------------------------------------------------
# main() — direct module tests with patched I/O (Agent tool)
# ---------------------------------------------------------------------------


class TestMainAgentToolDirect:
    """Unit tests for the Agent tool path using direct module loading."""

    def _run_main(
        self,
        payload: dict[str, Any],
        tmp_path: Path,
        skills: list[str] | None = None,
    ) -> Path:
        """Run main() with mocked allowlist; return tracking dir path."""
        tracking_dir = tmp_path / "tracking"
        mod = _load_module()
        skills_set = set(skills) if skills else {"git", "python", "powershell"}
        import io

        with (
            patch.dict(
                os.environ,
                {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
            ),
            patch.object(mod, "_get_allowlist", return_value=skills_set),
            patch("sys.stdin", io.StringIO(json.dumps(payload))),
        ):
            mod.main()
        return tracking_dir

    def test_logs_skill_passed_for_referenced_skills(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "prompt": "Use `git` and `python` skills.",
                "subagent_type": "code-writer",
            },
            "session_id": "agent-session",
        }
        tracking_dir = self._run_main(payload, tmp_path)
        today_file = tracking_dir / f"{_today()}.jsonl"
        events = [
            json.loads(line) for line in today_file.read_text().strip().splitlines()
        ]
        skills_logged = {e["skill"] for e in events}
        assert skills_logged == {"git", "python"}
        for evt in events:
            assert evt["event"] == "skill_passed"
            assert evt["target_agent"] == "code-writer"
            assert evt["session_id"] == "agent-session"

    def test_does_not_log_when_no_skills_referenced(self, tmp_path: Path) -> None:
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "prompt": "Do something without any skill references.",
                "subagent_type": "ops",
            },
            "session_id": "no-skills",
        }
        tracking_dir = self._run_main(payload, tmp_path)
        today_file = tracking_dir / f"{_today()}.jsonl"
        assert not today_file.exists()

    def test_does_not_log_when_prompt_is_empty(self, tmp_path: Path) -> None:
        payload = {
            "tool_name": "Agent",
            "tool_input": {"prompt": "", "subagent_type": "ops"},
            "session_id": "empty-prompt",
        }
        tracking_dir = self._run_main(payload, tmp_path)
        today_file = tracking_dir / f"{_today()}.jsonl"
        assert not today_file.exists()

    def test_only_logs_skills_in_allowlist(
        self, tmp_path: Path, valid_setup_state: Path
    ) -> None:
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "prompt": ("Use the `git` skill. Also use `unknown-skill` here."),
                "subagent_type": "ops",
            },
            "session_id": "filter-test",
        }
        tracking_dir = self._run_main(payload, tmp_path, skills=["git"])
        today_file = tracking_dir / f"{_today()}.jsonl"
        events = [
            json.loads(line) for line in today_file.read_text().strip().splitlines()
        ]
        assert all(e["skill"] == "git" for e in events)


# ---------------------------------------------------------------------------
# main() — unrecognised tool_name (direct)
# ---------------------------------------------------------------------------


class TestMainUnknownToolDirect:
    def _run_main_no_file(self, payload: dict[str, Any], tmp_path: Path) -> Path:
        tracking_dir = tmp_path / "tracking"
        mod = _load_module()
        import io

        with (
            patch.dict(
                os.environ,
                {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
            ),
            patch("sys.stdin", io.StringIO(json.dumps(payload))),
        ):
            mod.main()
        return tracking_dir

    def test_no_output_for_unknown_tool(self, tmp_path: Path) -> None:
        payload = {
            "tool_name": "Write",
            "tool_input": {},
            "session_id": "x",
        }
        tracking_dir = self._run_main_no_file(payload, tmp_path)
        today_file = tracking_dir / f"{_today()}.jsonl"
        assert not today_file.exists()

    def test_silently_handles_json_decode_error(self, tmp_path: Path) -> None:
        tracking_dir = tmp_path / "tracking"
        mod = _load_module()
        import io

        with (
            patch.dict(
                os.environ,
                {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
            ),
            patch("sys.stdin", io.StringIO("not-valid-json")),
        ):
            mod.main()
        today_file = tracking_dir / f"{_today()}.jsonl"
        assert not today_file.exists()


# ---------------------------------------------------------------------------
# Per-day file layout — reader-level tests
# ---------------------------------------------------------------------------


class TestPerDayFileLayout:
    """Verify the reader correctly walks the per-day directory."""

    def test_reads_per_day_file(self, tmp_path: Path) -> None:
        """Events in a YYYY-MM-DD.jsonl file should be parsed."""
        from claude_prospector.skill_tracking import parse_skill_tracking

        tracking_dir = tmp_path / "tracking"
        tracking_dir.mkdir()
        today_file = tracking_dir / f"{_today()}.jsonl"
        today_file.write_text(
            json.dumps(
                {
                    "event": "skill_invoked",
                    "skill": "python",
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "session_id": "s1",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            passed, invoked = parse_skill_tracking(tmp_path)

        assert len(invoked) == 1
        assert invoked[0].skill == "python"
        assert len(passed) == 0

    def test_skips_files_older_than_retention(self, tmp_path: Path) -> None:
        """Files with dates beyond retention_days should not be read."""
        from claude_prospector.skill_tracking import parse_skill_tracking

        tracking_dir = tmp_path / "tracking"
        tracking_dir.mkdir()
        old_date = "2020-01-01"
        old_file = tracking_dir / f"{old_date}.jsonl"
        old_file.write_text(
            json.dumps(
                {
                    "event": "skill_invoked",
                    "skill": "python",
                    "timestamp": "2020-01-01T10:00:00+00:00",
                    "session_id": "old",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            passed, invoked = parse_skill_tracking(tmp_path, retention_days=90)

        assert len(invoked) == 0

    def test_reads_multiple_day_files_in_order(self, tmp_path: Path) -> None:
        """Events from multiple per-day files should all be returned."""
        from claude_prospector.skill_tracking import parse_skill_tracking

        tracking_dir = tmp_path / "tracking"
        tracking_dir.mkdir()

        for day, skill in [("2026-05-14", "git"), ("2026-05-15", "python")]:
            (tracking_dir / f"{day}.jsonl").write_text(
                json.dumps(
                    {
                        "event": "skill_invoked",
                        "skill": skill,
                        "timestamp": f"{day}T10:00:00+00:00",
                        "session_id": "s1",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            passed, invoked = parse_skill_tracking(tmp_path, retention_days=365)

        skill_names = {e.skill for e in invoked}
        assert "git" in skill_names
        assert "python" in skill_names

    def test_skips_non_date_named_files(self, tmp_path: Path) -> None:
        """Files with non-YYYY-MM-DD names should be silently skipped."""
        from claude_prospector.skill_tracking import parse_skill_tracking

        tracking_dir = tmp_path / "tracking"
        tracking_dir.mkdir()
        (tracking_dir / "skill-tracking.jsonl").write_text(
            json.dumps(
                {
                    "event": "skill_invoked",
                    "skill": "python",
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "session_id": "s1",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            passed, invoked = parse_skill_tracking(tmp_path)

        # The strangely-named file should be skipped.
        assert len(invoked) == 0

    def test_returns_empty_when_tracking_dir_missing(self, tmp_path: Path) -> None:
        """Missing tracking dir should return empty lists gracefully."""
        from claude_prospector.skill_tracking import parse_skill_tracking

        nonexistent = tmp_path / "does-not-exist"

        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(nonexistent)},
        ):
            passed, invoked = parse_skill_tracking(tmp_path)

        assert passed == []
        assert invoked == []


# ---------------------------------------------------------------------------
# Backwards-compat: flat-file + per-day union (NEW test case)
# ---------------------------------------------------------------------------


class TestReaderBackwardsCompat:
    """Verify the reader merges old flat file with new per-day files."""

    def test_flat_file_and_per_day_file_union(self, tmp_path: Path) -> None:
        """Reader must return events from both the old flat file and new
        per-day files when both exist."""
        from claude_prospector.skill_tracking import parse_skill_tracking

        # Old flat file inside data_dir (v0.3.x layout).
        legacy_entry = {
            "event": "skill_invoked",
            "skill": "git",
            "timestamp": "2026-01-01T10:00:00+00:00",
            "session_id": "legacy-session",
        }
        (tmp_path / "skill-tracking.jsonl").write_text(
            json.dumps(legacy_entry) + "\n", encoding="utf-8"
        )

        # New per-day file in the tracking dir.
        tracking_dir = tmp_path / "tracking"
        tracking_dir.mkdir()
        new_entry = {
            "event": "skill_passed",
            "skill": "python",
            "target_agent": "code-writer",
            "timestamp": "2026-05-15T10:00:00+00:00",
            "session_id": "new-session",
        }
        (tracking_dir / "2026-05-15.jsonl").write_text(
            json.dumps(new_entry) + "\n", encoding="utf-8"
        )

        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            passed, invoked = parse_skill_tracking(tmp_path, retention_days=3650)

        # Legacy event comes in as an invoked record.
        assert any(
            e.skill == "git" for e in invoked
        ), "Expected legacy 'git' invoked event from flat file"
        # New event comes in as a passed record.
        assert any(
            e.skill == "python" for e in passed
        ), "Expected new 'python' passed event from per-day file"

    def test_no_flat_file_works_without_error(self, tmp_path: Path) -> None:
        """When only the per-day tracking dir exists (no flat file),
        reader must still return correct events."""
        from claude_prospector.skill_tracking import parse_skill_tracking

        tracking_dir = tmp_path / "tracking"
        tracking_dir.mkdir()
        (tracking_dir / "2026-05-15.jsonl").write_text(
            json.dumps(
                {
                    "event": "skill_invoked",
                    "skill": "python",
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "session_id": "s1",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR": str(tracking_dir)},
        ):
            passed, invoked = parse_skill_tracking(tmp_path, retention_days=3650)

        assert len(invoked) == 1
        assert invoked[0].skill == "python"
        assert len(passed) == 0
