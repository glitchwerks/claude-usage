# claude-prospector

Token usage analyzer for Claude Code that surfaces where your budget is going across all three billing windows, with per-model and per-agent attribution and concrete optimization recommendations.

## Why

Claude Code tracks three billing buckets (5h rolling, 7d rolling, Sonnet-only 7d) but provides no per-agent or per-skill visibility. This tool reads Claude Code's local JSONL session files and generates a dashboard that breaks down where your tokens are going — by model, agent, skill, and project.

## Install

### 1. Add the marketplace and install the plugin

```bash
claude plugin marketplace add glitchwerks/plugins
claude plugin install claude-prospector@glitchwerks
```

### 2. First-run setup

After installing (or after a plugin update), open a new Claude Code session. You will see a banner:

> claude-prospector requires setup. Run /setup-prospector to materialise the Python venv. After setup completes, open a new session to activate the dashboard, skill-tracking, and usage-analysis features.

Run `/setup-prospector` once. The skill will:

1. Discover a Python 3.10+ interpreter on your system.
2. Create a plugin-owned venv at `${CLAUDE_PLUGIN_DATA}/venv/`.
3. Install `claude-prospector` from PyPI into that venv.
4. Verify the install and record a setup-state flag.

After setup completes, open a new session — the banner will be gone and all features will work normally.

You will need to re-run `/setup-prospector` only when:

- The plugin updates to a new version (banner: "venv is for vX but plugin is vY").
- The venv is corrupted or deleted (banner: "venv at `<path>` is unreachable or corrupt").
- You move to a new machine (setup is per-machine; the flag is not portable).

## What you can do

### `usage-analysis` skill

Conversational analysis with recommendations. Triggered by natural-language phrases such as:

- "am I close to my Sonnet limit?"
- "where are my tokens going?"
- "which agent uses the most tokens?"
- "give me a usage analysis"

The skill reads your session data and responds inline — no browser required.

### `usage-dashboard` skill

Bare dashboard regeneration. Triggered by phrases like "regenerate the dashboard" or "rebuild my usage dashboard". Writes the HTML file and reports the path, without interpreting the data.

The generated HTML dashboard includes:

- **Budget gauges** — estimated usage against each billing bucket (5h / 7d / Sonnet-only 7d)
- **Model breakdown** — donut chart and daily stacked bar chart (Opus / Sonnet / Haiku)
- **Agent breakdown** — token usage per agent with model attribution and nested sub-agent tracing
- **Skill usage** — invocation counts per skill
- **Project breakdown** — tokens per project
- **Session drill-down** — click a day to see individual sessions with agents, tokens, and model split

### `setup-prospector` skill

First-run and post-update setup. Triggered by `/setup-prospector` or phrases like "set up claude-prospector", "fix prospector", or "prospector isn't working". See [Install](#install) for the full walkthrough.

### SessionStart hook (`check-prospector-setup.py`)

Fires once at the beginning of every session. Checks setup state and emits a banner when setup is missing, stale, or broken. Silent when everything is valid. This hook never blocks the session.

### `skill-tracker` hook (`skill-tracker.py`, PreToolUse)

Logs `Skill` and `Agent` tool-use events to the state directory for the `by_skill` and skill-passed-vs-invoked analyses. Gated on VALID setup state — if you skip `/setup-prospector`, skill-tracking is silently inactive until setup is complete.

### `dashboard-regen` hook (Stop, opt-in)

Auto-regenerates the dashboard after every session when `autoregen` is enabled. Off by default; toggle via the plugin manager (see [Configuration](#configuration)).

## Configuration

The `dashboard-regen` Stop hook is opt-in. Toggle it through the Claude Code plugin manager — no manual file edits required:

```
/plugin reconfigure claude-prospector
```

You will be prompted to enable or disable `autoregen`. You can also set it at install time when the plugin manager shows the initial configuration prompt.

To inspect the current plugin configuration, use the read-only CLI:

```bash
python -m claude_prospector config --show
```

When a config file exists, this prints its contents as pretty-printed JSON to stdout.
When no config file exists, it prints `(no config file yet)` and a redirect note to stderr, and `{}` to stdout. Exit code is 0 in both cases.

The authoritative `autoregen` value is whatever is set in the plugin manager — not the legacy `config.json`.

## Environment variables

| Variable | Controls | Notes |
|---|---|---|
| `CLAUDE_PLUGIN_DATA` | Venv placement and default state/dashboard storage | Set by the Claude Code plugin host; do not override in normal use |
| `CLAUDE_PROSPECTOR_BASE_DIR` | State and dashboard storage for hooks and CLI | Overrides `CLAUDE_PLUGIN_DATA` for hooks/CLI only; does not affect the venv location |
| `CLAUDE_PROSPECTOR_PIP_SPEC` | The pip spec used by `/setup-prospector` | Overrides the default `claude-prospector==<version>` — used in CI and dev to install from TestPyPI or a local checkout |

## Troubleshooting

The SessionStart hook emits one of four banner states. Use the banner text to decide what to do:

**MISSING** — No setup-state flag found, or the previous venv failed the per-session import probe.

> claude-prospector requires setup. Run /setup-prospector to materialise the Python venv. After setup completes, open a new session to activate the dashboard, skill-tracking, and usage-analysis features.

Action: run `/setup-prospector`, then open a new session.

**STALE** — The flag records a different plugin version than the one currently installed.

> claude-prospector venv is for v`<flag_version>` but plugin is v`<current_version>`. Run /setup-prospector to refresh the venv.

Action: run `/setup-prospector` to rebuild the venv for the new version.

**BROKEN** — The flag exists and the version matches, but the venv path is unreachable or corrupt.

> claude-prospector venv at `<venv_path>` is unreachable or corrupt. Run /setup-prospector to recreate it.

Action: run `/setup-prospector` to recreate the venv.

**VALID (probe failed)** — The flag looks valid but the per-session `import claude_prospector` probe failed. The hook downgrades state to MISSING and emits the MISSING banner.

Action: same as MISSING — run `/setup-prospector`, then open a new session.

**Silent session** — No banner emitted. Setup is valid and the import probe passed. All features are active.

## Subcommands

All functionality is accessed through named subcommands. Bare `claude-prospector` (no subcommand) prints help and exits 0.

### `dashboard` — interactive HTML dashboard

```bash
# Default: last 7 days, opens in browser
python -m claude_prospector dashboard

# Rolling window matching Claude billing buckets
python -m claude_prospector dashboard --window 5h
python -m claude_prospector dashboard --window 7d

# Custom date range
python -m claude_prospector dashboard --from 2026-04-01 --to 2026-04-09

# Output to file instead of opening browser
python -m claude_prospector dashboard --output report.html --no-open

# Custom Claude data directory
python -m claude_prospector dashboard --data-dir "D:\other\.claude"

# Set budget limits for gauge percentages
python -m claude_prospector dashboard --limit-5h 600000 --limit-7d 4000000 --limit-sonnet-7d 2000000

# Emit JSON for scripting or CI
python -m claude_prospector dashboard --format json
```

### `session-summary` — deterministic session recap

Reads a single Claude Code transcript JSONL file and emits a structured JSON summary suitable for consumption by the `/whats-next` skill or any other tool that needs to know what a session did.

```bash
python -m claude_prospector session-summary --path ~/.claude/projects/<hash>/<session>.jsonl
```

**Flags:**

| Flag | Default | Description |
|---|---|---|
| `--path PATH` | *(required)* | Path to the transcript JSONL file |
| `--format {json,text}` | `json` | Output format. `json` is the machine-readable contract; `text` is a human-readable debug view |
| `--max-actions N` | `50` | Cap on emitted actions. `0` disables the cap |

**Sample output (`--format json`):**

```json
{
  "project": "claude-prospector",
  "intent": "Implement the session-summary subcommand for the /whats-next skill",
  "actions": [
    "Edited claude_prospector/cli/session_summary.py",
    "Created tests/test_session_summary.py",
    "Ran pytest tests/test_session_summary.py -x",
    "Dispatched code-reviewer sub-agent"
  ],
  "stoppedNaturally": true
}
```

**Exit codes:**

| Code | Meaning | stderr |
|---|---|---|
| `0` | Success — JSON written to stdout | *(silent)* |
| `1` | IO failure reading `--path` (file missing, permission denied, etc.) | `session-summary: cannot read transcript at '<path>': <OSError class>: <message>` |
| `2` | File readable but contains no external user turns | `session-summary: transcript '<path>' contains no user turns` |
| `3` | File has content but none of it parses as JSONL | `session-summary: transcript '<path>' is not valid JSONL` |

On any non-zero exit, stdout is empty and stderr contains exactly one line.

### `config` — inspect configuration

```bash
python -m claude_prospector config --show
```

Prints current `config.json` contents, or `{}` when no config file exists. See [Configuration](#configuration) for full details.

## Migration

### v0.6.0 → v0.7.0 (Pattern W)

After upgrading to v0.7.0, open a new Claude Code session. A banner will prompt you to run `/setup-prospector`. This is a one-time action per machine.

If you previously installed `claude-prospector` into `~/.claude/.venv`, you can leave that install in place — Pattern W hooks always use the plugin-owned venv via an absolute path. To reclaim disk space you may `uv pip uninstall claude-prospector` from `~/.claude/.venv` after setup; this is optional.

### Pre-v0.2.0 CLI callers

The bare flag form **no longer works** after v0.2.0:

```bash
# REMOVED — will print help and exit 0, not run the dashboard
claude-prospector --format json

# CORRECT
claude-prospector dashboard --format json
```

Any script, skill, or CI step that invokes `claude-prospector` with bare flags (no subcommand) must be updated to use `claude-prospector dashboard [flags]`.

### Upgrading from v0.4.x (autoregen config)

If you previously ran `python -m claude_prospector config --enable-autoregen`, your old `config.json` is still readable via `--show`. Re-toggle via `/plugin reconfigure claude-prospector` to move to the managed setting. The old `config.json` file is not deleted.

## Internals

### Nested agent attribution

When Claude Code sessions dispatch sub-agents that themselves dispatch further sub-agents, `claude-prospector` traces the full depth and attributes tokens to the complete root-to-leaf chain rather than just the immediate leaf.

- **Data model.** Each `MessageRecord` carries an `agent_path: tuple[str, ...]` field (e.g. `("general-purpose", "project-planner", "Explore")`) and a parallel `agent_type: str` stored field. Both are populated at parse time; the parser enforces the invariant `agent_type == agent_path[-1]` when `agent_path` is non-empty. The two fields are kept in sync by the parser, not by the dataclass itself.

- **`by_agent` keys.** The aggregator's `by_agent` dict is keyed by the full path joined with U+2192 (`→`), for example `"general-purpose→project-planner→Explore"`. Depth-1 sessions produce single-segment keys identical to the pre-change shape.

- **Per-session `agents` list.** Each session's `agents` list contains only the deepest-leaf path per chain. Sibling chains that share a leaf name but differ in their ancestor are both kept. This rule preserves the dashboard JS's per-agent token apportionment, which divides session totals by `s.agents.length`.

- **Depth limit.** Path tuples may contain up to 10 segments total (`_MAX_AGENT_PATH_LENGTH = 10`). Beyond that, the parser emits a single `UserWarning` and stops descending; deeper messages are bucketed under the last walked ancestor.

- **Sanitization.** A literal `→` appearing inside an agent name is replaced with `﹖` (U+FE56) at parse time and a `UserWarning` fires. The sanitized name is used throughout.

- **Deferred.** Dashboard tree visualization (sunburst, indented tree, expand/collapse) is out of scope for the current release. The existing flat agent list in the dashboard JS receives path-keyed entries but no hierarchical rendering yet.

### State storage

When running as a plugin, state (dashboard HTML, hook log, skill-tracking JSONL files) is stored under `${CLAUDE_PLUGIN_DATA}` — the Anthropic-documented persistent state location that survives plugin updates.

Users upgrading from v0.4.0 get a one-time automatic migration: on the first session after upgrade, any existing files from `~/.claude/claude-prospector/` are moved into `${CLAUDE_PLUGIN_DATA}` and the legacy directory is removed.

## Development

### Install for development

```bash
git clone https://github.com/glitchwerks/claude-prospector.git
cd claude-prospector
uv pip install -e ".[dev]"   # installs runtime + ruff + pytest
```

Requires Python 3.10+.

### Testing

```bash
pytest   # 358 tests, typically finishes in under 5 seconds
```

### Linting and formatting

```bash
ruff check .          # lint
ruff format .         # autoformat in-place
ruff format --check . # format gate (used in CI — exits non-zero on drift)
```

### CI

GitHub Actions runs on every PR and push to `main`:

- **lint** (Ubuntu): `ruff check .` + `ruff format --check .`
- **test** (Ubuntu + Windows, Python 3.10): `pytest`

Both jobs must be green before a PR can merge.

### Future enhancements

Issue #67 tracks making `claude plugin update` handle the Python venv refresh automatically, so that `/setup-prospector` would not need to be run manually after updates. Until that lands, re-run `/setup-prospector` after each plugin update when prompted by the SessionStart banner.

## License

MIT — see [LICENSE](LICENSE).
