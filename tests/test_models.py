# tests/test_models.py
from datetime import datetime, timezone

from claude_usage.models import (
    MessageRecord,
    SessionRecord,
    SkillPassedEvent,
    SkillInvokedEvent,
)


class TestMessageRecord:
    def test_total_tokens(self):
        msg = MessageRecord(
            timestamp=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            model="claude-opus-4-6",
            agent_type="general-purpose",
            skill=None,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=200,
            cache_creation_tokens=300,
        )
        assert msg.total_tokens == 650

    def test_total_tokens_all_zero(self):
        msg = MessageRecord(
            timestamp=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            model="claude-sonnet-4-6",
            agent_type="code-writer",
            skill="superpowers:brainstorming",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        assert msg.total_tokens == 0

    def test_model_short_name_opus(self):
        msg = MessageRecord(
            timestamp=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            model="claude-opus-4-6",
            agent_type="general-purpose",
            skill=None,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        assert msg.model_short == "opus"

    def test_model_short_name_sonnet(self):
        msg = MessageRecord(
            timestamp=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            model="claude-sonnet-4-6",
            agent_type="code-writer",
            skill=None,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        assert msg.model_short == "sonnet"

    def test_model_short_name_haiku(self):
        msg = MessageRecord(
            timestamp=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            model="claude-haiku-4-5-20251001",
            agent_type="ops",
            skill=None,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        assert msg.model_short == "haiku"

    def test_model_short_name_unknown(self):
        msg = MessageRecord(
            timestamp=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            model="claude-future-model-9",
            agent_type="general-purpose",
            skill=None,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        assert msg.model_short == "claude-future-model-9"


class TestSessionRecord:
    def _make_msg(
        self,
        model="claude-opus-4-6",
        agent="general-purpose",
        input_t=100,
        output_t=50,
        cache_read=0,
        cache_create=0,
        skill=None,
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

    def test_total_tokens_sums_messages(self):
        session = SessionRecord(
            session_id="abc-123",
            project="my-project",
            start_time=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            root_agent="general-purpose",
            messages=[
                self._make_msg(input_t=100, output_t=50),
                self._make_msg(input_t=200, output_t=100),
            ],
            subagent_types=["code-writer"],
        )
        assert session.total_tokens == 450

    def test_total_tokens_empty_messages(self):
        session = SessionRecord(
            session_id="abc-123",
            project="my-project",
            start_time=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            root_agent="general-purpose",
            messages=[],
            subagent_types=[],
        )
        assert session.total_tokens == 0

    def test_duration_from_timestamps(self):
        session = SessionRecord(
            session_id="abc-123",
            project="my-project",
            start_time=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            root_agent="general-purpose",
            messages=[
                self._make_msg(ts=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)),
                self._make_msg(ts=datetime(2026, 4, 9, 12, 30, 0, tzinfo=timezone.utc)),
                self._make_msg(ts=datetime(2026, 4, 9, 13, 5, 0, tzinfo=timezone.utc)),
            ],
            subagent_types=[],
        )
        assert session.duration_minutes == 65

    def test_duration_single_message(self):
        session = SessionRecord(
            session_id="abc-123",
            project="my-project",
            start_time=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            root_agent="general-purpose",
            messages=[
                self._make_msg(ts=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)),
            ],
            subagent_types=[],
        )
        assert session.duration_minutes == 0

    def test_duration_no_messages(self):
        session = SessionRecord(
            session_id="abc-123",
            project="my-project",
            start_time=datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
            root_agent="general-purpose",
            messages=[],
            subagent_types=[],
        )
        assert session.duration_minutes == 0


class TestAgentPath:
    """Tests for the agent_path and agent_type parallel stored fields."""

    _TS = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)

    def _make(self, agent_path, model="claude-opus-4-7", **kwargs):
        # Mirror the parser invariant: agent_type defaults to leaf of path.
        kwargs.setdefault("agent_type", agent_path[-1])
        defaults = dict(
            timestamp=self._TS,
            model=model,
            skill=None,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        defaults.update(kwargs)
        return MessageRecord(agent_path=agent_path, **defaults)

    def test_agent_type_equals_leaf_when_invariant_held(self):
        """Parser invariant: agent_type matches agent_path leaf at construction."""
        record = self._make(agent_path=("router", "planner", "Explore"))
        assert record.agent_type == "Explore"

    def test_agent_path_is_tuple_not_list(self):
        record = self._make(agent_path=("router", "planner", "Explore"))
        assert isinstance(record.agent_path, tuple)

    def test_record_is_hashable(self):
        record = self._make(agent_path=("general-purpose",))
        assert hash(record) is not None  # must not raise

    def test_depth_one_path(self):
        record = self._make(agent_path=("main",))
        assert record.agent_type == "main"

    def test_existing_properties_preserved(self):
        """Pinned exact-value assertions for total_tokens and model_short."""
        # total_tokens: 100 + 200 + 50 + 300 = 650
        record = self._make(
            agent_path=("general-purpose",),
            model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=200,
            cache_read_tokens=50,
            cache_creation_tokens=300,
        )
        assert record.total_tokens == 650

    def test_model_short_opus(self):
        record = self._make(agent_path=("general-purpose",), model="claude-opus-4-7")
        assert record.model_short == "opus"

    def test_model_short_sonnet(self):
        record = self._make(agent_path=("general-purpose",), model="claude-sonnet-4-5")
        assert record.model_short == "sonnet"

    def test_model_short_haiku(self):
        record = self._make(agent_path=("general-purpose",), model="claude-haiku-3-5")
        assert record.model_short == "haiku"

    def test_model_short_unknown_passthrough(self):
        record = self._make(
            agent_path=("general-purpose",), model="claude-future-model-9"
        )
        assert record.model_short == "claude-future-model-9"

    def test_parallel_field_independence(self):
        """agent_type and agent_path are stored independently — neither derived.

        A record with agent_type="x" and no agent_path has agent_path==()
        and agent_type=="x". The invariant agent_type==agent_path[-1] is
        the parser's responsibility, not enforced by the dataclass.
        """
        record = MessageRecord(
            timestamp=self._TS,
            model="claude-opus-4-7",
            agent_type="x",
            skill=None,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        assert record.agent_type == "x"
        assert record.agent_path == ()


class TestSkillPassedEvent:
    def test_creation(self):
        evt = SkillPassedEvent(
            skill="python",
            target_agent="code-writer",
            timestamp=datetime(2026, 4, 9, tzinfo=timezone.utc),
            session_id="abc-123",
        )
        assert evt.skill == "python"
        assert evt.target_agent == "code-writer"
        assert evt.session_id == "abc-123"

    def test_frozen(self):
        import pytest

        evt = SkillPassedEvent(
            skill="python",
            target_agent="code-writer",
            timestamp=datetime(2026, 4, 9, tzinfo=timezone.utc),
            session_id="abc-123",
        )
        with pytest.raises(AttributeError):
            evt.skill = "other"


class TestSkillInvokedEvent:
    def test_creation(self):
        evt = SkillInvokedEvent(
            skill="python",
            timestamp=datetime(2026, 4, 9, tzinfo=timezone.utc),
            session_id="abc-123",
        )
        assert evt.skill == "python"
        assert evt.session_id == "abc-123"

    def test_frozen(self):
        import pytest

        evt = SkillInvokedEvent(
            skill="python",
            timestamp=datetime(2026, 4, 9, tzinfo=timezone.utc),
            session_id="abc-123",
        )
        with pytest.raises(AttributeError):
            evt.skill = "other"
