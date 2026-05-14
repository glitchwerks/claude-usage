from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_usage.aggregator import AGENT_PATH_SEPARATOR, aggregate
from claude_usage.models import MessageRecord, SessionRecord
from claude_usage.parser import parse_sessions


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
        agent_path=(agent,),
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


class TestAggregateByAgentPath:
    """Phase 4: path-keyed by_agent rollup and deepest-leaf agents_in_session.

    After Phase 4, ``by_agent`` keys are delimited path strings
    (``"root→child→leaf"``) and ``agents_in_session`` contains only the
    deepest-leaf path-key per chain so the dashboard JS does not double-count
    when apportioning ``s.total_tokens / s.agents.length``.
    """

    def test_depth_one_uses_single_segment_key(self):
        """A depth-1 session produces a bare single-segment key.

        Backward compat: after Phase 4, ``by_agent["main"]`` is still a
        valid key for a depth-1 session, identical to the old flat behavior.
        """
        sessions = [
            _session(
                [_msg(agent="main", input_t=100, output_t=50)],
            )
        ]
        result = aggregate(sessions)
        assert result.by_agent == {
            "main": result.by_agent["main"]
        }, "Depth-1 session must produce a single-segment key 'main'"
        assert result.by_agent["main"]["total_tokens"] == 150

    def test_depth_two_uses_delimited_key(self):
        """A depth-2 message produces a ``parent→child`` key."""
        sessions = [
            _session(
                [
                    _make_path_msg(
                        ("general-purpose", "code-writer"),
                        input_t=200,
                        output_t=100,
                    ),
                ]
            )
        ]
        result = aggregate(sessions)
        key = f"general-purpose{AGENT_PATH_SEPARATOR}code-writer"
        assert (
            key in result.by_agent
        ), f"Depth-2 path key '{key}' must appear in by_agent"
        assert result.by_agent[key]["total_tokens"] == 300

    def test_depth_three_uses_full_path_key(self, nested_session_dir: Path):
        """Depth-3 fixture produces the full three-segment path key."""
        sessions = parse_sessions(nested_session_dir)
        result = aggregate(sessions)
        key = (
            f"general-purpose{AGENT_PATH_SEPARATOR}"
            f"project-planner{AGENT_PATH_SEPARATOR}Explore"
        )
        assert key in result.by_agent, (
            f"Depth-3 path key '{key}' must appear in by_agent. "
            f"Keys present: {sorted(result.by_agent)}"
        )
        # depth-3 fixture: 400 input + 200 output = 600 total
        assert result.by_agent[key]["total_tokens"] == 600

    def test_intermediate_path_not_implicitly_created(self, nested_session_dir: Path):
        """No implicit rollup key is created for a path with no direct messages.

        The aggregator must not create synthetic intermediate buckets.  Only
        paths that appear as a literal ``agent_path`` on at least one message
        produce a ``by_agent`` entry.  The leaf-only bare key ``"Explore"``
        (which the old code emitted via ``m.agent_type``) must NOT appear;
        the full path-key ``"general-purpose→project-planner→Explore"`` is
        the only correct form for those depth-3 messages.

        Similarly, the bare key ``"project-planner"`` must not appear.  In
        the ``nested_session_dir`` fixture ``project-planner`` has its own
        direct messages, so it DOES produce the path-keyed entry
        ``"general-purpose→project-planner"`` — but it must NOT appear under
        the old flat ``"project-planner"`` key.  This asserts that the
        path-keyed shape applies to every depth, not only the deepest leaf.
        """
        sessions = parse_sessions(nested_session_dir)
        result = aggregate(sessions)
        # "Explore" (bare leaf) must not appear — it was the old flat key.
        # After Phase 4, only the full path key is emitted.
        assert "Explore" not in result.by_agent, (
            "Bare leaf key 'Explore' must NOT appear in by_agent after Phase 4; "
            "only the full path key 'general-purpose→project-planner→Explore' "
            "is valid"
        )
        # "project-planner" (bare depth-2 name) must also not appear as a
        # flat key — the path-keyed form is the only valid shape.
        assert "project-planner" not in result.by_agent, (
            "Bare depth-2 key 'project-planner' must NOT appear in by_agent; "
            f"only the full path key "
            f"'general-purpose{AGENT_PATH_SEPARATOR}project-planner' "
            "is valid"
        )

    def test_session_agents_uses_deepest_leaf_only(self, nested_session_dir: Path):
        """Per-session agents list contains only the deepest leaf path-key.

        A depth-3 session emits ``["general-purpose→project-planner→Explore"]``
        and must NOT contain ancestor path-keys such as ``"general-purpose"``
        or ``"general-purpose→project-planner"``.
        """
        sessions = parse_sessions(nested_session_dir)
        result = aggregate(sessions)
        assert len(result.sessions) == 1
        agents = result.sessions[0]["agents"]
        full_key = (
            f"general-purpose{AGENT_PATH_SEPARATOR}"
            f"project-planner{AGENT_PATH_SEPARATOR}Explore"
        )
        assert (
            full_key in agents
        ), f"Deepest-leaf key '{full_key}' must be in agents. Got: {agents}"
        # Ancestors must be absent
        assert (
            "general-purpose" not in agents
        ), "Root key 'general-purpose' must NOT appear as it is an ancestor"
        assert (
            f"general-purpose{AGENT_PATH_SEPARATOR}project-planner"
        ) not in agents, "Intermediate key must NOT appear as it is an ancestor"

    def test_session_agents_apportionment_invariant(self, nested_session_dir: Path):
        """Depth-3 session emits length-1 agents list so JS apportionment is exact.

        The dashboard JS computes ``share = total_tokens / s.agents.length``.
        If ancestors are included, ``length > 1`` and each agent gets a
        fractional share instead of the full session total.
        """
        sessions = parse_sessions(nested_session_dir)
        result = aggregate(sessions)
        assert len(result.sessions) == 1
        assert len(result.sessions[0]["agents"]) == 1, (
            "Depth-3 single-chain session must produce exactly 1 leaf key "
            f"so JS apportionment is T/1=T. Got: {result.sessions[0]['agents']}"
        )

    def test_sibling_chains_with_shared_leaf_both_survive(
        self, sibling_shared_leaf_session_dir: Path
    ):
        """Both sibling Explore chains appear as independent deepest leaves.

        The fixture has:
        - ``general-purpose → Explore`` (150 input tokens)
        - ``general-purpose → project-planner → Explore`` (350 input tokens)

        Neither key is a prefix of the other, so prefix-membership keeps both.
        Both must appear in ``agents_in_session`` and ``by_agent``.
        """
        sessions = parse_sessions(sibling_shared_leaf_session_dir)
        result = aggregate(sessions)

        gp_explore = f"general-purpose{AGENT_PATH_SEPARATOR}Explore"
        gp_pp_explore = (
            f"general-purpose{AGENT_PATH_SEPARATOR}"
            f"project-planner{AGENT_PATH_SEPARATOR}Explore"
        )

        # Both must be in by_agent with non-zero tokens
        assert (
            gp_explore in result.by_agent
        ), f"'{gp_explore}' must be in by_agent. Keys: {sorted(result.by_agent)}"
        assert (
            gp_pp_explore in result.by_agent
        ), f"'{gp_pp_explore}' must be in by_agent"
        # 150 input + 75 output = 225 total for explore-a
        assert result.by_agent[gp_explore]["total_tokens"] == 225
        # 350 input + 175 output = 525 total for explore-b
        assert result.by_agent[gp_pp_explore]["total_tokens"] == 525

        # Both must survive as deepest leaves in the session agents list
        assert len(result.sessions) == 1
        agents = result.sessions[0]["agents"]
        assert gp_explore in agents, f"'{gp_explore}' must be a deepest leaf"
        assert gp_pp_explore in agents, f"'{gp_pp_explore}' must be a deepest leaf"

    def test_session_agents_includes_root_when_no_subagents(self):
        """A depth-1 session with no subagents emits the root key.

        The deepest-leaf rule should degenerate gracefully: a session with
        only the root agent produces a single-element agents list.
        """
        sessions = [
            _session(
                [_msg(agent="general-purpose", input_t=100, output_t=50)],
            )
        ]
        result = aggregate(sessions)
        assert len(result.sessions) == 1
        assert result.sessions[0]["agents"] == [
            "general-purpose"
        ], "Depth-1 session must emit the root key as the sole agent"

    def test_primary_model_per_path_key(self, nested_session_dir: Path):
        """Each by_agent entry carries a primary_model field."""
        sessions = parse_sessions(nested_session_dir)
        result = aggregate(sessions)
        for key, bucket in result.by_agent.items():
            assert (
                "primary_model" in bucket
            ), f"by_agent['{key}'] is missing 'primary_model'"

    def test_session_count_per_path_key(self, nested_session_dir: Path):
        """Each by_agent entry carries a session_count field."""
        sessions = parse_sessions(nested_session_dir)
        result = aggregate(sessions)
        for key, bucket in result.by_agent.items():
            assert (
                "session_count" in bucket
            ), f"by_agent['{key}'] is missing 'session_count'"


def _make_path_msg(
    path: tuple[str, ...],
    model: str = "claude-opus-4-6",
    skill: str | None = None,
    input_t: int = 100,
    output_t: int = 50,
    ts=None,
) -> MessageRecord:
    """Build a MessageRecord with a full agent_path tuple.

    Unlike the ``_msg`` helper (which sets agent_type and derives a 1-tuple
    path), this helper accepts an arbitrary depth tuple so Phase 4 tests can
    construct depth-2 and depth-3 messages directly without a real fixture.

    Args:
        path: Full agent_path tuple, e.g. ``("general-purpose", "code-writer")``.
        model: Full model ID string.
        skill: Optional skill name.
        input_t: Input token count.
        output_t: Output token count.
        ts: Optional timestamp; defaults to a fixed UTC datetime.

    Returns:
        A ``MessageRecord`` with the given path and token counts.
    """
    return MessageRecord(
        timestamp=ts or datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
        model=model,
        agent_type=path[-1],
        agent_path=path,
        skill=skill,
        input_tokens=input_t,
        output_tokens=output_t,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )
