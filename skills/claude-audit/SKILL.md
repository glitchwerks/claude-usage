---
name: claude-audit
description: >
  Audit a project's effective Claude Code configuration — custom and plugin-provided agents and
  skills — and produce a structured overlap/conflict report with keep / modify / drop
  recommendations scoped to the project's stated objectives. Trigger this skill whenever the
  user types `/claude-audit`, asks to "audit my claude config", "find overlap in my agents",
  "check for skill conflicts", "are any of my agents duplicates", "what's redundant in my
  setup", or any similar request to review the agent/skill surface for the current project.
  Also trigger after a fresh plugin install when the user wants to verify nothing new collides
  with what's already there.
context-switch: false
---

# Claude Audit Skill

Produce a deterministic overlap/conflict report for the project's effective Claude Code
configuration. The audit considers user-scope (`~/.claude/`), project-scope
(`<project>/.claude/`), and plugin-provided sources together — because that is what the agent
actually loads at runtime.

The output is a single markdown report. The skill itself does **not** modify any files. All
recommendations are presented to the user; they decide what to change.

---

## Step 1: Discover the project objective

Before evaluating overlaps, read the project's `CLAUDE.md` (and any `README.md`) at the repo
root to understand what the project does. Specific things to extract:

- **Domain** — web app, infra, mobile, ML, mod development, etc.
- **Languages / frameworks** — informs which language skills are relevant
- **Workflows codified in CLAUDE.md** — issue tracking, PR conventions, branching, testing

Recommendations later are scoped to these. A `python` skill is not "redundant" just because
the project also uses TypeScript — it might still be load-bearing for tooling scripts.

If no project-level `CLAUDE.md` exists, fall back to the user-level `~/.claude/CLAUDE.md` and
note that the audit is using the user-scope objective only.

---

## Step 2: Inventory all sources

Enumerate every agent and skill that could be loaded:

### User-scope custom

```bash
ls ~/.claude/agents/*.md            # custom agents
ls ~/.claude/skills/*/SKILL.md      # custom skills
```

### Project-scope custom

```bash
ls <project>/.claude/agents/*.md    # if the dir exists
ls <project>/.claude/skills/*/SKILL.md
```

### Plugin-provided

1. Read `~/.claude/plugins/installed_plugins.json` to find the install path of every active
   plugin.
2. For each plugin's install path, list:
   - `<install-path>/agents/*.md`
   - `<install-path>/skills/*/SKILL.md`

### Other plugin-managed sources

If the user is on Windows running Claude Desktop, also check:

```
~/AppData/Roaming/Claude/local-agent-mode-sessions/skills-plugin/**/skills/*/SKILL.md
```

Skills loaded from there appear in the system reminder as `<plugin>:<skill>` and are real
sources of overlap (e.g. `anthropic-skills:git` lives here).

For each item discovered, parse the YAML frontmatter and capture:

- `name`
- `description` (collapse whitespace)
- `tools` (if agent)
- Source path
- Source kind (custom-user / custom-project / plugin:`<plugin>`)

---

## Step 3: Detect direct name collisions

Group all discovered items by `name`. Any group with more than one entry is a **direct
collision**.

For each collision, also capture:

- Which sources own each entry
- Whether the descriptions diverge or are near-identical (cheap signal: are they the same on
  the first 100 chars after lowercasing and collapsing whitespace?)
- Whether the `tools` lists differ (for agents)

Direct collisions are the most actionable finding — Claude Code namespaces them, but they
still pollute the agent picker and confuse routing.

---

## Step 4: Detect semantic overlaps

For pairs of items with **different** names, compute a description similarity score. A simple
bigram-Jaccard works well:

1. Lowercase and tokenize description into bigrams of words
2. Jaccard similarity = `|A ∩ B| / |A ∪ B|`
3. Flag any pair with similarity ≥ 0.5

Pairs scoring ≥ 0.5 should be inspected manually — they may be:

- True duplicates with different names (drop one)
- Overlapping triggers that compete (clarify trigger conditions)
- Different concerns that happen to share vocabulary (false positive — ignore)

Constrain the comparison to within a category (agent-vs-agent, skill-vs-skill) — not across
— to keep noise down.

---

## Step 5: Detect tool-coupling mismatches

For each agent, parse its `tools:` list. For each skill that names a tool in its body (e.g.
"use `mcp__plugin_github_github__list_pull_requests`"), record the dependency.

Then check: for any (agent, skill) pair where the skill is plausibly passed to the agent (by
the router's routing rules), does the agent have the tools the skill needs?

Common failure modes to flag:

- Skill uses `mcp__plugin_github_github__*` but the agent's `tools:` only has `Bash` (no
  GitHub MCP)
- Skill uses `PowerShell` but the agent only has `Bash`
- Skill uses `mcp__plugin_context7_context7__*` but the agent doesn't include Context7

This is heuristic — the skill might guard with "use this tool if available." Surface as a
warning, not an error.

---

## Step 6: Render the report

Produce a single markdown document with these sections, in order:

```markdown
# Claude Config Audit — <project name or "user-scope only">

## Project objective

<one paragraph paraphrased from the project CLAUDE.md, or "User-scope audit — no project CLAUDE.md found.">

## Inventory

- **Custom agents**: N (`name1`, `name2`, ...)
- **Custom skills**: N (`name1`, ...)
- **Plugin agents**: N from M plugins
- **Plugin skills**: N from M plugins
- **Effective total exposed to runtime**: N agents, M skills

## Direct name collisions

| Name            | Sources                          | Descriptions diverge? | Tools diverge? | Recommendation                       |
| --------------- | -------------------------------- | --------------------- | -------------- | ------------------------------------ |
| `code-reviewer` | custom, superpowers, feature-dev | No (near-identical)   | Yes            | Keep custom; disable plugin variants |

## Semantic overlaps

| Pair                                     | Jaccard | Verdict                                       | Recommendation                                   |
| ---------------------------------------- | ------- | --------------------------------------------- | ------------------------------------------------ |
| `git` (custom) ↔ `anthropic-skills:git` | 0.92    | True duplicate with project-specific addendum | Extract addendum to dedicated skill, drop custom |

## Tool-coupling concerns

| Agent         | Skill passed in | Missing tool                   | Recommendation                                                                  |
| ------------- | --------------- | ------------------------------ | ------------------------------------------------------------------------------- |
| `code-writer` | `powershell`    | `PowerShell` (only has `Bash`) | Translate guidance to POSIX in delegation, or pass to agent that has PowerShell |

## Recommendations summary

| Item                      | Action                | Priority | Rationale                   |
| ------------------------- | --------------------- | -------- | --------------------------- |
| Drop `feature-dev` plugin | uninstall via /plugin | high     | 3 overlap items in one move |

...
```

Order recommendations by **leverage** — a single action that resolves multiple overlaps
should rank above a single-item fix. Where the user has stated objectives in their CLAUDE.md,
mark recommendations that conflict with those objectives as "verify with user before
acting" rather than asserting them.

---

## Step 7: Offer follow-ups

After delivering the report, ask the user:

1. Whether to open GitHub Issues for each "drop" / "modify" recommendation (using the
   project's issue tracker per CLAUDE.md conventions)
2. Whether to create a Milestone grouping them, if there are 3+ recommendations
3. Whether to start on any specific recommendation now

Do **not** start making changes without explicit user confirmation. This skill is read-only
audit + recommendation; modifications are tracked separately.

---

## Reference

### Why "effective" config, not just custom?

A user might think "my config is fine, I only have 8 custom agents." But what loads at
runtime includes ~50 plugin skills and ~5 plugin agents. Overlaps appear at the boundary
between custom and plugin, and that boundary is invisible if you only audit one side.

### Why scope to project objective?

The same set of skills can be over-broad for one project and under-broad for another. A
`python` skill is essential in a Python repo and dead weight in a pure-Rust repo. The audit
should prefer keeping skills the project plausibly needs and dropping ones it does not —
which requires knowing what the project does.

### Related skills

- `superpowers:writing-skills` — for authoring new skills if the audit recommends extracting
  one
- `claude-md-management:claude-md-improver` — for the CLAUDE.md side of the same hygiene work
- `claude-prospector:usage-analysis` — for the cost-side view (which skills/agents are actually consumed)

## Long-Form Artifact Discipline

Audit reports are routinely 50–200 lines once every agent and skill is enumerated with a keep / modify / drop recommendation. Save the full report to `<repo>/.tmp/<YYYY-MM-DD>-claude-audit.md` and return a short chat reply listing:

1. **Inventory totals** — N agents and M skills audited (custom + plugin combined).
2. **Disposition counts** — keep / modify / drop tallies.
3. **Top 2-3 most consequential overlaps or conflicts** — typically direct name collisions or high-Jaccard semantic duplicates that resolve multiple items in one action.
4. **The file path** in backticks as the hand-off.

Do NOT paste the full report body inline — the file is the artifact, the chat reply is the pointer. The user opens the file for the full keep/modify/drop tables; the reply surfaces only what shapes their next decision.
