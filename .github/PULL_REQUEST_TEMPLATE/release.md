# Release: vX.Y.Z

> Full rationale and edge-case guidance: [docs/release-process.md](../../docs/release-process.md)

## Pre-release checklist

- [ ] All implementing PRs for this release are merged to `main`
- [ ] CI is green on the latest `main` commit (lint, test, wheel-smoke)
- [ ] `CHANGELOG.md` has a `## [X.Y.Z] - <date>` section ready
- [ ] `pyproject.toml` `version` = `X.Y.Z`
- [ ] `.claude-plugin/plugin.json` `version` = `X.Y.Z`
- [ ] This PR body lists `Closes #N` for every issue being closed (one keyword per issue, plain text)

## Release classification

- [ ] Patch (`x.y.Z`) — bug fixes, doc-only, test-only
- [ ] Minor (`x.Y.0`) — new skills, new commands, backward-compatible additions
- [ ] Major (`X.0.0`) — breaking changes, schema migrations
- [ ] Repo move — `source.repo` in `glitchwerks/plugins` marketplace changes

## Closing

<!-- Replace with actual issue numbers, one per line -->
Closes #

## Post-merge steps (complete after this PR merges)

- [ ] Tag the merge commit: `git tag -a vX.Y.Z <merge-sha> -m "vX.Y.Z"`
- [ ] Push the tag: `git push origin vX.Y.Z`
- [ ] Wait for release workflow (build + wheel-smoke + publish-pypi all green)
- [ ] Dereference the tag to commit SHA: `git rev-parse 'vX.Y.Z^{commit}'`
- [ ] Open marketplace PR on `glitchwerks/plugins` — bump `sha` + `version`
- [ ] Merge marketplace PR
- [ ] Verify live pin: `gh api repos/glitchwerks/plugins/contents/.claude-plugin/marketplace.json --jq '.content' | base64 -d | grep -A 6 '"claude-prospector"'`
- [ ] [Repo move only] Wipe cache: `rm -rf ~/.claude/plugins/cache/glitchwerks/claude-prospector/`
