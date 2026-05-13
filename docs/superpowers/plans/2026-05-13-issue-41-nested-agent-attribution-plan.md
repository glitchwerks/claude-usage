# Nested Agent Attribution via `agent_path` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Tracks:** https://github.com/glitchwerks/claude-usage/issues/41
**closes #41**
**Goal:** Replace the flat `MessageRecord.agent_type: str` with a path-aware `agent_path: tuple[str, ...]`, recurse the parser into nested `subagents/` directories, and surface the nested attribution in the most load-bearing aggregator (`AggregateResult.by_agent`) — landing as a single vertical-slice PR with full backward compatibility.
**Architecture:** New `agent_path: tuple[str, ...]` field on `MessageRecord`. Existing `agent_type` becomes a derived property returning the leaf (`agent_path[-1]`). Parser converts the single-level subagent walk into a depth-first recursion with a path accumulator, a defensive depth cap, and a `Path.resolve()`-based visited-set to defeat symlink/junction cycles. The aggregator's `by_agent` rollup gains delimited-string path keys (e.g. `"general-purpose→project-planner→Explore"`); the per-session `agents` list emits **only deepest-leaf paths** to keep the dashboard's `s.total_tokens / s.agents.length` apportionment correct (see § Dashboard JS Compatibility).
**Tech Stack:** Python 3.11+, stdlib (`dataclasses`, `pathlib`, `json`, `warnings`), pytest, ruff, uv.

---

## Locked Decisions (do not re-litigate)

1. **Data model:** Add `agent_path: tuple[str, ...]` to `MessageRecord`. Keep `agent_type` as a `@property` returning `agent_path[-1]`. (See `claude_usage/models.py:L9-L37` for the current full dataclass shape — including the existing `total_tokens` and `model_short` `@property` methods at L22-L37 which must be preserved unchanged.)
2. **Scope of first PR:** Full vertical slice — parser recursion + model field + aggregator path-keyed `by_agent`. **One PR**, phased internally with TDD checkpoints, mergeable as a single unit.
3. **Cadence:** Phase boundaries mirror `docs/superpowers/plans/2026-04-23-session-summary-implementation-plan.md` (Phases 0 → N with optional sub-agent dispatch between phases).
4. **Aggregator pick (justification):** The plan modifies **`aggregator.aggregate()`'s `by_agent` rollup** as the "load-bearing aggregator" for v1. Reasoning:
   - The dashboard's `by_agent` is the single most visible nested-attribution surface — it drives the per-agent bar chart and the per-session `agents` list (renderer.py:L46).
   - The `session-summary` subcommand does **not** consume `MessageRecord.agent_type` at all — it reads `tool_input.subagent_type` directly from raw transcript entries (`claude_usage/cli/session_summary.py:L332-L339`). It is therefore *unaffected* by this change and the acceptance-criterion "session-summary CLI output does not regress" is satisfied trivially.
   - Skill-adoption aggregation also does not consume `agent_type` (it keys on `target_agent` from `SkillPassedEvent`, see `aggregator.py:L215-L218`). No work needed.

---

## Current State (re-verified against `main` 2026-05-13)

Every citation below was opened and read at the exact line range listed during plan revision. Spot-checks extended to surrounding context to catch silent-omission drift.

| Locus | Citation | Verified content |
|---|---|---|
| Flat agent type on the record | `claude_usage/models.py:L9-L37` | `MessageRecord` is a `@dataclass(frozen=True, slots=True)` with `agent_type: str` at L15. **The class continues to L37** with `total_tokens` and `model_short` `@property` methods (L22-L37) — these must be preserved verbatim. |
| `_parse_jsonl_messages` signature & write | `claude_usage/parser.py:L47-L86` | Signature `(jsonl_path: Path, agent_type: str)` at L47; assigns `agent_type=agent_type` at L78 when constructing `MessageRecord`. |
| `_parse_session` top half | `claude_usage/parser.py:L92-L146` | Agent-setting resolution branches; root_agent computation. Untouched by this PR. |
| Single-depth subagent walk | `claude_usage/parser.py:L148-L167` | The single-level subagent walk: parent message parse at L149; `subagent_dir = jsonl_path.parent / session_id / "subagents"` (defined earlier at L114); for-loop over `*.meta.json` at L154-L167. **No recursion** into `<sub-agent-session-dir>/subagents/`. |
| `_parse_session` return | `claude_usage/parser.py:L169-L181` | Builds `SessionRecord` with `subagent_types=sorted(set(subagent_types))`. |
| Per-session `agents_in_session` | `claude_usage/aggregator.py:L92` | `agents_in_session = sorted(set(m.agent_type for m in session_messages))` (singular line). Feeds `result.sessions[*]["agents"]` at L102. |
| Flat `by_agent` rollup | `claude_usage/aggregator.py:L120-L128` | `for msg in filtered_messages: agent = msg.agent_type ... result.by_agent[agent] ... agent_models[agent][msg.model_short] += 1` then `primary_model` assignment. |
| `agent_session_count` block | `claude_usage/aggregator.py:L130-L137` | Rebuilds `session_count` per agent from `session_summary["agents"]`. Works unchanged when the agent strings are delimited path keys, because it treats them as opaque strings. |
| Render handoff | `claude_usage/renderer.py:L41-L52` | `data["by_agent"] = result.by_agent` (L46); whole `data` dict serialized via `json.dumps(...)` (L55) — keys pass through verbatim. Jinja `autoescape=True` is set at L37. |
| Dashboard JS reAggregator | `templates/dashboard.html:L434-L444` | **The per-session `s.agents` list is iterated, and `Math.round(s.total_tokens / Math.max(1, s.agents.length))` apportions session totals across each entry.** See § Dashboard JS Compatibility — this is the constraint that drives the deepest-leaf decision. |
| Dashboard JS primary_model lookup | `templates/dashboard.html:L455-L458` | `DATA.by_agent[agent].primary_model` is looked up by **exact key equality**. Whatever key shape the aggregator emits must match the key shape in `s.agents`. |
| Dashboard JS session-list rendering | `templates/dashboard.html:L855-L857` | `s.agents` is also rendered as `<span class="agent-tag">${a}</span>` in the per-session card. Delimited path strings render in-place; styling unchanged. |
| Session-summary subagent read | `claude_usage/cli/session_summary.py:L332-L339` | Reads `inp.get("subagent_type", ...)` from raw `tool_use` entries. Does not touch `MessageRecord`. |

**Backward-compat consumers of `MessageRecord.agent_type` — full enumeration of read AND write sites:**

| File | Lines | Read or write? | How it uses `agent_type` | Action |
|---|---|---|---|---|
| `claude_usage/aggregator.py` | L92, L121 | read | Reads `m.agent_type` for grouping and per-session `agents` list. | Replace both reads with helper that emits path key (Phase 4). |
| `claude_usage/parser.py` | L78 | write | Sets `agent_type=...` when constructing `MessageRecord`. | Change to `agent_path=...` (Phase 2). |
| `tests/test_models.py` | L17, L30, L43, L56, L69, L82, L107 | write | Constructs `MessageRecord(..., agent_type="...")` in seven places. | Update to `agent_path=("...",)` (Phase 2). |
| `tests/test_aggregator.py` | L20 | write | `_msg(...)` helper builds `MessageRecord(..., agent_type=agent, ...)`. | Update to `agent_path=(agent,)` (Phase 2). The helper's outward `agent=` parameter is unchanged. |
| `tests/test_parser.py` | L54, L59 | read | `m.agent_type` filtering. | No change — `@property` shim covers it. |
| `docs/design.md`, `docs/plan.md` | various | doc | Reference docs only. | Update opportunistically (Phase 5). |

**Full enumeration of `result.by_agent[<key>]` read sites in tests** (charge 1b — sites that break when keys gain delimiters):

| File | Lines | Current literal key | Action under new key shape |
|---|---|---|---|
| `tests/test_e2e.py` | L21 | `"general-purpose"` (depth-1 root) | **No change.** Root-only fixture (`sample_session_dir`) produces depth-1 path → single-segment key `"general-purpose"`. |
| `tests/test_e2e.py` | L220, L221, L223 | `"debugger"` | **Update to `"general-purpose→debugger"`.** Fixture is a depth-2 dispatch (general-purpose parent runs Opus, debugger sub-agent runs Sonnet) per `_build_session_dir` at L112-L204. Adjust assertions accordingly. |
| `tests/test_e2e.py` | L226 | `"general-purpose"` | **No change.** Root path is still a 1-tuple → key `"general-purpose"`. |
| `tests/test_e2e.py` | L281 | `f"agent-{i:02d}"` (synthetic) | **No change.** Test constructs an `AggregateResult` directly with synthetic depth-1 keys for the chart-label regression test; not derived from `MessageRecord`. |
| `tests/test_aggregator.py` | L97, L98, L109 | `"general-purpose"`, `"code-writer"` | These are tests in `TestAggregateByAgent` against `_msg(agent="...")` (depth-1 records). They remain valid because depth-1 path keys collapse to the single segment. **No change.** |
| `tests/test_aggregator.py` | L281 (TestChartLabelSkip clones same pattern via `f"agent-{i:02d}"`) | n/a (synthetic) | **No change.** |

**Budgeted explicit test edits (in scope for this PR):** 4 sites in `test_e2e.py` (L220, L221, L223, plus the f-string at L223 which embeds the key). All 9 construction sites in `test_models.py` + `test_aggregator.py::_msg` (already enumerated in Phase 2). No other test-file edits expected — if Phase 3/4 surfaces an additional read site, that triggers the "stop and re-evaluate" gate in § Test Strategy.

**Verified non-consumers** (no change needed):

| File | Reason |
|---|---|
| `claude_usage/cli/session_summary.py` | Reads `subagent_type` from raw transcript JSON (L332-L339), never touches `MessageRecord.agent_type`. |
| `claude_usage/cli/dashboard.py` | Passes `AggregateResult` to renderer; no field-level access. |
| `claude_usage/renderer.py` | Treats `by_agent` as an opaque dict (L46); `json.dumps` JSON-escapes non-ASCII keys to `→` form (L55) — decoded to U+2192 by `JSON.parse` client-side. |
| Skill adoption (`aggregator.compute_skill_adoption`) | Keys on `target_agent` from `SkillPassedEvent` (L215-L218), not `MessageRecord`. |

---

## Target State

### Data shape — `MessageRecord` before and after

**Before** (current `main`, full class):

```python
@dataclass(frozen=True, slots=True)
class MessageRecord:
    timestamp: datetime
    model: str
    agent_type: str            # flat leaf string
    skill: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )

    @property
    def model_short(self) -> str:
        """Extract short model name: 'opus', 'sonnet', 'haiku', or full name."""
        for name in ("opus", "sonnet", "haiku"):
            if name in self.model:
                return name
        return self.model
```

**After** — `agent_type` becomes a property; `total_tokens` and `model_short` properties are preserved verbatim:

```python
@dataclass(frozen=True, slots=True)
class MessageRecord:
    timestamp: datetime
    model: str
    agent_path: tuple[str, ...]   # root → leaf, e.g. ("general-purpose", "project-planner", "Explore")
    skill: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int

    @property
    def agent_type(self) -> str:
        """Leaf agent (for backward compat). Returns last segment of agent_path."""
        return self.agent_path[-1]

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )

    @property
    def model_short(self) -> str:
        """Extract short model name: 'opus', 'sonnet', 'haiku', or full name."""
        for name in ("opus", "sonnet", "haiku"):
            if name in self.model:
                return name
        return self.model
```

`tuple` (not `list`) because the dataclass is `frozen=True` and `list` is unhashable — keeps the record hashable and the field truly immutable.

**Sample records:**

```python
MessageRecord(agent_path=("general-purpose",), ...)                         # depth 1
MessageRecord(agent_path=("general-purpose", "code-writer"), ...)           # depth 2
MessageRecord(agent_path=("general-purpose", "project-planner", "Explore"), ...)  # depth 3
```

For backward-compat: `record.agent_type == "Explore"` in the depth-3 case.

### Parser recursion contract

`_parse_session` becomes the entry point that calls a recursive helper, with explicit cycle defense:

```python
_MAX_AGENT_DEPTH = 10        # defensive cap
_PATH_SEPARATOR = "→"   # "→" U+2192 RIGHTWARDS ARROW

def _parse_subagents_recursive(
    parent_session_dir: Path,
    parent_path: tuple[str, ...],
    subagent_types_accumulator: list[str],
    visited: set[Path],
    depth: int,
    overflow_emitted: list[bool],
) -> list[MessageRecord]:
    """Walk <parent_session_dir>/subagents/ and recurse into each sub-agent's own session.

    Contract:
    - If depth > _MAX_AGENT_DEPTH: return []. Emit one warnings.warn per session
      (deduped via overflow_emitted[0]).
    - Resolve parent_session_dir via .resolve() before walking; if the real path
      is already in `visited`, log via warnings.warn and return [] (cycle).
    - For each <parent_session_dir>/subagents/*.meta.json:
        - Read agentType. **Sanitize**: if it contains _PATH_SEPARATOR, replace with
          U+FE56 ('﹖') and emit warnings.warn — see § Agent-Name Invariants.
        - Append to accumulator (sanitized form).
        - Build child_path = parent_path + (agentType_sanitized,).
        - Parse the matched <agent_id>.jsonl with that child_path.
        - Recurse into <parent_session_dir>/subagents/<agent_id>/ with child_path
          and depth + 1.
    - Missing *.meta.json: skip silently (matches current behavior).
    - Empty subagents/ dir or non-existent: returns []; recursion terminates.
    """
```

The accumulator captures all agent types encountered at any depth, so `SessionRecord.subagent_types` stays a flat de-duped list (the existing API is unchanged).

### Agent-Name Invariants (charge 2 — explicit, enforced)

The kebab-case-ASCII-only assumption is **not** enforced anywhere in the codebase, and the existing fixtures already include PascalCase names (`Explore`). The plan therefore makes the separator-safety property an **explicit, validated invariant** rather than a tacit assumption:

- **Invariant:** No segment of `agent_path` contains the path separator `"→"` (`"→"`).
- **Where validated:** at parse time, in `_parse_subagents_recursive` immediately after reading `agentType` from `*.meta.json`, and in `_parse_session` after resolving `root_agent`.
- **Violation handling:** replace each `"→"` in the offending name with `"﹖"` (`"﹖"`, U+FE56 SMALL QUESTION MARK — visually distinct, will not collide with normal agent names) and emit `warnings.warn(f"Agent name contains path separator; sanitized: {original!r} -> {sanitized!r}", stacklevel=2)`. Parsing continues with the sanitized name.
- **Rationale for "sanitize, not reject":** rejecting would silently drop the session's data. Sanitizing preserves attribution while loudly flagging the anomaly.
- **Observability decision (pass-2 charge 5): option (a) — keep `warnings.warn`, accept the dashboard observability gap.** Rationale documented below. Implementers must NOT add an `AggregateResult.sanitized_agent_names` field or a dashboard banner as part of this PR.

  **Why (a) over (b):**
  1. **Frequency.** Agent names are author-controlled identifiers — the entire population is `general-purpose`, `code-writer`, `Explore`, `project-planner`, etc. The realistic rate of names containing U+2192 is effectively zero; the invariant is in the plan to make the code robust, not because it expects to fire. Plumbing a `sanitized_agent_names` set through `AggregateResult`, the renderer, the JSON payload, and the dashboard template costs ~5 file edits, new fields, and new template logic, for a feature that should never display anything in practice.
  2. **Where it does fire, the sanitized name is still visible.** The dashboard row shows e.g. `weird﹖name` — readable, distinct from any real agent name (`﹖` is U+FE56, not in any conventional agent name), and clickable. The user can investigate without a banner.
  3. **`warnings.warn` is observable at the CLI invocation that produced the data.** The user running `claude-usage dashboard` sees the warning on stderr at generation time — that is the moment they have the context to act. A dashboard-side banner shown weeks later, when re-opening the HTML, is *less* useful because the underlying session may not even exist anymore.

  **Reconsider trigger:** if sanitization ever fires in real-world telemetry (any reported instance from a user), revisit by adding the `sanitized_agent_names: set[str]` field and a one-line banner. Until then, the cost-benefit favors option (a).
- **Round-trip tested:** `tests/test_parser.py::TestNestedSubagents::test_pascalcase_agent_name_roundtrips` constructs a fixture with `agentType: "Explore"` (PascalCase) at depth 3 and asserts `agent_path == ("general-purpose", "project-planner", "Explore")` survives intact. A separate test `test_separator_in_agent_name_sanitized` constructs `agentType: "weird→name"` and asserts the warning fires plus the agent is recorded as `"weird﹖name"`.
- **JSON serialization (settled — commit `3114822`):** `json.dumps` does not HTML-escape, but it does JSON-escape non-ASCII characters (`ensure_ascii=True` default), producing `→` (literal 6-char ASCII escape) in the HTML source. Jinja autoescape never processes the JSON payload because it is emitted via a `|safe` filter — the HTML-entity forms `&#8594;` and `&rarr;` do not appear. The browser's `JSON.parse` decodes `→` back to U+2192 before key lookup, so `DATA.by_agent["general-purpose→code-writer"]` resolves correctly client-side. The `" / "` fallback is not needed.

### Aggregator behavior under nested paths

`by_agent` switches from leaf-string keys to **delimited path-string keys** using `"→"` (U+2192) as the separator:

```python
result.by_agent = {
    "general-purpose": {...},                              # depth 1
    "general-purpose→code-writer": {...},                  # depth 2
    "general-purpose→project-planner→Explore": {...},      # depth 3
}
```

**The per-session `agents_in_session` list emits deepest-leaf paths only** — see § Dashboard JS Compatibility below for the constraint that drives this.

### Dashboard JS Compatibility (charge 1 — load-bearing decision)

The dashboard's per-session-card and re-aggregator JS at `templates/dashboard.html:L434-L444` apportions `s.total_tokens` evenly across each entry in `s.agents`:

```javascript
for (const agent of (s.agents || [])) {
  if (!byAgent[agent]) byAgent[agent] = { total_tokens: 0, session_count: 0, primary_model: null, model_tokens: {} };
  byAgent[agent].session_count += 1;
  const share = Math.round(s.total_tokens / Math.max(1, s.agents.length));
  byAgent[agent].total_tokens += share;
  // ...
}
```

This means: **if `s.agents` contains both an ancestor path-key AND its descendant path-key, the apportionment double-counts** — at depth 3, `["general-purpose", "general-purpose→project-planner", "general-purpose→project-planner→Explore"]` would give `length=3`, crediting the root chunk 1/3 of total session tokens even though every descendant message strictly rolls up to it. The existing template comment at L447-L454 documents this exact class of bug for depth-2; reintroducing it at higher fan-out is a regression.

**Decision: option (b) from the charge — `agents_in_session` emits only the deepest-leaf path-key per chain.** A depth-3 session emits `["general-purpose→project-planner→Explore"]` (length 1); a depth-2 session emits `["general-purpose→code-writer"]`; a depth-1 session emits `["general-purpose"]`. If multiple sibling subagents exist at the deepest level, all of them appear (one per leaf chain — siblings, not nested).

**Cost of this decision (disclosed):**
- The per-session "agents in this session" tag list (`s.agents` rendered at `dashboard.html:L855-L857`) loses **ancestor visibility** — a session with depth-3 attribution shows only the leaf chain, not "this involved general-purpose AND project-planner AND Explore." Ancestor names are still recoverable by reading the delimited key, just not as separate tags.
- Server-side `AggregateResult.by_agent` continues to bucket every path that appears in any message — so the per-agent chart shows `general-purpose→project-planner→Explore` as a row, but **not** an intermediate `general-purpose→project-planner` row, because no message has that as its full `agent_path` (intermediate rollup is an explicit non-goal per § Out of scope, and the depth-3 aggregator test asserts intermediate buckets are NOT implicitly created).

**Rationale for accepting (b) over (a):**
1. Option (a) — defining a JS-side dedup/apportionment rule — pulls the dashboard JS into PR scope. The JS currently treats `s.agents` as a flat list and would need a path-prefix-detection step to drop ancestors. That is genuinely more code, more tests, and more browser-side risk than the data-shape choice.
2. The deepest-leaf rule preserves the **invariant that the existing JS relies on**: each entry in `s.agents` represents a unit of attribution distinct from every other entry in the same list. Ancestor inclusion violates that invariant.
3. The cost — ancestor visibility in the per-session card — was explicitly listed as part of the deferred dashboard tree visualization in § Out of scope (sunburst / indented tree / expand-collapse). Surfacing ancestors without a tree view shows them as flat siblings, which misrepresents the relationship anyway.

**Follow-up filed:** the in-scope work explicitly leaves the per-session card without ancestor breadcrumbs. The follow-up issue for the nested tree visualization (filed at merge time) is the right place to add ancestor surfacing with correct visual hierarchy.

### Out of scope

This PR explicitly does **not** ship:

- **Dashboard JS / HTML tree visualization** (sunburst, indented tree, expand/collapse). Delimited string renders as-is in the existing bar chart and per-session card; ancestor visibility intentionally deferred (see § Dashboard JS Compatibility above).
- **Intermediate path-key buckets.** `by_agent` only buckets path keys observed as a full `agent_path` on some message. There is no implicit rollup of `general-purpose→project-planner→Explore` into a synthetic `general-purpose→project-planner` bucket.
- **Breaking removal of the `agent_type` property.**
- **Schema migration** for any persisted/cached aggregator output (there is none today).
- **Nested-path filter/CLI flags.**

---

## Phase 0 — Pre-Change Empirical Pre-Flight

**Purpose:** Settle two empirical questions before fixtures or code commit to the separator character: (a) does Jinja autoescape mangle `"→"`? (b) does the dashboard's JS reAggregator handle a path-keyed `by_agent` without throwing? Both answers gate the separator choice for every downstream fixture and test.

### Task 0.1: Renderer pass-through smoke test (separator pre-flight)

- [x] Add `tests/test_renderer.py::test_path_keys_render_through` — build an `AggregateResult` manually (NO parser, NO aggregator changes yet) with one synthetic path-keyed entry: `result.by_agent["general-purpose→code-writer"] = {"total_tokens": 100, "primary_model": "opus", "session_count": 1}`. Invoke `render(...)` to a temp HTML file. Read the HTML and assert one of:
  - the literal `"general-purpose→code-writer"` substring appears (raw character survives), OR
  - the JSON-escaped form `"general-purpose→code-writer"` (`→`) appears in the HTML source.

  **Result (commit `3114822`):** the JSON-escaped form `→` appears in the HTML source. This is `json.dumps` default behavior (`ensure_ascii=True`) — `json.dumps` does not HTML-escape, but it does JSON-escape non-ASCII characters. The browser's `JSON.parse` decodes `→` back to U+2192 transparently. The HTML-entity forms `&#8594;` and `&rarr;` do NOT appear (Jinja autoescape never processes the JSON payload because it is emitted via a `|safe` filter). The JSON payload assertion (`data_json` contains the key) passes because the JS engine resolves the escape before key lookup.

- [x] ~~If the renderer mangles the JSON payload (vanishingly unlikely with `default=str`), or if the displayed form is unreadable in the dashboard table, **switch the separator constant to `" / "` (space-slash-space) before any downstream fixture is written**.~~ **Not needed** — the `→` JSON-escape round-trips correctly.

- [x] **Result captured in PR description:** the round-trip form is `→` (literal 6-char ASCII escape in the HTML source, decoded to U+2192 by the browser). The separator constant is `"→"`. All downstream fixtures and assertions reference this constant via `aggregator.AGENT_PATH_SEPARATOR`.

### Task 0.2: Capture flat-agent baseline (with explicit limit)

- [ ] Run `uv run pytest` on a clean `main` checkout; record the green commit SHA in the PR description.
- [ ] Add `tests/test_aggregator_baseline_flat.py` with **depth-2 fixture only** (router + one sub-agent). Assert current flat-key shape: `result.by_agent["general-purpose"]["total_tokens"] == X` and `result.by_agent["code-writer"]["total_tokens"] == Y`, plus the per-session `agents` list contains both literal strings.
- [ ] **Explicit limit (charge 5):** This baseline does NOT exercise depth-3 cases because depth-3 records cannot exist until Phase 3 lands. The baseline is therefore **not sufficient** to detect Phase 3's intermediate-state behavior; that gap is covered by Phase 3.5 (the sanity probe). This test is deleted in Phase 4 once subsumed.

---

## Phase 1 — Multi-Level Fixtures

### Task 1.1: Build a depth-3 subagent fixture

- [ ] Create `tests/conftest.py` fixture `nested_session_dir` that constructs:

  ```
  projects/C--Users-chris--myproject/
    sess-nested.jsonl                          # root: general-purpose (depth 1)
    sess-nested/
      subagents/
        agent-pp.meta.json                     # agentType: project-planner (depth 2)
        agent-pp.jsonl                         # assistant msgs (Opus)
        agent-pp/
          subagents/
            agent-exp.meta.json                # agentType: Explore (PascalCase, depth 3)
            agent-exp.jsonl                    # assistant msgs (Haiku)
  ```

  Each JSONL contains 1-2 assistant messages with deterministic, distinct token counts (e.g. 100/200/400 input tokens at depths 1/2/3) so individual contributions are recoverable by inspection. The `Explore` PascalCase name is deliberate — it doubles as the round-trip fixture for § Agent-Name Invariants.

- [ ] Add `pathological_depth_session_dir` fixture: a chain 12 levels deep to exercise `_MAX_AGENT_DEPTH = 10`.

- [ ] Add `separator_in_name_session_dir` fixture: depth-2 session whose subagent has `agentType: "weird→name"` to exercise the invariant sanitizer.

- [ ] Add `symlink_cycle_session_dir` fixture (charge 3): depth-2 session where `<root>/subagents/agent-x/subagents` is a symlink/junction back to `<root>/subagents/`. Skip the fixture (and the test that uses it) with `pytest.skip(...)` on Windows if `os.symlink` raises `OSError` due to missing developer-mode privileges — document this in the fixture's docstring. Fall back to faking the cycle via `monkeypatch` on `Path.resolve` in that scenario.

- [ ] Add `sibling_shared_leaf_session_dir` fixture (pass-2 charge 1): a single session where the router calls `Explore` directly AND calls `project-planner`, which itself calls `Explore`. Resulting layout:

  ```
  projects/C--Users-chris--myproject/
    sess-sibling.jsonl                     # router: general-purpose
    sess-sibling/
      subagents/
        agent-explore-a.meta.json          # agentType: Explore (sibling of project-planner)
        agent-explore-a.jsonl
        agent-pp.meta.json                 # agentType: project-planner
        agent-pp.jsonl
        agent-pp/
          subagents/
            agent-explore-b.meta.json      # agentType: Explore (under project-planner)
            agent-explore-b.jsonl
  ```

  This fixture is the sibling-chains-with-shared-leaf round-trip case: two distinct `Explore` invocations differing only by ancestor. Each JSONL carries a distinct, recoverable token count so apportionment can be checked.

### Sibling chains with shared leaf names (intentional design)

The deepest-leaf computation in Phase 4 uses prefix-membership (`other.startswith(k + AGENT_PATH_SEPARATOR)`). When two chains share a leaf name but have different ancestors — e.g. `"general-purpose→Explore"` and `"general-purpose→project-planner→Explore"` — **neither is a prefix of the other**, so both survive as deepest leaves. This is correct and intentional:

- The two `Explore` invocations are distinct attribution units (different parents, different contexts). They are not the same agent run twice.
- Apportionment is correct: `s.agents.length == 2` means each leaf receives `T/2`, which matches the physical fact that the session contained two independent leaf chains.
- Bucketing in `by_agent` is correct: each path-key gets its own row, no double-counting.

A regression here would silently merge the two `Explore` rows in the dashboard, hiding one of the invocations. The test below pins this behavior.

**Red / Green:** N/A — fixture-only.

---

## Phase 2 — Model Migration

### Task 2.1: Add `agent_path` field with backward-compat property

- [ ] **Red:** Add `tests/test_models.py::TestAgentPath`:
  - `test_agent_type_returns_leaf` — construct `MessageRecord(agent_path=("router", "planner", "Explore"), ...)`; assert `record.agent_type == "Explore"`.
  - `test_agent_path_is_tuple_not_list` — assert `isinstance(record.agent_path, tuple)`.
  - `test_record_is_hashable` — assert `hash(record)` does not raise.
  - `test_depth_one_path` — `agent_path=("main",)`; `agent_type == "main"`.
  - `test_existing_properties_preserved` (pass-2 charge 3) — pin exact values, not just non-emptiness. Mirrors the existing `tests/test_models.py` cases at L13-L89 so this test catches regressions in the migrated dataclass even if the original tests were missed. Construct a `MessageRecord` with `input_tokens=100, output_tokens=200, cache_read_tokens=50, cache_creation_tokens=300` (distinct non-zero values) and assert `record.total_tokens == 650` (matches `test_total_tokens` at L24 of the existing test). For `model_short`, parameterize over the four buckets from `claude_usage/models.py:L31-L37`:
    - `model="claude-opus-4-7"` → `model_short == "opus"` (mirrors L50)
    - `model="claude-sonnet-4-5"` → `model_short == "sonnet"` (mirrors L63)
    - `model="claude-haiku-3-5"` → `model_short == "haiku"` (mirrors L76)
    - `model="claude-future-model-9"` → `model_short == "claude-future-model-9"` (unknown bucket — mirrors L89, the full-name fallback)

    Note: the field names are `cache_read_tokens` and `cache_creation_tokens` (verified `claude_usage/models.py:L19-L20`), not the longer `_input_` variants. Use exact field names — pytest fails fast on typos in dataclass kwargs.

- [ ] **Green:** In `claude_usage/models.py`:
  - Replace `agent_type: str` with `agent_path: tuple[str, ...]`.
  - Add `@property def agent_type(self) -> str: return self.agent_path[-1]` **above** the existing `total_tokens` property.
  - **Preserve `total_tokens` and `model_short` properties verbatim** — do not delete or rewrite them. The Phase 2 diff should add lines, not remove the existing property block.

- [ ] **Red (regression cascade):** `uv run pytest` — existing `test_models.py` (L17, L30, L43, L56, L69, L82, L107) and `test_aggregator.py::_msg` (L20) fail with `TypeError`.

- [ ] **Green:** Update construction sites:
  - `tests/test_models.py`: replace each `agent_type="X"` kwarg with `agent_path=("X",)`. Seven occurrences.
  - `tests/test_aggregator.py::_msg`: replace `agent_type=agent` with `agent_path=(agent,)` at L20.

- [ ] **Verify:** `uv run pytest` green. Parser still constructs flat 1-tuples through the helper.

### Task 2.2: Update `_parse_jsonl_messages` to accept a path tuple

- [ ] **Red:** Add `tests/test_parser.py::TestParseJsonlMessages::test_assigns_full_path` — call with `agent_path=("router", "planner")`; assert messages carry that tuple.

- [ ] **Green:** Change signature from `(jsonl_path, agent_type: str)` to `(jsonl_path, agent_path: tuple[str, ...])`. Update the `MessageRecord` construction at L78 to use `agent_path=agent_path`. Update both callers in `_parse_session` (currently L149 and L167) to wrap in 1-tuples: `agent_path=(root_agent,)` and `agent_path=(agent_type,)`.

- [ ] **Verify:** `uv run pytest` green. All `agent_path` values are still 1-tuples; `agent_type` property normalizes back to the leaf.

---

## Phase 3 — Parser Recursion

### Task 3.1: Extract the subagent walk into a recursive helper with cycle defense

- [ ] **Red:** Add `tests/test_parser.py::TestNestedSubagents`:
  - `test_depth_three_path_attributed` — uses `nested_session_dir`; finds at least one message with `agent_path == ("general-purpose", "project-planner", "Explore")`.
  - `test_depth_two_still_works` — re-runs on the existing `sample_session_dir` (depth-2); finds the code-writer message at `agent_path == ("general-purpose", "code-writer")`.
  - `test_subagent_types_flattened` — asserts `session.subagent_types` includes all three of `project-planner`, `Explore`, plus the existing flat-case agents (de-duped, sorted).
  - `test_missing_meta_json_skipped` — drop a stray `.jsonl` in `subagents/` without its `.meta.json`; assert no crash and no spurious messages.
  - `test_empty_subagents_dir_no_crash` — empty `subagents/` at depth 2.
  - `test_pathological_depth_cap` — uses `pathological_depth_session_dir`; assert no messages found below depth 10 and a single warning emitted (use `pytest.warns(...)`).
  - `test_pascalcase_agent_name_roundtrips` — covered by `nested_session_dir`'s `Explore`; assert path tuple's last segment is the literal `"Explore"`.
  - `test_separator_in_agent_name_sanitized` — uses `separator_in_name_session_dir`; assert `warnings.warn` fires AND `agent_path` last segment is the sanitized form (`"weird﹖name"`).
  - `test_symlink_cycle_short_circuits` (pass-2 charge 2) — uses `symlink_cycle_session_dir`. Must distinguish cycle defense from depth-cap fallback with two assertions:
    - **(a) Cycle-specific warning fires.** Use `pytest.warns(UserWarning, match=r"Subagent directory cycle detected")` — this exact substring is unique to the visited-set branch in `_parse_subagents_recursive`. The depth-cap branch emits a different message (`"Subagent recursion depth cap (10) exceeded"`), so matching on the cycle phrase proves the cycle defense fired, not the cap.
    - **(b) Cycled segment appears at most once with depth ≤ 3.** Collect all `agent_path` tuples from messages produced. For the segment that participates in the cycle (e.g. `"agent-x"`), assert `max(p.count("agent-x") for p in paths) <= 1` AND `max(len(p) for p in paths) <= 3`. Both bounds are well below `_MAX_AGENT_DEPTH = 10`, so if the visited-set silently failed and the cap fired instead, depth would be 10 and the segment would repeat ~9 times — this test catches that.
  - `test_depth_cap_fires_when_visited_set_misses` (pass-2 charge 2 symmetry) — uses `pathological_depth_session_dir` (12-deep chain, no cycle). Assert `pytest.warns(UserWarning, match=r"depth cap")` AND no message has `agent_path` longer than 10 segments. This pairs with the cycle test: together they prove the two defenses are independently observable.

- [ ] **Green:** Refactor `_parse_session`:
  - Introduce module-level constants `_MAX_AGENT_DEPTH = 10` and `_PATH_SEPARATOR = "→"`.
  - Extract the block at `parser.py:L152-L167` into `_parse_subagents_recursive(parent_session_dir, parent_path, subagent_types_accumulator, visited, depth, overflow_emitted)`.
  - Cycle defense: at function entry, compute `real_dir = parent_session_dir.resolve()`. If `real_dir in visited`: `warnings.warn(f"Subagent directory cycle detected: {real_dir}", stacklevel=2)`; return `[]`. Otherwise add `real_dir` to `visited` before walking. **The exact substring `"Subagent directory cycle detected"` is part of the contract** — the cycle test in Task 3.1 matches on it to distinguish from the depth-cap branch.
  - Depth cap: if `depth > _MAX_AGENT_DEPTH`: if `not overflow_emitted[0]`: `warnings.warn(f"Subagent recursion depth cap ({_MAX_AGENT_DEPTH}) exceeded at {parent_session_dir}", stacklevel=2)` and set `overflow_emitted[0] = True`. Return `[]`. **The substring `"depth cap"` is part of the contract** — see Task 3.1 symmetry test.
  - Subagent walk: for each `*.meta.json`, read `agentType`; if `_PATH_SEPARATOR in agentType`: sanitize via `.replace(_PATH_SEPARATOR, "﹖")` and warn. Append sanitized form to accumulator. Build `child_path = parent_path + (agentType_sanitized,)`. Parse the matching JSONL with that path. Recurse with `<parent_session_dir>/subagents/<agent_id>/` as the new parent, `depth + 1`, and the same `visited` and `overflow_emitted`.
  - `_parse_session` initializes `visited: set[Path] = set()` and `overflow_emitted = [False]`, and calls the helper with `parent_session_dir=jsonl_path.parent / session_id`, `parent_path=(root_agent_sanitized,)`, `depth=1`.

- [ ] **Verify:** `uv run pytest`. All new depth-3 + invariant + cycle tests pass. Existing depth-2 tests still pass.

---

## Phase 3.5 — Intermediate-State Sanity Probe (charge 5)

**Purpose:** At end of Phase 3, parser emits depth-3 records but aggregator still flattens via `agent_type` property → leaf segment. Without an explicit assertion here, a depth-3 fixture's `result.by_agent` ends up flat-keyed by the leaf (`"Explore"`), and this **looks correct on its own** but means Phase 0's baseline test is silent about it. Phase 3.5 makes the intermediate state visible.

### Task 3.5.1: Pin intermediate aggregator behavior on depth-3 fixture

- [ ] Add `tests/test_aggregator.py::TestIntermediatePhase3State::test_depth_three_flattens_to_leaf_until_phase_4` — use `nested_session_dir`; aggregate; assert:
  - `"Explore" in result.by_agent` (leaf-only key — because aggregator still uses `m.agent_type` property which returns `agent_path[-1]`).
  - `"general-purpose→project-planner→Explore" not in result.by_agent` (path-keyed form has not landed yet).
  - All depth-3 message tokens are credited to the `"Explore"` bucket (totals must equal the depth-3 fixture's token counts).
- [ ] **Document expected change in Phase 4:** add a comment in the test body: `# This test is rewritten in Phase 4 task 4.1 to assert path-keyed behavior. If you are reading this comment AFTER Phase 4 merged, delete this whole test class.`
- [ ] **Delete in Phase 4:** the deletion of this test class is itself a Phase 4.1 task line item (see below) — proves the migration completed.

**Why this matters:** the existing test suite at end-of-Phase-3 passes because every consumer of `m.agent_type` still gets a sensible leaf. Without this probe, an implementer running tests between Phase 3 and Phase 4 commits sees green and might wrongly conclude the work is done. The probe makes the "leaf-flatten still active" state into an explicit, asserted invariant — so any deviation surfaces immediately.

---

## Phase 4 — Aggregator Path Keys

### Task 4.1: Path-keyed `by_agent` rollup, deepest-leaf `agents_in_session`

- [ ] **Red:** Add `tests/test_aggregator.py::TestAggregateByAgentPath`:
  - `test_depth_one_uses_single_segment_key` — one message with `agent_path=("main",)`; assert `result.by_agent == {"main": {...}}`.
  - `test_depth_two_uses_delimited_key` — assert `"general-purpose→code-writer"` is a key.
  - `test_depth_three_uses_full_path_key` — assert `"general-purpose→project-planner→Explore"` is a key.
  - `test_intermediate_path_not_implicitly_created` — depth-3 fixture must NOT spuriously create a `"general-purpose→project-planner"` bucket.
  - `test_session_agents_uses_deepest_leaf_only` (charge 1) — for a session with a depth-3 chain, `result.sessions[0]["agents"]` contains `"general-purpose→project-planner→Explore"` and **does NOT contain** `"general-purpose"` or `"general-purpose→project-planner"`. Sibling chains (multiple subagents at the same parent) each contribute their own deepest leaf.
  - `test_session_agents_apportionment_invariant` (charge 1) — directly model the JS reAggregator's behavior in Python: for a depth-3 session with total_tokens T, assert `len(result.sessions[0]["agents"]) == 1`, so the JS `share = T / 1 = T` (no double-counting).
  - `test_sibling_chains_with_shared_leaf_both_survive` (pass-2 charge 1) — uses `sibling_shared_leaf_session_dir`. Aggregate; assert `agents_in_session` for that session contains **both** `"general-purpose→Explore"` AND `"general-purpose→project-planner→Explore"` (neither is a prefix of the other, so prefix-membership correctly keeps both). Also assert `result.by_agent` has both keys as independent buckets with non-zero `total_tokens` matching the fixture's per-chain token counts.
  - `test_session_agents_includes_root_when_no_subagents` — depth-1 session emits `["general-purpose"]`.
  - `test_primary_model_per_path_key` — each `by_agent[k]` carries `primary_model`.
  - `test_session_count_per_path_key` — each `by_agent[k]` carries `session_count`.

- [ ] **Green:** In `claude_usage/aggregator.py`:
  - Add module-level `AGENT_PATH_SEPARATOR = "→"  # "→"`.
  - Add helper `def _path_key(msg: MessageRecord) -> str: return AGENT_PATH_SEPARATOR.join(msg.agent_path)`.
  - Replace `agent = msg.agent_type` at L121 with `agent = _path_key(msg)`.
  - Replace L92 with **deepest-leaf computation**:
    ```python
    # Emit only the deepest path-key per chain so the dashboard JS does not
    # double-count when it apportions s.total_tokens / s.agents.length.
    all_path_keys = set(_path_key(m) for m in session_messages)
    leaf_path_keys = {
        k for k in all_path_keys
        if not any(other != k and other.startswith(k + AGENT_PATH_SEPARATOR) for other in all_path_keys)
    }
    agents_in_session = sorted(leaf_path_keys)
    ```
  - The `agent_session_count` block at L130-L137 needs no code change — it treats `session_summary["agents"]` as opaque strings.

- [ ] **Verify:** `uv run pytest`. All Phase 0 baseline tests (depth-1 and depth-2 totals) still pass — depth-1 paths produce single-segment keys identical to old leaf-keyed output. The Phase 3.5 intermediate-state test is now **expected to fail** because the aggregator no longer flat-keys; delete it as the next bullet.

- [ ] **Delete (1 of 2):** Remove `tests/test_aggregator.py::TestIntermediatePhase3State` (the Phase 3.5 probe — now subsumed by `TestAggregateByAgentPath`). Capture rationale in the commit message.

- [ ] **Delete (2 of 2):** Remove `tests/test_aggregator_baseline_flat.py` (Phase 0 baseline — now subsumed by depth-1 cases in `TestAggregateByAgentPath`).

**Pass-2 charge 4 — decision:** the two deletions are kept as **separate checkboxes** (split, not bundled). Rationale: the rest of the plan uses one-checkbox-per-action, and although Phase 6.1's full-suite gate would catch a forgotten deletion (the deleted test would still pass on its own, but `TestIntermediatePhase3State` would fail because the aggregator now produces path keys, not flat-leaf keys), an implementer skimming the checklist should see each deletion as its own step. Splitting also gives the commit history one delete-per-commit if the implementer commits per checkbox.

### Task 4.2: Update test_e2e.py read sites for depth-2 keys (charge 1b)

- [ ] **Red:** Run `uv run pytest tests/test_e2e.py::TestSubagentModelAttribution`. Expect failure at L220 (`"debugger" in result.by_agent`) because the key is now `"general-purpose→debugger"`.

- [ ] **Green:** Update `tests/test_e2e.py`:
  - L220-L223: change `"debugger"` → `"general-purpose→debugger"`.
  - L226: leave `"general-purpose"` as-is (it's a depth-1 root key).
  - Verify the `test_rendered_html_embeds_correct_primary_model_for_subagent` test still passes — its assertion about embedded HTML should match the new path key as well (the test reads `DATA.by_agent[...]` in the rendered HTML).

- [ ] **Verify:** `uv run pytest` green.

### Task 4.3: Confirm renderer is pass-through (carry-over from Phase 0)

- [ ] **Red:** N/A — Phase 0 Task 0.1 already proved this. This task only re-runs it as a regression gate after Phase 4's changes.

- [ ] **Verify:** `uv run pytest tests/test_renderer.py::test_path_keys_render_through` still green against a real `AggregateResult` produced from the depth-3 fixture (no longer a synthetic one).

---

## Phase 5 — Documentation & Cross-References

### Task 5.1: Update internal docs

- [ ] Update `docs/design.md` to reflect `agent_path: tuple[str, ...]` and the `agent_type` property.
- [ ] Add a "Nested agent attribution" section to `README.md` covering: depth limit, delimiter character, sanitization-on-collision rule, deepest-leaf rule for per-session agents, backward-compat property, and the deferred dashboard tree visualization.
- [ ] PR body must include `closes #41` as plain text on its own line per CLAUDE.md `§ Pull Requests`.

### Task 5.2: Session-summary non-regression check

- [ ] `uv run pytest tests/test_session_summary.py` — green.
- [ ] Interactive smoke: `uv run claude-usage session-summary <real transcript>` — output JSON byte-identical to pre-change capture. Diff in PR description.

---

## Phase 6 — Final Verification

### Task 6.1: Full suite + lint + format

- [ ] `uv run pytest` — green.
- [ ] `uv run ruff check .` — green.
- [ ] `uv run ruff format --check .` — green.
- [ ] `git diff main...HEAD --stat` — sanity-check every referenced file is in the diff (CLAUDE.md `§ Verify Artifact Persistence`).
- [ ] PR body includes `closes #41` as plain text.

### Task 6.2: Two inquisitor passes before merge

- [ ] Pass 1: model/parser layer + invariants + cycle defense (Phases 2-3, 3.5).
- [ ] Pass 2: aggregator + renderer + dashboard-JS-compatibility argument (Phases 4-5).
- [ ] Merge only after both clean.

---

## Test Strategy

### New test files / classes

| File | Purpose |
|---|---|
| `tests/test_models.py::TestAgentPath` | Backward-compat property + immutability + existing-property preservation. |
| `tests/test_parser.py::TestNestedSubagents` | Depth-3, depth cap, missing-meta, PascalCase round-trip, separator sanitization, symlink cycle. |
| `tests/test_aggregator.py::TestAggregateByAgentPath` | Path-keyed `by_agent`, no implicit intermediate buckets, deepest-leaf-only `agents_in_session`, apportionment invariant. |
| `tests/test_aggregator.py::TestIntermediatePhase3State` | Phase 3.5 sanity probe — deleted in Phase 4.1. |
| `tests/test_renderer.py::test_path_keys_render_through` | Renderer treats delimited keys as opaque; settles separator question in Phase 0. |
| `tests/test_aggregator_baseline_flat.py` | Phase 0 baseline — deleted in Phase 4.1. |
| `tests/conftest.py::nested_session_dir` | Depth-3 fixture (PascalCase leaf). |
| `tests/conftest.py::pathological_depth_session_dir` | 12-deep chain. |
| `tests/conftest.py::separator_in_name_session_dir` | Sanitization fixture. |
| `tests/conftest.py::symlink_cycle_session_dir` | Cycle defense fixture (Windows-skip-aware). |

### Existing tests that must continue to pass

| Test | Why it must pass |
|---|---|
| `tests/test_parser.py::TestParseSessions::*` | Depth-1/2 attribution unchanged via property. |
| `tests/test_aggregator.py::TestAggregateByAgent::*` (L81-L110) | Flat-case (depth-1) totals identical — depth-1 path keys are single-segment. |
| `tests/test_session_summary.py::*` (17 tests) | Subcommand untouched. |
| `tests/test_dashboard_snapshot.py` | Pre-refactor snapshot byte-identical on depth-1 baseline fixture. |
| `tests/test_skill_tracking.py::*` | No data-model coupling. |
| `tests/test_e2e.py::TestEndToEnd::*` | End-to-end depth-1; assertions at L21 stay valid. |
| `tests/test_e2e.py::TestSubagentModelAttribution::*` | Depth-2; assertions at L220-L223 updated to new key shape (in scope, Phase 4 Task 4.2). |

### Gate definition

If any test outside the enumerated edit list (`test_models.py` × 7, `test_aggregator.py` × 1, `test_e2e.py` × 4 lines) requires modification, **stop and re-evaluate** — that signals an unenumerated read site of the old key shape.

---

## Migration & Backward Compatibility

Every reading consumer of `agent_type` continues to work via the `@property` shim. Only construction sites (`agent_path=...` kwarg) and the enumerated test read sites of the old key shape need edits.

| Consumer | File | Lines | Read or write? | Action |
|---|---|---|---|---|
| Aggregator `by_agent` grouping | `claude_usage/aggregator.py` | L92, L121 | read | Switches to `_path_key(msg)` in Phase 4. Property still works for any future leaf-only consumer. |
| Aggregator `agents_in_session` deepest-leaf | `claude_usage/aggregator.py` | L92 | read | Replaced by deepest-leaf computation in Phase 4. |
| Parser construction site | `claude_usage/parser.py` | L78 | write | `agent_path=...` kwarg (Phase 2). |
| Parser caller wrap | `claude_usage/parser.py` | L149, L167 | write | Wrap in 1-tuple at first; replaced by full recursion in Phase 3. |
| Test construction (models) | `tests/test_models.py` | L17, L30, L43, L56, L69, L82, L107 | write | Replace `agent_type="X"` → `agent_path=("X",)`. |
| Test construction (aggregator helper) | `tests/test_aggregator.py` | L20 | write | Replace `agent_type=agent` → `agent_path=(agent,)`. |
| Test read (e2e depth-2 keys) | `tests/test_e2e.py` | L220, L221, L223 | read | Update literal key `"debugger"` → `"general-purpose→debugger"`. |
| Test read (e2e depth-1 keys) | `tests/test_e2e.py` | L21, L226, L281 | read | No change — depth-1 keys stay single-segment. |
| Test read (parser) | `tests/test_parser.py` | L54, L59 | read | No change — `m.agent_type` property covers. |
| Session-summary subcommand | `claude_usage/cli/session_summary.py` | L332-L339 | n/a | Reads raw transcript JSON. No change. |
| Renderer | `claude_usage/renderer.py` | L46 | read (opaque) | Treats `by_agent` keys as opaque strings. No change. |
| Dashboard CLI | `claude_usage/cli/dashboard.py` | n/a | n/a | No field access. |
| Design doc | `docs/design.md` | various | doc | Update text only. |
| Plan doc | `docs/plan.md` | various | doc | Reference doc — opportunistic. |

---

## Risks & Open Questions

### Open Questions (resolve before merge)

1. **Renderer encoding of `"→"`.** **Resolved — Phase 0 Task 0.1, commit `3114822`.**

   U+2192 round-trips through the renderer as a **JSON `→` escape** — the literal 6-character ASCII sequence `→` in the HTML source. This is the default behavior of `json.dumps` with `ensure_ascii=True` (the Python stdlib default). The browser's `JSON.parse` decodes the escape back to U+2192 transparently, so `DATA.by_agent["general-purpose→Explore"]` resolves correctly client-side.

   The relevant escape layer is **`json.dumps`**, not Jinja autoescape. Jinja never touches the path keys because they live inside the `const DATA = ...` block, which is emitted via a `|safe` (or equivalent pass-through) filter — Jinja autoescape is therefore a non-issue for the JSON payload. The HTML-entity forms `&#8594;` and `&rarr;` do **not** appear; those forms would only arise if Jinja processed the string as template text, which it does not.

   The `" / "` fallback is **not needed**. All downstream fixtures and assertions reference `aggregator.AGENT_PATH_SEPARATOR` (the `"→"` constant) directly.

2. **Overflow warning channel.** Use `warnings.warn(..., UserWarning)` so `pytest.warns(...)` matches. Settled at code-writer time.

3. **`primary_model` semantics for intermediate path buckets.** Not created — only literal observed paths bucket. Tree-rollup view is out of scope.

4. **Symlink cycle behavior across platforms.** `Path.resolve()` normalizes POSIX symlinks reliably, so the visited-set defense catches cycles via symlinks on Linux/macOS. **On Windows, junctions are NOT normalized the same way by `Path.resolve()`** — junction-based cycles fall through to the depth-cap defense (`_MAX_AGENT_DEPTH = 10`) rather than being caught by the visited-set. This is acceptable: the depth cap still terminates recursion, just with up to 10 wasted frames instead of 1, and emits its own warning. The two test cases in Task 3.1 pin this split behavior:
   - `test_symlink_cycle_short_circuits` runs on POSIX (skipped on Windows when `os.symlink` raises) and proves the visited-set fires.
   - `test_depth_cap_fires_when_visited_set_misses` runs everywhere and proves the cap fires on a non-cyclic deep chain — which is the same defense that catches Windows junctions in production.
   Document the Windows-junction fallthrough in the README "Nested agent attribution" section (Phase 5).

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Jinja autoescape mangles `"→"` in HTML | **Eliminated** | Medium | Phase 0 Task 0.1 (commit `3114822`) confirmed Jinja never processes the JSON payload (emitted via `|safe`). `json.dumps` JSON-escapes to `→`; `JSON.parse` decodes it. Fallback not needed. |
| Agent name contains `"→"` (real-world) | Very low | Medium | Sanitize at parse time + warn; round-trip fixture proves it. |
| Symlink cycle blows recursion | Low (Windows: very low without dev-mode) | High (infinite loop) | `Path.resolve()` visited-set short-circuits; fixture test exercises it. |
| `tuple` field breaks an unknown internal serializer | Low | Medium | Grep enumerated all constructors. `json.dumps` serializes tuples as lists naturally. |
| Recursion blows the stack | Very low | Low | `_MAX_AGENT_DEPTH = 10` ≪ Python's 1000-frame default. |
| Phase-2 misses a construction site | Low | Low | Eight sites total, all enumerated. |
| Dashboard JS double-counts via ancestor inclusion | **Mitigated by design** | High (would silently inflate ancestor token totals) | Deepest-leaf rule for `agents_in_session` plus `test_session_agents_apportionment_invariant` regression test. |

---

## Phase / Task Summary

- **7 phases** (0, 1, 2, 3, 3.5, 4, 5, 6 — Phase 3.5 is the intermediate-state sanity probe), **~16 numbered tasks** total.
- Single PR, vertical slice, mergeable as one unit, with `closes #41` in the body.
- All claims cited to verifiable repo files (file:line) re-verified during plan revision (pass-1 charges 1-6 addressed in-line).

🤖 _Generated by Claude Code on behalf of @cbeaulieu-gt_
