"""Aggregate parsed session data by model, agent, skill, project, and time."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from claude_usage.constants import AGENT_PATH_SEPARATOR as _AGENT_PATH_SEPARATOR
from claude_usage.models import (
    MessageRecord,
    SessionRecord,
    SkillPassedEvent,
    SkillInvokedEvent,
)

#: Delimiter joining agent_path segments into a by_agent key string.
#: Sourced from :mod:`claude_usage.constants`; re-exported here so
#: existing callers that import this name from ``aggregator`` continue
#: to work unchanged.
AGENT_PATH_SEPARATOR: str = _AGENT_PATH_SEPARATOR


def _path_key(msg: MessageRecord) -> str:
    """Return the delimited path-string key for a message's agent_path.

    Joins ``msg.agent_path`` with ``AGENT_PATH_SEPARATOR``.  For depth-1
    records the result is a bare single-segment string identical to the old
    ``agent_type`` value, preserving backward compatibility.

    Args:
        msg: The message record whose ``agent_path`` is joined.

    Returns:
        Delimited path string, e.g. ``"general-purpose→project-planner→Explore"``.
        Returns the empty string if ``agent_path`` is empty (should not occur
        for records produced by the current parser, but guards against stale
        records with the default empty tuple).
    """
    return AGENT_PATH_SEPARATOR.join(msg.agent_path)


@dataclass
class AggregateResult:
    """Holds all aggregated data for rendering."""

    total_tokens: int = 0
    total_messages: int = 0
    total_sessions: int = 0

    by_model: dict[str, dict] = field(default_factory=dict)
    by_agent: dict[str, dict] = field(default_factory=dict)
    by_skill: dict[str, dict] = field(default_factory=dict)
    by_project: dict[str, dict] = field(default_factory=dict)
    by_day: dict[str, dict] = field(default_factory=dict)
    sessions: list[dict] = field(default_factory=list)
    by_skill_adoption: dict[str, dict] = field(default_factory=dict)


def _add_tokens(bucket: dict, msg: MessageRecord) -> None:
    """Add a message's token counts to an accumulator dict."""
    bucket["total_tokens"] = bucket.get("total_tokens", 0) + msg.total_tokens
    bucket["input_tokens"] = bucket.get("input_tokens", 0) + msg.input_tokens
    bucket["output_tokens"] = bucket.get("output_tokens", 0) + msg.output_tokens
    bucket["cache_read_tokens"] = (
        bucket.get("cache_read_tokens", 0) + msg.cache_read_tokens
    )
    bucket["cache_creation_tokens"] = (
        bucket.get("cache_creation_tokens", 0) + msg.cache_creation_tokens
    )
    bucket["message_count"] = bucket.get("message_count", 0) + 1


def aggregate(
    sessions: list[SessionRecord],
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    window_hours: float | None = None,
) -> AggregateResult:
    """Aggregate session data with optional time filtering.

    Args:
        sessions: Parsed session records.
        from_date: Only include messages on or after this time.
        to_date: Only include messages before this time.
        window_hours: Rolling window - only include messages from the last N hours.
                      Overrides from_date if set.
    """
    result = AggregateResult()

    if window_hours is not None:
        from_date = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        to_date = None

    filtered_messages: list[MessageRecord] = []
    session_ids_seen: set[str] = set()
    agent_models: dict[str, Counter] = defaultdict(Counter)
    project_sessions: dict[str, set] = defaultdict(set)

    for session in sessions:
        session_messages: list[MessageRecord] = []
        for msg in session.messages:
            if from_date and msg.timestamp < from_date:
                continue
            if to_date and msg.timestamp >= to_date:
                continue
            session_messages.append(msg)
            filtered_messages.append(msg)

        if session_messages:
            session_ids_seen.add(session.session_id)
            project_sessions[session.project].add(session.session_id)

            model_tokens: dict[str, int] = defaultdict(int)
            for m in session_messages:
                model_tokens[m.model_short] += m.total_tokens

            # Emit only the deepest path-key per chain so the dashboard JS
            # does not double-count when apportioning
            # s.total_tokens / s.agents.length.
            # An entry k is a leaf iff no other entry starts with
            # k + AGENT_PATH_SEPARATOR (i.e. k is not a proper prefix of
            # any other observed path).
            all_path_keys = {_path_key(m) for m in session_messages}
            leaf_path_keys = {
                k
                for k in all_path_keys
                if not any(
                    other != k and other.startswith(k + AGENT_PATH_SEPARATOR)
                    for other in all_path_keys
                )
            }
            agents_in_session = sorted(leaf_path_keys)

            result.sessions.append(
                {
                    "session_id": session.session_id,
                    "project": session.project,
                    "start_time": min(
                        m.timestamp for m in session_messages
                    ).isoformat(),
                    "root_agent": session.root_agent,
                    "agents": agents_in_session,
                    "total_tokens": sum(m.total_tokens for m in session_messages),
                    "model_split": dict(model_tokens),
                    "duration_minutes": session.duration_minutes,
                    "message_count": len(session_messages),
                }
            )

    result.total_tokens = sum(m.total_tokens for m in filtered_messages)
    result.total_messages = len(filtered_messages)
    result.total_sessions = len(session_ids_seen)

    for msg in filtered_messages:
        model = msg.model_short
        if model not in result.by_model:
            result.by_model[model] = {}
        _add_tokens(result.by_model[model], msg)

    for msg in filtered_messages:
        agent = _path_key(msg)
        if agent not in result.by_agent:
            result.by_agent[agent] = {}
        _add_tokens(result.by_agent[agent], msg)
        agent_models[agent][msg.model_short] += 1

    for agent, counter in agent_models.items():
        result.by_agent[agent]["primary_model"] = counter.most_common(1)[0][0]

    agent_session_count: dict[str, set] = defaultdict(set)
    for session_summary in result.sessions:
        for agent in session_summary["agents"]:
            agent_session_count[agent].add(session_summary["session_id"])
    for agent in result.by_agent:
        result.by_agent[agent]["session_count"] = len(
            agent_session_count.get(agent, set())
        )

    for msg in filtered_messages:
        if msg.skill is None:
            continue
        if msg.skill not in result.by_skill:
            result.by_skill[msg.skill] = {"invocation_count": 0, "total_tokens": 0}
        result.by_skill[msg.skill]["invocation_count"] += 1
        result.by_skill[msg.skill]["total_tokens"] += msg.total_tokens

    result.by_project = {}
    for session_summary in result.sessions:
        proj = session_summary["project"]
        if proj not in result.by_project:
            result.by_project[proj] = {
                "total_tokens": 0,
                "session_count": 0,
                "message_count": 0,
            }
        result.by_project[proj]["total_tokens"] += session_summary["total_tokens"]
        result.by_project[proj]["message_count"] += session_summary["message_count"]
    for proj, sess_ids in project_sessions.items():
        if proj in result.by_project:
            result.by_project[proj]["session_count"] = len(sess_ids)

    for msg in filtered_messages:
        day = msg.timestamp.strftime("%Y-%m-%d")
        if day not in result.by_day:
            result.by_day[day] = {"total_tokens": 0, "by_model": {}}
        result.by_day[day]["total_tokens"] += msg.total_tokens
        model = msg.model_short
        if model not in result.by_day[day]["by_model"]:
            result.by_day[day]["by_model"][model] = 0
        result.by_day[day]["by_model"][model] += msg.total_tokens

    result.sessions.sort(key=lambda s: s["start_time"], reverse=True)

    return result


def compute_skill_adoption(
    passed_events: list[SkillPassedEvent],
    invoked_events: list[SkillInvokedEvent],
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> dict[str, dict]:
    """Correlate skill_passed and skill_invoked events into adoption metrics.

    Only skills with at least one skill_passed event appear in the result.
    Direct invocations (no matching pass) are excluded.
    """
    if from_date:
        passed_events = [e for e in passed_events if e.timestamp >= from_date]
        invoked_events = [e for e in invoked_events if e.timestamp >= from_date]
    if to_date:
        passed_events = [e for e in passed_events if e.timestamp < to_date]
        invoked_events = [e for e in invoked_events if e.timestamp < to_date]

    invoked_sessions: dict[str, set[str]] = defaultdict(set)
    for evt in invoked_events:
        invoked_sessions[evt.skill].add(evt.session_id)

    passed_by_skill: dict[str, list[SkillPassedEvent]] = defaultdict(list)
    for evt in passed_events:
        passed_by_skill[evt.skill].append(evt)

    result: dict[str, dict] = {}
    for skill, pass_list in passed_by_skill.items():
        times_invoked = sum(
            1
            for evt in pass_list
            if evt.session_id in invoked_sessions.get(skill, set())
        )
        times_passed = len(pass_list)

        by_agent: dict[str, dict[str, int]] = defaultdict(
            lambda: {"passed": 0, "invoked": 0}
        )
        for evt in pass_list:
            by_agent[evt.target_agent]["passed"] += 1
            if evt.session_id in invoked_sessions.get(skill, set()):
                by_agent[evt.target_agent]["invoked"] += 1

        result[skill] = {
            "times_passed": times_passed,
            "times_invoked": times_invoked,
            "adoption_rate": round(times_invoked / times_passed, 3)
            if times_passed > 0
            else 0.0,
            "by_target_agent": dict(by_agent),
        }

    return result
