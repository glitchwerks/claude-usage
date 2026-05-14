"""Shared constants for the claude_usage package.

Centralises values that must be identical across multiple modules so
there is a single source of truth for each.
"""

from __future__ import annotations

#: Delimiter joining agent_path segments into a by_agent key string.
#: U+2192 RIGHTWARDS ARROW — round-trips through json.dumps as the
#: JSON Unicode escape ``→`` (decoded by JSON.parse client-side).
AGENT_PATH_SEPARATOR: str = "→"

#: Replacement character used when an agent name contains the path
#: separator.  U+FE56 SMALL QUESTION MARK — visually distinct and will
#: not collide with normal agent names.
SANITIZED_SEPARATOR_REPLACEMENT: str = "﹖"
