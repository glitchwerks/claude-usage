"""Parse skill tracking JSONL log and extract skill references from prompts."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from claude_prospector.models import SkillInvokedEvent, SkillPassedEvent

TRACKING_FILE = "skill-tracking.jsonl"


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a datetime."""
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)


def parse_skill_tracking(
    data_dir: Path,
) -> tuple[list[SkillPassedEvent], list[SkillInvokedEvent]]:
    """Read skill-tracking.jsonl and return parsed events.

    Returns empty lists if the file doesn't exist.
    """
    tracking_file = data_dir / TRACKING_FILE
    if not tracking_file.exists():
        return [], []

    passed: list[SkillPassedEvent] = []
    invoked: list[SkillInvokedEvent] = []

    for line in tracking_file.read_text(encoding="utf-8").splitlines():
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

    return passed, invoked


def build_skill_allowlist(claude_dir: Path) -> set[str]:
    """Scan filesystem to build a set of installed skill names.

    Scans:
    - ~/.claude/skills/ (user skills — directory names)
    - ~/.claude/plugins/cache/*/superpowers/*/skills/ (plugin skills)
    - Plugin subdirectories for prefix:name format
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

    1. **Backtick matches** — any backtick-quoted token.  Namespaced
       names (containing ``:``) are always accepted.  Single-segment
       names are only accepted when the word *skill* (or *skills*)
       appears within ``_SKILL_PROXIMITY_CHARS`` characters of the
       match, preventing incidental mentions like a bare ``git`` in
       command examples from inflating metrics.

    2. **Phrase pattern matches** — patterns like *"Use the python
       skill"* or *"Invoke the powershell skill"*.  These already
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
