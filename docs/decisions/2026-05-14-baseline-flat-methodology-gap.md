# Baseline-flat test methodology gap (PR #42)

**Date:** 2026-05-14
**Issue:** #45 (item 10)
**Status:** Documented; not fixed.

## What was supposed to happen

The implementation plan for Issue #41 (nested sub-agent attribution) —
[`docs/superpowers/plans/2026-05-13-issue-41-nested-agent-attribution-plan.md`](../superpowers/plans/2026-05-13-issue-41-nested-agent-attribution-plan.md)
— called for a Phase 0 baseline test at `tests/test_aggregator_baseline_flat.py`.
That test was meant to assert the *old* flat-agent-key shape on a depth-2 fixture,
then fail loudly under the new code path once Phase 4 landed — proving the migration
moved the needle rather than no-op'ing.

Plan reference: Task 0.2 — "Capture flat-agent baseline (with explicit limit)" —
checkbox unchecked.

## What actually happened

The baseline test was never written. Phase 4 implemented the new path-keyed shape
directly without first capturing the old contract. The Phase 4.1 "delete the
baseline-flat test" step was a no-op because the file never existed.

## Why we are not retroactively fixing it

Retroactively writing the baseline-flat test now would mean asserting behavior the
codebase no longer implements — the flat-key `by_agent` contract is gone. Such a
test would either:

1. Fail immediately (asserting deleted behavior) — adds noise, ships nothing.
2. Require synthetic fixtures of the *old* shape just to have something to assert
   against — circular and unmaintainable.

The migration shipped (PR #42). The new shape is exercised by
`TestAggregateByAgentPath` and related path-keyed tests in
`tests/test_aggregator.py`. The regression risk the baseline test was meant to
address has passed.

## What we will do differently next time

Any "we will write X as a baseline" plan task should be the **first commit on the
implementing branch**, before any code change that would obsolete the baseline. If it
is not the first commit, it gets skipped under deadline pressure and the methodology
guarantee is lost.

Concretely:

- Phase 0 tasks should be self-contained commits that pass on a clean `main`.
- Subsequent phases should not delete or modify Phase 0 tests in the same PR — if
  they must, the Phase 0 commit should ship on its own PR first so it enters
  `main`'s history independently.
- This applies to any "regression baseline" or "would-have-failed-but-for-the-fix"
  test pattern.

This is recorded here per `CLAUDE.md § Verify Artifact Persistence` (recovery
clause): methodology gaps should be honestly disclosed, not silently regenerated.
