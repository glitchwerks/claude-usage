"""Data classes for parsed Claude Code session data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """A single assistant message with token usage, attributed to an agent."""

    timestamp: datetime
    model: str
    agent_path: tuple[str, ...]
    skill: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int

    @property
    def agent_type(self) -> str:
        """Leaf agent (for backward compat). Returns last segment of agent_path."""
        return self.agent_path[-1]

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
