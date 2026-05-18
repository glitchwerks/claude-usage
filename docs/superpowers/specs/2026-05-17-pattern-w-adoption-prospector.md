---
title: Pattern W adoption for claude-prospector
touches:
  - .claude-plugin/plugin.json
  - pyproject.toml
  - hooks/hooks.json
  - hooks/skill-tracker.py
  - hooks/dashboard-regen.py
  - hooks/check-prospector-setup.py
  - hooks/lib/setup_state.py
  - skills/setup-prospector/SKILL.md
  - tests/integration/setup_pipeline.py
  - tests/integration/test_setup_skill.py
  - tests/unit/test_check_prospector_setup.py
  - tests/unit/test_dashboard_regen_guard.py
  - tests/unit/test_setup_state.py
  - tests/unit/test_skill_tracker_guard.py
  - tests/test_skill_pipeline_sync.py
  - .github/workflows/ci.yml
  - README.md
  - CHANGELOG.md
skills_relevant:
  - python
  - github-actions
  - claude-code-plugin-authoring
  - agent-authoring
---

# Pattern W adoption for claude-prospector

Tracking issue: [glitchwerks/claude-prospector#107](https://github.com/glitchwerks/claude-prospector/issues/107)
Author: project-planner session 2026-05-17 (cbeaulieu-gt + Claude)
Status: **design — input to `project-reviewer` then `writing-plans`**
Reference architecture: `claude-wayfinder` v0.4.0 design at
`I:/other/claude-wayfinder/docs/superpowers/specs/2026-05-17-setup-skill-architecture-design.md`
(hereafter "WAYFINDER-SPEC").

---

## § 1. Why this design exists

`claude-prospector` ships two Python hooks today:

- `hooks/skill-tracker.py` (`PreToolUse` matcher `Skill|Agent`) — fires
  constantly during a session, imports `claude_prospector.skill_tracking`
  if available, falls back to a filesystem scan otherwise
  (`hooks/skill-tracker.py:94-119`).
- `hooks/dashboard-regen.py` (`Stop`, unconditional) — fires at session
  end, spawns `python -m claude_prospector` as a subprocess
  (`hooks/dashboard-regen.py:508-514`, `544-560`).

The dashboard-regen hook resolves its interpreter by guessing the venv
root from `Path(sys.executable).parent.parent.parent`
(`hooks/dashboard-regen.py:513`, `:559`). That guess is correct only
when `sys.executable` is a venv `bin/python`/`Scripts/python.exe`
three levels above the venv root — which is exactly true for `~/.claude/.venv/`
today, **but only by accident**. Any other install location (a user-managed
`/usr/local/bin/python`, a Conda env, a Microsoft Store shim, a `pyenv`
shim, or a future `${CLAUDE_PLUGIN_DATA}/<slug>/venv/`) shifts that path
arithmetic and the subprocess CWD ends up somewhere meaningless.

The skill-tracker hook avoids the same problem only by using
`sys.executable` directly (no CWD inference) and by inlining its
path-resolution defensively (`hooks/skill-tracker.py:35-87`) because
`claude_prospector` may not be importable at hook fire time
(`hooks/skill-tracker.py:107-119`). That defensive mirror is real
complexity that exists to paper over the same root cause: **the hook
process inherits whatever interpreter Claude Code happened to spawn it
with, and that interpreter has no guaranteed relationship to where
`claude-prospector` is installed**.

WAYFINDER-SPEC § 1 names the same pattern: "the plugin hook child
process trying to resolve Python via the consumer's interactive shell
environment." Wayfinder's resolution — Pattern W — is to make the
plugin own its interpreter via a `${CLAUDE_PLUGIN_DATA}/<slug>/venv/`,
gate hook subprocess work on a `setup-state.json` flag that records the
venv path, and put the discovery + install logic in a user-invoked
skill (`/setup-wayfinder`) rather than a hook.

This spec adopts Pattern W for `claude-prospector` with the deltas
required by prospector's two-hook surface, `userConfig.autoregen`
coexistence, Python 3.10 floor, jinja2 dependency, and existing
state-storage migration mechanism. Out of scope: any behavioural change
to skill-tracking event shape, dashboard rendering, or the v0.6.0
config.json migration mechanism (`hooks/dashboard-regen.py:164-199`).

---

## § 2. Design decisions (locked)

Decisions D1–D7 are imported verbatim from WAYFINDER-SPEC § 2 unless
noted. D8–D12 are prospector-specific.

| #   | Decision                                                                                                                                                                                              | Rationale                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| D1  | **Install source: PyPI only.** Skill runs `pip install claude-prospector==<version>`. No path argument; no bundled wheels.                                                                            | Same rationale as WAYFINDER D1. Requires that `claude-prospector` be published to PyPI before v0.7.0 ships. Release workflow (PR #109) supports this via trusted-publisher OIDC. First publish target: a `v0.7.0rc1` pre-release rehearsal on TestPyPI, then `v0.7.0` to PyPI proper. **Rejected**: bundled-wheel install — same platform-tag concerns inquisitor flagged for wayfinder apply here (jinja2 has C-extension-free wheels but still platform-dependent transitively).                                                                                                                                                                                                                            |
| D2  | **Banner surface: `SessionStart` `additionalContext` only.**                                                                                                                                          | Same as WAYFINDER D2. Prospector has no `SessionStart` hook today; this spec adds one.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| D3  | **Re-setup trigger: cheap reads per hook + one import probe per session at SessionStart only.**                                                                                                       | Same as WAYFINDER D3. Critical for prospector because `PreToolUse(Skill\|Agent)` fires many times per session — running the import probe per fire would be a measurable session-wide cost. The probe runs once in `check-prospector-setup.py` at SessionStart; `skill-tracker.py` and `dashboard-regen.py` only do `readSetupState() == VALID` plus `Path(venv_python).exists()` cheap checks. **Rejected**: gating the import probe from skill-tracker — frequency is wrong.                                                                                                                                                                                                                                |
| D4  | **Destructive ops: always wipe + recreate.**                                                                                                                                                          | Same as WAYFINDER D4. Skill always `shutil.rmtree(<plugin_data>/venv)` before creating.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| D5  | **Trigger: slash command + natural-language triggers.**                                                                                                                                               | Same as WAYFINDER D5. Skill `name: setup-prospector`, slash form `/setup-prospector`. NL triggers: "set up claude-prospector", "install prospector dependencies", "prospector isn't working", "fix prospector", "repair prospector". Description tuned to avoid false-positive matches on the dashboard/usage-analysis skills.                                                                                                                                                                                                                                                                                                                                                                              |
| D6  | **Discovery fail: ask user for absolute path.** Probe chain `flag.interpreter` (from prior run) → `$CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON` → `py -3` (Windows) → `python3` → `python`; ask on exhaustion. | Same as WAYFINDER D6. Env-var name is **`CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON`** (parallels wayfinder's naming convention). Probe success criterion: Python ≥ 3.10 (see D10).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| D7  | **Code organization: hybrid.** Skill body owns LLM-judgment surface. `hooks/lib/setup_state.py` owns deterministic logic.                                                                             | Same as WAYFINDER D7, **except the helper is Python, not JavaScript** — see D8.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| D8  | **Hook language: stay Python.** Do not port hooks to JavaScript.                                                                                                                                      | Wayfinder's hooks are JS because wayfinder's runtime is JS-callable Node logic; the JS→Python spawn is a one-way edge. Prospector's hooks are Python today, and the package they spawn is Python. Porting to JS would (a) duplicate the path-resolution logic in two languages, (b) require a Node runtime assumption prospector doesn't currently make, (c) trade a known surface (Python subprocess management, argparse) for a less-mature one. The Pattern W setup-state helper is pure logic — porting it to Python is straightforward (~150 LOC, mirrors `setup-state.js`). **Rejected**: port to JS for parity with wayfinder. Symmetry is not a goal; minimising churn on a working hook surface is. |
| D9  | **Add a new `SessionStart` hook, do not gate the existing two hooks on `SessionStart`.**                                                                                                              | Pattern W requires a `SessionStart` hook to emit banners and run the import probe. Prospector has no `SessionStart` today. Adding one is unavoidable. The existing `PreToolUse` and `Stop` hooks gain only the cheap `readSetupState()` guard, not the probe. **Rejected**: roll the probe into `PreToolUse` — fires too often (see D3).                                                                                                                                                                                                                                                                                                                                                                    |
| D10 | **Keep `requires-python = ">=3.10"`.** Do not bump to 3.11 for parity with wayfinder.                                                                                                                 | Prospector's `pyproject.toml:9` declares 3.10. Bumping to 3.11 is a minor breaking change for any user still on 3.10. The Pattern W probe needs only a version check — adapting `discover_python` to assert `>=3.10` instead of `>=3.11` is a one-line change. The only argument for bumping is matrix simplicity, and prospector's CI already tests against 3.10 (`.github/workflows/ci.yml`); a Pattern W smoke matrix can also pin 3.10 and still validate cross-platform behaviour. **Rejected**: bump to 3.11 — gains no compatibility, costs at least one user.                                                                                                                                        |
| D11 | **Setup-state flag lives at `${CLAUDE_PLUGIN_DATA}/setup-state.json`.** Always. `CLAUDE_PROSPECTOR_BASE_DIR` does **not** override flag location.                                                      | The prospector three-tier resolver (`hooks/skill-tracker.py:35-56`, `hooks/dashboard-regen.py:74-95`) was designed for **runtime artifacts** (tracking JSONL, dashboard HTML, hook.log) that pre-date Pattern W. Pattern W's flag is **install-state**, not runtime state — its location must be predictable for the SessionStart hook before the venv is materialised. Pinning to `${CLAUDE_PLUGIN_DATA}` matches wayfinder, matches Anthropic's documented `${CLAUDE_PLUGIN_DATA}` mechanism (per `claude-code-plugin-authoring` skill § 4), and keeps the helper's path-resolution single-tier. **Rejected**: route flag through the three-tier base_dir() — premature generality, breaks the wayfinder symmetry. |
| D12 | **Version target: `v0.7.0`.** Minor bump, not breaking userspace beyond the one-time `/setup-prospector` invocation.                                                                                  | Pattern W adds a new install requirement (run `/setup-prospector` once after upgrade) but does not change any existing CLI flag, hook payload shape, dashboard output, or skill behaviour. The userspace-visible change is the SessionStart banner on first v0.7.0 session. Minor-version semantics (SemVer "added functionality in a backward-compatible manner") fit. Pre-release rehearsal: `v0.7.0rc1` to TestPyPI for end-to-end CI validation before publishing to PyPI proper. **Rejected**: major v1.0.0 — premature; reserve for if/when the v0.6.0 → v0.7.0 migration story turns out worse than expected.                                                                                          |
| D13 | **Setup pipeline uses `python -m pip install`, not `uv pip install`.**                                                                                                                               | End-user portability: `uv` is not assumed to be installed on user machines. The venv created by `python -m venv` already provides `pip` via `ensurepip`; using it in the setup pipeline means the end-user path requires nothing beyond a Python ≥ 3.10 interpreter. CI smoke jobs may use either `pip` or `uv` since CI already provides both. **Rejected**: `uv` as the install verb for the setup pipeline — would constrain end-user machine prerequisites without meaningful benefit. |

---

## § 3. Architecture flow

```
┌────────────────────────────────────────────────────────────────────────┐
│  User installs plugin (current install path or future marketplace)      │
└────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Session 1 SessionStart                                                  │
│  ──────────────────────                                                  │
│  hooks/check-prospector-setup.py                                         │
│    │                                                                     │
│    ├── setup_state.read(current_version) → FlagStatus                    │
│    │     ├── MISSING (flag absent)                                       │
│    │     ├── STALE   (version mismatch)                                  │
│    │     ├── BROKEN  (path exists but venv-python doesn't)               │
│    │     └── VALID   (flag + path + version all match)                   │
│    │                                                                     │
│    ├── If VALID: spawn <venv-python> -c 'import claude_prospector'       │
│    │     Failure → delete flag (state becomes MISSING) → emit MISSING banner │
│    │                                                                     │
│    └── If NOT VALID: emit additionalContext banner                       │
│         "claude-prospector requires setup. Run /setup-prospector."       │
└────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│  User reads banner, runs /setup-prospector                               │
│  ─────────────────────────────────────────                               │
│  Skill (LLM-driven):                                                     │
│    1. Resolve ${CLAUDE_PLUGIN_DATA}                                      │
│    2. Discover Python (D6, Python >= 3.10)                               │
│    3. Wipe ${CLAUDE_PLUGIN_DATA}/venv/ if it exists                      │
│    4. Create venv: <python> -m venv <data>/venv                          │
│    5. Install: <venv-python> -m pip install claude-prospector==<X>       │
│       (X = plugin version, read from pyproject.toml / plugin.json)       │
│    6. Verify: <venv-python> -c "import claude_prospector"                │
│    7. setup_state.write({version, venv_path, interpreter, installed_at}) │
│    8. Tell user: "Setup complete. Open a new session to activate."       │
└────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Subsequent sessions                                                     │
│  ────────────────────                                                    │
│  SessionStart  → check-prospector-setup.py: VALID + probe OK → silent    │
│                                                                          │
│  PreToolUse(Skill|Agent) → skill-tracker.py:                             │
│    setup_state.read() → if not VALID: exit 0 silent (banner already)     │
│                         if VALID: spawn <venv-python> hooks/             │
│                           skill-tracker.py inner logic                   │
│                                                                          │
│  Stop → dashboard-regen.py:                                              │
│    setup_state.read() → if not VALID: exit 0 silent                      │
│                         if VALID: spawn <venv-python> -m                 │
│                           claude_prospector dashboard ...                │
│                         --autoregen ${user_config.autoregen} still       │
│                         passed through unchanged                         │
└────────────────────────────────────────────────────────────────────────┘
```

### Key invariants

- **No hook ever spawns Python without first reading a VALID flag.** The
  hook check is `setup_state.read() == VALID` + `Path(flag.venv_path /
  python_suffix).exists()` — both cheap, no subprocess.
- **The `python -c 'import claude_prospector'` probe runs at most once
  per session,** inside `check-prospector-setup.py` only.
- **The setup skill never runs from a hook.** It is user-invoked
  exclusively. Hooks emit banners; they do not orchestrate.
- **`${CLAUDE_PLUGIN_DATA}` resolution is single-tier for the flag.** Per
  D11, the flag lives at `${CLAUDE_PLUGIN_DATA}/setup-state.json`. The
  three-tier `CLAUDE_PROSPECTOR_BASE_DIR` resolver continues to govern
  runtime artifacts (skill-tracking JSONL, dashboard HTML, hook.log)
  only.
- **PyPI is the only install source.**
- **`${user_config.autoregen}` substitution is preserved.** The Stop
  hook command in `hooks/hooks.json` keeps the `--autoregen
  "${user_config.autoregen}"` arg; only the executable changes (from
  bare `python` to `<venv-python>`).

---

## § 4. Components

| File                                       | Change                                                                                                                                              | Approx LOC | Notes                                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hooks/lib/setup_state.py`                 | **New.** Pure-functions helper. Mirrors wayfinder's `hooks/lib/setup-state.js` in Python. Each hook imports it via a `sys.path.insert` idiom (3 lines per hook, repeated identically): `import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent / 'lib')); import setup_state  # noqa: E402`. The `noqa: E402` suppresses ruff's non-top-of-file-import warning; this mirrors wayfinder's `require('./lib/setup-state.js')` but adapts to Python's import model. | ~150       | Surface: `read_setup_state(current_version) -> SetupStateResult`, `get_venv_python(venv_path) -> Path`, `get_current_version() -> str`, `get_plugin_data_dir() -> Path` (honors `$CLAUDE_PLUGIN_DATA` for tests), `get_flag_path() -> Path` (always `<plugin_data>/setup-state.json`). `SetupStateResult` is a `NamedTuple` or dataclass with `status` enum and `flag?`. The `sys.path.insert` block adds ~3 LOC to each of the three hooks (`check-prospector-setup.py`, `skill-tracker.py`, `dashboard-regen.py`) and is not folded into the per-hook LOC estimates elsewhere in this table — it is a fixed overhead of the Python import model. |
| `hooks/check-prospector-setup.py`          | **New.** SessionStart hook. Reads flag, runs import probe once per session, emits banner via `additionalContext`.                                   | ~120       | Banner text per § 5 table. On probe failure, deletes flag (downgrade to MISSING) before emitting banner. Wraps everything in try/except so SessionStart never crashes.                                                                                                                                                                                                 |
| `hooks/skill-tracker.py`                   | **Modified.** Add `setup_state.read()` guard at top of `main()`. If not VALID, exit 0 silent. If VALID, the rest of `main()` proceeds as today.     | +20 -0     | The inline `_get_allowlist()` ImportError fallback (`hooks/skill-tracker.py:107-119`) is **retained** for defense — even when VALID, importing `claude_prospector.skill_tracking` from the current `sys.executable` (which is the harness Python, not the venv Python) may still fail; the filesystem fallback is correct behaviour and not removed by Pattern W.        |
| `hooks/dashboard-regen.py`                 | **Modified.** Add `setup_state.read()` guard. **Both** subprocess callsites replace `sys.executable` with `get_venv_python(flag.venv_path)` and drop the `cwd=` arg: `:506-514` (version-mismatch gate — `subprocess.run([sys.executable, "-m", "claude_prospector", "--version"], ...)`) and `:543-560` (dashboard regen — `subprocess.run([sys.executable, "-m", "claude_prospector", "dashboard", ...])`). | +30 -12    | Removes the brittle `Path(sys.executable).parent.parent.parent` CWD inference from both callsites. New contract: `--data-dir` defaults to absolute `Path.home() / ".claude"` (verifiable in `claude_prospector/cli/dashboard.py:79`); `--output` is required-absolute in the spec'd invocation; no other argument resolves relative to cwd — so dropping `cwd=` is safe today. Implementers MUST re-verify this if any new dashboard CLI arg is added later. The `--autoregen` arg, version-mismatch gate logic, and migration-notice logic are all preserved untouched. |
| `hooks/hooks.json`                         | **Modified.** Add `SessionStart` entry. Existing `PreToolUse` and `Stop` entries unchanged.                                                         | +12 -0     | New entry shape: `"SessionStart": [{ "hooks": [{ "type": "command", "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/check-prospector-setup.py\"" }] }]`. Note that `python` here means the harness-provided Python — same as the other hooks today. Only the **logic inside** the hooks gates work behind Pattern W; the `hooks.json` command interpreter does not change. |
| `skills/setup-prospector/SKILL.md`         | **New.** Mirrors `skills/setup-wayfinder/SKILL.md`.                                                                                                 | ~150       | Frontmatter with NL triggers (D5). Body: 8-step checklist matching § 3 architecture flow. Explicit env-var name `CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON`. Probe asserts Python ≥ 3.10.                                                                                                                                                                                       |
| `tests/integration/setup_pipeline.py`      | **New.** Executable mirror of skill body's 8 steps. CI calls `run_full_pipeline(version, prior_interpreter=None)`.                                  | ~320       | Test seams: `$CLAUDE_PLUGIN_DATA`, `$CLAUDE_PROSPECTOR_BOOTSTRAP_PYTHON`, `$CLAUDE_PROSPECTOR_PIP_SPEC` (install from local checkout instead of PyPI — required for pre-publish CI; matches wayfinder's `CLAUDE_WAYFINDER_PIP_SPEC` pattern). Includes a `<venv-python> -m ensurepip --upgrade` step before `pip install` as defensive plumbing for Windows runners where `ensurepip` may be disabled (see § 9.5). Per D13, the install verb is `pip`.                                                                                                                              |
| `tests/integration/test_setup_skill.py`    | **New.** Pytest harness around `setup_pipeline.py`. Asserts venv exists, import succeeds, flag JSON shape valid.                                    | ~120       | Runs in CI smoke matrix.                                                                                                                                                                                                                                                                                                                                                |
| `tests/unit/test_setup_state.py`           | **New.** Unit tests for `hooks/lib/setup_state.py`. ~12 cases mirroring WAYFINDER-SPEC § 7.                                                         | ~250       | Fixture states from WAYFINDER-SPEC § 7 helper-unit-tests table.                                                                                                                                                                                                                                                                                                          |
| `tests/test_skill_pipeline_sync.py`        | **New.** Diff skill body's numbered steps against `setup_pipeline.py` headings to catch drift.                                                      | ~80        | Same purpose as wayfinder's sync test.                                                                                                                                                                                                                                                                                                                                  |
| `.github/workflows/ci.yml`                 | **Modified.** Add `skill-smoke-{ubuntu,windows}` jobs running `tests/integration/test_setup_skill.py` with `CLAUDE_PROSPECTOR_PIP_SPEC=$GITHUB_WORKSPACE`. | +35 -0     | Matrix decision in § 9. macOS deferred (see § 9).                                                                                                                                                                                                                                                                                                                       |
| `pyproject.toml`                           | **Modified.** Bump version to `0.7.0` (or `0.7.0rc1` for TestPyPI rehearsal).                                                                       | +1 -1      | No dep changes. `requires-python` stays at `>=3.10` (D10).                                                                                                                                                                                                                                                                                                              |
| `.claude-plugin/plugin.json`               | **Modified.** Bump `version` to `0.7.0`.                                                                                                            | +1 -1      | `userConfig.autoregen` unchanged.                                                                                                                                                                                                                                                                                                                                       |
| `README.md`                                | **Modified.** Document `/setup-prospector` install flow, banner UX, migration from v0.6.0.                                                          | ~50        | New section: "First-run setup".                                                                                                                                                                                                                                                                                                                                         |
| `CHANGELOG.md`                             | **Modified.** New v0.7.0 entry per § 11.                                                                                                            | ~25        |                                                                                                                                                                                                                                                                                                                                                                         |

### Net hook-code change

- ~150 LOC new helper (`setup_state.py`)
- ~120 LOC new SessionStart hook
- ~20 LOC added to `skill-tracker.py` (guard only, no removals — the defensive `_get_allowlist` fallback stays)
- ~30 LOC added / ~12 LOC removed in `dashboard-regen.py` (guard + venv-python wiring; removes the `.parent.parent.parent` CWD inference from both subprocess callsites: version gate `:506-514` and regen `:543-560`)
- The defensive inline `_base_dir()` mirrors in both Python hooks
  (`hooks/skill-tracker.py:35-56`, `hooks/dashboard-regen.py:74-95`) **stay
  unchanged** — they govern runtime artifact paths, not install state.

---

## § 5. Flag JSON shape

```json
{
  "version": "0.7.0",
  "venv_path": "C:/Users/alice/.claude/plugins/data/claude-prospector-claude-prospector/venv",
  "interpreter": "py -3",
  "installed_at": "2026-05-17T19:00:00Z"
}
```

Location: `${CLAUDE_PLUGIN_DATA}/setup-state.json`.

Slug computation: plugin-id with non-`[a-zA-Z0-9_-]` → `-`. For prospector
that is `claude-prospector-claude-prospector` (Anthropic's documented
namespacing — see `claude-code-plugin-authoring` skill § 4 reference).

### Comparison vs wayfinder

| Field          | Wayfinder | Prospector | Notes                                                                                              |
| -------------- | --------- | ---------- | -------------------------------------------------------------------------------------------------- |
| `version`      | identical | identical  | Read from `pyproject.toml` `[project].version`, falls back to `plugin.json` `version`.            |
| `venv_path`    | identical | identical  | Absolute path; resolved per machine on each setup.                                                  |
| `interpreter`  | identical | identical  | The string from D6 probe that succeeded (e.g. `py -3`, `python3`, or a user-provided absolute path). |
| `installed_at` | identical | identical  | UTC ISO 8601 string.                                                                                |

No prospector-specific fields. The flag is the same shape across both
plugins — a deliberate decision to keep Pattern W's helper portable.

---

## § 6. Scenarios A–G

Adapted from WAYFINDER-SPEC § 5. Where prospector behaviour diverges,
the divergence is called out inline; otherwise the scenario is identical.

### A. Fresh install

```
Plugin installed → Session 1 SessionStart: MISSING → banner shown.
User runs /setup-prospector → discovery, venv, install, verify, flag written.
Session 2: VALID + import probe passes → no banner.
  PreToolUse fires: setup_state.read() = VALID → tracking proceeds normally.
  Stop fires:       setup_state.read() = VALID → dashboard regen proceeds
                    (gated additionally by ${user_config.autoregen}).
```

### B. Normal session (steady state)

```
SessionStart: VALID + probe OK → no banner.
PreToolUse(Skill|Agent): VALID → skill-tracker.py logs events to
  <base_dir>/skill-tracking/<date>.jsonl as today (no change).
Stop: VALID + autoregen=true → dashboard-regen.py spawns <venv-python>
  -m claude_prospector dashboard ... (replaces today's
  sys.executable subprocess).
```

### C. Plugin version bump (v0.7.0 → v0.7.1)

```
User runs /plugin update.
Session SessionStart: flag.version == "0.7.0", get_current_version() == "0.7.1"
  → STALE.
Banner: "claude-prospector venv is for v0.7.0 but plugin is v0.7.1.
  Run /setup-prospector to refresh."
User runs /setup-prospector → wipe old venv, recreate against v0.7.1, flag rewritten.
```

### D. Venv corruption

```
SessionStart: flag valid, path exists, but `import claude_prospector` fails.
check-prospector-setup.py deletes flag → state is now MISSING → emits MISSING banner.
User re-runs /setup-prospector.
```

### E. Cross-machine sync

```
Machine A: flag.venv_path = C:/Users/alice/.claude/plugins/data/.../venv
Machine B (OneDrive syncs the flag):
  Path(<machine-A path>).exists() → False → BROKEN.
Banner fires. User runs /setup-prospector on machine B; flag overwritten.
```

Same explicit non-support note as wayfinder: per-machine setup is the
supported model.

### F. Setup interrupted mid-run

```
Skill crashes between step 4 (venv created) and step 7 (flag written).
<plugin_data>/venv/ exists half-populated; no flag.
User retries: step 3 wipes the half-built venv; rest succeeds.
```

D4 (always-wipe-first) makes this structural, not error-handling.

### G. PyPI unreachable

```
Skill step 5: pip install → exit 1.
Skill DOES NOT write flag. Surfaces pip stderr verbatim.
User retries when network/PyPI returns.
```

---

## § 7. Error modes

Adapted from WAYFINDER-SPEC § 6, with two prospector-specific additions (F9, F10).

| ID  | Failure                                        | Where                          | Recovery                                                                                                                                                                                              |
| --- | ---------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1  | No Python ≥ 3.10 interpreter found             | Skill step 2                   | Ask user for absolute path; persist to flag's `interpreter` field.                                                                                                                                    |
| F2  | `python -m venv` fails                         | Skill step 4                   | Surface stderr; wipe partial; exit without writing flag.                                                                                                                                              |
| F3  | `pip install` fails                            | Skill step 5                   | Surface pip stderr; wipe half-built venv; user retries.                                                                                                                                               |
| F4  | Import verification fails after install        | Skill step 6                   | Wipe venv; report import error; suggest `pip cache purge` and retry.                                                                                                                                  |
| F5  | Flag write fails                               | Skill step 7                   | Wipe the just-built venv; surface write error.                                                                                                                                                        |
| F6  | Skill interrupted mid-run                      | Anywhere in steps 3-7          | Self-healing via D4.                                                                                                                                                                                  |
| F7  | Hook can't parse flag JSON                     | Any hook calling helper        | `read_setup_state()` catches parse error, returns `MISSING`; banner fires next session.                                                                                                               |
| F8  | Banner emission fails                          | `check-prospector-setup.py`    | Hook exits 0 (never blocks session); degrades to silent-no-op.                                                                                                                                        |
| F9  | Legacy `~/.claude/.venv` import shadowing      | `check-prospector-setup.py` import probe | If a user has prospector installed in `~/.claude/.venv` AND the new venv's import probe spawns the **wrong** Python (e.g. user's PATH points there), the probe might "pass" against the legacy install rather than the new venv. **Mitigation**: the probe always uses `get_venv_python(flag.venv_path)` (an absolute path), never `python` from PATH. This is structural, not configurable. See § 11 for migration guidance to users running both. |
| F10 | Venv path exists at SessionStart but package becomes unavailable mid-session | `dashboard-regen.py` and `skill-tracker.py` during a live session | The SessionStart probe passed, but the venv was corrupted or the package uninstalled during the session. Next `dashboard-regen.py` fire: `venv_python -m claude_prospector dashboard ...` exits non-zero; the existing `_regen_failed_page()` mechanism writes a failure HTML page — recoverable, user sees a failure notice rather than a crash. `skill-tracker.py` is unaffected: its `_get_allowlist()` ImportError fallback (`hooks/skill-tracker.py:107-119`) covers package-missing under harness Python, and the effect here is identical (package missing from the venv rather than from the harness). **No new code required**; these are the intended recovery surfaces for mid-session degradation. The next SessionStart will detect BROKEN state and emit a banner. |

### Hook invariants

- Never spawn subprocesses when state ≠ VALID.
- Never throw uncaught exceptions.
- Never write to the flag file. Only the skill writes; only
  `check-prospector-setup.py` deletes (on corrupt-venv detection).
- **The `${user_config.autoregen}` arg is always passed to
  `dashboard-regen.py`**, regardless of setup state. The hook's own
  state guard fires before the autoregen arg is parsed, so a
  not-VALID setup state short-circuits before the autoregen logic
  runs. Both gates are independent and orthogonal.

---

## § 8. Invariants summary

1. **Hooks read VALID flag before spawning Python.** No exceptions.
2. **The import probe runs at most once per session,** in
   `check-prospector-setup.py` only — not in `skill-tracker.py` or
   `dashboard-regen.py`.
3. **Skill writes flag; SessionStart hook deletes flag on import
   failure; no other component mutates the flag.**
4. **`${CLAUDE_PLUGIN_DATA}/setup-state.json` is the single flag
   location.** `CLAUDE_PROSPECTOR_BASE_DIR` does not override it.
5. **Setup-state flag and `userConfig.autoregen` are orthogonal.** The
   former governs whether hooks may spawn Python; the latter governs
   whether dashboard regen runs when the spawn is permitted.
6. **The defensive `_get_allowlist()` ImportError fallback in
   `skill-tracker.py` (`hooks/skill-tracker.py:107-119`) stays.** Even
   when the flag is VALID, the hook's `sys.executable` is the harness
   Python, not the venv Python — the import may still fail. The
   filesystem fallback is correct behaviour, not a wart to remove.
7. **`Path(sys.executable).parent.parent.parent` is eliminated from
   `dashboard-regen.py` — in both subprocess callsites.** This covers
   both the version-mismatch gate (`:506-514`) and the dashboard regen
   call (`:543-560`). Both callsites use `get_venv_python(flag.venv_path)`
   (an absolute path) and omit the `cwd=` arg. No hook ever spawns Python
   without a VALID flag — this invariant binds equally to the version
   probe and the regen subprocess.

---

## § 9. Testing strategy

Mirrors WAYFINDER-SPEC § 7. Three surfaces.

### 9.1 Unit tests — `tests/unit/test_setup_state.py`

12 cases against `hooks/lib/setup_state.py`:

| Fixture state                                                            | Expected `status` |
| ------------------------------------------------------------------------ | ----------------- |
| Flag missing                                                             | `MISSING`         |
| Flag exists but unparseable JSON                                         | `MISSING`         |
| Flag parseable but `version` field missing                               | `MISSING`         |
| Flag valid, version matches, venv path exists, venv-python exists        | `VALID`           |
| Flag valid, version mismatch                                             | `STALE`           |
| Flag valid, version matches, venv path doesn't exist                     | `BROKEN`          |
| Flag valid, version matches, venv exists but `python` symlink missing    | `BROKEN`          |
| `get_current_version()` reads pyproject.toml correctly                   | passes            |
| `get_current_version()` falls back to plugin.json                        | passes            |
| `get_plugin_data_dir()` honors `$CLAUDE_PLUGIN_DATA` env var             | passes            |
| `get_venv_python()` returns `Scripts/python.exe` on Windows              | passes            |
| `get_venv_python()` returns `bin/python` on POSIX                        | passes            |

**Test-seam note — `$CLAUDE_PLUGIN_DATA` dual effect.** Setting
`$CLAUDE_PLUGIN_DATA` in a test isolates **both** the flag path AND all
runtime artifacts via the existing three-tier `base_dir()` resolver in
`claude_prospector/paths.py:base_dir()`. Test authors should set the env
var to a fresh temp dir and expect every state file — flag
(`setup-state.json`), dashboard HTML, `hook.log`, skill-tracking JSONL —
to land under that temp dir. This is the intended behaviour and simplifies
test cleanup. If a test needs to isolate only the flag (unusual), it must
additionally set `CLAUDE_PROSPECTOR_BASE_DIR` to redirect runtime artifacts
back to their normal location.

### 9.2 Hook integration tests

- `tests/unit/test_check_prospector_setup.py` (new): MISSING / STALE /
  VALID / BROKEN banner assertions; import-probe-fails flag-deletion
  behaviour (uses a Python shim that exits 1 on the probe command).
- `tests/unit/test_skill_tracker_guard.py` (new, tiny): asserts that
  `skill-tracker.py` exits 0 silent when `setup_state.read()` returns
  non-VALID, and proceeds otherwise. Reuses prospector's existing
  hook-test pattern.
- `tests/unit/test_dashboard_regen_guard.py` (new): same shape for
  `dashboard-regen.py`. Also asserts that when VALID, the subprocess
  is spawned with `<venv-python>` (an absolute path under
  `${CLAUDE_PLUGIN_DATA}`) rather than `sys.executable`.

### 9.3 Skill smoke test — `tests/integration/test_setup_skill.py`

End-to-end against real Python, real pip. Runs in CI on every PR.

1. Set up a fresh temp dir as fake `${CLAUDE_PLUGIN_DATA}`.
2. Call `setup_pipeline.run_full_pipeline(version=current_version)`.
3. Assert: venv exists at expected path; `<venv>/python -c "import
   claude_prospector"` exits 0; flag file is valid JSON with correct
   shape; `claude_prospector --version` matches `current_version`.
4. Cleanup.

Test seam: `$CLAUDE_PROSPECTOR_PIP_SPEC=$GITHUB_WORKSPACE` installs from
the checkout instead of PyPI — required because `claude-prospector`
won't be on PyPI until the same PR's release tag fires.

### 9.4 Skill/pipeline sync — `tests/test_skill_pipeline_sync.py`

Diffs the numbered headings in `skills/setup-prospector/SKILL.md`
against the function headings in `tests/integration/setup_pipeline.py`.
Fails CI if they drift.

### 9.5 CI matrix decision

| Job                          | OS              | Python | Notes                                                                                                                                                                                  |
| ---------------------------- | --------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lint` (existing)            | ubuntu-latest   | 3.10   | unchanged                                                                                                                                                                              |
| `test` (existing)            | ubuntu-latest   | 3.10   | unchanged                                                                                                                                                                              |
| `test` (existing)            | windows-latest  | 3.10   | unchanged                                                                                                                                                                              |
| `skill-smoke-ubuntu` (new)   | ubuntu-latest   | 3.10   | runs `tests/integration/test_setup_skill.py` with `CLAUDE_PROSPECTOR_PIP_SPEC=$GITHUB_WORKSPACE`                                                                                       |
| `skill-smoke-windows` (new)  | windows-latest  | 3.10   | same, on Windows runners                                                                                                                                                              |
| `skill-smoke-macos` (deferred) | macos-latest  | 3.10   | **Not in v0.7.0.** Prospector's current CI has no macOS coverage at all. Adding macOS just for the skill-smoke job introduces a runner cost without a matching `test` row. Track as #TBD follow-up. |

**Rationale for deferring macOS**: wayfinder added macOS because its
existing matrix already included it. Prospector's matrix does not.
Pulling macOS in via the smoke job alone produces an asymmetric matrix
(macOS validates install but not unit tests) and an opaque cost
increase. The pragmatic call is to land Pattern W with the same matrix
shape (Linux + Windows) and add macOS as a separate follow-up if/when
prospector users on macOS report Pattern W issues.

**`ensurepip` defensive plumbing (Windows runners).** On Windows
runners, the `python -m venv <dir>` step in `setup_pipeline.py` may
produce a venv whose `Scripts/pip.exe` is absent or non-functional if
`ensurepip` was disabled in the runner's Python build (rare but possible
on minimal Python images). As defensive plumbing, `setup_pipeline.py`
runs `<venv-python> -m ensurepip --upgrade` explicitly before the
`pip install` step. Wayfinder's CI did not report this issue in v0.4.0
but the cost is one additional subprocess and the cost of a CI failure
here — a silent broken venv — is high. Per D13, the install verb is
`pip`; this step ensures `pip` is available before it is called.

---

## § 10. Acceptance criteria — mapping to #107

Acceptance criteria from `glitchwerks/claude-prospector#107` (per the
session memory `project_pattern_w_prospector` and the user's brief):

1. **Publish `claude-prospector` to PyPI.**
   - **Files**: no source changes; uses existing `.github/workflows/release.yml` (PR #109).
   - **Gate**: tag `v0.7.0rc1` push → TestPyPI publish succeeds → manual smoke install works → tag `v0.7.0` push → PyPI publish succeeds.
2. **Build `/setup-prospector` skill.**
   - **Files**: `skills/setup-prospector/SKILL.md` (new, ~150 LOC).
3. **Port setup-state helper from JS to Python.**
   - **Files**: `hooks/lib/setup_state.py` (new, ~150 LOC); `tests/unit/test_setup_state.py` (new, ~250 LOC, 12 cases).
4. **SessionStart hook banner.**
   - **Files**: `hooks/check-prospector-setup.py` (new, ~120 LOC); `hooks/hooks.json` (modified — add `SessionStart` entry).
   - **Tests**: `tests/unit/test_check_prospector_setup.py` (new) — MISSING / STALE / VALID / BROKEN banner assertions; import-probe-fails → flag-deletion behaviour. `tests/unit/test_skill_tracker_guard.py` (new) — asserts `skill-tracker.py` exits 0 silent on non-VALID state. `tests/unit/test_dashboard_regen_guard.py` (new) — asserts `dashboard-regen.py` exits 0 silent on non-VALID state and spawns `<venv-python>` (absolute path) when VALID; covers both subprocess callsites.
5. **Rewire existing hooks to use venv-python.**
   - **Files**: `hooks/skill-tracker.py` (+20 — add VALID guard); `hooks/dashboard-regen.py` (+30 -12 — add VALID guard, replace `sys.executable` with `get_venv_python(flag.venv_path)` in both callsites, drop `.parent.parent.parent` cwd inference).
6. **CI smoke test + README update.**
   - **Files**: `tests/integration/setup_pipeline.py` (new, ~320 LOC); `tests/integration/test_setup_skill.py` (new, ~120 LOC); `tests/test_skill_pipeline_sync.py` (new, ~80 LOC); `.github/workflows/ci.yml` (modified — `skill-smoke-{ubuntu,windows}` jobs); `README.md` (modified — first-run setup section).

Each AC is independently verifiable by reading the listed files at the
implementation PR.

---

## § 11. Migration & rollout

### 11.1 Version target

`v0.7.0`. Pre-release rehearsal: `v0.7.0rc1` to TestPyPI first; bump to
`v0.7.0` for the real PyPI publish after the rc validates.

### 11.2 Breaking-change disclosure

Pattern W changes first-run behaviour for new installs (banner on first
session) and adds a one-time setup requirement for existing v0.6.0
users. No CLI flag, no hook payload shape, no dashboard output, no
skill behaviour changes. SemVer minor bump is appropriate.

### 11.3 CHANGELOG entry shape

```markdown
## [0.7.0] - 2026-MM-DD

### Added

- `/setup-prospector` skill: materialises a plugin-owned Python venv at
  `${CLAUDE_PLUGIN_DATA}/venv/` and writes a setup-state flag. Required
  once after install or after a plugin update.
- `SessionStart` hook: surfaces a banner when setup is required and
  runs a per-session import probe to detect venv corruption.
- `hooks/lib/setup_state.py`: shared deterministic helper for flag I/O,
  version comparison, and venv-python path resolution.
- CI: `skill-smoke-{ubuntu,windows}` jobs validate the full setup
  pipeline on every PR against real Python and real pip.

### Changed

- `hooks/dashboard-regen.py` no longer guesses the venv root via
  `Path(sys.executable).parent.parent.parent`. The dashboard regen
  subprocess is spawned with the absolute path recorded in the
  setup-state flag.
- `claude-prospector` is now published to PyPI. The setup skill
  installs from PyPI by default; the `CLAUDE_PROSPECTOR_PIP_SPEC` env
  var allows installing from a local checkout for development.

### Migration from v0.6.0

After upgrading to v0.7.0, open a new Claude Code session. A
SessionStart banner will prompt you to run `/setup-prospector`. This is
a one-time action per machine per major version.

If you previously installed `claude-prospector` into `~/.claude/.venv`
(the user-managed venv approach), you can leave that install in place —
Pattern W's hooks always spawn the plugin-owned venv via an absolute
path and will not pick up the legacy install. To reclaim disk, you may
`uv pip uninstall claude-prospector` from `~/.claude/.venv` after
Pattern W is working; this is optional and unrelated to plugin
operation.

The `${user_config.autoregen}` setting is preserved across the upgrade.
The legacy `config.json` migration mechanism added in v0.6.0 continues
to function unchanged.

**Harness Python requirement.** Pattern W does **not** remove the
requirement for a working harness Python. The hook scripts
(`check-prospector-setup.py`, `skill-tracker.py`, `dashboard-regen.py`)
still run under the harness-provided `python` (per `hooks/hooks.json`).
They do not require `claude-prospector` to be installed in the harness
Python, but they do require a working harness Python. Users who remove
their harness-environment Python entirely will break the plugin's
SessionStart, PreToolUse, and Stop hooks. The venv created by
`/setup-prospector` is for **subprocess spawning by the hooks**, not for
the hook scripts themselves.
```

### 11.4 README first-run-setup section (draft)

```markdown
## First-run setup

After installing claude-prospector for the first time (or after a
plugin update), open a new Claude Code session. You'll see a banner:

> claude-prospector requires setup. Run /setup-prospector to materialize
> the Python venv.

Run `/setup-prospector` once. The skill will:

1. Discover a Python 3.10+ interpreter on your system.
2. Create a plugin-owned venv at `${CLAUDE_PLUGIN_DATA}/venv/`.
3. Install `claude-prospector` from PyPI into that venv.
4. Verify the install and record a setup-state flag.

After setup completes, open a new session — the banner will be gone and
the dashboard, skill-tracking, and usage-analysis features will work
normally.

You'll need to re-run `/setup-prospector` only when:

- The plugin updates to a new version (banner: "venv is for vX but
  plugin is vY").
- The venv is corrupted or deleted (banner: "venv at <path> is
  unreachable or corrupt").
- You move to a new machine (per-machine setup; flag is not portable
  across machines).

**Note:** Pattern W does not remove the harness Python requirement. The
plugin's hook scripts still run under the harness-provided `python` and
require a working harness-environment Python interpreter. The venv
created by `/setup-prospector` is used by the hooks for subprocess
spawning only — not to run the hook scripts themselves.
```

---

## § 12. Out of scope / deferred

The following are explicitly **not** in this spec:

- **macOS CI coverage.** See § 9.5. Track as a follow-up if a macOS
  user files a Pattern W-related issue.
- **Removing the defensive `_get_allowlist()` ImportError fallback.**
  Per invariant 6 (§ 8), it stays. A future spec could revisit if
  `skill-tracker.py` itself is rewired to run inside the venv-python
  rather than the harness Python — out of scope here.
- **Removing the three-tier `CLAUDE_PROSPECTOR_BASE_DIR` resolver.**
  Pattern W governs install-state only. Runtime artifacts (skill-
  tracking JSONL, dashboard HTML, hook.log) keep the three-tier
  resolver. Conflating the two would re-introduce the v0.5.0 migration
  surface this spec deliberately leaves alone.
- **A breaking v1.0.0 cutover.** D12: minor bump is sufficient.
- **JS port of the hooks.** D8: rejected.
- **Bundled wheel install.** D1: rejected.
- **Bumping `requires-python` to >= 3.11.** D10: rejected.
- **macOS-specific Microsoft Store Python shim workarounds.** Same
  treatment as wayfinder: users hit by this take the F1 ask-user path.

---

## § 13. References

- `claude-wayfinder` spec: `I:/other/claude-wayfinder/docs/superpowers/specs/2026-05-17-setup-skill-architecture-design.md`
- `glitchwerks/claude-prospector#107` (tracking)
- `glitchwerks/claude-prospector#109` (PyPI release workflow — merged)
- `hooks/dashboard-regen.py:74-95` (three-tier `_base_dir()`)
- `hooks/dashboard-regen.py:506-514` (version-check subprocess with `.parent.parent.parent` cwd)
- `hooks/dashboard-regen.py:543-560` (dashboard regen subprocess with `.parent.parent.parent` cwd)
- `hooks/skill-tracker.py:35-56` (parallel three-tier `_base_dir()`)
- `hooks/skill-tracker.py:107-119` (defensive ImportError fallback)
- `hooks/hooks.json:14-23` (Stop hook `${user_config.autoregen}` substitution)
- `pyproject.toml:9` (`requires-python = ">=3.10"`)
- `.claude-plugin/plugin.json:13-19` (`userConfig.autoregen`)
- Anthropic `${CLAUDE_PLUGIN_DATA}` docs, fetched 2026-05-16 — see
  `claude-code-plugin-authoring` skill § 4 (link:
  `https://code.claude.com/docs/en/plugins-reference#environment-variables`)

---

## § 14. Open questions (post-reviewer status)

These were surfaced for the `project-reviewer` pass. All three have
been ratified.

1. ~~**Should `tests/integration/setup_pipeline.py` use `uv` instead of
   `pip` for the install step?**~~ **Ratified — promoted to D13.**
   Decision: use `pip` inside the venv for the end-user path; `uv`
   allowed in test fixtures only. See D13 in § 2 for the full rationale.
2. **Should the `SessionStart` banner suppress itself on the very
   first install** (no flag yet) to avoid a confusing "requires setup"
   message before the user has had a chance to learn the plugin
   exists? **Ratified — proposed answer accepted, no further action.**
   The banner is the discovery mechanism. Mirrors wayfinder.
3. **Should the import probe also assert
   `claude_prospector.__version__ == flag.version`?** **Ratified —
   proposed answer accepted, no further action.** Probe stays minimal
   (importability only). Version-mismatch downgrades to STALE via the
   version field at the next SessionStart, which is the correct
   recovery path.

---

*Generated by Claude Code (project-planner) on behalf of @cbeaulieu-gt*
