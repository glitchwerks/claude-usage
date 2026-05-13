"""End-to-end test: parse sample data -> aggregate -> render HTML."""

import json
from pathlib import Path

from claude_usage.aggregator import AggregateResult, aggregate
from claude_usage.parser import parse_sessions
from claude_usage.renderer import render


class TestEndToEnd:
    def test_full_pipeline(self, sample_session_dir: Path, tmp_path: Path):
        """Parse sample fixtures, aggregate, render to HTML file."""
        sessions = parse_sessions(sample_session_dir)
        assert len(sessions) == 1

        result = aggregate(sessions)
        assert result.total_tokens > 0
        assert result.total_sessions == 1
        assert "opus" in result.by_model
        assert "general-purpose" in result.by_agent

        output_path = tmp_path / "dashboard.html"
        rendered = render(result, output_path=output_path, open_browser=False)
        assert rendered.exists()

        html = rendered.read_text(encoding="utf-8")
        assert "Chart" in html or "chart" in html
        assert "claude" in html.lower()

    def test_full_pipeline_with_limits(self, sample_session_dir: Path, tmp_path: Path):
        sessions = parse_sessions(sample_session_dir)
        result = aggregate(sessions)

        limits = {"limit_5h": 600000, "limit_7d": 4000000, "limit_sonnet_7d": 2000000}
        output_path = tmp_path / "dashboard-limits.html"
        rendered = render(
            result, output_path=output_path, open_browser=False, limits=limits
        )
        assert rendered.exists()

        html = rendered.read_text(encoding="utf-8")
        assert "600000" in html or "limit_5h" in html

    def test_empty_data(self, tmp_path: Path):
        sessions = parse_sessions(tmp_path)
        result = aggregate(sessions)
        assert result.total_tokens == 0

        output_path = tmp_path / "empty.html"
        rendered = render(result, output_path=output_path, open_browser=False)
        assert rendered.exists()


class TestSkillAdoptionE2E:
    def test_adoption_data_in_rendered_html(
        self, sample_session_dir: Path, tmp_path: Path
    ):
        """Verify skill adoption data appears in the rendered dashboard."""
        from claude_usage.aggregator import compute_skill_adoption
        from claude_usage.skill_tracking import parse_skill_tracking

        tracking_file = sample_session_dir / "skill-tracking.jsonl"
        lines = [
            json.dumps(
                {
                    "event": "skill_passed",
                    "skill": "python",
                    "target_agent": "code-writer",
                    "timestamp": "2026-04-09T21:00:00Z",
                    "session_id": "test-1",
                }
            ),
            json.dumps(
                {
                    "event": "skill_invoked",
                    "skill": "python",
                    "timestamp": "2026-04-09T21:01:00Z",
                    "session_id": "test-1",
                }
            ),
        ]
        tracking_file.write_text("\n".join(lines) + "\n")

        sessions = parse_sessions(sample_session_dir)
        result = aggregate(sessions)

        passed, invoked = parse_skill_tracking(sample_session_dir)
        result.by_skill_adoption = compute_skill_adoption(passed, invoked)

        output = tmp_path / "test-dashboard.html"
        render(result, output_path=output, open_browser=False)

        html = output.read_text(encoding="utf-8")
        assert "Skill Adoption" in html
        assert "python" in html


class TestSubagentModelAttribution:
    """Regression test for issue #8: subagents misattributed to parent model.

    A subagent (e.g. 'debugger') running on Sonnet inside an Opus parent
    session must be labelled Sonnet in the dashboard, not Opus.  The bug was
    that the JavaScript reAggregate() function derived primary_model from
    session-level token splits divided equally across all agents — which
    caused the Sonnet subagent to accumulate more Opus tokens than Sonnet
    tokens and appear as Opus.  The fix uses DATA.by_agent[agent].primary_model
    (computed server-side from actual per-message model fields) as the
    authoritative source and embeds it in the rendered HTML.
    """

    def _build_session_dir(self, tmp_path: Path) -> Path:
        """Create a fixture: general-purpose (Opus) session with a debugger (Sonnet) subagent."""
        project_dir = tmp_path / "projects" / "C--Users-chris--test"
        project_dir.mkdir(parents=True)
        session_id = "sess-opus-parent-sonnet-sub"

        # Parent session: general-purpose runs on Opus
        parent_lines = [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            {
                "parentUuid": None,
                "type": "user",
                "message": {"role": "user", "content": "Debug the auth module"},
                "uuid": "p-msg-1",
                "timestamp": "2026-04-10T10:00:00.000Z",
                "sessionId": session_id,
            },
            # Opus parent message — large token count to dominate session totals
            {
                "parentUuid": "p-msg-1",
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Routing to debugger..."}],
                    "usage": {
                        "input_tokens": 5000,
                        "output_tokens": 2000,
                        "cache_read_input_tokens": 10000,
                        "cache_creation_input_tokens": 8000,
                    },
                },
                "uuid": "p-msg-2",
                "timestamp": "2026-04-10T10:00:05.000Z",
                "sessionId": session_id,
            },
        ]

        (project_dir / f"{session_id}.jsonl").write_text(
            "\n".join(json.dumps(rec) for rec in parent_lines), encoding="utf-8"
        )

        # Subagent directory
        subagent_dir = project_dir / session_id / "subagents"
        subagent_dir.mkdir(parents=True)

        # debugger subagent metadata
        (subagent_dir / "agent-debugger1.meta.json").write_text(
            json.dumps(
                {"agentType": "debugger", "description": "Debug the auth module"}
            ),
            encoding="utf-8",
        )

        # debugger subagent JSONL: runs on Sonnet (small token count relative to Opus parent)
        sub_lines = [
            {
                "parentUuid": None,
                "type": "user",
                "message": {"role": "user", "content": "Debug the auth module"},
                "uuid": "s-msg-1",
                "timestamp": "2026-04-10T10:00:10.000Z",
                "sessionId": session_id,
            },
            {
                "parentUuid": "s-msg-1",
                "type": "assistant",
                "message": {
                    "model": "claude-sonnet-4-6",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Investigating..."}],
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 100,
                        "cache_read_input_tokens": 50,
                        "cache_creation_input_tokens": 0,
                    },
                },
                "uuid": "s-msg-2",
                "timestamp": "2026-04-10T10:00:30.000Z",
                "sessionId": session_id,
            },
        ]

        (subagent_dir / "agent-debugger1.jsonl").write_text(
            "\n".join(json.dumps(rec) for rec in sub_lines), encoding="utf-8"
        )

        return tmp_path

    def test_subagent_primary_model_uses_actual_message_model(self, tmp_path: Path):
        """Python aggregator must attribute debugger to sonnet, not opus.

        The Opus parent has ~25000 tokens; debugger has only ~350.  The old JS
        heuristic would split session totals equally across agents (general-purpose
        and debugger each get half of 25350 tokens, of which most are opus) and
        incorrectly label debugger as opus.  The Python aggregator reads the
        model field per message and must produce primary_model='sonnet' for
        debugger regardless of token volumes.
        """
        session_dir = self._build_session_dir(tmp_path)
        sessions = parse_sessions(session_dir)
        result = aggregate(sessions)

        assert (
            "general-purpose→debugger" in result.by_agent
        ), "debugger agent should be present as 'general-purpose→debugger'"
        assert (
            result.by_agent["general-purpose→debugger"]["primary_model"] == "sonnet"
        ), (
            "debugger ran on claude-sonnet-4-6; primary_model must be 'sonnet', "
            f"got {result.by_agent['general-purpose→debugger']['primary_model']!r}"
        )
        assert (
            result.by_agent["general-purpose"]["primary_model"] == "opus"
        ), "general-purpose ran on claude-opus-4-6; primary_model must be 'opus'"

    def test_rendered_html_embeds_correct_primary_model_for_subagent(
        self, tmp_path: Path
    ):
        """Rendered HTML must embed primary_model='sonnet' for debugger in DATA.by_agent.

        The dashboard JavaScript reads DATA.by_agent[agent].primary_model to
        colour agent bars.  This test verifies the server-computed value is
        correctly embedded so the JS fix has correct data to work with.
        """
        session_dir = self._build_session_dir(tmp_path)
        sessions = parse_sessions(session_dir)
        result = aggregate(sessions)

        output_path = tmp_path / "test-dashboard.html"
        render(result, output_path=output_path, open_browser=False)
        html = output_path.read_text(encoding="utf-8")

        # Extract the DATA JSON blob embedded in the HTML
        marker = "const DATA = "
        start = html.index(marker) + len(marker)
        # Find the matching closing brace by scanning for the semicolon after the JSON object
        end = html.index(";\n", start)
        data = json.loads(html[start:end])

        assert (
            "general-purpose→debugger" in data["by_agent"]
        ), "by_agent must contain 'general-purpose→debugger'"
        actual = data["by_agent"]["general-purpose→debugger"]["primary_model"]
        assert actual == "sonnet", (
            f"DATA.by_agent['general-purpose→debugger'].primary_model must be "
            f"'sonnet' in rendered HTML, got {actual!r}. "
            "The JS fix uses this value as authoritative; if it is wrong here "
            "the dashboard will still misattribute."
        )


class TestChartLabelSkip:
    """Regression test for issue #7: category-axis labels skipped on Tokens by Agent
    and Skill Invocations charts.

    Chart.js defaults autoSkip=true on tick axes, which causes every other label to
    vanish when the chart height is small relative to the number of categories.  The
    fix sets ticks: { autoSkip: false } on the y-axis of every horizontal bar chart so
    that all labels are always rendered.  This test verifies the rendered HTML contains
    that config by inspecting the template source.
    """

    def _build_large_result(self, n: int = 20) -> AggregateResult:
        """Build an AggregateResult with *n* agents and *n* skills — enough to
        trigger label-skipping at the default 260 px chart height."""
        result = AggregateResult()
        result.total_tokens = n * 1000
        result.total_sessions = n

        for i in range(n):
            agent = f"agent-{i:02d}"
            result.by_agent[agent] = {
                "total_tokens": (n - i) * 1000,
                "primary_model": "sonnet",
                "session_count": 1,
            }
            skill = f"skill-{i:02d}"
            result.by_skill[skill] = {"invocation_count": n - i}
            project = f"project-{i:02d}"
            result.by_project[project] = {
                "total_tokens": (n - i) * 500,
                "primary_model": "sonnet",
            }

        return result

    def test_agent_bar_chart_has_auto_skip_false(self, tmp_path: Path) -> None:
        """Rendered dashboard must contain autoSkip: false on the agentBar y-axis.

        With 20 agents and a fixed-height container, Chart.js would skip every
        other label unless autoSkip is explicitly disabled.
        """
        result = self._build_large_result(20)
        output = tmp_path / "dashboard.html"
        render(result, output_path=output, open_browser=False)

        html = output.read_text(encoding="utf-8")

        # The template contains the literal JS source for both charts.
        # We verify the autoSkip: false config is present in the output.
        assert "autoSkip: false" in html, (
            "Rendered HTML must contain 'autoSkip: false' — Chart.js will skip "
            "category-axis labels at the default chart height without it."
        )

    def test_skill_bar_chart_has_auto_skip_false(self, tmp_path: Path) -> None:
        """renderSkillBar must also have autoSkip: false on its y-axis."""
        result = self._build_large_result(20)
        output = tmp_path / "dashboard.html"
        render(result, output_path=output, open_browser=False)

        html = output.read_text(encoding="utf-8")

        # Count occurrences — there should be one per horizontal bar chart
        # (agentBar, skillBar, projectBar, skillAdoption = 4 charts).
        count = html.count("autoSkip: false")
        assert count >= 2, (
            f"Expected at least 2 occurrences of 'autoSkip: false' (agentBar + skillBar), "
            f"found {count}. Both charts need the config to fix label skipping."
        )

    def test_dynamic_height_set_for_many_categories(self, tmp_path: Path) -> None:
        """Rendered HTML must set container height dynamically based on item count.

        Without dynamic height, disabling autoSkip alone causes labels to overlap.
        The template sets canvas.parentElement.style.height proportionally.
        """
        result = self._build_large_result(20)
        output = tmp_path / "dashboard.html"
        render(result, output_path=output, open_browser=False)

        html = output.read_text(encoding="utf-8")

        assert "parentElement.style.height" in html, (
            "Rendered HTML must contain parentElement.style.height — "
            "dynamic container sizing is required to prevent label overlap "
            "after disabling autoSkip."
        )
