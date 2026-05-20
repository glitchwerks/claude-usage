# Release Process

Authoritative release runbook for `claude-prospector`. Every command shown was used in an actual release (0.8.2, PR #139, marketplace PR glitchwerks/plugins#30).

The **Quick reference card** at the end is the section to keep open during a release. Return to the sections above for rationale and edge-case guidance.

---

## Pre-release checklist

- [ ] All implementing PRs for this release are merged to `main`
- [ ] CI is green on the latest `main` commit (lint, test, wheel-smoke)
- [ ] `CHANGELOG.md` has a draft `## [X.Y.Z] - <date>` section ready
- [ ] `pyproject.toml` `version` = target version
- [ ] `.claude-plugin/plugin.json` `version` = target version
- [ ] Release PR body lists `Closes #N` for every issue being closed (one keyword per issue)

---

## Release classification

| Class | When | Extra steps beyond patch | Cache wipe? |
|---|---|---|---|
| **Patch** (`x.y.Z`) | Bug fixes, doc-only, test-only | — | No |
| **Minor** (`x.Y.0`) | New skills, new commands, backward-compatible additions | Update README skill/command sections | No |
| **Major** (`X.0.0`) | Breaking changes, schema migrations | Update README; note breaking changes in CHANGELOG | No |
| **Repo move** | `source.repo` in `glitchwerks/plugins` marketplace changes | All of major + cache wipe (step 10) | **Yes** |

The cache wipe applies **only to repo moves**. Pure version bumps — including major bumps — do not need it. See the cache-wipe footgun entry below for the incident that proved this rule.

---

## Step-by-step sequence

**1. Open the release PR**

Branch from `main`. Bump `pyproject.toml` `version`, `.claude-plugin/plugin.json` `version`, and `CHANGELOG.md` (move draft entry to `## [X.Y.Z] - YYYY-MM-DD`). Include `Closes #N` for every issue. For minor/major: also update `README.md` if skill names, command names, or environment variables changed.

**2. Wait for CI and merge**

CI must be green on all three jobs: lint, test (Ubuntu + Windows), wheel-smoke. Merge to `main` (squash merge).

**3. Tag the merge commit**

```bash
git -C <repo> pull origin main
git -C <repo> rev-parse HEAD                           # note the merge SHA
git -C <repo> tag -a vX.Y.Z <merge-sha> -m "vX.Y.Z"
```

**4. Push the tag**

```bash
git -C <repo> push origin vX.Y.Z
```

This triggers `release.yml`: build → wheel-smoke → publish-pypi, in sequence. Pre-release tags (`-rc`, `-alpha`, `-beta`) publish to TestPyPI instead.

**5. Wait for the release workflow**

```bash
gh run list --repo glitchwerks/claude-prospector
gh run view <run-id> --repo glitchwerks/claude-prospector
```

All three jobs must be green. The `wheel-smoke` job gates publish: it installs the wheel into a fresh venv and runs `python -m claude_prospector dashboard` against a fixture. Do not proceed until publish-pypi is green.

**6. Dereference the annotated tag**

```bash
git -C <repo> rev-parse 'vX.Y.Z^{commit}'
```

This returns the underlying commit SHA. **Never use bare `git rev-parse vX.Y.Z`** — on annotated tags that returns the tag-object SHA, which the marketplace loader cannot resolve. See Footguns below.

**7. Open the marketplace bump PR**

In `glitchwerks/plugins`, update `.claude-plugin/marketplace.json`:
- `plugins[?name=="claude-prospector"].source.sha` → commit SHA from step 6
- `plugins[?name=="claude-prospector"].version` → `X.Y.Z`

**8. Merge the marketplace PR**

`glitchwerks/plugins` has no CI (as of 2026-05-18) — squash-merge immediately.

**9. Verify the live pin**

```bash
gh api repos/glitchwerks/plugins/contents/.claude-plugin/marketplace.json \
  --jq '.content' | base64 -d | grep -A 6 '"claude-prospector"'
```

Confirm `sha` matches step 6 and `version` matches `X.Y.Z`.

**10. [Repo move only] Wipe the per-plugin cache**

Runs only when `source.repo` changed. Do not run for patch/minor/major.

```bash
rm -rf ~/.claude/plugins/cache/glitchwerks/claude-prospector/
```

Then open a new Claude Code session and run `/reload-plugins`.

---

## Footguns

### Annotated-tag SHA trap

**Rule:** Use `git rev-parse 'vX.Y.Z^{commit}'` for the marketplace SHA pin. Bare `git rev-parse vX.Y.Z` returns the tag-object SHA on annotated tags, which the marketplace loader cannot resolve.

**Source of truth:** `~/.claude/agent-memory/general-purpose/feedback_action_pin_use_commit_not_tag_obj.md` — proven in glitchwerks/plugins#20, fixed in #21.

**Comply:** Always append `^{commit}` (step 6 above).

---

### Cache wipe is for repo moves only

**Rule:** Do not wipe `~/.claude/plugins/cache/glitchwerks/claude-prospector/` unless `source.repo` in `marketplace.json` actually changed. Wiping on a pure version bump removes the slot for the previous version while users still have it active.

**Source of truth:** `~/.claude/agent-memory/general-purpose/feedback_plugin_cache_survives_repo_split.md` — proven by the 0.8.1 → 0.8.2 release (#140), where unconditional wipe produced `Plugin directory does not exist: ...\0.8.1`.

**Comply:** Check the marketplace PR diff for `source.repo` change. If unchanged, skip step 10.

---

### PR body must contain the closing keyword

**Rule:** `Closes #N` must appear in the PR body, not only in commit messages. With squash merge GitHub synthesizes the merge commit from PR title + body, not source commits.

**Source of truth:** CLAUDE.md § Pull Requests.

**Comply:** One `Closes #N` line per issue, plain text, in the PR body.

---

### Verify PR open before pushing

**Rule:** Before pushing to an in-flight release branch, confirm the PR is still open. A merged branch accepts pushes silently.

**Source of truth:** CLAUDE.md § Pull Requests; enforced by `hooks/check-pr-open.js`.

**Comply:** `gh pr view <branch>` before each push.

---

### Wheel-smoke must pass before proceeding past step 5

**Rule:** A green `build` job does not mean the wheel works at runtime. The `wheel-smoke` job is the gate.

**Source of truth:** PR #138 — the 0.8.0 wheel shipped with `TemplateNotFound` at runtime because this job did not yet exist.

**Comply:** Wait for wheel-smoke green (step 5) before deref (step 6).

---

### Marketplace repo bump is required

**Rule:** A release is not installable from `glitchwerks/plugins` until `marketplace.json` is bumped.

**Source of truth:** `~/.claude/agent-memory/general-purpose/feedback_release_requires_marketplace_repo_bump.md` — proven during claude-wayfinder v0.4.1 (glitchwerks/plugins#19).

**Comply:** Steps 7–9 are not optional. Verify with step 9 before announcing.

---

## Rollback procedure

1. **Yank from PyPI** — use the PyPI web UI (`https://pypi.org/manage/project/claude-prospector/releases/`) to yank the version. Yank hides it from unconstrained installs; Delete is irreversible.
2. **Delete the tag** — `git push --delete origin vX.Y.Z` then `git tag -d vX.Y.Z`.
3. **Revert the marketplace pin** — PR on `glitchwerks/plugins` restoring the prior `sha` and `version`. Merge immediately.
4. **Comment on tracking issue** — note the rollback, symptom, and next steps. Do not re-close the issue until a corrected release lands.
5. **Post-mortem** — add a CHANGELOG entry for the reverted version and update the relevant Footguns entry or memory file.

---

## Quick reference card

```
Pre-flight
  [ ] Implementing PRs merged, CI green on main
  [ ] CHANGELOG.md draft section ready
  [ ] pyproject.toml + plugin.json versions bumped

1.  Open release PR (version bumps + CHANGELOG entry + Closes #N)
2.  CI green (lint + test + wheel-smoke) → merge to main
3.  git -C <repo> pull origin main
    git -C <repo> rev-parse HEAD           # note merge SHA
    git -C <repo> tag -a vX.Y.Z <sha> -m "vX.Y.Z"
4.  git -C <repo> push origin vX.Y.Z
5.  gh run view <run-id> --repo glitchwerks/claude-prospector
    # wait for build + wheel-smoke + publish-pypi all green
6.  git -C <repo> rev-parse 'vX.Y.Z^{commit}'   # commit SHA (not tag-obj SHA)
7.  Open PR on glitchwerks/plugins: bump sha + version in marketplace.json
8.  Merge marketplace PR
9.  gh api repos/glitchwerks/plugins/contents/.claude-plugin/marketplace.json \
      --jq '.content' | base64 -d | grep -A 6 '"claude-prospector"'

Repo move only (source.repo changed):
10. rm -rf ~/.claude/plugins/cache/glitchwerks/claude-prospector/
11. /reload-plugins in a new Claude Code session
```
