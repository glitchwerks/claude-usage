"""Parse Claude Code session JSONL files and subagent metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_usage.models import MessageRecord, SessionRecord


def decode_project_hash(hash_name: str) -> str:
    """Decode a project hash directory name to a human-readable project name.

    Claude Code encodes project paths: '--' represents a path separator,
    '-' represents a hyphen or space within segment names. We split on '--'
    and take the last segment as the project name.

    Examples:
        'C--Users-chris--claude' -> 'claude'
        'i--games-raid-rsl-rule-generator' -> 'games-raid-rsl-rule-generator'
    """
    if not hash_name:
        return ""
    segments = hash_name.split("--")
    return segments[-1]


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a datetime."""
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)


def _extract_skill(content: list[dict]) -> str | None:
    """Extract skill name from assistant message content blocks."""
    for block in content:
        if (
            block.get("type") == "tool_use"
            and block.get("name") == "Skill"
            and isinstance(block.get("input"), dict)
        ):
            return block["input"].get("skill")
    return None


def _parse_jsonl_messages(
    jsonl_path: Path,
    agent_type: str,
    agent_path: tuple[str, ...] = (),
) -> list[MessageRecord]:
    """Parse assistant messages from a JSONL file, attributing to agent."""
    messages: list[MessageRecord] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue

            msg = entry.get("message", {})
            usage = msg.get("usage")
            model = msg.get("model")
            if not usage or not model:
                continue

            content = msg.get("content", [])
            skill = _extract_skill(content) if isinstance(content, list) else None

            timestamp = _parse_timestamp(entry["timestamp"])

            messages.append(
                MessageRecord(
                    timestamp=timestamp,
                    model=model,
                    agent_type=agent_type,
                    skill=skill,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    agent_path=agent_path,
                )
            )
    return messages


_AGENT_SETTING_SCAN_LINES = 10


def _parse_session(jsonl_path: Path, project_name: str) -> SessionRecord | None:
    """Parse a single session JSONL file and its subagents.

    Agent-setting resolution uses a three-branch strategy to handle recent
    Claude Code versions that prepend a ``last-prompt`` line before the
    ``agent-setting`` line:

    1. **Bounded scan**: read the first ``_AGENT_SETTING_SCAN_LINES`` lines;
       use the ``agentSetting`` value from the first ``agent-setting`` entry.
    2. **Subagents fallback**: if no ``agent-setting`` was found and the
       ``<session_id>/subagents/`` directory exists (only the router spawns
       sub-agents, implying general-purpose), set ``root_agent`` to
       ``"general-purpose"``.
    3. **Main fallback**: plain top-level CLI sessions that have no
       ``agent-setting`` record and no subagents directory default to
       ``"main"`` rather than ``"unknown"``.
    4. **Unknown preserved**: degenerate cases (empty file, all-malformed JSON,
       file unreadable) retain ``"unknown"`` so they are not silently mislabelled.
    """
    session_id = jsonl_path.stem

    # Resolve the subagent directory early — needed for the fallback branch.
    subagent_dir = jsonl_path.parent / session_id / "subagents"

    # Branch 1: bounded scan for agent-setting in the first N lines.
    # Track whether any parseable line was seen to distinguish a populated
    # session (no agent-setting → "main") from an empty/degenerate one
    # (no lines at all → "unknown").
    root_agent = "unknown"
    saw_any_line = False
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for _ in range(_AGENT_SETTING_SCAN_LINES):
            raw = f.readline()
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            saw_any_line = True
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "agent-setting":
                root_agent = entry.get("agentSetting", "unknown")
                break

    # Branch 2: subagents-directory fallback when no agent-setting found.
    if root_agent == "unknown" and subagent_dir.is_dir():
        root_agent = "general-purpose"

    # Branch 3: populated session with no agent-setting and no subagents/ dir
    # → top-level main-thread CLI session.
    if root_agent == "unknown" and saw_any_line:
        root_agent = "main"

    # Parse parent session messages
    messages = _parse_jsonl_messages(
        jsonl_path, agent_type=root_agent, agent_path=(root_agent,)
    )

    # Parse subagent messages
    subagent_types: list[str] = []
    if subagent_dir.is_dir():
        for meta_path in subagent_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                agent_type = meta.get("agentType", "unknown")
            except (json.JSONDecodeError, OSError):
                agent_type = "unknown"

            subagent_types.append(agent_type)

            # Find matching JSONL
            agent_id = meta_path.stem.replace(".meta", "")
            sub_jsonl = subagent_dir / f"{agent_id}.jsonl"
            if sub_jsonl.is_file():
                messages.extend(
                    _parse_jsonl_messages(
                        sub_jsonl,
                        agent_type=agent_type,
                        agent_path=(agent_type,),
                    )
                )

    if not messages:
        start_time = datetime.now(timezone.utc)
    else:
        start_time = min(m.timestamp for m in messages)

    return SessionRecord(
        session_id=session_id,
        project=project_name,
        start_time=start_time,
        root_agent=root_agent,
        messages=messages,
        subagent_types=sorted(set(subagent_types)),
    )


def parse_sessions(data_dir: Path) -> list[SessionRecord]:
    """Parse all sessions from a Claude Code data directory.

    Args:
        data_dir: Path to the Claude data directory (e.g. ~/.claude).
                  Sessions are in data_dir/projects/<hash>/<session>.jsonl

    Returns:
        List of SessionRecord objects, sorted by start_time descending.
    """
    projects_dir = data_dir / "projects"
    if not projects_dir.is_dir():
        return []

    sessions: list[SessionRecord] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = decode_project_hash(project_dir.name)

        for jsonl_path in project_dir.glob("*.jsonl"):
            session = _parse_session(jsonl_path, project_name)
            if session is not None:
                sessions.append(session)

    sessions.sort(key=lambda s: s.start_time, reverse=True)
    return sessions
