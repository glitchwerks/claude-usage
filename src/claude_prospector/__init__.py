"""Claude Prospector — Claude Code usage analytics dashboard."""

from __future__ import annotations

try:
    import importlib.metadata as _meta

    __version__: str = _meta.version("claude-prospector")
except Exception:
    __version__ = "0.0.0+local"
