"""Shared test fixtures for claude-usage tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    """Write a list of dicts as JSONL to *path*."""
    path.write_text(
        "\n".join(json.dumps(line) for line in lines),
        encoding="utf-8",
    )


def _assistant_line(
    session_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    uuid: str,
    timestamp: str,
) -> dict:
    """Build a minimal assistant message dict for JSONL."""
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": session_id,
        "uuid": uuid,
        "message": {
            "model": model,
            "role": "assistant",
            "content": [{"type": "text", "text": "response"}],
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }


def _meta_json(agent_type: str) -> dict:
    """Build a subagent meta.json dict."""
    return {"agentType": agent_type}


# ---------------------------------------------------------------------------
# Existing fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_session_dir(tmp_path: Path) -> Path:
    """Create a mock Claude Code projects directory with sample session data."""
    project_dir = tmp_path / "projects" / "C--Users-chris--myproject"
    project_dir.mkdir(parents=True)

    session_id = "abc-123-def"

    # Main session JSONL
    lines = [
        {
            "type": "agent-setting",
            "agentSetting": "general-purpose",
            "sessionId": session_id,
        },
        {
            "parentUuid": None,
            "type": "user",
            "message": {"role": "user", "content": "Hello"},
            "uuid": "msg-1",
            "timestamp": "2026-04-09T12:00:00.000Z",
            "sessionId": session_id,
        },
        {
            "parentUuid": "msg-1",
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there"}],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 300,
                },
            },
            "uuid": "msg-2",
            "timestamp": "2026-04-09T12:00:05.000Z",
            "sessionId": session_id,
        },
        {
            "parentUuid": "msg-2",
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Skill",
                        "input": {"skill": "superpowers:brainstorming"},
                    }
                ],
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 25,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
            "uuid": "msg-3",
            "timestamp": "2026-04-09T12:01:00.000Z",
            "sessionId": session_id,
        },
        {
            "parentUuid": "msg-3",
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "role": "assistant",
                "content": [{"type": "text", "text": "Done"}],
                "usage": {
                    "input_tokens": 80,
                    "output_tokens": 40,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 0,
                },
            },
            "uuid": "msg-4",
            "timestamp": "2026-04-09T12:30:00.000Z",
            "sessionId": session_id,
        },
    ]

    jsonl_path = project_dir / f"{session_id}.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(line) for line in lines),
        encoding="utf-8",
    )

    # Subagent directory
    subagent_dir = project_dir / session_id / "subagents"
    subagent_dir.mkdir(parents=True)

    # Subagent metadata
    meta = {"agentType": "code-writer", "description": "Write feature X"}
    (subagent_dir / "agent-sub1.meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )

    # Subagent JSONL
    sub_lines = [
        {
            "parentUuid": None,
            "type": "user",
            "agentId": "sub1",
            "message": {"role": "user", "content": "Implement feature X"},
            "uuid": "sub-msg-1",
            "timestamp": "2026-04-09T12:05:00.000Z",
            "sessionId": session_id,
        },
        {
            "parentUuid": "sub-msg-1",
            "type": "assistant",
            "agentId": "sub1",
            "message": {
                "model": "claude-sonnet-4-6",
                "role": "assistant",
                "content": [{"type": "text", "text": "Implementing..."}],
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 250,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 1000,
                },
            },
            "uuid": "sub-msg-2",
            "timestamp": "2026-04-09T12:10:00.000Z",
            "sessionId": session_id,
        },
    ]

    (subagent_dir / "agent-sub1.jsonl").write_text(
        "\n".join(json.dumps(line) for line in sub_lines),
        encoding="utf-8",
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Phase 1 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nested_session_dir(tmp_path: Path) -> Path:
    """Create a depth-3 subagent fixture directory tree.

    Layout::

        projects/C--Users-chris--myproject/
          sess-nested.jsonl               # root: general-purpose (depth 1)
          sess-nested/
            subagents/
              agent-pp.meta.json          # agentType: project-planner (depth 2)
              agent-pp.jsonl              # 1 assistant msg, 200 input tokens (Opus)
              agent-pp/
                subagents/
                  agent-exp.meta.json     # agentType: Explore (PascalCase, depth 3)
                  agent-exp.jsonl         # 1 assistant msg, 400 input tokens (Haiku)

    Token counts at each depth are deliberately distinct so individual
    contributions are recoverable by inspection:

    - Depth 1 (general-purpose): 100 input tokens
    - Depth 2 (project-planner): 200 input tokens
    - Depth 3 (Explore):         400 input tokens

    The PascalCase ``Explore`` name is intentional — it doubles as the
    round-trip fixture for the Agent-Name Invariants section (§ Agent-Name
    Invariants in the plan), proving that non-ASCII-kebab agent names survive
    the path tuple without mutation.
    """
    session_id = "sess-nested"
    project_dir = tmp_path / "projects" / "C--Users-chris--myproject"
    project_dir.mkdir(parents=True)

    # Depth 1: general-purpose root
    _write_jsonl(
        project_dir / f"{session_id}.jsonl",
        [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            _assistant_line(
                session_id=session_id,
                model="claude-opus-4-6",
                input_tokens=100,
                output_tokens=50,
                uuid="nest-msg-1",
                timestamp="2026-05-13T10:00:00.000Z",
            ),
        ],
    )

    # Depth 2: project-planner subagent
    depth2_subagents = project_dir / session_id / "subagents"
    depth2_subagents.mkdir(parents=True)

    (depth2_subagents / "agent-pp.meta.json").write_text(
        json.dumps(_meta_json("project-planner")), encoding="utf-8"
    )
    _write_jsonl(
        depth2_subagents / "agent-pp.jsonl",
        [
            _assistant_line(
                session_id=session_id,
                model="claude-opus-4-6",
                input_tokens=200,
                output_tokens=100,
                uuid="nest-msg-2",
                timestamp="2026-05-13T10:01:00.000Z",
            ),
        ],
    )

    # Depth 3: Explore (PascalCase) subagent under project-planner
    depth3_subagents = depth2_subagents / "agent-pp" / "subagents"
    depth3_subagents.mkdir(parents=True)

    (depth3_subagents / "agent-exp.meta.json").write_text(
        json.dumps(_meta_json("Explore")), encoding="utf-8"
    )
    _write_jsonl(
        depth3_subagents / "agent-exp.jsonl",
        [
            _assistant_line(
                session_id=session_id,
                model="claude-haiku-4-5",
                input_tokens=400,
                output_tokens=200,
                uuid="nest-msg-3",
                timestamp="2026-05-13T10:02:00.000Z",
            ),
        ],
    )

    return tmp_path


@pytest.fixture
def pathological_depth_session_dir(tmp_path: Path) -> Path:
    """Create a 12-level-deep subagent chain to exercise _MAX_AGENT_PATH_LENGTH = 10.

    Layout::

        projects/C--Users-chris--myproject/
          sess-pathological.jsonl            # root: general-purpose
          sess-pathological/
            subagents/
              agent-d01.meta.json            # depth 1
              agent-d01.jsonl
              agent-d01/
                subagents/
                  agent-d02.meta.json        # depth 2
                  ...                        # continues to depth 12

    Each level has agentType ``f"depth-{n:02d}"`` with 10 input tokens, so
    token counts are uniform (the depth-cap test cares about path length, not
    token amounts). The chain is 12 levels deep, two beyond the cap of 10,
    ensuring the overflow warning must fire.
    """
    session_id = "sess-pathological"
    project_dir = tmp_path / "projects" / "C--Users-chris--myproject"
    project_dir.mkdir(parents=True)

    # Root JSONL (general-purpose)
    _write_jsonl(
        project_dir / f"{session_id}.jsonl",
        [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            _assistant_line(
                session_id=session_id,
                model="claude-opus-4-6",
                input_tokens=10,
                output_tokens=5,
                uuid="path-root",
                timestamp="2026-05-13T10:00:00.000Z",
            ),
        ],
    )

    # Build chain of 12 levels
    current_parent = project_dir / session_id
    for depth in range(1, 13):
        subagents_dir = current_parent / "subagents"
        subagents_dir.mkdir(parents=True)
        agent_id = f"agent-d{depth:02d}"
        (subagents_dir / f"{agent_id}.meta.json").write_text(
            json.dumps(_meta_json(f"depth-{depth:02d}")), encoding="utf-8"
        )
        _write_jsonl(
            subagents_dir / f"{agent_id}.jsonl",
            [
                _assistant_line(
                    session_id=session_id,
                    model="claude-opus-4-6",
                    input_tokens=10,
                    output_tokens=5,
                    uuid=f"path-msg-{depth}",
                    timestamp=f"2026-05-13T10:{depth:02d}:00.000Z",
                ),
            ],
        )
        current_parent = subagents_dir / agent_id

    return tmp_path


@pytest.fixture
def separator_in_name_session_dir(tmp_path: Path) -> Path:
    """Create a depth-2 session where the subagent has a separator in its name.

    Layout::

        projects/C--Users-chris--myproject/
          sess-separator.jsonl              # root: general-purpose
          sess-separator/
            subagents/
              agent-bad.meta.json           # agentType: "weird→name"
              agent-bad.jsonl

    The ``agentType`` value ``"weird→name"`` contains U+2192 (RIGHTWARDS ARROW),
    which is the same character used as the path separator. This fixture is the
    sanitizer round-trip test: the parser must replace ``→`` with ``﹖``
    (U+FE56 SMALL QUESTION MARK) and emit a warning.
    """
    session_id = "sess-separator"
    project_dir = tmp_path / "projects" / "C--Users-chris--myproject"
    project_dir.mkdir(parents=True)

    _write_jsonl(
        project_dir / f"{session_id}.jsonl",
        [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            _assistant_line(
                session_id=session_id,
                model="claude-opus-4-6",
                input_tokens=10,
                output_tokens=5,
                uuid="sep-root",
                timestamp="2026-05-13T10:00:00.000Z",
            ),
        ],
    )

    subagents_dir = project_dir / session_id / "subagents"
    subagents_dir.mkdir(parents=True)

    # agentType deliberately contains the path separator character
    (subagents_dir / "agent-bad.meta.json").write_text(
        json.dumps({"agentType": "weird→name"}), encoding="utf-8"
    )
    _write_jsonl(
        subagents_dir / "agent-bad.jsonl",
        [
            _assistant_line(
                session_id=session_id,
                model="claude-sonnet-4-6",
                input_tokens=20,
                output_tokens=10,
                uuid="sep-sub",
                timestamp="2026-05-13T10:01:00.000Z",
            ),
        ],
    )

    return tmp_path


@pytest.fixture
def symlink_cycle_session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a depth-2 session where subagents/ is a symlink cycle.

    On Windows with developer mode (or POSIX), this creates a real symlink:
    ``<root>/subagents/agent-x/subagents`` → ``<root>/subagents/``
    so that following the sub-agent's own subagents/ directory loops back.

    On Windows *without* developer mode ``os.symlink`` raises ``OSError``
    with ``[WinError 1314]``. In that case the fixture falls back to
    monkeypatching ``pathlib.Path.resolve`` to simulate the cycle.

    Either path exercises the visited-set cycle defense in
    ``_parse_subagents_recursive`` — the monkeypatch approach is preferred
    over ``pytest.skip`` because it keeps the cycle-detection code path
    active on all platforms. The choice between real symlink and monkeypatch
    is transparent to the test; both return the same ``tmp_path``-rooted
    directory tree, just with different cycle mechanics.

    Layout::

        projects/C--Users-chris--myproject/
          sess-cycle.jsonl                  # root: general-purpose
          sess-cycle/
            subagents/
              agent-x.meta.json             # agentType: agent-x
              agent-x.jsonl
              agent-x/
                subagents/  →  (symlink back to sess-cycle/subagents/)
    """
    session_id = "sess-cycle"
    project_dir = tmp_path / "projects" / "C--Users-chris--myproject"
    project_dir.mkdir(parents=True)

    _write_jsonl(
        project_dir / f"{session_id}.jsonl",
        [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            _assistant_line(
                session_id=session_id,
                model="claude-opus-4-6",
                input_tokens=10,
                output_tokens=5,
                uuid="cycle-root",
                timestamp="2026-05-13T10:00:00.000Z",
            ),
        ],
    )

    root_subagents = project_dir / session_id / "subagents"
    root_subagents.mkdir(parents=True)

    (root_subagents / "agent-x.meta.json").write_text(
        json.dumps({"agentType": "agent-x"}), encoding="utf-8"
    )
    _write_jsonl(
        root_subagents / "agent-x.jsonl",
        [
            _assistant_line(
                session_id=session_id,
                model="claude-sonnet-4-6",
                input_tokens=20,
                output_tokens=10,
                uuid="cycle-sub",
                timestamp="2026-05-13T10:01:00.000Z",
            ),
        ],
    )

    # agent-x's own session directory (needed for recursion target)
    agent_x_dir = root_subagents / "agent-x"
    agent_x_dir.mkdir(parents=True)

    try:
        # Create the symlink: agent-x/subagents -> ../  (back to root_subagents)
        cycle_link = agent_x_dir / "subagents"
        os.symlink(str(root_subagents), str(cycle_link))
    except OSError:
        # Windows without developer mode: fall back to monkeypatching resolve.
        # We place a real subagents/ dir but patch Path.resolve so the
        # resolved real path of agent-x/subagents matches root_subagents,
        # triggering the visited-set branch.
        fake_subagents = agent_x_dir / "subagents"
        fake_subagents.mkdir(parents=True)

        real_root = root_subagents.resolve()
        _original_resolve = Path.resolve

        def _patched_resolve(self: Path, strict: bool = False) -> Path:
            """Return root_subagents real path when called on the fake dir."""
            if self == fake_subagents or self == (agent_x_dir / "subagents"):
                return real_root
            return _original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", _patched_resolve)

    return tmp_path


@pytest.fixture
def sibling_shared_leaf_session_dir(tmp_path: Path) -> Path:
    """Create a session where two distinct chains share the same leaf agent name.

    Layout::

        projects/C--Users-chris--myproject/
          sess-sibling.jsonl                 # root: general-purpose
          sess-sibling/
            subagents/
              agent-explore-a.meta.json      # agentType: Explore (sibling)
              agent-explore-a.jsonl          # 150 input tokens
              agent-pp.meta.json             # agentType: project-planner
              agent-pp.jsonl                 # 250 input tokens
              agent-pp/
                subagents/
                  agent-explore-b.meta.json  # agentType: Explore (nested)
                  agent-explore-b.jsonl      # 350 input tokens

    Two independent ``Explore`` invocations:

    - ``general-purpose → Explore`` (agent-explore-a, sibling of project-planner)
    - ``general-purpose → project-planner → Explore`` (agent-explore-b, nested)

    Neither path key is a prefix of the other, so both survive as deepest
    leaves in the aggregator's deepest-leaf computation (Phase 4).

    Token counts are deliberately distinct so per-chain apportionment can
    be verified: 150 / 250 / 350 for explore-a / project-planner / explore-b.
    """
    session_id = "sess-sibling"
    project_dir = tmp_path / "projects" / "C--Users-chris--myproject"
    project_dir.mkdir(parents=True)

    # Root: general-purpose
    _write_jsonl(
        project_dir / f"{session_id}.jsonl",
        [
            {
                "type": "agent-setting",
                "agentSetting": "general-purpose",
                "sessionId": session_id,
            },
            _assistant_line(
                session_id=session_id,
                model="claude-opus-4-6",
                input_tokens=50,
                output_tokens=25,
                uuid="sib-root",
                timestamp="2026-05-13T10:00:00.000Z",
            ),
        ],
    )

    root_subagents = project_dir / session_id / "subagents"
    root_subagents.mkdir(parents=True)

    # agent-explore-a: Explore as direct sibling of project-planner
    (root_subagents / "agent-explore-a.meta.json").write_text(
        json.dumps(_meta_json("Explore")), encoding="utf-8"
    )
    _write_jsonl(
        root_subagents / "agent-explore-a.jsonl",
        [
            _assistant_line(
                session_id=session_id,
                model="claude-haiku-4-5",
                input_tokens=150,
                output_tokens=75,
                uuid="sib-explore-a",
                timestamp="2026-05-13T10:01:00.000Z",
            ),
        ],
    )

    # agent-pp: project-planner
    (root_subagents / "agent-pp.meta.json").write_text(
        json.dumps(_meta_json("project-planner")), encoding="utf-8"
    )
    _write_jsonl(
        root_subagents / "agent-pp.jsonl",
        [
            _assistant_line(
                session_id=session_id,
                model="claude-opus-4-6",
                input_tokens=250,
                output_tokens=125,
                uuid="sib-pp",
                timestamp="2026-05-13T10:02:00.000Z",
            ),
        ],
    )

    # agent-explore-b: Explore nested under project-planner
    depth3_subagents = root_subagents / "agent-pp" / "subagents"
    depth3_subagents.mkdir(parents=True)

    (depth3_subagents / "agent-explore-b.meta.json").write_text(
        json.dumps(_meta_json("Explore")), encoding="utf-8"
    )
    _write_jsonl(
        depth3_subagents / "agent-explore-b.jsonl",
        [
            _assistant_line(
                session_id=session_id,
                model="claude-haiku-4-5",
                input_tokens=350,
                output_tokens=175,
                uuid="sib-explore-b",
                timestamp="2026-05-13T10:03:00.000Z",
            ),
        ],
    )

    return tmp_path
