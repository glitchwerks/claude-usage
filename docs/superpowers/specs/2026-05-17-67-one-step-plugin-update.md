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
  - tests/test_readme_no_pip_install.py
---

# #67 — One-step plugin update (design pass, 2026-05-17)

Scoping issue: [#105](https://github.com/glitchwerks/claude-prospector/issues/105). Parent feature issue: [#67](https://github.com/glitchwerks/claude-prospector/issues/67).

## Revision 4 (2026-05-17)

Addresses 10 findings from `project-reviewer` Rev 3:

- **BLOCKING-1, BLOCKING-2, BLOCKING-3** — Resolved jointly by hoisting `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` to a job-level `env:` block, declaring `shell: bash` as the job-level default for all run-steps in the new `plugin-invocation` job, and replacing every `$PWD` with `${{ github.workspace }}`. The fully resolved YAML snippet is now embedded in AC3. This eliminates the cross-step propagation problem, the PowerShell-on-Windows step-5 mismatch, and the `$PWD` ambiguity in one stroke.
- **CONCERN-4** — Rewrote AC1's "Why in-package vendor and not top-level" paragraph. Editable installs would in fact reach a top-level `vendor/` via `__file__`-relative resolution (the existing `renderer.py:L15` proves this for `templates/`). The real load-bearing reason for in-package `vendor/` is the **wheel/sdist distribution path**: only `[tool.setuptools.package-data]` includes non-Python files in the built distribution, and `package-data` keys must name a package. A top-level `vendor/` cannot be packaged this way. The recommendation (in-package `vendor/`) is unchanged; the rationale is corrected so the implementer does not skip `package-data` thinking it is optional.
- **CONCERN-5** — `_vendor` expression unified to `Path(__file__).resolve().parent / "vendor"` in all three locations (inline code block, import-chain narrative, AC1 Files section). Matches `renderer.py:L15` convention; symlink-safe.
- **CONCERN-6** — `tests/test_readme_no_pip_install.py` mechanics nailed down: install-section boundary = `## Installation` heading through the next `##` heading or EOF; assertion = no line in that block matches the regex `^\s*\$?\s*uv pip install\b` (case-sensitive); allowlist = a sibling `## Development` (or similarly-named contributor) section is unconstrained.
- **CONCERN-7** — Outer-hook no-cwd test specification now requires supplying `--autoregen true` (else the hook hits the early-return gate at `dashboard-regen.py:L490` and proves nothing), `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` env vars (pointed at a tmp dir), and a minimal session-log fixture (or stubbed parser) so the regen path executes from the unusual cwd.
- **NIT-8** — `[\d]+` simplified to `\d+` in the `_VERSION_RE` example.
- **NIT-9** — Acknowledged; no action.
- **NIT-10** — Added a one-line note in AC4 flagging that `dashboard-regen.py:L499` has a pre-existing path bug (`Path(plugin_root_env) / "plugin.json"` is wrong — manifest lives at `.claude-plugin/plugin.json`); the AC4 deletion removes the buggy line; the new `__init__.py` manifest fallback correctly uses `.claude-plugin/plugin.json`.

## Revision 3 (2026-05-17)

Addresses 10 findings from `project-reviewer` Rev 2 (NIT-11 was already clean — no action):

- **BLOCKING-1** — CI precondition + post-condition steps gain `shell: bash` so the `!`-negation and assertion both run under Git Bash on `windows-latest`.
- **BLOCKING-2** — Step 8 post-condition rewritten: runs `PYTHONPATH=$PWD python -c "import jinja2; print(jinja2.__file__)"` then a follow-up `assert 'vendor' in jinja2.__file__` so the assertion can actually succeed and proves the vendored copy is what imports.
- **BLOCKING-3** — Vendor relocated **inside the package** at `claude_prospector/vendor/`. Cascades through `_vendor = Path(__file__).parent / "vendor"`, `[tool.setuptools.package-data] "claude_prospector" = ["vendor/**/*"]`, import-chain narrative, CI post-condition `jinja2.__file__` expected pattern, and the `touches:` list (which already names `claude_prospector/__init__.py`).
- **CONCERN-4** — `tests/test_version_flag.py` regex update spelled out in AC4 "Kept files" — fixes quantifier typo and adds the `0.0.0+unknown` sentinel.
- **CONCERN-5** — `tests/test_readme_no_pip_install.py` added to `touches:`.
- **CONCERN-6** — PowerShell diagnostic in `_regen_failed_page` uses child-scope `& { $env:PYTHONPATH = ...; python -m ... }` to avoid poisoning the user's shell.
- **CONCERN-7** — New outer-hook no-cwd test: runs `hooks/dashboard-regen.py` itself from `tempfile.gettempdir()` to catch any latent `os.getcwd()` dependency in the hook process (not just the child subprocess).
- **NIT-8** — Import-chain step 3 now uses `${os.pathsep}` notation to be cross-platform-explicit.
- **NIT-9** — "pass `cwd=None`" reworded to "omit the `cwd` keyword argument entirely".
- **NIT-10** — Manifest fallback `except Exception` gains a one-line prose explanation of the deliberate breadth (covers `PackageNotFoundError`, `FileNotFoundError`, `JSONDecodeError`, `KeyError`).

## Revision 2 (2026-05-17)

Addressed 9 findings from `project-reviewer` Rev 1: import-chain narrative, drop-cwd note, manifest version fallback, CI precondition for vendor isolation, `_regen_failed_page` PYTHONPATH guidance, prepend-ordering test, test-file naming, `pyproject.toml` in `touches:`, and removal of speculative follow-ups.

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

_vendor = Path(__file__).resolve().parent / "vendor"   # in-package: claude_prospector/vendor/
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
        # Deliberately broad: catches PackageNotFoundError (no .dist-info),
        # FileNotFoundError (manifest missing), JSONDecodeError (manifest corrupt),
        # and KeyError (no "version" key). All four collapse to the same sentinel —
        # there is nothing else useful to do here, and the sentinel is itself the signal.
        __version__ = "0.0.0+unknown"
```

**Why in-package vendor and not a top-level `vendor/`?** The load-bearing reason is the **wheel/sdist distribution path**, not editable installs. Editable installs would in fact find a top-level `vendor/` through `__file__`-relative resolution — the existing `claude_prospector/renderer.py:L15` does exactly this for `templates/`, computing `Path(__file__).resolve().parent.parent / "templates"`, and it works in editable mode because `__file__` points into the source tree. So a top-level `vendor/` would *work in dev*.

It would fail in the wheel/sdist path: `[tool.setuptools.package-data]` is the only mechanism that includes non-Python files in a built distribution, and its keys must name a package. A top-level `vendor/` sibling to `claude_prospector/` cannot be packaged this way and would be silently dropped from the wheel. If the plugin install path ever moves from "verbatim repo copy" to "install the wheel" (today it is the former; this could change), a top-level `vendor/` becomes invisible at runtime. Placing `vendor/` inside the package tree (`claude_prospector/vendor/`) makes it reachable through `[tool.setuptools.package-data] "claude_prospector" = ["vendor/**/*"]` for both the wheel path and the plugin-cache verbatim-copy path (`${CLAUDE_PLUGIN_ROOT}/claude_prospector/vendor/`).

`package-data` is not optional polish — it is what makes the in-package location actually correct for distribution. Do not skip it.

#### Import chain (numbered)

1. SessionEnd fires. Claude Code invokes `python "${CLAUDE_PLUGIN_ROOT}/hooks/dashboard-regen.py"`.
2. `dashboard-regen.py` runs in `sys.executable` with its own (stdlib-only) imports. It reads `os.environ["CLAUDE_PLUGIN_ROOT"]` at `L496`.
3. `dashboard-regen.py` reaches the regen call site (`L544-L560`). It constructs `env` with `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}${os.pathsep}$PYTHONPATH` (`:` on POSIX, `;` on Windows) and calls `subprocess.run([sys.executable, "-m", "claude_prospector", "dashboard", ...], env=env)` — `cwd` keyword omitted entirely.
4. The child Python starts, sees `PYTHONPATH`, finds `claude_prospector/` under the plugin root, and begins executing `claude_prospector/__init__.py`.
5. `__init__.py` line 1 (after stdlib imports) inserts `${CLAUDE_PLUGIN_ROOT}/claude_prospector/vendor` at `sys.path[0]`.
6. Anything in `claude_prospector` (or its transitive imports) that does `import jinja2` now resolves the vendored copy first, regardless of what's in site-packages.

**Drop either mechanism and the system fails:**
- Without A: `ModuleNotFoundError: No module named 'claude_prospector'` in the child.
- Without B: the child imports `claude_prospector` fine, but `import jinja2` resolves a stale user-site copy and may crash on a removed API or render with deprecation warnings.

#### Drop the `cwd=` workaround

Today, both `subprocess.run` sites pass `cwd=str(Path(sys.executable).parent.parent.parent)`. That was a workaround for the pre-E1 world where `claude_prospector` had to be `pip install`-ed to be importable; the `cwd` arg was an attempt to land the child in a directory where the installed package could be found. With Mechanism A in place, the `cwd` trick is **dead logic** — at best a no-op, at worst misleading future readers into thinking it's load-bearing. **Drop it.** Omit the `cwd` keyword argument entirely at both call sites. The new test at `tests/test_vendored_import.py` will assert no cwd dependency by running the child subprocess with `cwd=tempfile.gettempdir()` and verifying success.

A complementary test runs the **outer hook** `hooks/dashboard-regen.py` itself from `tempfile.gettempdir()` to catch any latent `os.getcwd()` dependency in the hook process — not just the child subprocess. **The test must drive the hook all the way through its regen path; the default early-return at `dashboard-regen.py:L490` (autoregen gate) means a naive `subprocess.run([sys.executable, str(hook_path)], cwd=tempfile.gettempdir(), ...)` would only prove the early-exit path doesn't crash.** Required test setup:

- Pass `--autoregen true` as a CLI arg (or otherwise satisfy the gate at L490).
- Supply `CLAUDE_PLUGIN_ROOT` in the child env (pointed at the repo root so `claude_prospector` and its `vendor/` are reachable).
- Supply `CLAUDE_PLUGIN_DATA` in the child env (pointed at a tmp dir so dashboard output and any persistent state land somewhere reapable).
- Seed a minimal session-log fixture under `CLAUDE_PLUGIN_DATA` (or monkeypatch the aggregator entry point), so the regen path has something to render.

Only with all four in place does the test actually exercise the regen path from an unusual cwd. Without them it rubber-stamps a no-op.

#### Files

- `claude_prospector/vendor/jinja2/` and `claude_prospector/vendor/markupsafe/` (new) — vendored source dirs **inside the package tree**. Strip `tests/`, `docs/`, `*.dist-info/RECORD` to minimize bloat.
- `claude_prospector/__init__.py` — `sys.path.insert(0, vendor)` bootstrap with `_vendor = Path(__file__).resolve().parent / "vendor"` (Mechanism B) **and** `importlib.metadata` → `plugin.json` version fallback per AC4.
- `hooks/dashboard-regen.py:L508-L514, L544-L560` — add `env=` kwarg with PYTHONPATH-prepend (Mechanism A); drop the `cwd=...` arg.
- `pyproject.toml` — add `[tool.setuptools.package-data]` with `"claude_prospector" = ["vendor/**/*"]` to include the vendored tree in the wheel for the dev-install case. The plugin-cache invocation path already gets `claude_prospector/vendor/` because it's a verbatim copy of the repo.

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
  (POSIX form; document the PowerShell equivalent using a **child-scope script block** so the env mutation dies with the scope and does not poison the user's shell: `& { $env:PYTHONPATH = $env:CLAUDE_PLUGIN_ROOT; python -m claude_prospector dashboard --window 7d }`.)
- `.claude-plugin/plugin.json` — no `uv pip install` reference today; no change beyond the version bump.

**Verification:** `tests/test_readme_no_pip_install.py` — assert no `uv pip install` reference survives in the user-facing install section of the README. Mechanics:

- **Section boundary:** the "install section" is the content between the `## Installation` heading (case-sensitive, anchored) and the next `## ` heading (any level-2 heading) or EOF, whichever comes first.
- **Assertion:** no line within that block matches the regex `^\s*\$?\s*uv pip install\b` (case-sensitive). The optional leading `$` allows for shell-prompt-prefixed code samples; `\b` keeps the match anchored to the command name without requiring trailing flag specifics.
- **Allowlist:** a sibling `## Development` section (or any other `##` section that is not `## Installation`) may freely contain `uv pip install -e ".[dev]"` and similar — only the user-facing install section is constrained. The test simply does not scan outside the section bounds defined above; no per-line allowlist logic is needed.
- **Failure mode:** if the README is restructured such that no `## Installation` heading exists, the test fails loudly (rather than vacuously passing) — it asserts the section is found before scanning.

### AC3: CI verifies the bundled invocation path on Linux + Windows

**Files:**
- `.github/workflows/ci.yml` — add a `plugin-invocation` job. The job-level `defaults.run.shell: bash` declaration applies bash to every step (covering both `ubuntu-latest` and `windows-latest`'s Git Bash), which eliminates the PowerShell-default footgun on Windows for the `!`-negation in step 4 and for the `=` env assignments. `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` are hoisted to a job-level `env:` block so they propagate to every step without `$GITHUB_ENV` plumbing. `${{ github.workspace }}` is used in place of `$PWD` for self-documentation.

Resolved snippet:

```yaml
plugin-invocation:
  name: plugin-invocation (${{ matrix.os }})
  runs-on: ${{ matrix.os }}
  strategy:
    fail-fast: false
    matrix:
      os: [ubuntu-latest, windows-latest]
  defaults:
    run:
      shell: bash
  env:
    CLAUDE_PLUGIN_ROOT: ${{ github.workspace }}
    CLAUDE_PLUGIN_DATA: ${{ runner.temp }}/plugin-data
  steps:
    - uses: actions/checkout@v4

    - uses: actions/setup-python@v5
      with:
        python-version: "3.10"

    - name: Create empty CI venv (no dev install)
      run: python -m venv .ci-venv

    - name: Vendor-isolation precondition — jinja2 must NOT be importable from bare venv
      run: |
        source .ci-venv/Scripts/activate 2>/dev/null || source .ci-venv/bin/activate
        ! python -c "import jinja2" 2>/dev/null

    - name: Seed minimal usage-log fixture
      run: |
        mkdir -p "${CLAUDE_PLUGIN_DATA}"
        # (fixture contents per the test_dashboard_regen_hook.py harness conventions)

    - name: Invoke the hook end-to-end
      run: |
        source .ci-venv/Scripts/activate 2>/dev/null || source .ci-venv/bin/activate
        python hooks/dashboard-regen.py --autoregen true

    - name: Assert the dashboard rendered
      run: |
        test -f "${CLAUDE_PLUGIN_DATA}/dashboard.html"
        grep -q "<!-- jinja2-rendered -->" "${CLAUDE_PLUGIN_DATA}/dashboard.html"

    - name: Vendor-isolation post-condition — vendored jinja2 is what imports
      run: |
        source .ci-venv/Scripts/activate 2>/dev/null || source .ci-venv/bin/activate
        PYTHONPATH="${{ github.workspace }}" python -c "import jinja2; print(jinja2.__file__)"
        PYTHONPATH="${{ github.workspace }}" python -c "import jinja2; assert 'vendor' in jinja2.__file__, jinja2.__file__"
```

Notes on the snippet:

- **`shell: bash` at the job level** (via `defaults.run.shell`) applies to every `run:` step, so steps 4–8 inherit it without per-step redeclaration. This resolves the BLOCKING-1 narrow-scope issue.
- **`env:` at the job level** declares `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` once. GHA propagates them to every step's process environment automatically; no `$GITHUB_ENV` plumbing or per-step exports are needed. This resolves BLOCKING-2.
- **`${{ github.workspace }}`** replaces every `$PWD`. The contextual expression is unambiguous about which directory it names (the checkout root), regardless of any earlier step that may have changed cwd. This resolves BLOCKING-3.
- The `source .ci-venv/Scripts/activate 2>/dev/null || source .ci-venv/bin/activate` idiom handles both layouts (Windows `Scripts/`, POSIX `bin/`) in one line and avoids per-OS branching.
- The post-condition's grep assertion (`<!-- jinja2-rendered -->`) requires the dashboard template to carry a stable comment marker; if it does not today, add one as a one-line template tweak rather than parsing the HTML structurally.

- Existing `lint` and `test` jobs keep `uv pip install --system -e ".[dev]"` for their respective purposes.

**Verification:** the new job is the verification. Failure on either OS blocks merge. The precondition step is what distinguishes "the hook worked" from "the hook worked because of vendor isolation specifically."

### AC4: Version-pin failure machinery becomes structurally unreachable — **delete, do not keep as defense-in-depth**

The version-mismatch path in `dashboard-regen.py:L495-L531` exists because the Python package and the plugin manifest can drift when installed separately. After E1, they are **literally the same files on disk** in the plugin cache — there is no possible drift between `__version__` and the plugin manifest because both originate from the same `${CLAUDE_PLUGIN_ROOT}` snapshot.

**Files (delete):**
- `hooks/dashboard-regen.py:L220-L260` — `_version_tuple` and `_compare_versions`.
- `hooks/dashboard-regen.py:L344-L370` — `_version_mismatch_page`.
- `hooks/dashboard-regen.py:L495-L531` — the version-pin check block in the main function.
- `tests/test_dashboard_regen_hook.py:L223-L248` — the entire `TestVersionMismatch` class.

**Note on a pre-existing bug being deleted:** `dashboard-regen.py:L499` currently reads `manifest_path = Path(plugin_root_env) / "plugin.json"`, which is wrong — the manifest lives at `.claude-plugin/plugin.json`, not at the plugin-root top level. This bug predates the spec. AC4's deletion removes the buggy line entirely; the implementer should **not** carry the bug forward into the new `__init__.py` manifest fallback. The fallback as specified in AC1 uses the correct path:

```python
_manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
```

(`__file__` is `claude_prospector/__init__.py` → `.parent.parent` is the plugin root → then `.claude-plugin/plugin.json`.) Cross-check this when implementing.

**Files (keep):**
- `hooks/dashboard-regen.py:L322-L341` — `_python_not_found_page`. Reachable.
- `hooks/dashboard-regen.py:L373-L396` — `_regen_failed_page`. Reachable.
- `claude_prospector/__init__.py:L5-L10` — `__version__` resolution, **with manifest fallback** (see below).
- `tests/test_version_flag.py:L46-L67` — `--version` CLI tests. **Regex update required:** the current `_VERSION_RE` has a quantifier typo (`[\d]` instead of `[\d]+` on the patch segment) and does not match the new `0.0.0+unknown` sentinel returned by the manifest fallback's outer `except`. Replace with:
  ```python
  _VERSION_RE = re.compile(r"\d+\.\d+\.\d+|0\.0\.0\+local|0\.0\.0\+unknown")
  ```
  This is exactly the path the new CI job exercises (no `.dist-info` in `.ci-venv`), so the regex bug would surface there first if left unfixed.

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
