# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-05-16

### Added

- `/usage-dashboard` slash command at `commands/usage-dashboard.md` (#80).
- `hooks/skill-tracker.py` PreToolUse hook with per-day JSONL rotation under `~/.claude/claude-prospector/skill-tracking/<YYYY-MM-DD>.jsonl` — caps unbounded file growth, eliminates concurrent-append contention, and enforces a 90-day retention window (#84).
- `hooks/dashboard-regen.py` Stop hook that regenerates the usage dashboard automatically after each session, with opt-in via `{"autoregen": true}` in `config.json` (#90).
- Three failure HTML pages for the Stop hook covering missing Python interpreter, version mismatch, and regen failure (#90).
- `config` CLI subcommand (`--enable-autoregen` / `--disable-autoregen` / `--show`) for managing hook settings (#90).
- `--version` flag to the CLI (#90).
- `claude_prospector/paths.py` centralizing all persistent-state path resolution (#90).
- Plugin manifest scaffolding: `.claude-plugin/plugin.json`, `commands/`, `skills/`, and `hooks/` directories (#66).
- `skills/usage-analysis/SKILL.md` — conversational token-usage analysis ported into the plugin with trigger-phrase prune (6 Claude-Code-specific phrases retained) (#78).
- All persistent plugin state now consolidated under `~/.claude/claude-prospector/` (`config.json`, `dashboard.html`, `skill-tracking/`, `hook.log`) — was previously scattered across `~/.claude/` (#82, updated in #85).

### Changed

- **Breaking:** Python package renamed from `claude_usage` to `claude_prospector` — any code importing the old name must be updated (#62).
- Plugin description updated to "Claude Code token usage analyzer with optimization recommendations" (#69).
- README restructured so plugin installation leads and the Python-module CLI is demoted to a Development section (#75).
- `skill-tracker.py` reader retains a one-version transitional fallback for the legacy flat `~/.claude/skill-tracking.jsonl` to ease migration (#84).

### Removed

- Unused `pyyaml` runtime dependency (#58).

[0.4.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.4.0
