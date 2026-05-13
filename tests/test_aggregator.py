from datetime import datetime, timedelta, timezone

from claude_usage.aggregator import aggregate
from claude_usage.models import MessageRecord, SessionRecord


def _msg(
    model="claude-opus-4-6",
    agent="general-purpose",
    skill=None,
    input_t=100,
    output_t=50,
    cache_read=0,
    cache_create=0,
    ts=None,
):
    return MessageRecord(
        timestamp=ts or datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
        model=model,
        agent_type=agent,
        skill=skill,
        input_tokens=input_t,
        output_tokens=output_t,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_create,
    )


def _session(
    messages,
    session_id="s1",
    project="proj",
    root_agent="general-purpose",
    subagent_types=None,
):
    start = (
        min(m.timestamp for m in messages)
        if messages
        else datetime(2026, 4, 9, tzinfo=timezone.utc)
    )
    return SessionRecord(
        session_id=session_id,
        project=project,
        start_time=start,
        root_agent=root_agent,
        messages=messages,
        subagent_types=subagent_types or [],
    )


class TestAggregateByModel:
    def test_groups_by_model_short(self):
        sessions = [
            _session(
                [
                    _msg(model="claude-opus-4-6", input_t=100, output_t=50),
                    _msg(model="claude-sonnet-4-6", input_t=200, output_t=100),
                    _msg(model="claude-opus-4-6", input_t=50, output_t=25),
                ]
            )
        ]
        result = aggregate(sessions)
        assert result.by_model["opus"]["total_tokens"] == 225
        assert result.by_model["sonnet"]["total_tokens"] == 300

    def test_model_message_count(self):
        sessions = [
            _session(
                [
                    _msg(model="claude-opus-4-6"),
                    _msg(model="claude-opus-4-6"),
                    _msg(model="claude-sonnet-4-6"),
                ]
            )
        ]
        result = aggregate(sessions)
        assert result.by_model["opus"]["message_count"] == 2
        assert result.by_model["sonnet"]["message_count"] == 1


class TestAggregateByAgent:
    def test_groups_by_agent_type(self):
        sessions = [
            _session(
                [
                    _msg(agent="general-purpose", input_t=100, output_t=50),
                    _msg(
                        agent="code-writer",
                        model="claude-sonnet-4-6",
                        input_t=200,
                        output_t=100,
                    ),
                ]
            )
        ]
        result = aggregate(sessions)
        assert result.by_agent["general-purpose"]["total_tokens"] == 150
        assert result.by_agent["code-writer"]["total_tokens"] == 300

    def test_agent_includes_model(self):
        sessions = [
            _session(
                [
                    _msg(agent="general-purpose", model="claude-opus-4-6"),
                ]
            )
        ]
        result = aggregate(sessions)
        assert result.by_agent["general-purpose"]["primary_model"] == "opus"


class TestAggregateBySkill:
    def test_groups_by_skill(self):
        sessions = [
            _session(
                [
                    _msg(skill="superpowers:brainstorming", input_t=100, output_t=50),
                    _msg(skill="superpowers:brainstorming", input_t=200, output_t=100),
                    _msg(
                        skill="commit-commands:commit-push-pr", input_t=50, output_t=25
                    ),
                    _msg(skill=None, input_t=1000, output_t=500),
                ]
            )
        ]
        result = aggregate(sessions)
        assert result.by_skill["superpowers:brainstorming"]["invocation_count"] == 2
        assert (
            result.by_skill["commit-commands:commit-push-pr"]["invocation_count"] == 1
        )
        assert None not in result.by_skill


class TestAggregateByProject:
    def test_groups_by_project(self):
        sessions = [
            _session([_msg(input_t=100, output_t=50)], project="proj-a"),
            _session(
                [_msg(input_t=200, output_t=100)], session_id="s2", project="proj-b"
            ),
        ]
        result = aggregate(sessions)
        assert result.by_project["proj-a"]["total_tokens"] == 150
        assert result.by_project["proj-b"]["total_tokens"] == 300


class TestAggregateDaily:
    def test_groups_by_day(self):
        day1 = datetime(2026, 4, 8, 10, 0, 0, tzinfo=timezone.utc)
        day2 = datetime(2026, 4, 9, 14, 0, 0, tzinfo=timezone.utc)
        sessions = [
            _session(
                [
                    _msg(ts=day1, input_t=100, output_t=50),
                    _msg(ts=day2, input_t=200, output_t=100),
                ]
            )
        ]
        result = aggregate(sessions)
        assert "2026-04-08" in result.by_day
        assert "2026-04-09" in result.by_day
        assert result.by_day["2026-04-08"]["total_tokens"] == 150
        assert result.by_day["2026-04-09"]["total_tokens"] == 300


class TestAggregateTimeFilter:
    def test_filter_by_date_range(self):
        old = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        recent = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
        sessions = [
            _session(
                [
                    _msg(ts=old, input_t=100, output_t=50),
                    _msg(ts=recent, input_t=200, output_t=100),
                ]
            )
        ]
        from_date = datetime(2026, 4, 5, tzinfo=timezone.utc)
        result = aggregate(sessions, from_date=from_date)
        assert result.total_tokens == 300

    def test_filter_by_window(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=10)
        recent = now - timedelta(hours=2)
        sessions = [
            _session(
                [
                    _msg(ts=old, input_t=100, output_t=50),
                    _msg(ts=recent, input_t=200, output_t=100),
                ]
            )
        ]
        result = aggregate(sessions, window_hours=5)
        assert result.total_tokens == 300
