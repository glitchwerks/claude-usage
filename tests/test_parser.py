import json
from datetime import datetime, timezone
from pathlib import Path

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
