"""Tests for skill adoption correlation in aggregator."""

from __future__ import annotations

from datetime import datetime, timezone

from claude_prospector.aggregator import compute_skill_adoption
from claude_prospector.models import SkillInvokedEvent, SkillPassedEvent


class TestComputeSkillAdoption:
    def test_empty_inputs(self):
        result = compute_skill_adoption([], [])
        assert result == {}

    def test_passed_but_never_invoked(self):
        passed = [
            SkillPassedEvent(
                "python", "code-writer", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
            SkillPassedEvent(
                "python", "debugger", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
        ]
        result = compute_skill_adoption(passed, [])
        assert result["python"]["times_passed"] == 2
        assert result["python"]["times_invoked"] == 0
        assert result["python"]["adoption_rate"] == 0.0
        assert result["python"]["by_target_agent"]["code-writer"]["passed"] == 1
        assert result["python"]["by_target_agent"]["code-writer"]["invoked"] == 0

    def test_invoked_without_pass(self):
        invoked = [
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
        ]
        result = compute_skill_adoption([], invoked)
        assert result == {}

    def test_full_adoption(self):
        passed = [
            SkillPassedEvent(
                "python",
                "code-writer",
                datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc),
                "s1",
            ),
        ]
        invoked = [
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, 12, 1, tzinfo=timezone.utc), "s1"
            ),
        ]
        result = compute_skill_adoption(passed, invoked)
        assert result["python"]["times_passed"] == 1
        assert result["python"]["times_invoked"] == 1
        assert result["python"]["adoption_rate"] == 1.0

    def test_partial_adoption(self):
        passed = [
            SkillPassedEvent(
                "python", "code-writer", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
            SkillPassedEvent(
                "python", "code-writer", datetime(2026, 4, 9, tzinfo=timezone.utc), "s2"
            ),
            SkillPassedEvent(
                "python", "debugger", datetime(2026, 4, 9, tzinfo=timezone.utc), "s3"
            ),
        ]
        invoked = [
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, tzinfo=timezone.utc), "s2"
            ),
        ]
        result = compute_skill_adoption(passed, invoked)
        assert result["python"]["times_passed"] == 3
        assert result["python"]["times_invoked"] == 2
        assert abs(result["python"]["adoption_rate"] - 0.667) < 0.01

    def test_multiple_skills(self):
        passed = [
            SkillPassedEvent(
                "python", "code-writer", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
            SkillPassedEvent(
                "powershell",
                "debugger",
                datetime(2026, 4, 9, tzinfo=timezone.utc),
                "s1",
            ),
        ]
        invoked = [
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
        ]
        result = compute_skill_adoption(passed, invoked)
        assert result["python"]["adoption_rate"] == 1.0
        assert result["powershell"]["adoption_rate"] == 0.0

    def test_per_agent_breakdown(self):
        passed = [
            SkillPassedEvent(
                "python", "code-writer", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
            SkillPassedEvent(
                "python", "code-writer", datetime(2026, 4, 9, tzinfo=timezone.utc), "s2"
            ),
            SkillPassedEvent(
                "python", "debugger", datetime(2026, 4, 9, tzinfo=timezone.utc), "s3"
            ),
        ]
        invoked = [
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, tzinfo=timezone.utc), "s1"
            ),
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, tzinfo=timezone.utc), "s3"
            ),
        ]
        result = compute_skill_adoption(passed, invoked)
        agents = result["python"]["by_target_agent"]
        assert agents["code-writer"]["passed"] == 2
        assert agents["code-writer"]["invoked"] == 1
        assert agents["debugger"]["passed"] == 1
        assert agents["debugger"]["invoked"] == 1

    def test_time_filtering(self):
        cutoff = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        passed = [
            SkillPassedEvent(
                "python",
                "code-writer",
                datetime(2026, 4, 9, 11, 0, tzinfo=timezone.utc),
                "s1",
            ),
            SkillPassedEvent(
                "python",
                "code-writer",
                datetime(2026, 4, 9, 13, 0, tzinfo=timezone.utc),
                "s2",
            ),
        ]
        invoked = [
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, 11, 1, tzinfo=timezone.utc), "s1"
            ),
            SkillInvokedEvent(
                "python", datetime(2026, 4, 9, 13, 1, tzinfo=timezone.utc), "s2"
            ),
        ]
        result = compute_skill_adoption(passed, invoked, from_date=cutoff)
        assert result["python"]["times_passed"] == 1
        assert result["python"]["times_invoked"] == 1
