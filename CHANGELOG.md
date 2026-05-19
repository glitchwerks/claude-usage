# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.1] - 2026-05-18

### Changed

- Rewrote `description:` frontmatter for both plugin skills
  (`usage-analysis`, `usage-dashboard`) to use "Use when..." activation
  framing with explicit "Do NOT use ... (use other skill instead)"
  boundaries. Trigger phrases now carry `Claude` / `prospector` / `token`
  disambiguators to prevent false positives in cloud-billing or
  API-quota contexts. (#119, closes #101)
- README audited for correctness against v0.7.0 code and restructured
  into 12 sections; "Why" section rewritten to acknowledge Claude
  Code's built-in `/usage` command and clarify what `claude-prospector`
  adds on top. (#118)

### Removed

- Empty `commands/` folder (deprecated surface — skills replaced
  commands in v0.6.0). (#117)

## [0.7.0] - 2026-05-18

### Added

- `/setup-prospector` skill: materialises a plugin-owned Python venv at
  `${CLAUDE_PLUGIN_DATA}/venv/` and writes a setup-state flag. Required
  once after install or after a plugin update.
- `SessionStart` hook (`hooks/check-prospector-setup.py`): surfaces a
  banner when setup is required and runs a per-session import probe to
  detect venv corruption.
- `hooks/lib/setup_state.py`: shared deterministic helper for flag I/O,
  version comparison, and venv-python path resolution.
- CI: `skill-smoke-{ubuntu,windows}` jobs validate the full setup
  pipeline on every PR against real Python 3.10 and real pip.

### Changed

- `hooks/dashboard-regen.py` no longer guesses the venv root via
  `Path(sys.executable).parent.parent.parent`. Both the version-check
  subprocess (`:506-514`) and the dashboard regen subprocess (`:543-560`)
  now use the absolute path recorded in the setup-state flag.
- `hooks/skill-tracker.py` now short-circuits silently when the
  setup-state flag is not VALID, deferring to the SessionStart banner
  for user guidance.
- `claude-prospector` is now published to PyPI. The setup skill installs
  from PyPI by default; `CLAUDE_PROSPECTOR_PIP_SPEC` allows installing
  from a local checkout for development.

### Migration from v0.6.0

After upgrading to v0.7.0, open a new Claude Code session. A
SessionStart banner will prompt you to run `/setup-prospector`. This is
a one-time action per machine per major version.

If you previously installed `claude-prospector` into `~/.claude/.venv`
(the user-managed venv approach), you can leave that install in place —
Pattern W's hooks always spawn the plugin-owned venv via an absolute
path and will not pick up the legacy install. To reclaim disk, you may
`uv pip uninstall claude-prospector` from `~/.claude/.venv` after
Pattern W is working; this is optional and unrelated to plugin operation.

The `${user_config.autoregen}` setting is preserved across the upgrade.
The legacy `config.json` migration mechanism added in v0.6.0 continues
to function unchanged.

## [0.7.0rc1] - 2026-05-18

### Added

- TestPyPI rehearsal of the PyPI publish workflow shipped in #109. No functional changes — this release-candidate validates the OIDC trusted-publisher + tag-routing wiring end-to-end before the real `v0.7.0` ships Pattern W adoption (#107). (#111)

[0.7.0rc1]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.7.0-rc1

## [0.6.0] - 2026-05-17

### Changed

- **Breaking — user-config mechanism:** the `autoregen` setting is now declared in `plugin.json` under the `userConfig` block and toggled through the plugin manager (`/plugin reconfigure claude-prospector` or the install-time prompt), per [Anthropic's documented convention](https://code.claude.com/docs/en/plugins-reference#user-configuration). The `Stop` hook receives the value via `--autoregen "${user_config.autoregen}"` and parses truthiness in Python (`true` / `1` / `yes` case-insensitive). (#99, #100)
- **Breaking — CLI surface:** `python -m claude_prospector config` is now read-only (`--show`). The mutation flags `--enable-autoregen` and `--disable-autoregen` are removed — their job belongs to the plugin manager now.
- **Behavioral break for existing users:** if you had `autoregen: true` in the legacy `${CLAUDE_PLUGIN_DATA}/config.json`, autoregen will stop firing after upgrading until you re-toggle it through the plugin manager. The legacy file is preserved (not deleted) so you can consult your previous state.

### Added

- One-time `[migration]` notice written to `hook.log` when the legacy `config.json` is detected, advising users to re-toggle through the plugin manager. A sentinel file (`config.json.migrated-notice`) suppresses duplicate notices. (#100)

[0.6.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.6.0

## [0.5.0] - 2026-05-17

### Changed

- State-storage path resolution now uses a three-tier `base_dir()` lookup: `CLAUDE_PROSPECTOR_BASE_DIR` (explicit override) → `CLAUDE_PLUGIN_DATA` (Anthropic plugin state dir, populated by Claude Code at plugin load) → legacy `~/.claude/claude-prospector/` (fallback). Both hook scripts replicate the resolver inline to remain stdlib-only. (#96)

### Added

- One-time auto-migration: when `CLAUDE_PLUGIN_DATA` is set and the legacy `~/.claude/claude-prospector/` directory has content while the new location is empty, `paths.base_dir()` moves the contents via `shutil.move` and removes the legacy dir. Idempotent (skipped if new dir is non-empty); failures are logged to `hook.log` with a `[migration]` prefix and never crash the run. (#96)

[0.5.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.5.0

## [0.4.0] - 2026-05-16

### Added

- `skills/usage-dashboard/SKILL.md` — bare dashboard-regeneration sibling to `usage-analysis`, triggered by phrases like "regenerate the dashboard". (Originally landed as a `/usage-dashboard` slash command in #80, then ported to a skill in #92 before the v0.4.0 tag.)
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
