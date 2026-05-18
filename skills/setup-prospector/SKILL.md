---
name: setup-prospector
description: >
  Set up claude-prospector's plugin-owned Python venv. Invoked via /setup-prospector
  or natural-language triggers: "set up claude-prospector", "install prospector
  dependencies", "prospector isn't working", "fix prospector", "repair prospector".
  Do not trigger on "dashboard", "usage analysis", or "skill adoption" — those
  are distinct skills.
triggers:
  - /setup-prospector
  - set up claude-prospector
  - install prospector dependencies
  - prospector isn't working
  - fix prospector
  - repair prospector
---

# Setup claude-prospector

This skill materialises the plugin-owned Python venv that the plugin's hooks
need to run `claude-prospector` as a subprocess. Run it once after first install
and after any plugin version update.

## Step 1: Resolve `${CLAUDE_PLUGIN_DATA}`

Read the `CLAUDE_PLUGIN_DATA` environment variable. If unset, compute the default:

```
~/.claude/plugins/data/claude-prospector-claude-prospector/
```

The slug is the plugin ID `claude-prospector@claude-prospector` with every
character outside `[a-zA-Z0-9_-]` replaced by a hyphen.

Create the directory if it does not exist.

## Step 2: Discover Python

Find a Python ≥ 3.10 interpreter using this probe chain (stop at first success):

1. `flag.interpreter` from the prior `setup-state.json` (if a flag exists from a
   previous run, try that interpreter first).
2. `$CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON` environment variable (absolute path).
3. `py -3` (Windows only).
4. `python3`
5. `python`

Probe each candidate with:
```
<candidate> -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
```

If all candidates fail, ask the user:
> "No Python ≥ 3.10 interpreter found. Please provide an absolute path to
> a Python 3.10+ executable, or set CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON."

## Step 3: Wipe the existing venv

If `${CLAUDE_PLUGIN_DATA}/venv/` exists, remove it entirely:
```
shutil.rmtree(<plugin_data>/venv)
```
This is always-wipe-first (spec D4). A partial venv from a failed previous run
is handled correctly by this unconditional removal.

## Step 4: Create the venv

```
<python_cmd> -m venv <plugin_data>/venv
```

Where `<python_cmd>` is the interpreter found in Step 2. If this fails, surface
the stderr to the user and do NOT proceed to Step 5.

## Step 5: Install claude-prospector from PyPI

First, ensure pip is available in the new venv:
```
<venv_python> -m ensurepip --upgrade
```

Then install:
```
<venv_python> -m pip install claude-prospector==<version>
```

Where `<version>` is the current plugin version (read from `pyproject.toml`
`[project].version`, falling back to `.claude-plugin/plugin.json` `version`).

If `$CLAUDE_PROSPECTOR_PIP_SPEC` is set, use its value as the entire package
spec instead of `claude-prospector==<version>` (test/dev override only).

If pip fails, surface the stderr verbatim, wipe the partial venv, and do NOT
proceed to Step 6.

## Step 6: Verify import

```
<venv_python> -c "import claude_prospector"
```

If this fails, wipe the venv and report the import error. Suggest
`pip cache purge` and retry if the error looks like a wheel issue.

## Step 7: Write the setup-state flag

Write `${CLAUDE_PLUGIN_DATA}/setup-state.json` with this shape:

```json
{
  "version": "<current_version>",
  "venv_path": "<absolute_path_to_venv_dir>",
  "interpreter": "<probe_string_from_step_2>",
  "installed_at": "<UTC_ISO_8601_timestamp>"
}
```

The `venv_path` is the absolute path to the venv root (e.g.
`C:/Users/alice/.claude/plugins/data/claude-prospector-claude-prospector/venv`).
The `interpreter` is the raw command string from Step 2 (e.g. `py -3` or
`python3`), not an absolute path, so re-setup can reuse it.

## Step 8: Tell the user

Report success:
> "Setup complete. Open a new Claude Code session to activate claude-prospector.
> The dashboard, skill-tracking, and usage-analysis features will work normally
> after the next session starts."
