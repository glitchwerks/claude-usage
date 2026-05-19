"""Parse skill tracking JSONL log and extract skill references from prompts.

Tracking data is written by ``hooks/skill-tracker.py`` as per-day JSONL
files under ``~/.claude/claude-prospector/skill-tracking/<YYYY-MM-DD>.jsonl``.
The directory can be overridden via the
``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` environment variable for testing.

Backwards-compatibility note (transitional, remove in v0.5.x):
If the old flat file ``<data_dir>/skill-tracking.jsonl`` exists, its
records are concatenated with the per-day directory records so users who
migrated from the flat layout continue to see historical data.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from claude_prospector.models import SkillInvokedEvent, SkillPassedEvent


def _default_tracking_dir() -> Path:
    """Return the per-day tracking directory.

    Reads ``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` from the environment;
    falls back to ``~/.claude/claude-prospector/skill-tracking/``.

    Returns:
        Path to the tracking directory.
    """
    env_val = os.environ.get("CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR")
    if env_val:
        return Path(env_val)
    return Path.home() / ".claude" / "claude-prospector" / "skill-tracking"


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a datetime.

    Args:
        ts_str: ISO 8601 string, with optional trailing ``Z``.

    Returns:
        Parsed :class:`datetime` object.
    """
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)


def _parse_lines(
    lines: list[str],
    passed: list[SkillPassedEvent],
    invoked: list[SkillInvokedEvent],
) -> None:
    """Parse JSONL lines and append events to the supplied lists in-place.

    Silently skips malformed JSON lines and unknown event types.

    Args:
        lines: Raw text lines from a JSONL file.
        passed: Accumulator list for :class:`SkillPassedEvent` records.
        invoked: Accumulator list for :class:`SkillInvokedEvent` records.
    """
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = entry.get("event")
        if event_type == "skill_passed":
            try:
                passed.append(
                    SkillPassedEvent(
                        skill=entry["skill"],
                        target_agent=entry["target_agent"],
                        timestamp=_parse_timestamp(entry["timestamp"]),
                        session_id=entry["session_id"],
                    )
                )
            except (KeyError, ValueError):
                continue
        elif event_type == "skill_invoked":
            try:
                invoked.append(
                    SkillInvokedEvent(
                        skill=entry["skill"],
                        timestamp=_parse_timestamp(entry["timestamp"]),
                        session_id=entry["session_id"],
                    )
                )
            except (KeyError, ValueError):
                continue


def parse_skill_tracking(
    data_dir: Path,
    retention_days: int = 90,
) -> tuple[list[SkillPassedEvent], list[SkillInvokedEvent]]:
    """Read skill-tracking event files and return parsed events.

    Walks per-day JSONL files from the configured tracking directory
    (``CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`` env var or
    ``~/.claude/claude-prospector/skill-tracking/``), skipping files
    whose date is older than ``retention_days`` days.

    Backwards-compatibility (transitional — remove in v0.5.x): if a
    flat ``skill-tracking.jsonl`` file exists inside ``data_dir``, its
    records are read first and merged with the per-day records. This
    eases migration from the v0.3.x flat-file layout.

    Args:
        data_dir: Session data directory. Used only for the transitional
            flat-file fallback; per-day files come from the tracking
            directory resolved via environment variable.
        retention_days: Per-day files older than this many days from
            today are skipped. Defaults to 90.

    Returns:
        A 2-tuple ``(passed_events, invoked_events)`` of parsed records.
        Returns empty lists if no tracking files exist.
    """
    passed: list[SkillPassedEvent] = []
    invoked: list[SkillInvokedEvent] = []

    # ------------------------------------------------------------------
    # Backwards-compat: read old flat file if present (v0.3.x layout)
    # ------------------------------------------------------------------
    legacy_file = data_dir / "skill-tracking.jsonl"
    if legacy_file.exists():
        _parse_lines(
            legacy_file.read_text(encoding="utf-8").splitlines(),
            passed,
            invoked,
        )

    # ------------------------------------------------------------------
    # Per-day files from the new directory layout
    # ------------------------------------------------------------------
    tracking_dir = _default_tracking_dir()
    if not tracking_dir.is_dir():
        return passed, invoked

    cutoff = date.today() - timedelta(days=retention_days)

    # Sort by filename so files are processed in chronological order.
    for jsonl_file in sorted(tracking_dir.glob("*.jsonl")):
        # Extract the date from the filename stem (YYYY-MM-DD).
        try:
            file_date = date.fromisoformat(jsonl_file.stem)
        except ValueError:
            # Skip files whose names don't match the expected date format.
            continue

        if file_date < cutoff:
            continue

        _parse_lines(
            jsonl_file.read_text(encoding="utf-8").splitlines(),
            passed,
            invoked,
        )

    return passed, invoked


def build_skill_allowlist(claude_dir: Path) -> set[str]:
    """Scan filesystem to build a set of installed skill names.

    Scans:

    - ``<claude_dir>/skills/`` — user skills (directory names).
    - ``<claude_dir>/plugins/cache/*/*/skills/`` — plugin skills,
      emitted both bare (``brainstorming``) and namespaced
      (``superpowers:brainstorming``).

    Args:
        claude_dir: Path to the ``.claude`` user directory.

    Returns:
        Set of skill name strings, including namespaced variants for
        plugin skills.
    """
    skills: set[str] = set()
    skills_dir = claude_dir / "skills"
    if skills_dir.is_dir():
        for child in skills_dir.iterdir():
            if child.is_dir():
                skills.add(child.name)

    plugins_cache = claude_dir / "plugins" / "cache"
    if plugins_cache.is_dir():
        for marketplace in plugins_cache.iterdir():
            if not marketplace.is_dir():
                continue
            for plugin_dir in marketplace.iterdir():
                if not plugin_dir.is_dir():
                    continue
                for version_dir in plugin_dir.iterdir():
                    if not version_dir.is_dir():
                        continue
                    plugin_skills = version_dir / "skills"
                    if plugin_skills.is_dir():
                        prefix = plugin_dir.name
                        for skill_dir in plugin_skills.iterdir():
                            if skill_dir.is_dir():
                                skills.add(skill_dir.name)
                                skills.add(f"{prefix}:{skill_dir.name}")

    return skills


# Patterns for extracting skill references from Agent dispatch prompts
_BACKTICK_PATTERN = re.compile(r"`([a-zA-Z0-9_-]+(?::[a-zA-Z0-9_-]+)?)`")
_PHRASE_PATTERNS = [
    re.compile(
        r"[Uu]se (?:the )?[\"']?"
        r"([a-zA-Z0-9_-]+(?::[a-zA-Z0-9_-]+)?)"
        r"[\"']? skill",
        re.IGNORECASE,
    ),
    re.compile(
        r"[Ii]nvoke (?:the )?[\"']?"
        r"([a-zA-Z0-9_-]+(?::[a-zA-Z0-9_-]+)?)"
        r"[\"']? skill",
        re.IGNORECASE,
    ),
    re.compile(
        r"[Uu]se skill:?\s*[\"']?" r"([a-zA-Z0-9_-]+(?::[a-zA-Z0-9_-]+)?)" r"[\"']?",
        re.IGNORECASE,
    ),
]

# Characters to search on each side of a backtick match when checking
# for nearby "skill" context.
_SKILL_PROXIMITY_CHARS = 60


def _has_nearby_skill_word(prompt: str, match_start: int, match_end: int) -> bool:
    """Return True if the word 'skill' appears within proximity of a match.

    Args:
        prompt: The full prompt text being scanned.
        match_start: Start index of the backtick match in the prompt.
        match_end: End index of the backtick match in the prompt.

    Returns:
        True if the word ``skill`` or ``skills`` (case-insensitive)
        appears within ``_SKILL_PROXIMITY_CHARS`` characters before or
        after the match boundaries, False otherwise.
    """
    window_start = max(0, match_start - _SKILL_PROXIMITY_CHARS)
    window_end = min(len(prompt), match_end + _SKILL_PROXIMITY_CHARS)
    window = prompt[window_start:window_end]
    return bool(re.search(r"\bskills?\b", window, re.IGNORECASE))


def extract_skills_from_prompt(prompt: str, allowlist: set[str]) -> list[str]:
    """Extract skill names from an Agent dispatch prompt.

    Uses two detection strategies and merges results before filtering
    against the allowlist:

    1. **Backtick matches** — any backtick-quoted token. Namespaced
       names (containing ``:``) are always accepted. Single-segment
       names are only accepted when the word *skill* (or *skills*)
       appears within ``_SKILL_PROXIMITY_CHARS`` characters of the
       match, preventing incidental mentions like a bare ``git`` in
       command examples from inflating metrics.

    2. **Phrase pattern matches** — patterns like *"Use the python
       skill"* or *"Invoke the powershell skill"*. These already
       require the word *skill* in their regex, so they are accepted
       unconditionally (no proximity check needed).

    Args:
        prompt: The Agent dispatch prompt to scan.
        allowlist: Set of known installed skill names to validate
            candidates against.

    Returns:
        Sorted list of skill names that appear in the prompt and are
        present in the allowlist.
    """
    backtick_candidates: set[str] = set()

    for match in _BACKTICK_PATTERN.finditer(prompt):
        name = match.group(1)
        if ":" in name:
            # Namespaced skills (e.g. superpowers:brainstorming) are
            # unambiguous — accept without proximity check.
            backtick_candidates.add(name)
        elif _has_nearby_skill_word(prompt, match.start(), match.end()):
            # Single-segment name confirmed by nearby "skill" keyword.
            backtick_candidates.add(name)

    phrase_candidates: set[str] = set()
    for pattern in _PHRASE_PATTERNS:
        for match in pattern.finditer(prompt):
            phrase_candidates.add(match.group(1))

    candidates = backtick_candidates | phrase_candidates
    return sorted(c for c in candidates if c in allowlist)
