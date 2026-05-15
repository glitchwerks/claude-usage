"""Data classes for parsed Claude Code session data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """A single assistant message with token usage, attributed to an agent.

    Attributes:
        timestamp: When the assistant message was produced.
        model: Full model ID string (e.g. ``"claude-opus-4-7"``).
        agent_type: Leaf agent name (e.g. ``"general-purpose"``). Stored
            independently from ``agent_path``; maintaining the invariant
            ``agent_type == agent_path[-1]`` (when ``agent_path`` is
            non-empty) is the parser's responsibility at construction time.
        agent_path: Full ancestry tuple from root to leaf agent. Defaults
            to the empty tuple for records that pre-date nested attribution.
            Neither field is derived from the other.
        skill: Skill name invoked in this message, or ``None``.
        input_tokens: Prompt token count.
        output_tokens: Completion token count.
        cache_read_tokens: Tokens served from the prompt cache.
        cache_creation_tokens: Tokens written to the prompt cache.
    """

    timestamp: datetime
    model: str
    agent_type: str
    skill: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    agent_path: tuple[str, ...] = ()

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )

    @property
    def model_short(self) -> str:
        """Extract short model name: 'opus', 'sonnet', 'haiku', or full name."""
        for name in ("opus", "sonnet", "haiku"):
            if name in self.model:
                return name
        return self.model


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """A parsed session with all its messages (including subagent messages)."""

    session_id: str
    project: str
    start_time: datetime
    root_agent: str
    messages: list[MessageRecord]
    subagent_types: list[str]

    @property
    def total_tokens(self) -> int:
        return sum(m.total_tokens for m in self.messages)

    @property
    def duration_minutes(self) -> int:
        """Duration from first to last message timestamp, in minutes."""
        if len(self.messages) < 2:
            return 0
        timestamps = [m.timestamp for m in self.messages]
        delta = max(timestamps) - min(timestamps)
        return int(delta.total_seconds() / 60)


@dataclass(frozen=True, slots=True)
class SkillPassedEvent:
    """A skill reference found in an Agent dispatch prompt."""

    skill: str
    target_agent: str
    timestamp: datetime
    session_id: str


@dataclass(frozen=True, slots=True)
class SkillInvokedEvent:
    """An actual Skill tool invocation."""

    skill: str
    timestamp: datetime
    session_id: str
