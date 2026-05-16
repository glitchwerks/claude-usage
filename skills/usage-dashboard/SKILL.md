---
name: usage-dashboard
description: >
  Regenerates the Claude Code token usage HTML dashboard for the
  `claude-prospector` plugin. Bare regeneration surface — writes the file and
  reports the path; does not interpret the data.
  Trigger phrases: "regenerate the dashboard", "rebuild my usage dashboard",
  "refresh the usage dashboard", "regen the dashboard",
  "regenerate the usage dashboard".
---

## Prerequisites

This skill invokes `python -m claude_prospector` under the hood. The Python package must be installed in the environment Claude Code uses. See the [README install steps](https://github.com/glitchwerks/claude-prospector#install-as-a-claude-code-plugin) for the two-step install.

# Usage Dashboard Skill

You are regenerating the `claude-prospector` interactive HTML token-usage dashboard for the user. The user triggered this skill explicitly — produce the dashboard and report the output path. **Do not interpret the data.** The conversational analysis path lives in the `usage-analysis` skill; this skill is the bare "regenerate the file" surface.

## Companion skill

For interpretation (budget status, top consumers, recommendations), point the user at `usage-analysis` instead. If the user's request mixes "rebuild the dashboard" with "and tell me what's happening", run this skill first to refresh the file, then hand off to `usage-analysis` for the analysis pass.

## Default behavior

If the user passes no arguments, run the **7-day rolling** window (matches the most useful billing bucket) and write the dashboard to the platform-appropriate path:

- POSIX: `$HOME/.claude/claude-prospector/dashboard.html`
- Windows: `%USERPROFILE%\.claude\claude-prospector\dashboard.html`

Pass `--no-open` so the file lands at the known path without spawning a browser tab — that side effect is usually unwanted from inside a Claude Code session.

```bash
# POSIX
python -m claude_prospector dashboard --window 7d --output "$HOME/.claude/claude-prospector/dashboard.html" --no-open

# Windows
python -m claude_prospector dashboard --window 7d --output "%USERPROFILE%\.claude\claude-prospector\dashboard.html" --no-open
```

The CLI prints `Dashboard written to <path>` to stdout on success. Echo that line back to the user so they have the absolute path to open or read.

## Arguments

The user may pass any of these. Forward them through to the underlying CLI; do not re-interpret.

| Argument | Behavior |
| --- | --- |
| `--window 5h` | 5-hour rolling window — useful for "how am I doing right now in this session". |
| `--window 7d` | 7-day rolling window (default). |
| `--window 30d` | 30-day rolling window — useful for monthly trend context. Larger windows are slower; flag that if `--window` exceeds 30d. |
| `--from YYYY-MM-DD --to YYYY-MM-DD` | Explicit date range. Mutually exclusive with `--window`. If both are supplied, surface the conflict and ask which one to use. |
| Any other CLI flag (`--limit-5h`, `--limit-7d`, `--limit-sonnet-7d`, `--format json`, `--data-dir`, etc.) | Forward verbatim. See `python -m claude_prospector dashboard --help` for the full surface. |

Always include `--output <path>` and `--no-open` in the final command line, even when the user passed neither — they are quality-of-life defaults for the skill's invocation context.

## When the dashboard already exists

The CLI overwrites `--output` unconditionally. Do not pre-check or back-up the existing file — that's the user's job if they want one. Just regenerate.

## Errors

If the CLI exits non-zero, capture stderr and surface it to the user verbatim under a `**Dashboard generation failed:**` heading. Common causes:

- `python` not on PATH — the user has not installed the Python package; point them at the README's `## Install as a Claude Code plugin` § `### Prerequisite: Python package` section.
- `ModuleNotFoundError: claude_prospector` — same cause as above; the plugin is installed but the package isn't.
- Permission errors on the output path — surface verbatim and suggest passing a different `--output`.

Do not retry; surface the error and stop.
