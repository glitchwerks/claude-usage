# claude-prospector — Project Instructions

Project-scoped guidance for Claude Code agents working in this repo. The user's global `~/.claude/CLAUDE.md` still applies; this file adds project-specific facts and points at the in-repo authoritative docs. Keep this file short — reference, do not duplicate.

## Releases

**Before tagging, opening a release PR, or bumping the marketplace pin, read `docs/release-process.md` end-to-end.** That doc is the authoritative runbook — it covers the pre-release checklist, the four release classes (patch / minor / major / repo-move), the exact step-by-step sequence, the footguns (annotated-tag SHA trap; cache-wipe scope), the rollback procedure, and a Quick Reference Card.

When opening a release PR, use the `release.md` PR template (`?template=release.md` in the URL, or selectable in the PR creation UI).

Do not freelance release steps. Every command in the runbook came from an actual release (PR #139 → 0.8.2). If a step in the runbook is unclear or appears stale, update the runbook in the same PR — never deviate silently.

## Repo layout

`src/`-layout (per PR #128):

- Package source: `src/claude_prospector/`
- Templates: `src/claude_prospector/templates/` — loaded via `PackageLoader("claude_prospector", "templates")` (see PR #139 for the loader-hardening fix; do not switch back to `FileSystemLoader` with `__file__`-relative paths)
- Tests: `tests/` (unit + integration)
- Build backend: setuptools with `include-package-data` driven by `[tool.setuptools.package-data]` in `pyproject.toml`

## Python interpreter and test commands

Python is pinned to **3.12** via `.python-version`. `uv run` honors this; bare `pytest` / `ruff` invocations do not, and on this Windows host fall through to system Python 3.14 (where `claude_prospector` is not installed). The fallout is documented in #136 / PR #137.

Always invoke via `uv run`:

```bash
uv run pytest                              # full test suite
uv run pytest tests/unit/                  # unit only
uv run pytest -q tests/<file>::<test>      # single test
uv run ruff check src/ tests/              # lint
uv build --wheel                           # local wheel build (used by release runbook)
```

`uv sync --group dev` (not `pip install -e ".[dev]"`) installs dev deps — they live in `[dependency-groups]` (PEP 735), not `[project.optional-dependencies]`.

## CI gates

CI runs Lint, Test (Ubuntu + Windows), Skill Smoke (Ubuntu + Windows), and — on the release workflow only — **`wheel-smoke`** (added in PR #139 for issue #138). The wheel-smoke job installs the built wheel into a fresh venv and runs `python -m claude_prospector dashboard` end-to-end. Any change touching wheel contents — `pyproject.toml` `package-data`, `MANIFEST.in`, `[build-system]`, the template loader, or anything that affects what gets packaged — MUST be verified locally before PR:

```bash
uv build --wheel
unzip -l dist/claude_prospector-*.whl | grep templates    # confirm templates ship
```

`docs/release-process.md § Footguns › Wheel-smoke must pass before proceeding past step 5` covers the broader rule.

## Branch / worktree conventions

Per the user-global `~/.claude/CLAUDE.md`: feature work uses worktrees under `.worktrees/<branch>` (gitignored). Never commit directly to `main`; always go through a PR.

## Issue / PR conventions

GitHub Issues is the single tracking system. Use closing keywords (`Closes #N` / `Fixes #N`) in the PR body — one keyword per issue, no comma-continuation. The user's global CLAUDE.md covers the rest of the conventions.
