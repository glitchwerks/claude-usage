---
name: usage-analysis
description: >
  Analyzes Claude Code token usage and provides optimization recommendations.
  Trigger phrases: "am I close to my limit", "how much Sonnet am I using",
  "token budget", "where are my tokens going", "what's eating my budget",
  "which agent uses the most".
---

## Prerequisites

This skill invokes `python -m claude_prospector` under the hood. The Python package must be installed in the environment Claude Code uses. See the [README install steps](https://github.com/glitchwerks/claude-prospector#install-as-a-claude-code-plugin) for the two-step install.

# Usage Analysis Skill

You are analyzing the user's Claude Code token usage to help them understand and optimize their
spend across the three billing buckets (5h rolling, 7d rolling, Sonnet-only 7d).

## How the Tool Works

`claude-prospector` reads JSONL session files from `~/.claude/projects/` and generates an
**interactive HTML dashboard**. It does not write structured data to stdout — all output is HTML.

The tool is installed as the `claude_prospector` package. Invoke it as:

```
python -m claude_prospector
```

The dashboard is automatically regenerated after every session via the Stop hook and written to:

- POSIX: `$HOME/.claude/claude-prospector/dashboard.html`
- Windows: `%USERPROFILE%\.claude\claude-prospector\dashboard.html`

## Regenerating the Dashboard

Use these commands to regenerate the dashboard with a specific time window. Always pass
`--output` and `--no-open` so the file lands at the known path without opening a browser tab.

| Question                                 | Command                                                                                                                                                                                                               |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full history (default)                   | `python -m claude_prospector dashboard --output $HOME/.claude/claude-prospector/dashboard.html --no-open` (POSIX) / `python -m claude_prospector dashboard --output %USERPROFILE%\.claude\claude-prospector\dashboard.html --no-open` (Windows) |
| Last 7 days                              | `python -m claude_prospector dashboard --window 7d --output $HOME/.claude/claude-prospector/dashboard.html --no-open`                                                                                                              |
| Last 5 hours (matches 5h billing bucket) | `python -m claude_prospector dashboard --window 5h --output $HOME/.claude/claude-prospector/dashboard.html --no-open`                                                                                                              |
| Specific date range                      | `python -m claude_prospector dashboard --from 2026-04-01 --to 2026-04-30 --output $HOME/.claude/claude-prospector/dashboard.html --no-open`                                                                                        |
| With budget gauges                       | `python -m claude_prospector dashboard --window 7d --limit-5h 600000 --limit-7d 4000000 --limit-sonnet-7d 2000000 --output $HOME/.claude/claude-prospector/dashboard.html --no-open`                                               |

On Windows, substitute `%USERPROFILE%\.claude\claude-prospector\dashboard.html` for `$HOME/.claude/claude-prospector/dashboard.html` in all commands above.

All commands exit 0 and print a confirmation line to stdout:
`Dashboard written to <path>`

> **Tip:** for programmatic analysis, append `--format json` and the tool writes the full
> structured payload (the same `DATA` object embedded in the HTML) to stdout instead of
> rendering HTML. The progress lines ("Scanning sessions…", "Found N sessions.") still go to
> stderr, so redirect with `--format json --no-open > snapshot.json 2>/dev/null` to get clean
> JSON. Useful for `jq`-style summaries or feeding into Python.

## Reading Data from the Dashboard

After regenerating, use the `Read` tool to load the HTML file. The dashboard embeds all data
as a JavaScript constant (`const DATA = {`) near the top of the `<script>` block at around
line 179. Read the file starting at that line to extract the payload:

```powershell
# Windows PowerShell
Get-Content "$env:USERPROFILE\.claude\claude-prospector\dashboard.html" |
  Select-Object -Skip 178 -First 50
```

```bash
# POSIX
sed -n '179,228p' "$HOME/.claude/claude-prospector/dashboard.html"
```

The `const DATA` object contains all the fields described in the analysis sections below.

### Dashboard Sections to Scan

When you read the HTML, look for these embedded data keys (all present in the `const DATA`
object starting at line 179):

- `total_tokens` / `total_messages` / `total_sessions` — top-level summary
- `by_model` — token counts keyed by model name (`opus`, `sonnet`, `haiku`)
- `by_agent` — token counts keyed by agent name with `primary_model`
- `by_skill` — invocation counts per skill name
- `by_project` — tokens per project name
- `by_day` — daily token breakdown with per-model split
- `sessions` — individual session records with agents, tokens, and model split

## Skill Adoption Data

Skill invocation events are logged to a separate file that is machine-readable:

- POSIX: `$HOME/.claude/claude-prospector/skill-tracking/<YYYY-MM-DD>.jsonl` (per-day rotation)
- Windows: `%USERPROFILE%\.claude\claude-prospector\skill-tracking\<YYYY-MM-DD>.jsonl`

Each day's events land in a new file; the reader walks the directory in date order. Older files outside the 90-day retention window are skipped.

Each line is a JSON object:

```json
{"event": "skill_invoked", "skill": "superpowers:brainstorming", "timestamp": "...", "session_id": "..."}
{"event": "skill_passed", "skill": "python", "timestamp": "...", "session_id": "..."}
```

Use the `Read` tool on this file directly to count invocations, find most-used skills, or
detect skills that are passed (present in conversation) but never invoked.

## Analysis Framework

When interpreting the data, focus on these areas:

### 1. Budget Status

The user has three billing buckets. Regenerate for each window and read the summary line
from stdout, or check the gauge values in the HTML:

- **5h rolling**: Regenerate with `--window 5h`. High usage means the user is in an
  intensive session.
- **7d rolling**: Regenerate with `--window 7d`. This is the primary limit to watch.
- **Sonnet-only 7d**: From the 7d dashboard, read `by_model.sonnet.total_tokens`. This is
  often the tightest of the three buckets — if the user is approaching this limit, look
  at which agents drive Sonnet usage (`by_agent` filtered to `primary_model == "sonnet"`)
  for the largest levers.

### 2. Model Distribution

Check `by_model` for balance across Opus/Sonnet/Haiku. Different harnesses assign
agents to models differently — there is no universal "correct" mapping. What to look
for instead:

- Cross-reference `by_model` with `by_agent.<name>.primary_model` to see whether each
  agent is running on the model the user *intended* for that role. Drift here is a
  common cost source (an agent that should be on Haiku but is actually defaulting to
  Sonnet, for example).
- If one model dominates disproportionately for the user's stated workflow, that's a
  signal to investigate — not a fixed prescription. Surface the imbalance and ask
  which agents the user expected to be on which model.

### 3. Agent Efficiency

Check `by_agent` for outliers:

- Which agent consumes the most tokens? Is that expected given its role?
- Are Haiku agents (ops, code-reviewer) actually running on Haiku?
  Check `primary_model` for each.
- Is the router (general-purpose) consuming too much? It should mostly route, not do
  heavy work itself.

### 4. Skill Cost

Check `by_skill` for expensive skills and cross-reference with the per-day `skill-tracking/<YYYY-MM-DD>.jsonl` files:

- Brainstorming is expected to be expensive (long back-and-forth)
- Subagent-driven-development dispatches many subagents — check if reviews add
  significant overhead
- Skills with high invocation counts but low tokens are healthy (quick, efficient)
- Skills appearing in `skill_passed` events but rarely in `skill_invoked` events may
  not be triggering correctly

### 5. Project Distribution

Check `by_project` if the user works across multiple projects. Some projects may be
token-heavy due to large codebases or complex work.

### 6. Session Outliers

Check `sessions` for anomalies:

- Any single session consuming >10% of the 7d budget?
- Sessions with many agents spawned (complex orchestration)?
- Very long sessions (>2h) that could have been split?

## Recommendations Format

Present findings as:

1. **Budget status** — where they stand on each bucket (use percentages if limits are
   known)
2. **Top consumers** — the 2-3 agents/skills/projects eating the most budget
3. **Actionable recommendations** — specific, concrete changes. Examples:
   - "code-writer is using 40% of your Sonnet budget. Most of it is large greenfield features — consider whether some of that work could be split into smaller plan-file-driven tasks dispatched in parallel."
   - "Agent `<X>` is running on Opus but its role is mostly read-only lookups; check whether your harness allows downgrading it to Haiku for those calls."
   - "Project X consumed 60% of your 7d budget. Consider pausing other work until the
     rolling window resets."
4. **Trend** — if daily data shows increasing/decreasing usage, note it

Keep recommendations specific to what the data shows. Do not speculate about things
not in the data.

---

## Triggers we deliberately do not claim

The following phrases were present in the original private skill but are excluded here because
they are too generic for a public marketplace skill and would cause false-positive activations
in unrelated contexts:

| Phrase                 | Why excluded                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| `show usage`           | Matches any CLI tool or dashboard; not specific to Claude Code token accounting.                 |
| `show my token usage`  | Broad — applies to any LLM or API context, not specifically Claude Code billing buckets.         |
| `check my usage`       | Ambiguous — could refer to disk usage, API rate limits, quota on any service.                    |
| `how much am I using`  | No Claude-specific signal; triggers on resource questions of all kinds.                          |
| `how much have I used` | Same problem as above; past-tense variant with no additional specificity.                        |
| `usage breakdown`      | Common analytics phrase; would steal traffic from project-specific dashboard or reporting tools. |
| `usage report`         | Same as above; too broad for a specialised skill.                                                |
| `optimize my usage`    | Could apply to any resource optimization context — storage, bandwidth, API calls, etc.           |

Do not re-add these phrases to the `description:` frontmatter. If a user types one of these
and the context makes it clear they mean Claude Code token usage, the skill body's language
about billing buckets and `claude_prospector` will guide the response correctly once
activated by a sharper trigger phrase.
