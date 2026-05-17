---
title: "#67 one-step plugin update — eliminate separate `uv pip install`"
touches:
  - claude_prospector/paths.py
  - claude_prospector/__init__.py
  - hooks/dashboard-regen.py
  - hooks/hooks.json
  - .claude-plugin/plugin.json
  - .github/workflows/ci.yml
  - README.md
  - tests/test_dashboard_regen_hook.py
  - tests/test_version_flag.py
  - tests/test_session_start_install.py
skills_relevant:
  - claude-code-plugin-authoring
  - python
  - github-actions
---

# #67 — One-step plugin update (design pass, 2026-05-17)

Scoping issue: [#105](https://github.com/glitchwerks/claude-prospector/issues/105). Parent feature issue: [#67](https://github.com/glitchwerks/claude-prospector/issues/67).

## 1. Why a fresh pass

The original [#67 analysis](https://github.com/glitchwerks/claude-prospector/issues/67) (dated 2026-05-15) tentatively favored **E2 (`uvx --from`)** with **E1 (vendor jinja2)** as fallback. Three shifts since then change the matrix:

1. **`${CLAUDE_PLUGIN_DATA}` is load-bearing.** Merged in [PR #96](https://github.com/glitchwerks/claude-prospector/pull/96) (v0.5.0). Documented as the Anthropic-canonical persistent state dir in [Plugins reference § Environment variables](https://code.claude.com/docs/en/plugins-reference#environment-variables) (fetched 2026-05-16). Survives `claude plugin update`. Already wired in `claude_prospector/paths.py:L46-L75` as tier 2 of base-dir resolution, with legacy-dir migration at `paths.py:L151-L192`.
2. **`uv` is already in CI.** `.github/workflows/ci.yml:L20-L22, L42-L44` use `astral-sh/setup-uv@v5` on both lint (ubuntu) and test (ubuntu + windows). `uv` is a CI dependency today.
3. **Runtime dep surface is minimal.** `pyproject.toml:L10-L12` declares only `jinja2>=3.1`. The optional `packaging` import at `hooks/dashboard-regen.py:L242` has a tuple-comparison fallback. Hook scripts (`hooks/skill-tracker.py`, `hooks/dashboard-regen.py`) are stdlib-only at import time; the third-party reach happens via subprocess into `python -m claude_prospector` (`dashboard-regen.py:L508-L514, L544-L560`).

## 2. Option matrix (updated)

| Dimension | E1 — Vendor `jinja2` + `markupsafe` | E2 — `uvx --from "${CLAUDE_PLUGIN_ROOT}"` materializing into `${CLAUDE_PLUGIN_DATA}/venv` | B — JS rewrite |
|---|---|---|---|
| **Runtime cost (per session-end)** | ~0 ms (in-process) | ~30–80 ms warm; 2–5 s cold first run | ~0 ms |
| **First-run cost** | 0 (shipped in plugin cache) | 2–5 s (`uv` resolves + installs into `${CLAUDE_PLUGIN_DATA}/venv`) | 0 |
| **Repo size delta** | +~1.5 MB (jinja2 ~700 KB + markupsafe ~200 KB + tests stripped) | 0 | -large delta after port, +~3000 LOC churn |
| **Update cadence for jinja2 security fixes** | Manual; author must re-vendor and bump `version` in `plugin.json` | Automatic on next `claude plugin update` (`uv` re-resolves against `pyproject.toml`) | N/A |
| **Cross-platform** | Identical on win/lin/mac — pure-python jinja2 has no C extensions | Depends on `uv` on user PATH; Windows has known `uv` shim quirks but is supported (`setup-uv@v5` runs `windows-latest` in our own CI) | Identical |
| **`uv` runtime prereq for end-users** | None (today: users `uv pip install -e .`; after E1: nothing) | **Yes** — `uv` becomes a hard runtime prereq | None |
| **Failure modes** | sys.path shadowing if user has site-installed jinja2; security lag; vendor-dir missing if mis-packaged | `uv` not on PATH; cache corruption; first-run latency mistaken for hang; venv-materialize SessionStart hook ordering | N/A — not under evaluation |
| **Code complexity** | Add `vendor/` dir + a sys.path bootstrap in `claude_prospector/__init__.py` | Add SessionStart hook + venv-materialize script + change subprocess invocation from `sys.executable -m claude_prospector` to `uvx`/venv-python | High — full port |
| **Lockstep guarantee** | Yes — vendor is part of the plugin cache copy (`${CLAUDE_PLUGIN_ROOT}`) | Yes — `uv` resolves against `${CLAUDE_PLUGIN_ROOT}/pyproject.toml` on materialize | Yes |

**B is not under evaluation** in this spec (per #105 out-of-scope). Kept as a v1.0 placeholder.

## 3. Recommendation: **E1 (vendor jinja2)**

Pick E1. Justification, ranked:

1. **Zero new runtime prereq.** E2 makes `uv` a hard dependency the user can't fail-soft on. The plugin's whole value prop is "show me my usage at session end" — taking that out of the user's hands because `uv` isn't on PATH is a worse failure than the current two-step install. E1 has no such prereq.
2. **The dep surface is tiny.** One pure-python dependency (`jinja2>=3.1`, plus its single transitive `markupsafe`). The "manual security cadence" downside of vendoring shrinks proportionally — there is one library to watch, and jinja2's security advisories are infrequent and well-publicized. Compare to a project with a dep tree of dozens, where vendoring becomes unmanageable.
3. **Anthropic's documented `${CLAUDE_PLUGIN_DATA}` pattern fits E2 best when there's *something to materialize* — `npm install` of a real `package.json`, or a Python venv with multiple deps and a build step.** For a single pure-python dep, materializing a venv on every session start (or even just first-run) is overkill: it spends 2–5 s of latency and ~30 MB of disk to install one package that could have been a 700 KB file in the plugin cache.
4. **No SessionStart hook ordering hazard.** E2 needs a SessionStart hook (per [Plugins reference § Environment variables](https://code.claude.com/docs/en/plugins-reference#environment-variables), fetched 2026-05-16) to materialize the venv before the Stop hook ever runs. That hook has to be idempotent, fast on hot path, and correct on first session after `claude plugin update`. E1 skips the entire surface.
5. **Repo bloat is small and bounded.** ~1.5 MB after stripping tests/docs from the vendored package. The repo today is ~2 MB. Acceptable.

**Acceptable hedge:** if a future release adds a second non-trivial runtime dep (e.g. `httpx`, a templating extension, anything with C extensions), revisit E2 — at that point the vendor-dir maintenance cost crosses over the `uv`-prereq cost.

## 4. Implementation plan, keyed to #67 ACs

### AC1: Single `claude plugin update claude-prospector@glitchwerks` ships new Python changes

**Files:**
- `vendor/jinja2/` and `vendor/markupsafe/` (new) — vendored source dirs. Strip `tests/`, `docs/`, `*.dist-info/RECORD` to minimize bloat.
- `claude_prospector/__init__.py` — prepend `vendor/` to `sys.path` *before* the `importlib.metadata` import. Specifically: insert `Path(__file__).resolve().parent.parent / "vendor"` at `sys.path[0]` so vendored copies win over user-site installs (addresses the "vendored jinja2 conflicts with user-site jinja2" failure mode in § 5).
- `pyproject.toml` — keep `jinja2>=3.1` as a declared dep for the dev-install case (so `pytest` running in CI still installs it normally), but ensure the runtime path uses vendor first. Add a `tool.setuptools.package-data` or equivalent to include `vendor/` in the wheel if anyone still installs that way; for the plugin-cache invocation path, `vendor/` is already shipped because it's in the repo.
- **No subprocess change required** at `dashboard-regen.py:L508-L514, L544-L560` — they keep calling `sys.executable -m claude_prospector`. The plugin-cache copy of `claude_prospector/__init__.py` sets `sys.path` correctly before any jinja2 import.

**Critical change:** `dashboard-regen.py` currently invokes `[sys.executable, "-m", "claude_prospector", ...]` with `cwd=str(Path(sys.executable).parent.parent.parent)` (lines 513, 559). `sys.executable` here is whichever Python Claude Code is using — *not* the plugin's. For `claude_prospector` to be importable, it must either (a) already be `pip install`-ed in that Python (today's two-step), or (b) be reachable via `sys.path`.

E1 changes this by:
- Adding `${CLAUDE_PLUGIN_ROOT}` to `PYTHONPATH` in the hook command so `claude_prospector` and its `vendor/` are importable without installation.
- Updating `hooks/hooks.json` line 19 from `python "${CLAUDE_PLUGIN_ROOT}/hooks/dashboard-regen.py" ...` to set env: this is best done by changing `dashboard-regen.py:L508-L514, L544-L560` to call `[sys.executable, "-c", "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}'); ...]` — *or* (cleaner) by passing `env={**os.environ, "PYTHONPATH": plugin_root + os.pathsep + os.environ.get("PYTHONPATH", "")}` to `subprocess.run`.

The cleaner subprocess-env-injection is preferred. The hook script already reads `CLAUDE_PLUGIN_ROOT` at `dashboard-regen.py:L496`; thread it into the two `subprocess.run` calls.

**Verification:** new test `tests/test_session_start_install.py` (despite the name — repurposed for E1 as `tests/test_vendored_import.py`) that spawns the dashboard subprocess in an isolated env (`PYTHONPATH=`, no site-packages jinja2) and asserts the dashboard renders successfully.

### AC2: No `uv pip install` in user-facing install docs

**Files:**
- `README.md:L22-L26, L82-L85` — remove the `uv pip install -e .` and `uv pip install "git+https://..."` install steps from the install section. Replace with the single `claude plugin install claude-prospector@glitchwerks` line. Keep `uv pip install -e ".[dev]"` only in a clearly-marked **Contributor setup** section (so the dev workflow stays usable).
- `hooks/dashboard-regen.py:L362-L363` — delete the hardcoded `uv pip install --upgrade ...` string from `_version_mismatch_page`. See AC4 for the page's full fate.
- `hooks/dashboard-regen.py:L330-L335` — `_python_not_found_page` references "Make sure the claude-prospector Python package is installed". With vendoring, the package is always present in the plugin cache. Rewrite this page to surface a different real failure mode (e.g. "Python interpreter not found on PATH"); see § 5.
- `.claude-plugin/plugin.json` — `description` does not currently reference `uv pip install`; no change needed. Verified by reading `.claude-plugin/plugin.json:L4`.

**Verification:** `tests/test_readme_no_pip_install.py` — grep-style assertion that the README install section does not contain `uv pip install` (with an allowlist for the contributor section). A simple regex on the file's `## Install` section.

### AC3: CI verifies the bundled invocation path on Linux + Windows

**Files:**
- `.github/workflows/ci.yml` — add a new job `plugin-invocation` to the test matrix. It must:
  1. Check out the repo.
  2. **Not** run `uv pip install -e ".[dev]"` for the test under test (that's what we're trying to prove unnecessary). Run only `actions/setup-python@v5` to get bare Python.
  3. Set `CLAUDE_PLUGIN_ROOT=$PWD` and `CLAUDE_PLUGIN_DATA=$RUNNER_TEMP/plugin-data`.
  4. Invoke `python hooks/dashboard-regen.py --autoregen true` after seeding a minimal usage-log fixture.
  5. Assert the resulting dashboard HTML exists and contains expected jinja2-rendered markers.
- Existing `lint` and `test` jobs keep `uv pip install --system -e ".[dev]"` for their respective purposes (linting needs ruff; pytest needs pytest). Only the new `plugin-invocation` job runs bare.
- Matrix: `[ubuntu-latest, windows-latest]`, Python 3.10. (Mac is not in the existing matrix; do not expand scope here.)

**Verification:** the new job itself is the verification. Failure on either OS blocks merge.

### AC4: Version-pin failure machinery becomes structurally unreachable — **delete, do not keep as defense-in-depth**

The version-mismatch path in `dashboard-regen.py:L495-L531` exists because the Python package and the plugin manifest can drift when installed separately. After E1 lands, they are **literally the same files on disk**: `claude_prospector/__init__.py`'s `__version__` resolves via `importlib.metadata` (`__init__.py:L5-L10`), and the plugin cache copy is the source of both. There is no possible drift.

**Files (delete):**
- `hooks/dashboard-regen.py:L220-L260` — `_version_tuple` and `_compare_versions`.
- `hooks/dashboard-regen.py:L344-L370` — `_version_mismatch_page`.
- `hooks/dashboard-regen.py:L495-L531` — the version-pin check block in the main function.
- `tests/test_dashboard_regen_hook.py:L223-L248` — the entire `TestVersionMismatch` class.

**Files (keep):**
- `hooks/dashboard-regen.py:L322-L341` — `_python_not_found_page`. Still reachable: Python may not be on PATH on a user's machine even if `claude_prospector` is bundled. Rewrite the body per AC2.
- `hooks/dashboard-regen.py:L373-L396` — `_regen_failed_page`. Reachable when the dashboard subprocess errors for any reason (template bug, malformed log data, OS file-permission). Keep.
- `claude_prospector/__init__.py:L5-L10` — `__version__` resolution. Still useful for `--version` CLI flag and for telemetry. Keep.
- `tests/test_version_flag.py:L46-L67` — `--version` CLI tests. Independent of version-mismatch; keep.

**Justification for deletion over defense-in-depth:** the machinery is non-trivial (~80 LOC across check + page + tests), and "defense-in-depth" against a structurally-impossible failure is dead code that confuses future readers. It implies the failure is still possible. After E1, it isn't. If a future change reintroduces independent installation (e.g. a v1.0 with system-pip support), the machinery can be re-added then with a clear motivating issue. Keep the git history; lose the dead code.

## 5. Failure-mode analysis (E1)

| Failure | Likelihood | User-facing UX | Mitigation |
|---|---|---|---|
| **User has `jinja2` installed in user site-packages, at a different (older or newer) version, that shadows the vendored copy** | Medium on dev machines; low for end-users | If older, dashboard may render with deprecation warnings or crash on a removed API. If newer, vendored copy still wins (we control `sys.path[0]`) | `claude_prospector/__init__.py` inserts vendor path at `sys.path[0]`, *before* `site-packages`. Test: `tests/test_vendored_import_wins.py` asserts that with a stub `jinja2` ahead in site-packages, `import jinja2; jinja2.__file__` resolves to the vendor copy. |
| **Vendor dir missing at runtime (e.g. user manually deleted it, or a packaging mistake left it out of the plugin cache)** | Low | Dashboard subprocess fails on `ImportError: jinja2`; `_regen_failed_page` shows the traceback | `_regen_failed_page` already captures stderr (`dashboard-regen.py:L373-L396`). The page is informative enough; no new code needed. |
| **jinja2 security CVE published; vendored copy is stale** | Low-frequency, high-severity when it hits | Silent — no user-facing signal until a release ships | Document a maintainer-side checklist in `CONTRIBUTING.md` (out of scope for this spec; tracked as follow-up). Subscribe to jinja2 security advisories via GitHub. Treat re-vendoring as a routine release task. |
| **Python interpreter not on PATH** | Low on dev machines; medium on stripped-down corp Windows installs | `subprocess.run([sys.executable, ...])` works inside dashboard-regen.py because `sys.executable` is the interpreter that just launched it. The failure mode is the hook *script* itself not launching — i.e. `python` in `hooks/hooks.json:L9, L19` fails to resolve | This is pre-existing and not in scope for #67. The current `hooks.json` already uses bare `python`; no regression introduced by E1. |
| **`vendor/` dir bloats clone time / install time noticeably** | Low | Slightly slower `claude plugin install` | ~1.5 MB delta on a current ~2 MB repo. Acceptable. Strip tests and docs from the vendored package to keep delta tight. |

## 6. Migration story (v0.6.0 → v0.7.0)

**For users on v0.6.0:** their environment currently has `claude-prospector` installed via `uv pip install -e .` (or `uv pip install "git+..."`). After upgrading via `claude plugin update`:

1. The plugin cache at `${CLAUDE_PLUGIN_ROOT}` updates to v0.7.0, which includes `vendor/jinja2`.
2. The user's existing `uv pip install`-ed copy of `claude-prospector` is still present in whichever Python `sys.executable` resolves to.
3. **The hook subprocess will find both:** the `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}` injection (AC1) places the plugin cache copy *first*. So the v0.7.0 cached copy is what runs, and it pulls jinja2 from its own `vendor/` dir.
4. The pip-installed v0.6.0 copy is harmless dead weight in the user's environment. It will not be invoked by the hook path.

**Recommended (optional) user action:** `uv pip uninstall claude-prospector`. Surface this in the v0.7.0 release notes as a cleanup step, not a required one. The plugin works correctly either way.

**Do not auto-uninstall.** The plugin has no business reaching into the user's Python environments to remove packages. Surfacing it as a one-line release note is enough.

**For new users on v0.7.0+:** they never run `uv pip install`. The single `claude plugin install claude-prospector@glitchwerks` is sufficient. README install section reflects this (AC2).

## 7. Open questions

None blocking. Two follow-ups noted for downstream issues:

1. **Re-vendoring cadence and tooling.** Should `vendor/` be regenerated by a Makefile target / script (`scripts/revendor.sh` running `pip download --no-binary=:all: jinja2 markupsafe` + extraction + cleanup)? Track as a child issue.
2. **CONTRIBUTING.md update** documenting the jinja2 security-advisory subscription expectation for maintainers. Track as a child issue.

## 8. Source citations

All factual claims in this spec are backed by one of the following:

- `pyproject.toml:L7-L18`, `.claude-plugin/plugin.json:L1-L20`, `hooks/hooks.json:L1-L25`, `hooks/dashboard-regen.py:L220-L260, L322-L396, L490-L560`, `claude_prospector/paths.py:L46-L192`, `claude_prospector/__init__.py:L5-L10`, `tests/test_dashboard_regen_hook.py:L223-L248`, `.github/workflows/ci.yml:L1-L48`, `README.md:L22-L26, L82-L85` — verified via `Read` 2026-05-17.
- [Issue #67](https://github.com/glitchwerks/claude-prospector/issues/67) and [Issue #105](https://github.com/glitchwerks/claude-prospector/issues/105) — verified via `WebFetch` 2026-05-17.
- [PR #96](https://github.com/glitchwerks/claude-prospector/pull/96) — referenced in issue #105 body as the v0.5.0 PR that landed `${CLAUDE_PLUGIN_DATA}` support. `unverified:` PR body not directly fetched in this pass; the in-repo evidence at `claude_prospector/paths.py:L46-L75` confirms the mechanism is implemented.
- [Plugins reference § Environment variables](https://code.claude.com/docs/en/plugins-reference#environment-variables) (fetched 2026-05-16 per the `claude-code-plugin-authoring` skill).
