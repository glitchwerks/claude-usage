import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_usage.parser import (
    decode_project_hash,
    parse_sessions,
    _parse_session,
    _parse_jsonl_messages,
)


class TestDecodeProjectHash:
    def test_windows_path_deep(self):
        assert decode_project_hash("C--Users-chris--claude") == "claude"

    def test_windows_path_shallow(self):
        assert (
            decode_project_hash("i--games-raid-rsl-rule-generator")
            == "games-raid-rsl-rule-generator"
        )

    def test_single_segment(self):
        assert decode_project_hash("myproject") == "myproject"

    def test_three_segments(self):
        assert (
            decode_project_hash("C--Users-chris--code-deep-nested--project")
            == "project"
        )

    def test_empty_string(self):
        assert decode_project_hash("") == ""


class TestParseSessions:
    def test_parses_single_session(self, sample_session_dir: Path):
        sessions = parse_sessions(sample_session_dir)
        assert len(sessions) == 1

    def test_session_metadata(self, sample_session_dir: Path):
        session = parse_sessions(sample_session_dir)[0]
        assert session.session_id == "abc-123-def"
        assert session.project == "myproject"
        assert session.root_agent == "general-purpose"

    def test_session_start_time(self, sample_session_dir: Path):
        session = parse_sessions(sample_session_dir)[0]
        expected = datetime(2026, 4, 9, 12, 0, 5, tzinfo=timezone.utc)
        assert session.start_time == expected

    def test_message_count_includes_subagent(self, sample_session_dir: Path):
        session = parse_sessions(sample_session_dir)[0]
        # 3 parent assistant messages + 1 subagent assistant message = 4
        assert len(session.messages) == 4

    def test_parent_messages_attributed_to_root_agent(self, sample_session_dir: Path):
        session = parse_sessions(sample_session_dir)[0]
        parent_msgs = [m for m in session.messages if m.agent_type == "general-purpose"]
        assert len(parent_msgs) == 3

    def test_subagent_messages_attributed_to_agent_type(self, sample_session_dir: Path):
        session = parse_sessions(sample_session_dir)[0]
        sub_msgs = [m for m in session.messages if m.agent_type == "code-writer"]
        assert len(sub_msgs) == 1
        assert sub_msgs[0].input_tokens == 500
        assert sub_msgs[0].output_tokens == 250

    def test_skill_extracted_from_tool_use(self, sample_session_dir: Path):
        session = parse_sessions(sample_session_dir)[0]
        skill_msgs = [m for m in session.messages if m.skill is not None]
        assert len(skill_msgs) == 1
        assert skill_msgs[0].skill == "superpowers:brainstorming"

    def test_subagent_types_listed(self, sample_session_dir: Path):
        session = parse_sessions(sample_session_dir)[0]
        assert session.subagent_types == ["code-writer"]

    def test_token_totals(self, sample_session_dir: Path):
        session = parse_sessions(sample_session_dir)[0]
        # Parent: (100+50+200+300) + (50+25+0+0) + (80+40+100+0) = 650+75+220 = 945
        # Subagent: 500+250+0+1000 = 1750
        # Total: 2695
        assert session.total_tokens == 2695

    def test_empty_projects_dir(self, tmp_path: Path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        sessions = parse_sessions(tmp_path)
        assert sessions == []

    def test_no_projects_dir(self, tmp_path: Path):
        sessions = parse_sessions(tmp_path)
        assert sessions == []


# ---------------------------------------------------------------------------
# Helpers for agent-setting resolution tests
# ---------------------------------------------------------------------------


def _make_assistant_line(session_id: str) -> dict:
    """Return a minimal assistant message dict for JSONL."""
    return {
        "type": "assistant",
        "timestamp": "2026-04-09T12:00:05.000Z",
        "sessionId": session_id,
        "message": {
            "model": "claude-opus-4-6",
            "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }


def _make_agent_setting_line(session_id: str, value: str) -> dict:
    """Return an agent-setting dict for JSONL."""
    return {
        "type": "agent-setting",
        "agentSetting": value,
        "sessionId": session_id,
    }


def _make_last_prompt_line(session_id: str) -> dict:
    """Return a last-prompt dict (prepended by recent Claude Code versions)."""
    return {
        "type": "last-prompt",
        "sessionId": session_id,
        "content": "some prior prompt text",
    }


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    """Write a list of dicts as JSONL to *path*."""
    path.write_text(
        "\n".join(json.dumps(line) for line in lines),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# TestAgentSettingResolution
# ---------------------------------------------------------------------------


class TestAgentSettingResolution:
    """Tests for the bounded agent-setting scan in _parse_session."""

    def test_agent_setting_on_line_0(self, tmp_path: Path):
        """agent-setting on the first line resolves root_agent correctly."""
        session_id = "sess-line0"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl,
            [
                _make_agent_setting_line(session_id, "general-purpose"),
                _make_assistant_line(session_id),
            ],
        )

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "general-purpose"

    def test_agent_setting_on_line_1_after_last_prompt(self, tmp_path: Path):
        """agent-setting on line 1 (after last-prompt) is found by bounded scan."""
        session_id = "sess-line1"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl,
            [
                _make_last_prompt_line(session_id),
                _make_agent_setting_line(session_id, "general-purpose"),
                _make_assistant_line(session_id),
            ],
        )

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "general-purpose"

    def test_no_agent_setting_with_subagents_dir(self, tmp_path: Path):
        """No agent-setting in first 5 lines + subagents/ dir → general-purpose."""
        session_id = "sess-subagents"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl,
            [
                _make_assistant_line(session_id),
            ],
        )
        # Create the subagents directory (no metadata files needed)
        (project_dir / session_id / "subagents").mkdir(parents=True)

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "general-purpose"

    def test_no_agent_setting_no_subagents_dir(self, tmp_path: Path):
        """No agent-setting in first 10 lines + no subagents/ dir → main."""
        session_id = "sess-main"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl,
            [
                _make_assistant_line(session_id),
            ],
        )

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "main"

    def test_no_agent_setting_no_subagents_dir_falls_back_to_main(self, tmp_path: Path):
        """No agent-setting + no subagents/ dir → root_agent == 'main'.

        Represents a plain top-level CLI session (e.g. opens with
        file-history-snapshot) that has no agent-setting record anywhere
        in the first 10 lines. These should be labelled 'main', not
        'unknown'.
        """
        session_id = "sess-main-fallback"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "file-history-snapshot", "sessionId": session_id},
                _make_assistant_line(session_id),
            ],
        )

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "main"

    def test_empty_file_remains_unknown(self, tmp_path: Path):
        """Empty JSONL file → root_agent == 'unknown'.

        We do not label degenerate / unreadable sessions as 'main'.
        """
        session_id = "sess-empty"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        jsonl.write_text("", encoding="utf-8")

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "unknown"

    def test_agent_setting_at_line_8_is_found(self, tmp_path: Path):
        """agent-setting placed at line index 8 is found by the N=10 scan."""
        session_id = "sess-line8"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        # 8 filler lines (file-history-snapshot), then agent-setting, then msg
        filler = [{"type": "file-history-snapshot", "sessionId": session_id}] * 8
        _write_jsonl(
            jsonl,
            filler
            + [
                _make_agent_setting_line(session_id, "general-purpose"),
                _make_assistant_line(session_id),
            ],
        )

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "general-purpose"

    def test_agent_setting_at_line_15_is_not_found(self, tmp_path: Path):
        """agent-setting at line index 15 is beyond N=10 and not found.

        Falls through to 'main' (no subagents/ dir), confirming the scan
        is still bounded.
        """
        session_id = "sess-line15"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        filler = [{"type": "file-history-snapshot", "sessionId": session_id}] * 15
        _write_jsonl(
            jsonl,
            filler
            + [
                _make_agent_setting_line(session_id, "general-purpose"),
                _make_assistant_line(session_id),
            ],
        )

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "main"

    def test_malformed_json_in_first_5_lines_does_not_crash(self, tmp_path: Path):
        """Malformed JSON lines in the scan window are skipped; scan continues."""
        session_id = "sess-malformed"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        # Write raw text: line 0 bad JSON, line 1 valid agent-setting
        content = (
            "this is not json\n"
            + json.dumps(_make_agent_setting_line(session_id, "ops"))
            + "\n"
            + json.dumps(_make_assistant_line(session_id))
            + "\n"
        )
        jsonl.write_text(content, encoding="utf-8")

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert session.root_agent == "ops"


class TestParseJsonlMessages:
    """Tests for _parse_jsonl_messages path-tuple assignment."""

    def test_assigns_full_path(self, tmp_path: Path):
        """Messages carry the full agent_path tuple passed to the function."""
        session_id = "sess-path"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        _write_jsonl(jsonl, [_make_assistant_line(session_id)])

        messages = _parse_jsonl_messages(
            jsonl, agent_type="planner", agent_path=("router", "planner")
        )
        assert len(messages) == 1
        assert messages[0].agent_path == ("router", "planner")


class TestNestedSubagents:
    """Tests for the recursive subagent walk in Phase 3."""

    def test_depth_three_path_attributed(self, nested_session_dir: Path):
        """Depth-3 messages carry the full 3-segment agent_path."""
        sessions = parse_sessions(nested_session_dir)
        assert len(sessions) == 1
        all_paths = [m.agent_path for m in sessions[0].messages]
        assert (
            "general-purpose",
            "project-planner",
            "Explore",
        ) in all_paths

    def test_depth_two_still_works(self, sample_session_dir: Path):
        """Existing depth-2 fixture still produces correct 2-segment path."""
        sessions = parse_sessions(sample_session_dir)
        assert len(sessions) == 1
        paths = [m.agent_path for m in sessions[0].messages]
        assert ("general-purpose", "code-writer") in paths

    def test_subagent_types_flattened(self, nested_session_dir: Path):
        """subagent_types includes agents from all depths, de-duped and sorted."""
        sessions = parse_sessions(nested_session_dir)
        assert len(sessions) == 1
        sub_types = sessions[0].subagent_types
        assert "project-planner" in sub_types
        assert "Explore" in sub_types

    def test_missing_meta_json_skipped(self, tmp_path: Path):
        """A stray .jsonl without a .meta.json is silently skipped."""
        session_id = "sess-stray"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl,
            [
                _make_agent_setting_line(session_id, "general-purpose"),
                _make_assistant_line(session_id),
            ],
        )
        subagent_dir = project_dir / session_id / "subagents"
        subagent_dir.mkdir(parents=True)
        # Stray JSONL with no accompanying .meta.json
        _write_jsonl(subagent_dir / "orphan.jsonl", [_make_assistant_line(session_id)])

        session = _parse_session(jsonl, "proj")
        assert session is not None
        # Only the root message should be present — orphan JSONL ignored
        assert len(session.messages) == 1

    def test_empty_subagents_dir_no_crash(self, tmp_path: Path):
        """Empty subagents/ directory at depth 2 does not crash the parser."""
        session_id = "sess-empty-sub"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            jsonl,
            [
                _make_agent_setting_line(session_id, "general-purpose"),
                _make_assistant_line(session_id),
            ],
        )
        # Create the subagents directory but leave it empty
        (project_dir / session_id / "subagents").mkdir(parents=True)

        session = _parse_session(jsonl, "proj")
        assert session is not None
        assert len(session.messages) == 1

    def test_pathological_depth_cap(self, pathological_depth_session_dir: Path):
        """12-deep chain triggers path-length-cap warning; no path exceeds 10."""
        with pytest.warns(UserWarning, match=r"path length cap"):
            sessions = parse_sessions(pathological_depth_session_dir)
        assert len(sessions) == 1
        for msg in sessions[0].messages:
            assert len(msg.agent_path) <= 10, f"agent_path too long: {msg.agent_path!r}"

    def test_pascalcase_agent_name_roundtrips(self, nested_session_dir: Path):
        """PascalCase agent name 'Explore' survives the path tuple unchanged."""
        sessions = parse_sessions(nested_session_dir)
        explore_msgs = [
            m for m in sessions[0].messages if m.agent_path[-1] == "Explore"
        ]
        assert len(explore_msgs) >= 1
        assert explore_msgs[0].agent_path[-1] == "Explore"

    def test_well_formed_tree_emits_no_warnings(self, nested_session_dir: Path):
        """A well-formed nested session tree must not emit any UserWarnings.

        Specifically, no cycle, depth-cap, OSError, or sanitization warning
        should fire when parsing a tree whose agent names are valid and whose
        depth is within the path-length cap.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            _ = parse_sessions(nested_session_dir)

    def test_separator_in_agent_name_sanitized(
        self, separator_in_name_session_dir: Path
    ):
        """Agent name containing '→' is sanitized to '﹖' and a warning fires."""
        with pytest.warns(UserWarning, match=r"Agent name contains path separator"):
            sessions = parse_sessions(separator_in_name_session_dir)
        assert len(sessions) == 1
        leaf_names = [m.agent_path[-1] for m in sessions[0].messages]
        assert "weird﹖name" in leaf_names
        assert "weird→name" not in leaf_names

    def test_symlink_cycle_short_circuits(self, symlink_cycle_session_dir: Path):
        """Visited-set cycle defense fires before depth cap; warns distinctly.

        Two assertions:
        (a) Cycle-specific warning fires (distinct from depth-cap warning).
        (b) Cycled segment appears at most once, and max path depth is <= 3
            (well below _MAX_AGENT_PATH_LENGTH = 10, proving the cap didn't fire).
        """
        with pytest.warns(UserWarning, match=r"Subagent directory cycle detected"):
            sessions = parse_sessions(symlink_cycle_session_dir)
        assert len(sessions) == 1
        paths = [m.agent_path for m in sessions[0].messages]
        # No path should exceed 3 segments (root + 1 level) — far below cap
        for path in paths:
            assert len(path) <= 3, f"Path too long for a cycle-stopped walk: {path!r}"
        # The cycled segment 'agent-x' appears at most once per path
        for path in paths:
            assert path.count("agent-x") <= 1, f"Cycled segment repeated: {path!r}"

    def test_depth_cap_fires_when_visited_set_misses(
        self, pathological_depth_session_dir: Path
    ):
        """Non-cyclic 12-deep chain triggers path-length-cap (not cycle) warning.

        Distinct message text from the cycle warning proves the two defenses
        are independently observable.
        """
        with pytest.warns(UserWarning, match=r"path length cap"):
            sessions = parse_sessions(pathological_depth_session_dir)
        assert len(sessions) == 1
        # No path should exceed the cap
        for msg in sessions[0].messages:
            assert len(msg.agent_path) <= 10


class TestOSErrorDefense:
    """Tests for OSError handling in _parse_subagents_recursive.

    Covers AC #1-3 from issue #43: the parser emits a distinct
    UserWarning when ``Path.resolve`` raises ``OSError``, continues
    parsing other subagent directories, and returns records for healthy
    sessions alongside the one with the unreadable subagent directory.
    """

    def test_oserror_on_resolve_emits_distinct_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OSError from resolve() emits a warning distinct from cycle/depth-cap.

        AC #1: the warning message must be different from the cycle
        warning ("Subagent directory cycle detected") and the depth-cap
        warning ("depth cap").
        """
        session_id = "sess-oserror"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"

        lines = [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            {
                "type": "assistant",
                "timestamp": "2026-05-14T10:00:00.000Z",
                "sessionId": session_id,
                "message": {
                    "model": "claude-opus-4-6",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hi"}],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ]
        jsonl.write_text(
            "\n".join(json.dumps(line) for line in lines),
            encoding="utf-8",
        )

        subagent_dir = project_dir / session_id / "subagents"
        subagent_dir.mkdir(parents=True)
        (subagent_dir / "agent-err.meta.json").write_text(
            json.dumps({"agentType": "code-writer"}), encoding="utf-8"
        )

        _original_resolve = Path.resolve

        def _patched_resolve(self: Path, strict: bool = False) -> Path:
            """Raise OSError when called on the subagent dir under test."""
            if self == subagent_dir:
                raise OSError("Simulated unreadable directory")
            return _original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", _patched_resolve)

        with pytest.warns(UserWarning, match=r"unreadable subagent directory"):
            _parse_session(jsonl, "proj")

    def test_oserror_warning_distinct_from_cycle_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OSError warning text does not match cycle or depth-cap patterns.

        Confirms message text is distinguishable from both existing
        warning types without relying on pytest.warns exclusion.
        """
        session_id = "sess-oserror-distinct"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"
        jsonl.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-05-14T10:00:00.000Z",
                    "sessionId": session_id,
                    "message": {
                        "model": "claude-opus-4-6",
                        "role": "assistant",
                        "content": [],
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        subagent_dir = project_dir / session_id / "subagents"
        subagent_dir.mkdir(parents=True)

        _original_resolve = Path.resolve

        def _patched_resolve(self: Path, strict: bool = False) -> Path:
            if self == subagent_dir:
                raise OSError("No such device")
            return _original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", _patched_resolve)

        caught_messages: list[str] = []
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _parse_session(jsonl, "proj")
        caught_messages = [str(warning.message) for warning in w]

        assert len(caught_messages) == 1
        msg = caught_messages[0]
        # Must not match the other two warning types
        assert "cycle detected" not in msg
        assert "path length cap" not in msg
        # Must contain the OSError-specific text
        assert "unreadable subagent directory" in msg

    def test_parser_continues_after_oserror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Parser continues and returns records when one subagent dir raises OSError.

        AC #2 + #3: two subagent entries exist; only the first triggers
        OSError on resolve(). The second parses successfully, proving the
        loop continues and records for the healthy session are returned.
        """
        session_id = "sess-oserror-continue"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"

        lines = [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            {
                "type": "assistant",
                "timestamp": "2026-05-14T10:00:00.000Z",
                "sessionId": session_id,
                "message": {
                    "model": "claude-opus-4-6",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ]
        jsonl.write_text(
            "\n".join(json.dumps(line) for line in lines),
            encoding="utf-8",
        )

        subagent_dir = project_dir / session_id / "subagents"
        subagent_dir.mkdir(parents=True)

        # First subagent: the one whose subagents/ child will raise OSError
        (subagent_dir / "agent-bad.meta.json").write_text(
            json.dumps({"agentType": "broken-agent"}), encoding="utf-8"
        )
        bad_subagent_jsonl_lines = [
            {
                "type": "assistant",
                "timestamp": "2026-05-14T10:01:00.000Z",
                "sessionId": session_id,
                "message": {
                    "model": "claude-sonnet-4-6",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ]
        (subagent_dir / "agent-bad.jsonl").write_text(
            "\n".join(json.dumps(line) for line in bad_subagent_jsonl_lines),
            encoding="utf-8",
        )
        bad_child_dir = subagent_dir / "agent-bad"
        bad_child_dir.mkdir(parents=True)
        bad_child_subagents = bad_child_dir / "subagents"
        bad_child_subagents.mkdir(parents=True)

        # Second subagent: healthy, should produce one record
        (subagent_dir / "agent-ok.meta.json").write_text(
            json.dumps({"agentType": "healthy-agent"}), encoding="utf-8"
        )
        ok_subagent_jsonl_lines = [
            {
                "type": "assistant",
                "timestamp": "2026-05-14T10:02:00.000Z",
                "sessionId": session_id,
                "message": {
                    "model": "claude-haiku-4-5",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 99,
                        "output_tokens": 33,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ]
        (subagent_dir / "agent-ok.jsonl").write_text(
            "\n".join(json.dumps(line) for line in ok_subagent_jsonl_lines),
            encoding="utf-8",
        )

        _original_resolve = Path.resolve

        def _patched_resolve(self: Path, strict: bool = False) -> Path:
            """Raise OSError only for the bad child's subagents directory."""
            if self == bad_child_subagents:
                raise OSError("Simulated permission denied")
            return _original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", _patched_resolve)

        with pytest.warns(UserWarning, match=r"unreadable subagent directory"):
            session = _parse_session(jsonl, "proj")

        assert session is not None
        # Root (1) + bad agent (1) + healthy agent (1) = 3 messages total
        agent_types = {m.agent_type for m in session.messages}
        assert (
            "healthy-agent" in agent_types
        ), "healthy-agent records must be present even after OSError"

    def test_other_sessions_unaffected_by_oserror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sessions without an unreadable subagent dir parse fully.

        AC #3: when one session's subagent dir raises OSError, other
        sessions in the same data directory parse without errors or
        missing records.
        """
        # Session 1: has an unreadable subagent directory
        bad_session_id = "sess-bad"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        bad_jsonl = project_dir / f"{bad_session_id}.jsonl"
        bad_jsonl.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-05-14T09:00:00.000Z",
                    "sessionId": bad_session_id,
                    "message": {
                        "model": "claude-opus-4-6",
                        "role": "assistant",
                        "content": [],
                        "usage": {
                            "input_tokens": 5,
                            "output_tokens": 2,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        bad_subagent_dir = project_dir / bad_session_id / "subagents"
        bad_subagent_dir.mkdir(parents=True)

        # Session 2: fully healthy
        ok_session_id = "sess-ok"
        ok_jsonl = project_dir / f"{ok_session_id}.jsonl"
        ok_jsonl.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-05-14T10:00:00.000Z",
                    "sessionId": ok_session_id,
                    "message": {
                        "model": "claude-haiku-4-5",
                        "role": "assistant",
                        "content": [],
                        "usage": {
                            "input_tokens": 77,
                            "output_tokens": 44,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        _original_resolve = Path.resolve

        def _patched_resolve(self: Path, strict: bool = False) -> Path:
            if self == bad_subagent_dir:
                raise OSError("Simulated unreadable directory")
            return _original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", _patched_resolve)

        with pytest.warns(UserWarning, match=r"unreadable subagent directory"):
            sessions = parse_sessions(tmp_path)

        assert len(sessions) == 2
        session_ids = {s.session_id for s in sessions}
        assert ok_session_id in session_ids
        # Verify the healthy session has its record intact
        ok_session = next(s for s in sessions if s.session_id == ok_session_id)
        assert len(ok_session.messages) == 1
        assert ok_session.messages[0].input_tokens == 77


class TestEmptyAgentTypeDefense:
    """Tests for empty/null agentType defense in _parse_subagents_recursive.

    Covers issue #45 Item 3: ``meta.get("agentType") or "unknown"`` must
    handle missing-key, ``None``, and empty-string ``""`` uniformly,
    producing ``agent_type == "unknown"`` in all three cases.
    """

    def _make_session_with_subagent_meta(
        self, tmp_path: Path, agent_type_value: object
    ) -> Path:
        """Build a minimal session fixture with one subagent whose meta has
        the given agentType value (or omits the key when value is a sentinel).

        Args:
            tmp_path: Pytest-provided temporary directory.
            agent_type_value: The value to write for ``agentType`` in the
                subagent's ``*.meta.json``.  Pass the string ``"__omit__"``
                to omit the key entirely.

        Returns:
            Path to the data directory suitable for ``parse_sessions()``.
        """
        session_id = "sess-empty-agent-type"
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl = project_dir / f"{session_id}.jsonl"

        root_lines = [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            {
                "type": "assistant",
                "timestamp": "2026-05-14T10:00:00.000Z",
                "sessionId": session_id,
                "message": {
                    "model": "claude-opus-4-6",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ]
        jsonl.write_text(
            "\n".join(json.dumps(line) for line in root_lines),
            encoding="utf-8",
        )

        subagent_dir = project_dir / session_id / "subagents"
        subagent_dir.mkdir(parents=True)

        if agent_type_value == "__omit__":
            meta: dict = {}
        else:
            meta = {"agentType": agent_type_value}
        (subagent_dir / "agent-ea.meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )

        subagent_lines = [
            {
                "type": "assistant",
                "timestamp": "2026-05-14T10:01:00.000Z",
                "sessionId": session_id,
                "message": {
                    "model": "claude-sonnet-4-6",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ]
        (subagent_dir / "agent-ea.jsonl").write_text(
            "\n".join(json.dumps(line) for line in subagent_lines),
            encoding="utf-8",
        )
        return tmp_path

    def test_empty_string_agent_type_defaults_to_unknown(self, tmp_path: Path) -> None:
        """agentType ``""`` in metadata.json must parse as ``"unknown"``.

        An empty string passes through ``meta.get("agentType", "unknown")``
        unchanged, producing an empty-string leaf in ``agent_path``.  The
        ``or "unknown"`` fix must short-circuit the empty string.
        """
        data_dir = self._make_session_with_subagent_meta(tmp_path, "")
        sessions = parse_sessions(data_dir)
        assert len(sessions) == 1
        subagent_msgs = [m for m in sessions[0].messages if len(m.agent_path) == 2]
        assert len(subagent_msgs) >= 1
        for msg in subagent_msgs:
            assert msg.agent_type == "unknown", (
                f"Expected agent_type='unknown' for empty agentType, "
                f"got {msg.agent_type!r}"
            )
            assert (
                msg.agent_path[-1] == "unknown"
            ), f"Expected agent_path leaf='unknown', got {msg.agent_path!r}"

    def test_null_agent_type_defaults_to_unknown(self, tmp_path: Path) -> None:
        """agentType ``null`` in metadata.json must parse as ``"unknown"``.

        JSON ``null`` deserialises to Python ``None``.
        ``meta.get("agentType", "unknown")`` returns ``None`` (key present),
        which must be caught by the ``or "unknown"`` guard.
        """
        data_dir = self._make_session_with_subagent_meta(tmp_path, None)
        sessions = parse_sessions(data_dir)
        assert len(sessions) == 1
        subagent_msgs = [m for m in sessions[0].messages if len(m.agent_path) == 2]
        assert len(subagent_msgs) >= 1
        for msg in subagent_msgs:
            assert msg.agent_type == "unknown", (
                f"Expected agent_type='unknown' for null agentType, "
                f"got {msg.agent_type!r}"
            )
            assert (
                msg.agent_path[-1] == "unknown"
            ), f"Expected agent_path leaf='unknown', got {msg.agent_path!r}"
