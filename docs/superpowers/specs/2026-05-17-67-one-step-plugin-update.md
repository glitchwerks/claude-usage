---
title: "#67 one-step plugin update — eliminate separate `uv pip install`"
touches:
  - claude_prospector/paths.py
  - claude_prospector/__init__.py
  - hooks/dashboard-regen.py
  - hooks/hooks.json
  - .claude-plugin/plugin.json
  - .github/workflows/ci.yml
  - pyproject.toml
  - README.md
  - tests/test_dashboard_regen_hook.py
  - tests/test_version_flag.py
  - tests/test_vendored_import.py
---

# #67 — One-step plugin update (design pass, 2026-05-17)

Scoping issue: [#105](https://github.com/glitchwerks/claude-prospector/issues/105). Parent feature issue: [#67](https://github.com/glitchwerks/claude-prospector/issues/67).

## Revision 2 (2026-05-17)

Addresses 9 findings from `project-reviewer`:

- **BLOCKING-1** — AC1 rewritten to make explicit that PYTHONPATH injection (on the subprocess `env`) and `__init__.py` `sys.path.insert(0, vendor)` are **two cooperating mechanisms**, not alternatives. Added numbered import-chain walkthrough.
- **BLOCKING-2** — Added explicit implementation note: drop the `cwd=str(Path(sys.executable).parent.parent.parent)` argument at both `subprocess.run` sites; new test asserts no cwd dependency.
- **CONCERN-3** — Decision: add a `plugin.json` version-field fallback in `__init__.py` (`importlib.metadata.PackageNotFoundError` → read manifest JSON). Defended in AC4.
- **CONCERN-4** — CI verification step now asserts `! python -c "import jinja2"` succeeds (i.e. import fails) *before* the hook runs, in a clean venv, so vendor isolation is actually proven.
- **CONCERN-5** — `_regen_failed_page` rewritten to suggest `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python -m claude_prospector dashboard --window 7d`. Added to AC2 file list.
- **CONCERN-6** — Explicit `PYTHONPATH = str(plugin_root) + os.pathsep + os.environ.get("PYTHONPATH", "")` ordering called out at both call sites; new test sets a user PYTHONPATH and asserts the plugin root still wins.
- **NIT-7** — Test file standardized to `tests/test_vendored_import.py` in frontmatter + body.
- **NIT-8** — `pyproject.toml` added to `touches:`.
- **NIT-9** — Follow-up Makefile + CONTRIBUTING.md mentions in § 7 struck (no issue numbers, no commitment).

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

1. **Zero new runtime prereq.** E2 makes `uv` a hard dependency the user can't fail-soft on.
2. **The dep surface is tiny.** One pure-python dependency (`jinja2>=3.1`, plus `markupsafe`). Vendoring cost shrinks proportionally.
3. **`${CLAUDE_PLUGIN_DATA}` materialization fits E2 best when there's *something to materialize*** — multi-dep venvs with build steps. For a single pure-python dep, it's overkill.
4. **No SessionStart hook ordering hazard.** E1 skips the entire surface.
5. **Repo bloat is small and bounded.** ~1.5 MB on a ~2 MB repo. Acceptable.

**Acceptable hedge:** if a future release adds a second non-trivial runtime dep (e.g. `httpx`, anything with C extensions), revisit E2.

## 4. Implementation plan, keyed to #67 ACs

### AC1: Single `claude plugin update claude-prospector@glitchwerks` ships new Python changes

**Two cooperating mechanisms — both are required, neither alone is sufficient.**

The hook outer process (`hooks/dashboard-regen.py`) is stdlib-only by design and does NOT import `claude_prospector`. The `claude_prospector` import happens inside the **child subprocesses** spawned at `hooks/dashboard-regen.py:L508-L514` (the version check, slated for deletion per AC4) and `L544-L560` (the dashboard regen). For those children to (a) find `claude_prospector` at all, and (b) bind to the *vendored* jinja2 rather than any user-site copy, both of the following must be in place:

#### Mechanism A — `PYTHONPATH` injection on the child subprocess `env`

This is **how `claude_prospector` itself becomes importable** in the child. After E1 the package is no longer pip-installed; it lives only in the plugin cache at `${CLAUDE_PLUGIN_ROOT}`. The hook outer process must pass:

```python
env = {
    **os.environ,
    "PYTHONPATH": str(plugin_root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
}
subprocess.run([sys.executable, "-m", "claude_prospector", ...], env=env, cwd=None, ...)
```

**Ordering is load-bearing:** `str(plugin_root)` must be *prepended*, not appended. Any pre-existing user `PYTHONPATH` may also resolve `claude_prospector` (e.g. a dev checkout); prepending the plugin root guarantees the cached copy wins.

#### Mechanism B — `claude_prospector/__init__.py` `sys.path.insert(0, vendor)`

Mechanism A gets the child *into* `claude_prospector/__init__.py`. Once there, the package itself must guarantee the **vendored** jinja2 wins over any jinja2 the user happens to have installed in their site-packages. The package-init does this *before* any other import that might pull jinja2 transitively:

```python
# claude_prospector/__init__.py — runs in the child process
import sys
from pathlib import Path

_vendor = Path(__file__).resolve().parent.parent / "vendor"
if _vendor.is_dir():
    sys.path.insert(0, str(_vendor))   # prepend, so vendor wins over site-packages

# Then, and only then:
from importlib.metadata import version, PackageNotFoundError
try:
    __version__ = version("claude-prospector")
except PackageNotFoundError:
    # Plugin-cache install has no .dist-info — fall back to the plugin manifest.
    # See AC4 for rationale.
    import json
    _manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        __version__ = json.loads(_manifest.read_text(encoding="utf-8")).get("version", "0.0.0+unknown")
    except Exception:
        __version__ = "0.0.0+unknown"
```

#### Import chain (numbered)

1. SessionEnd fires. Claude Code invokes `python "${CLAUDE_PLUGIN_ROOT}/hooks/dashboard-regen.py"`.
2. `dashboard-regen.py` runs in `sys.executable` with its own (stdlib-only) imports. It reads `os.environ["CLAUDE_PLUGIN_ROOT"]` at `L496`.
3. `dashboard-regen.py` reaches the regen call site (`L544-L560`). It constructs `env` with `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}:$PYTHONPATH` and calls `subprocess.run([sys.executable, "-m", "claude_prospector", "dashboard", ...], env=env, cwd=None)`.
4. The child Python starts, sees `PYTHONPATH`, finds `claude_prospector/` under the plugin root, and begins executing `claude_prospector/__init__.py`.
5. `__init__.py` line 1 (after stdlib imports) inserts `${CLAUDE_PLUGIN_ROOT}/vendor` at `sys.path[0]`.
6. Anything in `claude_prospector` (or its transitive imports) that does `import jinja2` now resolves the vendored copy first, regardless of what's in site-packages.

**Drop either mechanism and the system fails:**
- Without A: `ModuleNotFoundError: No module named 'claude_prospector'` in the child.
- Without B: the child imports `claude_prospector` fine, but `import jinja2` resolves a stale user-site copy and may crash on a removed API or render with deprecation warnings.

#### Drop the `cwd=` workaround

Today, both `subprocess.run` sites pass `cwd=str(Path(sys.executable).parent.parent.parent)`. That was a workaround for the pre-E1 world where `claude_prospector` had to be `pip install`-ed to be importable; the `cwd` arg was an attempt to land the child in a directory where the installed package could be found. With Mechanism A in place, the `cwd` trick is **dead logic** — at best a no-op, at worst misleading future readers into thinking it's load-bearing. **Drop it.** Pass `cwd=None` (or omit the argument) at both call sites. The new test at `tests/test_vendored_import.py` will assert no cwd dependency by running the subprocess with `cwd=tempfile.gettempdir()` and verifying success.

#### Files

- `vendor/jinja2/` and `vendor/markupsafe/` (new) — vendored source dirs. Strip `tests/`, `docs/`, `*.dist-info/RECORD` to minimize bloat.
- `claude_prospector/__init__.py` — `sys.path.insert(0, vendor)` bootstrap (Mechanism B) **and** `importlib.metadata` → `plugin.json` version fallback per AC4.
- `hooks/dashboard-regen.py:L508-L514, L544-L560` — add `env=` kwarg with PYTHONPATH-prepend (Mechanism A); drop the `cwd=...` arg.
- `pyproject.toml` — add `[tool.setuptools.package-data]` to include `vendor/**` in the wheel for the dev-install case. The plugin-cache invocation path already gets `vendor/` because it's a verbatim copy of the repo.

**Verification:** `tests/test_vendored_import.py` (new) — spawn the dashboard subprocess in an isolated env (`PYTHONPATH=`, no site-packages jinja2 in the test venv) and assert (a) the dashboard renders, (b) `cwd` does not matter, (c) when a stub jinja2 is *added* to site-packages, the vendored copy still wins (Mechanism B), (d) when a user `PYTHONPATH` is set to a different `claude_prospector` checkout, the plugin-root copy still wins (Mechanism A ordering).

### AC2: No `uv pip install` in user-facing install docs

**Files:**
- `README.md:L22-L26, L82-L85` — remove `uv pip install -e .` and `uv pip install "git+https://..."` from the install section. Replace with `claude plugin install claude-prospector@glitchwerks`. Keep `uv pip install -e ".[dev]"` only under a **Contributor setup** section.
- `hooks/dashboard-regen.py:L362-L363` — delete the hardcoded `uv pip install --upgrade ...` string from `_version_mismatch_page`. See AC4 for the page's full deletion.
- `hooks/dashboard-regen.py:L330-L335` — `_python_not_found_page`: rewrite to surface the actual remaining failure (Python interpreter not on PATH).
- `hooks/dashboard-regen.py:L373-L396` — `_regen_failed_page`: today suggests `python -m claude_prospector dashboard --window 7d`. After E1 that command fails (no `.dist-info`, no `claude_prospector` on `sys.path` without PYTHONPATH). Rewrite to suggest:
  ```
  PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python -m claude_prospector dashboard --window 7d
  ```
  (POSIX form; document the PowerShell equivalent `$env:PYTHONPATH = $env:CLAUDE_PLUGIN_ROOT; python -m claude_prospector dashboard --window 7d` in a parenthetical.)
- `.claude-plugin/plugin.json` — no `uv pip install` reference today; no change beyond the version bump.

**Verification:** `tests/test_readme_no_pip_install.py` — assert the README install section contains no `uv pip install` (with an allowlist for the contributor section).

### AC3: CI verifies the bundled invocation path on Linux + Windows

**Files:**
- `.github/workflows/ci.yml` — add `plugin-invocation` job to the test matrix. It must:
  1. Check out the repo.
  2. Run `actions/setup-python@v5` for bare Python. **Do not** run `uv pip install -e ".[dev]"` for the system Python.
  3. Create a fresh venv (`python -m venv .ci-venv`) — explicitly empty, no inherited site-packages.
  4. **Vendor-isolation precondition:** activate `.ci-venv` and run `! python -c "import jinja2" 2>/dev/null`, asserting exit nonzero. This proves the venv has no jinja2 before the hook runs. If this step succeeds (i.e. jinja2 *is* importable), the vendor-isolation guarantee is unproven on this runner and the job must fail.
  5. Set `CLAUDE_PLUGIN_ROOT=$PWD` and `CLAUDE_PLUGIN_DATA=$RUNNER_TEMP/plugin-data`.
  6. Invoke `python hooks/dashboard-regen.py --autoregen true` after seeding a minimal usage-log fixture.
  7. Assert the resulting dashboard HTML exists and contains expected jinja2-rendered markers.
  8. After success, run `python -c "import jinja2; print(jinja2.__file__)"` in the same venv and assert the path is under `${CLAUDE_PLUGIN_ROOT}/vendor/` — proves the *vendored* copy is what ran, not some accidental fallback.
- Existing `lint` and `test` jobs keep `uv pip install --system -e ".[dev]"` for their respective purposes.
- Matrix: `[ubuntu-latest, windows-latest]`, Python 3.10.

**Verification:** the new job is the verification. Failure on either OS blocks merge. The precondition in step 4 is what distinguishes "the hook worked" from "the hook worked because of vendor isolation specifically."

### AC4: Version-pin failure machinery becomes structurally unreachable — **delete, do not keep as defense-in-depth**

The version-mismatch path in `dashboard-regen.py:L495-L531` exists because the Python package and the plugin manifest can drift when installed separately. After E1, they are **literally the same files on disk** in the plugin cache — there is no possible drift between `__version__` and the plugin manifest because both originate from the same `${CLAUDE_PLUGIN_ROOT}` snapshot.

**Files (delete):**
- `hooks/dashboard-regen.py:L220-L260` — `_version_tuple` and `_compare_versions`.
- `hooks/dashboard-regen.py:L344-L370` — `_version_mismatch_page`.
- `hooks/dashboard-regen.py:L495-L531` — the version-pin check block in the main function.
- `tests/test_dashboard_regen_hook.py:L223-L248` — the entire `TestVersionMismatch` class.

**Files (keep):**
- `hooks/dashboard-regen.py:L322-L341` — `_python_not_found_page`. Reachable.
- `hooks/dashboard-regen.py:L373-L396` — `_regen_failed_page`. Reachable.
- `claude_prospector/__init__.py:L5-L10` — `__version__` resolution, **with manifest fallback** (see below).
- `tests/test_version_flag.py:L46-L67` — `--version` CLI tests.

#### Manifest version fallback in `__init__.py`

`importlib.metadata.version("claude-prospector")` walks `sys.path` for a `*.dist-info` directory. The **plugin-cache install has none** — the package is reachable via PYTHONPATH (Mechanism A above) but no wheel was ever installed against it. Today, that returns the placeholder `"0.0.0+local"` (or raises `PackageNotFoundError` depending on Python version) for every plugin-cache user. After E1 that path becomes the *primary* path, so `--version` output and any `__version__`-based telemetry become permanently wrong unless we fix it.

**Decision: add a `plugin.json` manifest fallback.** When `importlib.metadata.version()` raises `PackageNotFoundError`, read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and use its `version` field. This is correct-by-construction in the plugin-cache path (the manifest *is* the authoritative version source for `claude plugin update`) and degrades gracefully in dev (developer's editable install will still have a `.dist-info` so the fallback never fires).

Why this matters in tandem with AC4's deletion: the deleted version-pin machinery rested on the assumption that "plugin cache is the single source of truth." That assumption is only as strong as `__version__` being correct in the plugin-cache path. With the manifest fallback, it is. Without it, the deletion would be defensible (drift is impossible) but `--version` output and telemetry would be silently broken — a smaller bug, but a real one.

**Why not skip the fallback and accept `"0.0.0+local"`?** Telemetry usage today is low, but `--version` is user-facing and the wrong number there is unambiguously a defect. The fallback is ~6 lines of code. The cost/benefit is clear.

**Justification for deleting the rest:** the version-mismatch machinery is ~80 LOC of dead code after E1. "Defense-in-depth against a structurally-impossible failure" is dead code that confuses readers and implies the failure is still possible. Keep git history; lose the dead code.

## 5. Failure-mode analysis (E1)

| Failure | Likelihood | User-facing UX | Mitigation |
|---|---|---|---|
| **User has `jinja2` in site-packages at a different version, shadowing the vendor copy** | Medium on dev machines; low for end-users | If older, dashboard may render with deprecation warnings or crash; if newer, vendored copy still wins (Mechanism B prepends vendor) | `__init__.py` inserts vendor path at `sys.path[0]`. Test: `tests/test_vendored_import.py` asserts the vendor copy wins against a stub site-packages jinja2. |
| **User has a different `claude_prospector` checkout on `PYTHONPATH`** | Low | Could import the wrong package; version mismatch with `vendor/` | Mechanism A *prepends* `${CLAUDE_PLUGIN_ROOT}` to PYTHONPATH. Test: `tests/test_vendored_import.py` sets a competing PYTHONPATH entry and asserts the plugin root wins. |
| **Vendor dir missing at runtime** | Low | Dashboard subprocess fails on `ImportError: jinja2`; `_regen_failed_page` shows traceback | `_regen_failed_page` captures stderr; the rewritten manual-diagnostic command (AC2) tells the user how to reproduce locally. |
| **jinja2 security CVE; vendored copy is stale** | Low-frequency, high-severity when it hits | Silent — no user-facing signal until a release ships | Treat re-vendoring as a routine release task. (Tooling and contributor-doc updates intentionally not bundled into this spec — see § 7.) |
| **`importlib.metadata` returns no version in plugin-cache install** | Certain (no `.dist-info` present) | Without fallback: `--version` shows wrong value and telemetry is wrong | Manifest fallback in `__init__.py` per AC4. |
| **Python interpreter not on PATH** | Low on dev; medium on stripped corp Windows | Hook script itself fails to launch | Pre-existing; not in scope for #67. |
| **`vendor/` dir bloats install** | Low | Slightly slower `claude plugin install` | ~1.5 MB on a ~2 MB repo. Acceptable. |

## 6. Migration story (v0.6.0 → v0.7.0)

**For users on v0.6.0:** their environment has `claude-prospector` installed via `uv pip install -e .` (or `uv pip install "git+..."`). After upgrading via `claude plugin update`:

1. The plugin cache at `${CLAUDE_PLUGIN_ROOT}` updates to v0.7.0, including `vendor/jinja2`.
2. The user's existing `uv pip install`-ed copy of `claude-prospector` is still present in whichever Python `sys.executable` resolves to.
3. **The hook subprocess will find both, but the plugin-cache copy wins** because Mechanism A *prepends* `${CLAUDE_PLUGIN_ROOT}` to `PYTHONPATH`. So the v0.7.0 cached copy is what runs, and it pulls jinja2 from its own `vendor/`.
4. The pip-installed v0.6.0 copy is harmless dead weight. It will not be invoked.

**The "newer user-installed jinja2 still wins" claim depends entirely on this prepend ordering.** The implementation note in AC1 and the corresponding test in `tests/test_vendored_import.py` make this explicit and verifiable.

**Recommended (optional) user action:** `uv pip uninstall claude-prospector`. Surface in release notes as cleanup, not a requirement.

**Do not auto-uninstall.** The plugin has no business reaching into the user's Python environments.

**For new users on v0.7.0+:** they never run `uv pip install`. `claude plugin install claude-prospector@glitchwerks` is sufficient.

## 7. Open questions

None blocking. Re-vendoring tooling and contributor-doc updates are intentionally **not** bundled into this spec and **not** filed as follow-up issues at spec-freeze time — if they prove necessary post-merge, file them then with concrete motivation rather than as speculative placeholders here.

## 8. Source citations

All factual claims in this spec are backed by one of the following:

- `pyproject.toml:L7-L18`, `.claude-plugin/plugin.json:L1-L20`, `hooks/hooks.json:L1-L25`, `hooks/dashboard-regen.py:L220-L260, L322-L396, L490-L560`, `claude_prospector/paths.py:L46-L192`, `claude_prospector/__init__.py:L5-L10`, `tests/test_dashboard_regen_hook.py:L223-L248`, `.github/workflows/ci.yml:L1-L48`, `README.md:L22-L26, L82-L85` — verified via `Read` 2026-05-17.
- [Issue #67](https://github.com/glitchwerks/claude-prospector/issues/67) and [Issue #105](https://github.com/glitchwerks/claude-prospector/issues/105) — verified via `WebFetch` 2026-05-17.
- [PR #96](https://github.com/glitchwerks/claude-prospector/pull/96) — referenced in issue #105 body as the v0.5.0 PR that landed `${CLAUDE_PLUGIN_DATA}` support. `unverified:` PR body not directly fetched in this pass; in-repo evidence at `claude_prospector/paths.py:L46-L75` confirms the mechanism is implemented.
- [Plugins reference § Environment variables](https://code.claude.com/docs/en/plugins-reference#environment-variables) (fetched 2026-05-16 per the `claude-code-plugin-authoring` skill).
