#!/usr/bin/env python3
"""PreToolUse hook that tracks skill pass-through and invocation.

Registered for both 'Skill' and 'Agent' tool matchers. Reads the
PreToolUse JSON payload from stdin and appends events to a per-day
JSONL file under ``~/.claude/claude-prospector/skill-tracking/``.

The tracking directory defaults to
``~/.claude/claude-prospector/skill-tracking/`` but can be overridden
via the ``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` environment variable
(used primarily during testing). Diagnostic logs are written to
``~/.claude/claude-prospector/hook.log`` (overridable via
``CLAUDE_PROSPECTOR_HOOK_LOG``) using a last-run-wins truncate-on-each-
run strategy so the log never grows unbounded.

Events emitted:
- ``skill_invoked``: when the Skill tool is called directly.
- ``skill_passed``: when an Agent dispatch prompt references a skill.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Pattern W: import setup_state helper from hooks/lib/
# ---------------------------------------------------------------------------
# sys and Path are already imported above.
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import setup_state  # noqa: E402


# ---------------------------------------------------------------------------
# Path resolution — overridable via environment variables for testability
# ---------------------------------------------------------------------------


def _base_dir() -> Path:
    """Return the claude-prospector base directory.

    Three-tier resolution (highest priority first):

    1. ``CLAUDE_PROSPECTOR_BASE_DIR`` — explicit test/override path.
    2. ``CLAUDE_PLUGIN_DATA`` — Anthropic plugin state dir (used as-is).
    3. Legacy ``~/.claude/claude-prospector/`` — pre-migration fallback.

    Migration logic is intentionally omitted here; it runs only from
    ``claude_prospector.paths.base_dir()`` so it happens exactly once.

    Returns:
        Resolved base directory path.
    """
    env_override = os.environ.get("CLAUDE_PROSPECTOR_BASE_DIR")
    if env_override:
        return Path(env_override)
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data)
    return Path.home() / ".claude" / "claude-prospector"


def _tracking_dir() -> Path:
    """Return the directory used for per-day tracking JSONL files.

    Reads ``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` from the environment;
    falls back to ``<base_dir>/skill-tracking/``.

    Returns:
        Path to the tracking directory (not guaranteed to exist yet).
    """
    env_val = os.environ.get("CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR")
    if env_val:
        return Path(env_val)
    return _base_dir() / "skill-tracking"


def _log_path() -> Path:
    """Return the path to the hook diagnostic log file.

    Reads ``CLAUDE_PROSPECTOR_HOOK_LOG`` from the environment; falls back
    to ``<base_dir>/hook.log``.

    Returns:
        Path to the hook log file (not guaranteed to exist yet).
    """
    env_val = os.environ.get("CLAUDE_PROSPECTOR_HOOK_LOG")
    if env_val:
        return Path(env_val)
    return _base_dir() / "hook.log"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_allowlist() -> set[str]:
    """Build allowlist of installed skill names by scanning the filesystem.

    Attempts to import
    ``claude_prospector.skill_tracking.build_skill_allowlist`` for full
    plugin-aware coverage. Falls back to a minimal filesystem scan of
    ``~/.claude/skills/`` when the package is not importable (e.g. when
    the hook runs outside the project's venv).

    Returns:
        Set of installed skill name strings (may include namespaced forms
        like ``superpowers:brainstorming``).
    """
    claude_dir = Path.home() / ".claude"
    try:
        from claude_prospector.skill_tracking import build_skill_allowlist

        return build_skill_allowlist(claude_dir)
    except ImportError:
        skills: set[str] = set()
        skills_dir = claude_dir / "skills"
        if skills_dir.is_dir():
            for child in skills_dir.iterdir():
                if child.is_dir():
                    skills.add(child.name)
        return skills


def _extract_skills(prompt: str, allowlist: set[str]) -> list[str]:
    """Extract skill references from a prompt, validated against allowlist.

    Delegates to
    ``claude_prospector.skill_tracking.extract_skills_from_prompt``
    when the package is importable. Falls back to an inline
    implementation that applies the same contextual filtering rules:

    - Namespaced backtick matches (containing ``:``) are always
      accepted.
    - Single-segment backtick matches require the word *skill* to
      appear within 60 characters of the match to avoid false
      positives from incidental mentions (e.g. a bare ``git`` in
      command examples).

    Args:
        prompt: The Agent dispatch prompt to scan.
        allowlist: Set of known installed skill names to validate
            against.

    Returns:
        Sorted list of skill names present in both the prompt and the
        allowlist.
    """
    try:
        from claude_prospector.skill_tracking import extract_skills_from_prompt

        return extract_skills_from_prompt(prompt, allowlist)
    except ImportError:
        import re

        _PROXIMITY = 60
        bt_pattern = re.compile(r"`([a-zA-Z0-9_-]+(?::[a-zA-Z0-9_-]+)?)`")
        candidates: set[str] = set()

        for match in bt_pattern.finditer(prompt):
            name = match.group(1)
            if ":" in name:
                candidates.add(name)
            else:
                start = max(0, match.start() - _PROXIMITY)
                end = min(len(prompt), match.end() + _PROXIMITY)
                window = prompt[start:end]
                if re.search(r"\bskills?\b", window, re.IGNORECASE):
                    candidates.add(name)

        return sorted(c for c in candidates if c in allowlist)


def _append_event(event: dict) -> None:
    """Append a JSON event line to today's per-day tracking file.

    The target file is
    ``<tracking_dir>/<YYYY-MM-DD>.jsonl`` where the date is the local
    wall-clock date of the event. Parent directories are created as
    needed.

    Args:
        event: Mapping to serialise as a single JSONL line.
    """
    tracking_dir = _tracking_dir()
    tracking_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    tracking_file = tracking_dir / f"{today}.jsonl"
    with open(tracking_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _log(message: str) -> None:
    """Write a diagnostic message to the hook log (truncate-on-each-run).

    Uses ``"w"`` mode so each run starts with a fresh log; only the
    most recent run's output is kept (last-run-wins).

    Args:
        message: The diagnostic text to record.
    """
    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(message + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse a PreToolUse JSON payload from stdin and emit tracking events.

    Reads one JSON object from stdin. Dispatches on ``tool_name``:

    - ``"Skill"``: emits a ``skill_invoked`` event when
      ``tool_input.skill`` is present.
    - ``"Agent"``: scans ``tool_input.prompt`` for skill references and
      emits a ``skill_passed`` event per discovered skill.

    Silently returns on JSON parse errors or missing fields.
    """
    # Pattern W guard: only proceed if setup state is VALID.
    # This check is cheap (flag read + path exists) — no subprocess.
    # Runs on every PreToolUse(Skill|Agent) fire, so it must stay minimal.
    try:
        _current_ver = setup_state.get_current_version()
        _state = setup_state.read_setup_state(_current_ver)
        if _state.status != "VALID":
            return  # Banner already shown by SessionStart hook; silent exit here
    except Exception:
        return  # Defensive: never crash the session on a guard error

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "unknown")
    now = datetime.now(timezone.utc).isoformat()

    if tool_name == "Skill":
        skill = tool_input.get("skill")
        if skill:
            _append_event(
                {
                    "event": "skill_invoked",
                    "skill": skill,
                    "timestamp": now,
                    "session_id": session_id,
                }
            )
        else:
            _log("skipped: no skill found in Skill tool_input")

    elif tool_name == "Agent":
        prompt = tool_input.get("prompt", "")
        target_agent = tool_input.get("subagent_type", "unknown")
        if not prompt:
            _log("skipped: empty prompt in Agent tool_input")
            return

        allowlist = _get_allowlist()
        skills = _extract_skills(prompt, allowlist)

        if not skills:
            _log(f"skipped: no skills found in Agent prompt for {target_agent}")
            return

        for skill in skills:
            _append_event(
                {
                    "event": "skill_passed",
                    "skill": skill,
                    "target_agent": target_agent,
                    "timestamp": now,
                    "session_id": session_id,
                }
            )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
