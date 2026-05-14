# Claude Code Usage Dashboard — Design Spec

**Date**: 2026-04-09
**Status**: Draft
**Goal**: Build a Python CLI tool that parses Claude Code's local session data and generates a self-contained HTML dashboard showing token consumption by model, agent, skill, project, and time period.

---

## Problem

Claude Code has three billing buckets (5h rolling, 7d rolling, Sonnet-only 7d) but no per-agent or per-skill usage visibility. The built-in `stats-cache.json` tracks daily model totals but doesn't attribute tokens to individual agents or skills. Without this breakdown, optimizing token spend across models requires guesswork.

## Solution

A Python package (`claude-usage`) that reads Claude Code's local JSONL session files, aggregates token usage across multiple dimensions, and renders an interactive HTML dashboard with Chart.js. Run on-demand via CLI; future hook integration for automatic refresh.

---

## Data Sources

All data is read from the local filesystem under `~/.claude/`.

### Session JSONL Files

**Location:** `~/.claude/projects/<project-hash>/<session-id>.jsonl`

Each line is a JSON object. Key entry types:

- **Agent setting** (line 0): `{"type":"agent-setting","agentSetting":"general-purpose"}` — identifies the root agent for the session.
- **Assistant messages**: Contains `message.model` (e.g., `"claude-opus-4-6"`) and `message.usage` with:
  - `input_tokens`
  - `output_tokens`
  - `cache_read_input_tokens`
  - `cache_creation_input_tokens`
- **Tool use entries**: `name` field identifies the tool. When `name` is `"Skill"`, `input.skill` contains the skill name (e.g., `"superpowers:brainstorming"`).

### Subagent Metadata

**Location:** `~/.claude/projects/<project-hash>/<session-id>/subagents/agent-<id>.meta.json`

Contains `{"agentType":"code-writer","description":"..."}`. Links a subagent's JSONL file to its agent type.

### Subagent JSONL Files

**Location:** `~/.claude/projects/<project-hash>/<session-id>/subagents/agent-<id>.jsonl`

Same format as session JSONL. Token usage per message is attributed to the agent type from the corresponding `.meta.json`.

### stats-cache.json

**Location:** `~/.claude/stats-cache.json`

Contains `dailyModelTokens` and `modelUsage` aggregates. Useful as a cross-reference for total model usage but lacks agent/skill attribution. Not the primary data source.

### Project Identification

The project hash directory name (e.g., `C--Users-chris--claude`) encodes the working directory path. The parser decodes this to produce a human-readable project name (e.g., `claude_personal_configs`).

---

## Architecture

### Package Structure

```
claude-usage/
  claude_usage/
    __init__.py
    __main__.py        # CLI entry point (python -m claude_usage)
    parser.py          # JSONL + meta.json reading
    aggregator.py      # Grouping, filtering, rolling windows
    renderer.py        # HTML + Chart.js generation
    models.py          # Data classes (Session, Message, AgentUsage, etc.)
  templates/
    dashboard.html     # Jinja2 template with Chart.js
  pyproject.toml       # Package config, dependencies
  README.md
```

### Module Responsibilities

**`models.py`** — Data classes representing parsed data.

#### MessageRecord

A single assistant message attributed to a specific agent in the invocation tree.
Each record carries the full root-to-leaf path of the agent that produced it, plus
independent token-count fields for the four billing buckets Claude Code tracks.

**Fields:**

- `timestamp: datetime` — when the assistant message was produced.
- `model: str` — full model ID string (e.g. `"claude-opus-4-6"`).
- `agent_type: str` — leaf agent name (e.g. `"general-purpose"`). Stored as a plain
  field; not derived from `agent_path`. See the invariant below.
- `agent_path: tuple[str, ...]` — full ancestry tuple from root to leaf (e.g.
  `("general-purpose", "project-planner", "Explore")`). Defaults to the empty
  tuple for records that pre-date nested attribution.
- `skill: str | None` — skill name invoked in this message, or `None`.
- `input_tokens: int` — prompt token count.
- `output_tokens: int` — completion token count.
- `cache_read_tokens: int` — tokens served from the prompt cache.
- `cache_creation_tokens: int` — tokens written to the prompt cache.
- `total_tokens` (property) — sum of all four token fields.

**Invariants:**

- `agent_type == agent_path[-1]` when `agent_path` is non-empty. The dataclass does
  not enforce this automatically; it is the parser's responsibility at construction
  time (`claude_usage/parser.py`, `_parse_jsonl_messages` and
  `_parse_subagents_recursive`).
- `agent_path` segments are sanitized: no segment may contain the path separator
  U+2192 `→`. See Sanitization below.

**Aggregation contract:**

The aggregator (`claude_usage/aggregator.py`) keys `by_agent` on the full path string
`AGENT_PATH_SEPARATOR.join(agent_path)`, e.g. `"general-purpose→project-planner→Explore"`.
Keys are created only for paths with direct messages — there are no implicit
intermediate keys. A path `"general-purpose→project-planner"` does not appear in
`by_agent` unless the `project-planner` agent itself produced messages (not just its
descendants). The per-session `agents` list (used by the dashboard JS for token
apportionment) contains only the deepest-leaf path per chain: a path key `k` is
included only when no other key in the same session starts with
`k + AGENT_PATH_SEPARATOR`. Sibling chains that share a leaf name but differ in
their ancestors are both kept, as neither is a prefix of the other.

**Sanitization:**

The path separator `→` (U+2192 RIGHTWARDS ARROW, defined as `AGENT_PATH_SEPARATOR`
in `claude_usage/constants.py`) must not appear inside any `agent_path` segment.
If an agent name read from a `.meta.json` file contains this character,
`_sanitize_agent_name` in `claude_usage/parser.py` replaces it with `﹖`
(U+FE56 SMALL QUESTION MARK, defined as `SANITIZED_SEPARATOR_REPLACEMENT`) and
emits a `UserWarning`. The sanitized name is used throughout parse, aggregation,
and the dashboard key.

**Defenses:**

- **Depth cap** — `_MAX_AGENT_PATH_LENGTH = 10` in `claude_usage/parser.py`. When
  `len(parent_path) >= 10`, the recursive walk stops and a `UserWarning` is emitted.
  Maximum path length is 10 segments (root agent + up to 9 nested sub-agent levels).
- **Cycle detection** — a `visited: set[Path]` accumulator short-circuits
  symlink/junction cycles by comparing resolved real paths. On Windows, junctions
  may not resolve correctly; the depth cap provides a second-line defense.
- **OSError on resolve()** — broken symlinks and revoked permissions raise `OSError`
  on `Path.resolve()`; the parser catches this, emits a warning, and skips the
  affected branch.

All three warnings are de-duplicated per `_parse_session` call: each fires at most
once regardless of how many times the condition is hit within a single session.

**Examples:**

```python
# Depth-1 (root only — equivalent to the pre-PR42 flat model)
MessageRecord(agent_type="general-purpose", agent_path=("general-purpose",), ...)

# Depth-2 (one sub-agent)
MessageRecord(agent_type="project-planner", agent_path=("general-purpose", "project-planner"), ...)

# Depth-3 (two levels of sub-agent)
MessageRecord(agent_type="Explore", agent_path=("general-purpose", "project-planner", "Explore"), ...)
```

**`SessionRecord`** — session_id, project, start_time, root_agent, messages (list of
MessageRecord), subagents (list of agent types). Total tokens computed as sum of all
four token fields across all messages.

**`parser.py`** — Reads the filesystem and produces `SessionRecord` objects:
- Walks `~/.claude/projects/` to find session JSONL files
- Parses each JSONL line, extracts agent-setting, assistant message usage, and skill tool_use entries
- Reads subagent `.meta.json` to map subagent IDs to agent types
- Reads subagent JSONL to attribute their token usage to the correct agent type
- Decodes project hash directory names to human-readable project names
- Returns a list of `SessionRecord` objects

**`aggregator.py`** — Groups and filters parsed data:
- Group by: model, agent, skill, project, time period (day/week/custom range)
- Cross-dimensional queries: e.g., "Sonnet tokens by agent over last 7 days"
- Rolling window support: filter to "last 5 hours" or "last 7 days" to approximate billing bucket usage
- Metrics per group: input tokens, output tokens, cache tokens, total tokens, message count, session count, percentage of total

**`renderer.py`** — Generates the HTML dashboard:
- Loads the Jinja2 template from `templates/dashboard.html`
- Serializes aggregated data as JSON embedded in the HTML
- Chart.js loaded from CDN — no local JS dependencies
- Outputs a single self-contained `.html` file
- Optionally opens the file in the default browser

**`__main__.py`** — CLI entry point:
- Parses arguments (date range, rolling window, output path, data directory)
- Orchestrates: parse → aggregate → render → open

### Dependencies

- `jinja2` — HTML templating
- No pandas, numpy, or heavy data libraries. Aggregation is straightforward dict/list operations.

---

## Dashboard Layout

### Top Bar — Budget Gauges

Three horizontal progress bars estimating usage against each billing bucket:
- **5-Hour Rolling** — tokens consumed in the last 5 hours
- **7-Day Rolling** — tokens consumed in the last 7 days
- **Sonnet-Only 7-Day** — Sonnet model tokens consumed in the last 7 days

Color-coded: green (<60%), yellow (60-80%), red (>80%). The gauge denominators (bucket limits) are not available programmatically from Claude Code. The CLI accepts `--limit-5h`, `--limit-7d`, and `--limit-sonnet-7d` flags to set the denominators manually. If not provided, the gauges display raw token counts without percentages. These are estimates based on local token counts — Claude's actual billing may differ slightly but provides a directional signal.

### Row 1 — Model Breakdown

- **Donut chart**: token distribution across Opus / Sonnet / Haiku
- **Stacked bar chart**: daily token consumption by model over the selected time range

### Row 2 — Agent Breakdown

- **Horizontal bar chart**: total tokens per agent, color-coded by model
- **Details table**: agent name, model, total tokens, % of total, session count

### Row 3 — Skill & Project Breakdown

- **Skill bar chart**: invocation count per skill (only skills that were actually invoked)
- **Project bar chart**: total tokens per project

### Session Drill-Down

- Clicking a day in the daily chart filters to show individual sessions for that day
- Each session row shows: start time, project, agents involved (as tags), total tokens, model split (mini stacked bar), duration

### Interactivity

- **Date range picker**: defaults to last 7 days; options for last 5 hours, last 30 days, custom range
- **Metric toggle**: switch between token count, message count, or session count
- All charts update client-side when filters change — full dataset embedded as JSON in the HTML

### Visual Design

- Dark theme (GitHub-dark inspired: `#0d1117` background, `#161b22` cards)
- Model colors: Opus = purple (`#8b5cf6`), Sonnet = green (`#2ea043`), Haiku = blue (`#58a6ff`)
- Project names in orange (`#ffa657`) in session drill-down
- Agent tags as small gray badges
- Mockup reference: `C:\Users\chris\AppData\Local\Temp\claude-mockups\dashboard-mockup.html`

---

## CLI Interface

```powershell
# Default: last 7 days, opens in browser
python -m claude_usage

# Custom date range
python -m claude_usage --from 2026-04-01 --to 2026-04-09

# Rolling window view (matches billing buckets)
python -m claude_usage --window 5h
python -m claude_usage --window 7d

# Output to file instead of opening browser
python -m claude_usage --output report.html

# Point at a non-default Claude data directory
python -m claude_usage --data-dir "D:\other\.claude"

# Set bucket limits for gauge percentages (tokens)
python -m claude_usage --limit-5h 600000 --limit-7d 4000000 --limit-sonnet-7d 2000000
```

**Default behavior:** Parse all sessions within the selected time range, aggregate, render to a temp HTML file, and open it in the default browser.

---

## Separate Repository

This tool lives in its own repository (`claude-usage`), not inside `~/.claude/`. It reads from `~/.claude/` but has its own dependencies and lifecycle.

---

## Future Extensions (Not in v1)

- **Stop hook integration**: A Claude Code `Stop` hook that runs `python -m claude_usage --output latest.html` after each session, keeping the dashboard fresh without manual runs.
- **CSV/JSON export**: `--format csv` or `--format json` for programmatic consumption.
- **Cost estimation**: Map token counts to approximate dollar costs using published pricing.
- **Trend alerts**: Highlight when a specific agent or model is consuming significantly more than its rolling average.

---

## Trade-offs

| Trade-off | Accepted because |
|---|---|
| Token counts are estimates, not exact billing data | Local JSONL is the only source available; directional accuracy is sufficient for optimization decisions |
| Chart.js loaded from CDN (requires internet) | Avoids bundling JS; dashboard is a reporting tool, not an offline-critical app |
| Full dataset embedded in HTML (large files for heavy users) | Keeps the tool zero-server; gzip/filtering mitigates size for most users |
| No real-time updates (must re-run CLI) | v1 scope; hook integration planned for future |
| Jinja2 is the only dependency | Minimal footprint; HTML templating is the one thing that genuinely benefits from a library |

---

## Implementation Scope

1. Create new repository `claude-usage`
2. Implement `models.py` — data classes
3. Implement `parser.py` — JSONL reading and project hash decoding
4. Implement `aggregator.py` — grouping, filtering, rolling windows
5. Implement `renderer.py` — Jinja2 + Chart.js HTML generation
6. Create `templates/dashboard.html` — Jinja2 template matching the approved mockup
7. Implement `__main__.py` — CLI argument parsing and orchestration
8. Add `pyproject.toml` with dependencies and entry point
9. Write tests for parser and aggregator
10. Write README with usage instructions
