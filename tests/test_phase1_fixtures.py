"""Phase 1 fixture validation tests.

These tests verify that the Phase 1 fixtures produce the correct directory
structure and file contents. They do not invoke the parser or aggregator —
those are Phase 2+ concerns.

Each test is a structural smoke test: it confirms the fixture loads without
raising and that the key files exist with the expected layout.
"""

from __future__ import annotations

import json
from pathlib import Path


class TestNestedSessionDirFixture:
    """Validate the nested_session_dir (depth-3) fixture structure."""

    def test_root_jsonl_exists(self, nested_session_dir: Path) -> None:
        """Root session JSONL exists at projects/*/sess-nested.jsonl."""
        project_dir = nested_session_dir / "projects" / "C--Users-chris--myproject"
        assert (project_dir / "sess-nested.jsonl").is_file()

    def test_depth2_meta_and_jsonl_exist(self, nested_session_dir: Path) -> None:
        """Depth-2 subagent files exist under sess-nested/subagents/."""
        project_dir = nested_session_dir / "projects" / "C--Users-chris--myproject"
        subagents = project_dir / "sess-nested" / "subagents"
        assert (subagents / "agent-pp.meta.json").is_file()
        assert (subagents / "agent-pp.jsonl").is_file()

    def test_depth2_agent_type_is_project_planner(
        self, nested_session_dir: Path
    ) -> None:
        """Depth-2 meta.json has agentType == 'project-planner'."""
        project_dir = nested_session_dir / "projects" / "C--Users-chris--myproject"
        meta = json.loads(
            (
                project_dir / "sess-nested" / "subagents" / "agent-pp.meta.json"
            ).read_text(encoding="utf-8")
        )
        assert meta["agentType"] == "project-planner"

    def test_depth3_meta_and_jsonl_exist(self, nested_session_dir: Path) -> None:
        """Depth-3 subagent files exist under sess-nested/subagents/agent-pp/subagents/."""
        project_dir = nested_session_dir / "projects" / "C--Users-chris--myproject"
        depth3_subagents = (
            project_dir / "sess-nested" / "subagents" / "agent-pp" / "subagents"
        )
        assert (depth3_subagents / "agent-exp.meta.json").is_file()
        assert (depth3_subagents / "agent-exp.jsonl").is_file()

    def test_depth3_agent_type_is_explore_pascalcase(
        self, nested_session_dir: Path
    ) -> None:
        """Depth-3 meta.json has agentType == 'Explore' (PascalCase)."""
        project_dir = nested_session_dir / "projects" / "C--Users-chris--myproject"
        meta = json.loads(
            (
                project_dir
                / "sess-nested"
                / "subagents"
                / "agent-pp"
                / "subagents"
                / "agent-exp.meta.json"
            ).read_text(encoding="utf-8")
        )
        assert meta["agentType"] == "Explore"

    def test_distinct_token_counts_per_depth(self, nested_session_dir: Path) -> None:
        """Each depth level has distinct, recoverable input token counts.

        Plan specifies 100/200/400 input tokens at depths 1/2/3.
        """
        project_dir = nested_session_dir / "projects" / "C--Users-chris--myproject"

        def first_assistant_input_tokens(jsonl_path: Path) -> int:
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("type") == "assistant":
                    return entry["message"]["usage"]["input_tokens"]
            raise AssertionError(f"No assistant message in {jsonl_path}")

        root_tokens = first_assistant_input_tokens(project_dir / "sess-nested.jsonl")
        depth2_tokens = first_assistant_input_tokens(
            project_dir / "sess-nested" / "subagents" / "agent-pp.jsonl"
        )
        depth3_tokens = first_assistant_input_tokens(
            project_dir
            / "sess-nested"
            / "subagents"
            / "agent-pp"
            / "subagents"
            / "agent-exp.jsonl"
        )
        assert root_tokens == 100
        assert depth2_tokens == 200
        assert depth3_tokens == 400


class TestPathologicalDepthFixture:
    """Validate the pathological_depth_session_dir (12-deep) fixture structure."""

    def test_chain_is_12_levels_deep(
        self, pathological_depth_session_dir: Path
    ) -> None:
        """The chain has exactly 12 levels of subagent nesting."""
        project_dir = (
            pathological_depth_session_dir / "projects" / "C--Users-chris--myproject"
        )
        # Root JSONL
        assert (project_dir / "sess-pathological.jsonl").is_file()

        # Walk the chain: each level has subagents/<agent-id>/ with
        # the next level's meta.json and subagents/ inside.
        current = project_dir / "sess-pathological"
        for depth in range(1, 13):
            subagents_dir = current / "subagents"
            assert subagents_dir.is_dir(), f"Missing subagents/ at depth {depth}"
            meta_files = list(subagents_dir.glob("*.meta.json"))
            assert len(meta_files) == 1, (
                f"Expected 1 meta.json at depth {depth}, got {len(meta_files)}"
            )
            agent_id = meta_files[0].stem.replace(".meta", "")
            current = subagents_dir / agent_id


class TestSeparatorInNameFixture:
    """Validate separator_in_name_session_dir fixture."""

    def test_subagent_agent_type_contains_separator(
        self, separator_in_name_session_dir: Path
    ) -> None:
        """Depth-2 subagent has agentType containing the path separator arrow."""
        project_dir = (
            separator_in_name_session_dir / "projects" / "C--Users-chris--myproject"
        )
        subagents = project_dir / "sess-separator" / "subagents"
        meta_files = list(subagents.glob("*.meta.json"))
        assert len(meta_files) >= 1
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
        assert "→" in meta["agentType"]  # U+2192 RIGHT ARROW


class TestSymlinkCycleFixture:
    """Validate symlink_cycle_session_dir fixture.

    On Windows without developer mode the fixture may skip or use monkeypatch.
    """

    def test_fixture_loads_without_error(
        self, symlink_cycle_session_dir: object
    ) -> None:
        """The fixture itself loads without raising any exception."""
        # symlink_cycle_session_dir is either a Path (real symlink) or a
        # mock context dict — either way it must not raise on access.
        assert symlink_cycle_session_dir is not None


class TestSiblingSharedLeafFixture:
    """Validate sibling_shared_leaf_session_dir fixture."""

    def test_root_jsonl_exists(self, sibling_shared_leaf_session_dir: Path) -> None:
        """Root session JSONL exists."""
        project_dir = (
            sibling_shared_leaf_session_dir / "projects" / "C--Users-chris--myproject"
        )
        assert (project_dir / "sess-sibling.jsonl").is_file()

    def test_explore_a_at_root_subagents(
        self, sibling_shared_leaf_session_dir: Path
    ) -> None:
        """agent-explore-a (Explore, sibling of project-planner) exists."""
        project_dir = (
            sibling_shared_leaf_session_dir / "projects" / "C--Users-chris--myproject"
        )
        subagents = project_dir / "sess-sibling" / "subagents"
        meta = json.loads(
            (subagents / "agent-explore-a.meta.json").read_text(encoding="utf-8")
        )
        assert meta["agentType"] == "Explore"

    def test_project_planner_at_root_subagents(
        self, sibling_shared_leaf_session_dir: Path
    ) -> None:
        """agent-pp (project-planner) exists at root subagents."""
        project_dir = (
            sibling_shared_leaf_session_dir / "projects" / "C--Users-chris--myproject"
        )
        subagents = project_dir / "sess-sibling" / "subagents"
        meta = json.loads(
            (subagents / "agent-pp.meta.json").read_text(encoding="utf-8")
        )
        assert meta["agentType"] == "project-planner"

    def test_explore_b_under_project_planner(
        self, sibling_shared_leaf_session_dir: Path
    ) -> None:
        """agent-explore-b (Explore, under project-planner) exists at depth-3."""
        project_dir = (
            sibling_shared_leaf_session_dir / "projects" / "C--Users-chris--myproject"
        )
        depth3_subagents = (
            project_dir / "sess-sibling" / "subagents" / "agent-pp" / "subagents"
        )
        meta = json.loads(
            (depth3_subagents / "agent-explore-b.meta.json").read_text(encoding="utf-8")
        )
        assert meta["agentType"] == "Explore"

    def test_distinct_token_counts_per_chain(
        self, sibling_shared_leaf_session_dir: Path
    ) -> None:
        """Each chain has distinct, recoverable token counts for apportionment tests."""
        project_dir = (
            sibling_shared_leaf_session_dir / "projects" / "C--Users-chris--myproject"
        )

        def first_assistant_input_tokens(jsonl_path: Path) -> int:
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("type") == "assistant":
                    return entry["message"]["usage"]["input_tokens"]
            raise AssertionError(f"No assistant message in {jsonl_path}")

        subagents = project_dir / "sess-sibling" / "subagents"
        explore_a_tokens = first_assistant_input_tokens(
            subagents / "agent-explore-a.jsonl"
        )
        pp_tokens = first_assistant_input_tokens(subagents / "agent-pp.jsonl")
        explore_b_tokens = first_assistant_input_tokens(
            subagents / "agent-pp" / "subagents" / "agent-explore-b.jsonl"
        )
        # All three must be distinct and non-zero
        token_set = {explore_a_tokens, pp_tokens, explore_b_tokens}
        assert len(token_set) == 3, (
            f"Token counts must all be distinct; got {token_set}"
        )
        assert all(t > 0 for t in token_set)
