"""Tests for skill tracking JSONL parser and prompt skill extraction."""

from __future__ import annotations

import json
from pathlib import Path

from claude_prospector.skill_tracking import (
    parse_skill_tracking,
    extract_skills_from_prompt,
    build_skill_allowlist,
)


class TestParseSkillTracking:
    def test_empty_when_no_file(self, tmp_path: Path):
        passed, invoked = parse_skill_tracking(tmp_path)
        assert passed == []
        assert invoked == []

    def test_parses_skill_invoked_event(self, tmp_path: Path):
        log = tmp_path / "skill-tracking.jsonl"
        log.write_text(
            json.dumps(
                {
                    "event": "skill_invoked",
                    "skill": "python",
                    "timestamp": "2026-04-09T21:00:00Z",
                    "session_id": "sess-001",
                }
            )
            + "\n"
        )
        passed, invoked = parse_skill_tracking(tmp_path)
        assert len(passed) == 0
        assert len(invoked) == 1
        assert invoked[0].skill == "python"
        assert invoked[0].session_id == "sess-001"

    def test_parses_skill_passed_event(self, tmp_path: Path):
        log = tmp_path / "skill-tracking.jsonl"
        log.write_text(
            json.dumps(
                {
                    "event": "skill_passed",
                    "skill": "superpowers:test-driven-development",
                    "target_agent": "code-writer",
                    "timestamp": "2026-04-09T21:00:00Z",
                    "session_id": "sess-001",
                }
            )
            + "\n"
        )
        passed, invoked = parse_skill_tracking(tmp_path)
        assert len(passed) == 1
        assert passed[0].skill == "superpowers:test-driven-development"
        assert passed[0].target_agent == "code-writer"
        assert len(invoked) == 0

    def test_parses_mixed_events(self, tmp_path: Path):
        log = tmp_path / "skill-tracking.jsonl"
        lines = [
            json.dumps(
                {
                    "event": "skill_passed",
                    "skill": "python",
                    "target_agent": "code-writer",
                    "timestamp": "2026-04-09T21:00:00Z",
                    "session_id": "s1",
                }
            ),
            json.dumps(
                {
                    "event": "skill_invoked",
                    "skill": "python",
                    "timestamp": "2026-04-09T21:01:00Z",
                    "session_id": "s1",
                }
            ),
            json.dumps(
                {
                    "event": "skill_passed",
                    "skill": "powershell",
                    "target_agent": "debugger",
                    "timestamp": "2026-04-09T21:02:00Z",
                    "session_id": "s1",
                }
            ),
        ]
        log.write_text("\n".join(lines) + "\n")
        passed, invoked = parse_skill_tracking(tmp_path)
        assert len(passed) == 2
        assert len(invoked) == 1

    def test_skips_malformed_lines(self, tmp_path: Path):
        log = tmp_path / "skill-tracking.jsonl"
        lines = [
            "not valid json",
            json.dumps(
                {
                    "event": "skill_invoked",
                    "skill": "python",
                    "timestamp": "2026-04-09T21:00:00Z",
                    "session_id": "s1",
                }
            ),
            json.dumps({"event": "unknown_event", "skill": "x"}),
        ]
        log.write_text("\n".join(lines) + "\n")
        passed, invoked = parse_skill_tracking(tmp_path)
        assert len(invoked) == 1
        assert len(passed) == 0


class TestExtractSkillsFromPrompt:
    def setup_method(self):
        self.allowlist = {
            "python",
            "powershell",
            "git",
            "superpowers:test-driven-development",
            "superpowers:brainstorming",
            "commit-commands:commit",
        }

    def test_backtick_quoted_skill(self):
        prompt = "Use the `python` skill for code style."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["python"]

    def test_backtick_with_prefix(self):
        prompt = "Invoke `superpowers:test-driven-development` before writing code."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["superpowers:test-driven-development"]

    def test_phrase_pattern_use_the(self):
        prompt = "Use the python skill for this task."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["python"]

    def test_phrase_pattern_invoke(self):
        prompt = "Invoke the powershell skill for debugging."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["powershell"]

    def test_multiple_skills_in_prompt(self):
        prompt = "Use the `python` skill and invoke `superpowers:brainstorming` first."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["python", "superpowers:brainstorming"]

    def test_ignores_non_allowlisted_names(self):
        prompt = "Use the `nonexistent-skill` for this."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == []

    def test_no_skills_in_prompt(self):
        prompt = "Write a function that adds two numbers."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == []

    def test_deduplicates(self):
        prompt = "Use the `python` skill. Also invoke the python skill."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["python"]

    # ------------------------------------------------------------------
    # False-positive filtering tests
    # ------------------------------------------------------------------

    def test_backtick_without_skill_context_rejected(self):
        """Backtick mention of a skill name with no nearby 'skill' word
        should NOT be counted as a skill pass."""
        prompt = "Run `python` -m pytest"
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == []

    def test_backtick_with_nearby_skill_word_accepted(self):
        """Backtick mention with 'skill' in close proximity should be
        detected via both the backtick path and the phrase pattern."""
        prompt = "Use the `python` skill for style"
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["python"]

    def test_namespaced_backtick_always_accepted(self):
        """Namespaced skills in backticks need no 'skill' word nearby —
        the colon makes them unambiguous."""
        prompt = "Use `superpowers:test-driven-development` before coding"
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["superpowers:test-driven-development"]

    def test_git_backtick_in_command_context_rejected(self):
        """'git' in a command context (no nearby 'skill') should NOT
        be detected."""
        prompt = "Run `git diff` to check changes"
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == []

    def test_powershell_incidental_mention_rejected(self):
        """An incidental backtick mention of 'powershell' without a
        nearby 'skill' keyword should be filtered out."""
        prompt = "Use Bash not `powershell` for this agent"
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == []

    def test_phrase_pattern_still_works_without_backticks(self):
        """Phrase patterns ('Use the X skill') must still work even
        when there are no backticks around the skill name."""
        prompt = "Use the python skill for this"
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["python"]

    def test_mixed_real_and_incidental(self):
        """A prompt that genuinely passes 'python' via phrase pattern
        AND mentions 'git' incidentally should match only 'python'."""
        prompt = "Use the `python` skill. Run `git diff` first."
        result = extract_skills_from_prompt(prompt, self.allowlist)
        assert result == ["python"]


class TestBuildSkillAllowlist:
    def test_reads_user_skills(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        (skills_dir / "python").mkdir(parents=True)
        (skills_dir / "powershell").mkdir(parents=True)
        result = build_skill_allowlist(tmp_path)
        assert "python" in result
        assert "powershell" in result

    def test_reads_plugin_skills_with_prefix(self, tmp_path: Path):
        plugin_skills = (
            tmp_path
            / "plugins"
            / "cache"
            / "official"
            / "superpowers"
            / "5.0.7"
            / "skills"
        )
        (plugin_skills / "brainstorming").mkdir(parents=True)
        (plugin_skills / "test-driven-development").mkdir(parents=True)
        result = build_skill_allowlist(tmp_path)
        assert "brainstorming" in result
        assert "superpowers:brainstorming" in result
        assert "test-driven-development" in result
        assert "superpowers:test-driven-development" in result

    def test_empty_when_no_dirs(self, tmp_path: Path):
        result = build_skill_allowlist(tmp_path)
        assert result == set()
