# claude-prospector

Token usage analyzer for Claude Code that surfaces where your budget is going across all three billing windows, with per-model and per-agent attribution and concrete optimization recommendations.

## Why

Claude Code tracks three billing buckets (5h rolling, 7d rolling, Sonnet-only 7d) but provides no per-agent or per-skill visibility. This tool reads Claude Code's local JSONL session files and generates a dashboard that breaks down where your tokens are going.

## Install as a Claude Code plugin

The easiest way to use `claude-prospector` is as a Claude Code plugin — no manual
cloning or path configuration required.

```bash
claude plugin marketplace add glitchwerks/plugins
claude plugin install claude-prospector@glitchwerks
```

### Prerequisite: Python package

The plugin invokes `python -m claude_prospector` under the hood, so the Python
package must be importable in the environment Claude Code uses. Install with either:

- **From a local clone**: `uv pip install -e .`
- **Directly from GitHub**: `uv pip install "git+https://github.com/glitchwerks/claude-prospector.git"`

> A future enhancement (#67) tracks eliminating this two-step install so `claude plugin update` is sufficient on its own.

## What the plugin provides

v0.4.0 ships the full plugin surface:

- **Interactive dashboard** — HTML report with three-bucket budget gauges (5h / 7d / Sonnet-7d), per-model donut and bar charts, per-agent token attribution with nested sub-agent tracing, skill-invocation counts, and per-project breakdowns.
- **`usage-analysis` skill** — conversational analysis with recommendations. Answers questions like "am I close to my Sonnet limit?", "where are my tokens going?", and "which agent uses the most?". Triggered by natural-language phrases.
- **`usage-dashboard` skill** — bare regeneration surface. Triggered by phrases like "regenerate the dashboard" or "rebuild my usage dashboard"; writes the HTML file and reports the path, without interpreting the data.
- **`skill-tracker` hook** (PreToolUse, always-on) — logs `Skill` tool-use events to `~/.claude/claude-prospector/skill-tracking/<YYYY-MM-DD>.jsonl` for the `by_skill` and skill-passed-vs-invoked analyses.
- **`dashboard-regen` hook** (Stop, opt-in) — auto-regenerates the dashboard after every session when enabled via `python -m claude_prospector config --enable-autoregen`.

## Development / Standalone CLI

For working on the package directly, or running it without the Claude Code plugin.

### Install for development

```bash
git clone https://github.com/cbeaulieu-gt/claude-prospector.git
cd claude-prospector
uv pip install -e ".[dev]"   # installs runtime + ruff + pytest
```

Requires Python 3.10+.

### Run the CLI directly

```bash
# Default: last 7 days, opens in browser
python -m claude_prospector

# Rolling window matching billing buckets
python -m claude_prospector --window 5h
python -m claude_prospector --window 7d

# Custom date range
python -m claude_prospector --from 2026-04-01 --to 2026-04-09

# Output to file instead of opening browser
python -m claude_prospector --output report.html --no-open

# Custom Claude data directory
python -m claude_prospector --data-dir "D:\other\.claude"

# Set budget limits for gauge percentages
python -m claude_prospector --limit-5h 600000 --limit-7d 4000000 --limit-sonnet-7d 2000000
```

### Subcommands

All functionality is accessed through named subcommands. Bare `claude-prospector` prints help and exits 0.

#### `dashboard` — interactive HTML dashboard

```bash
# Default: last 7 days, opens in browser
claude-prospector dashboard

# Rolling window matching Claude billing buckets
claude-prospector dashboard --window 5h
claude-prospector dashboard --window 7d

# Custom date range
claude-prospector dashboard --from 2026-04-01 --to 2026-04-09

# Output to file instead of opening browser
claude-prospector dashboard --output report.html --no-open

# Custom Claude data directory
claude-prospector dashboard --data-dir "D:\other\.claude"

# Set budget limits for gauge percentages
claude-prospector dashboard --limit-5h 600000 --limit-7d 4000000 \
    --limit-sonnet-7d 2000000

# Emit JSON (for scripting / CI)
claude-prospector dashboard --format json
```

All flags are unchanged from the pre-refactor form — only their location
moved (now under the `dashboard` subparser).

#### `session-summary` — deterministic session recap (new in v0.2.0)

Reads a single Claude Code transcript JSONL file and emits a structured
JSON summary suitable for consumption by the `/whats-next` skill or any
other tool that needs to know what a session did.

```bash
claude-prospector session-summary --path ~/.claude/projects/<hash>/<session>.jsonl
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
| `2` | File readable but contains no external user turns (empty session, zero-byte file, whitespace-only file) | `session-summary: transcript '<path>' contains no user turns` |
| `3` | File has content but none of it parses as JSONL | `session-summary: transcript '<path>' is not valid JSONL` |

On any non-zero exit, stdout is empty and stderr contains exactly one line.

#### Migration note

The old flag-only form **no longer works** after v0.2.0:

```bash
# REMOVED — will print help and exit 0, not run the dashboard
claude-prospector --format json

# CORRECT — migrate all callers to:
claude-prospector dashboard --format json
```

Any script, skill, or CI step that invokes `claude-prospector` with bare flags
(no subcommand) must be updated to use `claude-prospector dashboard [flags]`.

### Testing

```bash
pytest                # ~151 tests, typically finishes in under 5 seconds
```

### Linting & formatting

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

## Nested agent attribution

When Claude Code sessions dispatch sub-agents that themselves dispatch further
sub-agents, `claude-prospector` traces the full depth and attributes tokens to the
complete root-to-leaf chain rather than just the immediate leaf.

- **Data model.** Each `MessageRecord` carries an `agent_path: tuple[str, ...]`
  field (e.g. `("general-purpose", "project-planner", "Explore")`) and a
  parallel `agent_type: str` stored field. Both are populated together at parse
  time; the parser enforces the invariant `agent_type == agent_path[-1]` (when
  `agent_path` is non-empty). `agent_type` is not a computed property — it is a
  plain dataclass field, so consumers that construct `MessageRecord` with an
  explicit `agent_type=` argument continue to work without change. The two
  fields are kept in sync by the parser, not by the dataclass itself.

- **`by_agent` keys.** The aggregator's `by_agent` dict is keyed by the full
  path joined with U+2192 (`→`), for example
  `"general-purpose→project-planner→Explore"`. Depth-1 sessions produce
  single-segment keys identical to the pre-change shape, so existing
  integrations are unaffected.

- **Per-session `agents` list.** Each session's `agents` list contains only
  the deepest-leaf path per chain (e.g. a depth-3 chain
  `general-purpose → project-planner → Explore` contributes one entry,
  `"general-purpose→project-planner→Explore"`). Sibling chains that share a
  leaf name but differ in their ancestor are both kept — neither is a prefix
  of the other. This rule preserves the dashboard JS's per-agent token
  apportionment, which divides session totals by `s.agents.length`.

- **Depth limit.** Path tuples may contain up to **10 segments** total —
  the root agent plus up to 9 levels of nested sub-agents
  (`_MAX_AGENT_PATH_LENGTH = 10`). Beyond that, the parser emits a single
  `UserWarning` and stops descending; deeper messages are bucketed under the
  last walked ancestor. The warning fires at most once per session parse (not
  once per overflowing message), as do the cycle and OSError warnings below.
  On Windows, junction-based cycles are caught by this same cap rather than
  by the POSIX visited-set short-circuit.

- **Sanitization.** A literal `→` appearing inside an agent name is replaced
  with `﹖` (U+FE56) at parse time and a `UserWarning` fires. The sanitized
  name is used throughout (parse, aggregation, dashboard key) so attribution
  data is preserved even when the invariant is violated.

- **Deferred.** Dashboard tree visualization (sunburst, indented tree,
  expand/collapse) is out of scope for this release. The existing flat agent
  list in the dashboard JS receives path-keyed entries but no hierarchical
  rendering yet.

## Dashboard

The generated HTML dashboard includes:

- **Budget gauges** - estimated usage against each billing bucket (5h, 7d, Sonnet-only 7d)
- **Model breakdown** - donut chart and daily stacked bar chart (Opus/Sonnet/Haiku)
- **Agent breakdown** - token usage per agent with model attribution
- **Skill usage** - invocation counts per skill
- **Project breakdown** - tokens per project
- **Session drill-down** - click a day to see individual sessions with agents, tokens, and model split

## How It Works

Reads JSONL session files from `~/.claude/projects/`. Each session file contains timestamped assistant messages with model name and token usage. Subagent metadata (`.meta.json`) maps child agent tokens to their agent type. Skill invocations are extracted from `Skill` tool-use entries.
