"""Session-summary subcommand: derive a structured recap from a transcript.

Walks a Claude Code transcript JSONL once, derives project, intent,
actions, and stoppedNaturally deterministically, and emits the result
as pretty-printed JSON to stdout.

Exit codes:
    0  Success — JSON written to stdout.
    1  IO failure — file missing, unreadable, or other OSError.
    2  No user turns — transcript has no external user entries.
    3  Not JSONL — file has content but every line fails json.loads.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_IO_FAILURE = 1
EXIT_NO_USER_TURNS = 2
EXIT_NOT_JSONL = 3

DEFAULT_MAX_ACTIONS: int = 50

_EDIT_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "NotebookEdit"})
_BASH_TOOLS: frozenset[str] = frozenset({"Bash", "PowerShell"})
_MAX_COMMAND_CHARS: int = 80
SKIPPED_TOOLS: frozenset[str] = frozenset(
    {
        "Read",
        "Grep",
        "Glob",
        "WebFetch",
        "WebSearch",
        "Skill",
        "TodoWrite",
    }
)

_XML_WRAPPER_RE = re.compile(
    r"<(system-reminder|command-message|command-name"
    r"|command-args|local-command-stdout)>.*?</\1>",
    flags=re.DOTALL,
)
_SLASH_COMMAND_RE = re.compile(r"<command-name>(/[^<]+)</command-name>")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?])\s|\n")


@dataclass(frozen=True)
class ActionRecord:
    """A single classified tool-use action from a transcript.

    Attributes:
        type: Action category — one of "edit", "bash", "agent_dispatch",
            "mcp", or "other".
        raw_tool: The original tool name as it appears in the transcript.
        target: The primary subject of the action (file path, command,
            agent name, MCP server.method) — used as the collapse key.
        summary: A past-tense human-readable string suitable for display.
    """

    type: str
    raw_tool: str
    target: str
    summary: str


@dataclass(frozen=True)
class SessionSummary:
    """Derived session recap ready for JSON serialisation.

    Attributes:
        project: Repository or project name. Never empty; falls back to
            "unknown" when undetectable.
        intent: One-sentence description of what the session set out to do.
            Never empty; falls back to "Ran /<command>" for slash-command
            sessions or "Session on <project>" as a final fallback.
        actions: Chronologically ordered list of past-tense action strings,
            bounded by the max_actions cap. May be empty when the session
            contained no state-changing tool uses.
        stopped_naturally: True when the last assistant turn ended cleanly
            ("end_turn"), False on any definitive interrupt signal, or None
            when the signal is indeterminate (no assistant entries, or
            stop_reason absent/unrecognised).
    """

    project: str
    intent: str
    actions: list[str]
    stopped_naturally: bool | None


def _derive_project(entries: list[dict], slug_fallback: str | None = None) -> str:
    """Derive the project name from transcript entries.

    Strategy:
    1. First entry with a non-empty ``cwd`` field → ``Path(cwd).name``.
    2. Fallback: apply ``decode_project_hash`` to ``slug_fallback``
       (the transcript-directory name passed in by ``run()``).
    3. Final fallback: ``"unknown"``.

    Args:
        entries: Parsed JSONL entries in file order.
        slug_fallback: Optional project-slug string from the transcript
            directory name, used when no ``cwd`` field appears on any
            entry.

    Returns:
        A non-empty project name string.
    """
    from claude_usage.parser import decode_project_hash

    # Strategy 1: cwd field on any entry.
    for entry in entries:
        cwd = entry.get("cwd")
        if cwd and isinstance(cwd, str):
            name = Path(cwd).name
            if name:
                return name

    # Strategy 2: decode the project-hash slug supplied by the caller.
    if slug_fallback:
        decoded = decode_project_hash(slug_fallback)
        if decoded:
            return decoded

    # Strategy 3: final fallback.
    return "unknown"


def _extract_text_from_content(
    content: str | list,
) -> str:
    """Extract plain text from a message content value.

    Args:
        content: Either a raw string or a list of content blocks. In the
            list form, only blocks with ``type == "text"`` are included;
            tool_result and other block types are skipped.

    Returns:
        A single string with all text joined by spaces, not yet stripped.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and "text" in block
        ]
        return " ".join(parts)
    return ""


def _first_sentence(text: str, max_chars: int = 200) -> str:
    """Return the first sentence of text, capped at max_chars.

    Splits on ". ", "! ", "? ", or a newline. If the first segment is
    longer than max_chars, truncates at max_chars. Trailing punctuation
    from the split is not included in the result.

    Args:
        text: Already-stripped input text.
        max_chars: Maximum character count for the returned string.

    Returns:
        The first sentence or the first max_chars characters.
    """
    parts = _SENTENCE_SPLIT_RE.split(text, maxsplit=1)
    sentence = parts[0].rstrip(". !?")
    return sentence[:max_chars]


def _derive_intent(entries: list[dict], project: str) -> str:
    """Derive the user's intent from the first external user turn.

    Steps:
    1. Find the first ``type: "user"`` + ``userType: "external"`` entry.
    2. Extract text from ``message.content`` (string or list of blocks).
    3. Strip the five XML wrapper tag families via regex.
    4. Trim whitespace. If non-empty → take the first sentence (or 200
       chars, whichever is shorter).
    5. If empty, look for a ``<command-name>/<name></command-name>``
       pattern in the original content → ``"Ran /<name>"``.
    6. Final fallback → ``"Session on <project>"``.

    Args:
        entries: Parsed JSONL entries in file order.
        project: The already-derived project name (used as fallback).

    Returns:
        A non-empty intent string.
    """
    for entry in entries:
        if not (entry.get("type") == "user" and entry.get("userType") == "external"):
            continue
        msg = entry.get("message", {})
        raw_content = msg.get("content", "")
        original_text = _extract_text_from_content(raw_content)

        # Strip XML wrappers.
        stripped = _XML_WRAPPER_RE.sub("", original_text).strip()

        if stripped:
            return _first_sentence(stripped)

        # Slash-command fallback.
        m = _SLASH_COMMAND_RE.search(original_text)
        if m:
            return f"Ran {m.group(1)}"

        # Generic fallback.
        return f"Session on {project}"

    # No external user turn found (should not reach here after LookupError
    # guard in build_session_summary, but keep defensive).
    return f"Session on {project}"


def _normalize_mcp_tool_name(raw: str) -> str | None:
    """Normalize an MCP tool name to '<server>.<method>'.

    Handles both forms:
    - Plugin-scoped: ``mcp__plugin_<plugin>_<server>__<method>``
      e.g. ``mcp__plugin_github_github__create_issue`` → ``github.create_issue``
    - Direct: ``mcp__<server>__<method>``
      e.g. ``mcp__azure__storage`` → ``azure.storage``

    Returns None when the name is malformed (starts with ``mcp__`` but
    does not contain the expected structural separators after stripping
    the plugin segment), so the caller can fall back to the ``other``
    action class. This provides forward-compatibility when new MCP naming
    conventions appear in future Claude Code versions.

    Args:
        raw: The raw tool name from the transcript.

    Returns:
        A normalised ``<server>.<method>`` string, or None if the name
        is structurally malformed.
    """
    if not raw.startswith("mcp__"):
        return None
    remainder = raw[len("mcp__") :]

    # Strip the plugin segment if present.
    # Plugin form: plugin_<plugin>_<server>__<method>
    # After stripping "plugin_", the next segment is "<plugin>_<server>"
    # which is separated from <method> by "__".
    if remainder.startswith("plugin_"):
        after_plugin = remainder[len("plugin_") :]
        # after_plugin is "<plugin>_<server>__<method>" — split once on "_"
        # to skip the plugin label, leaving "<server>__<method>".
        parts = after_plugin.split("_", 1)
        if len(parts) < 2:
            return None  # Malformed: nothing after plugin label.
        remainder = parts[1]

    # remainder is now "<server>__<method>" for both forms.
    if "__" not in remainder:
        return None  # Malformed: no method separator.
    server, _, method = remainder.partition("__")
    if not server or not method:
        return None  # Malformed: empty server or method.
    return f"{server}.{method}"


def _classify_tool_use(tool_use: dict) -> ActionRecord | None:
    """Classify a single tool-use content block into an ActionRecord.

    Returns None only for tools in SKIPPED_TOOLS (info-gathering,
    skill enablers, ceremony). Every other tool name produces an
    ActionRecord — either a typed record for known tools or an
    ``other``-type record for forward compatibility with unknown tools.

    Classification priority:
    1. Skip list (SKIPPED_TOOLS) — return None immediately.
    2. Edit family (_EDIT_TOOLS) — return "edit" ActionRecord.
    3. Bash/PowerShell family (_BASH_TOOLS) — return "bash" ActionRecord.
    4. Agent dispatch — return "agent_dispatch" ActionRecord.
    5. MCP tools (mcp__* prefix) — normalise name; return "mcp" on success,
       "other" on malformed name.
    6. Catch-all — return "other" ActionRecord for forward compatibility.

    Args:
        tool_use: A content block dict with ``type == "tool_use"``.

    Returns:
        An ActionRecord, or None if this tool use is in the skip list.
    """
    name: str = tool_use.get("name", "")
    inp: dict = tool_use.get("input", {})

    # 1. Skip list — info-gathering and ceremony.
    if name in SKIPPED_TOOLS:
        return None

    # 2. Edit family.
    if name in _EDIT_TOOLS:
        target = inp.get("file_path", "")
        return ActionRecord(
            type="edit",
            raw_tool=name,
            target=target,
            summary=f"Edited {target}",
        )

    # 3. Bash / PowerShell.
    if name in _BASH_TOOLS:
        raw_command: str = inp.get("command", "")
        collapsed_command = " ".join(raw_command.split())
        if len(collapsed_command) > _MAX_COMMAND_CHARS:
            rendered = collapsed_command[:_MAX_COMMAND_CHARS] + "…"
        else:
            rendered = collapsed_command
        return ActionRecord(
            type="bash",
            raw_tool=name,
            target=collapsed_command,
            summary=f"Ran `{rendered}`",
        )

    # 4. Agent dispatch.
    if name == "Agent":
        subagent_type: str = inp.get("subagent_type", "unknown")
        return ActionRecord(
            type="agent_dispatch",
            raw_tool=name,
            target=subagent_type,
            summary=f"Dispatched {subagent_type} sub-agent",
        )

    # 5. MCP tools — both plugin-scoped and direct forms.
    if name.startswith("mcp__"):
        normalised = _normalize_mcp_tool_name(name)
        if normalised is not None:
            return ActionRecord(
                type="mcp",
                raw_tool=name,
                target=normalised,
                summary=f"Called `{normalised}` (MCP)",
            )
        # Malformed MCP name — fall through to the "other" default below.
        # Do NOT return None here; let the catch-all produce an ActionRecord.
        return ActionRecord(
            type="other",
            raw_tool=name,
            target=name,
            summary=f"Used {name} tool",
        )

    # 6. Catch-all — default-include unknown tools for forward compatibility.
    return ActionRecord(
        type="other",
        raw_tool=name,
        target=name,
        summary=f"Used {name} tool",
    )


def _collapse_consecutive(
    records: list[ActionRecord],
) -> list[ActionRecord]:
    """Collapse consecutive ActionRecords that share (type, target).

    Non-adjacent duplicates are NOT collapsed — chronological order
    is preserved and the collapse is strictly sequential.

    Args:
        records: Chronologically ordered list of ActionRecords.

    Returns:
        Collapsed list with no two adjacent records sharing
        (type, target).
    """
    if not records:
        return []
    collapsed: list[ActionRecord] = [records[0]]
    for rec in records[1:]:
        prev = collapsed[-1]
        if rec.type == prev.type and rec.target == prev.target:
            continue  # Duplicate of the previous record — drop it.
        collapsed.append(rec)
    return collapsed


def _collect_tool_uses(entries: list[dict]) -> list[ActionRecord]:
    """Classify all tool-use content blocks from assistant entries.

    Iterates entries in file order, collects tool_use blocks from
    assistant message content, classifies each, skips None results,
    then collapses consecutive duplicates.

    Args:
        entries: Parsed JSONL entries in file order.

    Returns:
        Chronologically ordered, collapsed list of ActionRecord
        instances.
    """
    raw: list[ActionRecord] = []
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            record = _classify_tool_use(block)
            if record is not None:
                raw.append(record)
    return _collapse_consecutive(raw)


def _derive_stopped_naturally(
    entries: list[dict],
) -> bool | None:
    """Resolve the tri-state stoppedNaturally field per the spec's table.

    Walks entries once, tracking:
    - ``has_any_assistant``: True once any assistant entry is seen.
    - ``last_stop_reason``: Updated on every assistant entry; last wins.
    - ``prevented_continuation``: True if any stop_hook_summary entry
      has ``preventedContinuation: true``.

    Resolution table (applied in priority order):
    - no assistant entries → None (nothing to judge)
    - last stop_reason absent/empty → None (signal absent)
    - prevented_continuation is True → False (definitive interrupt)
    - last stop_reason == "end_turn" → True
    - last stop_reason in {"max_tokens", "tool_use", "stop_sequence"} → False
    - any other non-empty stop_reason → None (unknown variant; don't guess)

    Callers emit None as JSON null so consumers can distinguish
    'unknown' from 'interrupted'.

    Args:
        entries: Parsed JSONL entries in file order.

    Returns:
        True for a clean natural end, False for a definitive interrupt
        signal, or None when the signal is genuinely indeterminate.
    """
    has_any_assistant: bool = False
    last_stop_reason: str | None = None
    prevented_continuation: bool = False

    for entry in entries:
        etype = entry.get("type")

        if etype == "assistant":
            has_any_assistant = True
            message = entry.get("message") or {}
            reason = message.get("stop_reason")
            # Update on every assistant entry — last one wins.
            last_stop_reason = reason if reason else None

        elif etype == "system":
            if entry.get("subtype") == "stop_hook_summary":
                if entry.get("preventedContinuation") is True:
                    prevented_continuation = True

    # Resolution table — applied in priority order.
    if not has_any_assistant:
        return None
    if last_stop_reason is None:
        return None
    if prevented_continuation:
        return False
    if last_stop_reason == "end_turn":
        return True
    if last_stop_reason in ("max_tokens", "tool_use", "stop_sequence"):
        return False
    # Unknown non-empty stop_reason — don't guess.
    return None


def _apply_max_actions_cap(
    actions: list[str],
    max_actions: int,
) -> list[str]:
    """Apply the --max-actions cap with sentinel truncation.

    When ``max_actions`` is 0, the cap is disabled and the full list is
    returned. Otherwise, if ``len(actions) > max_actions``, keep the
    first ``max_actions - 1`` entries and append a sentinel string of
    the form ``'… (<K> additional actions omitted)'`` where ``K`` is the
    number of dropped entries.

    Args:
        actions: Already-rendered past-tense action strings.
        max_actions: Cap value. 0 means no cap.

    Returns:
        The (possibly truncated) list of action strings.
    """
    if max_actions <= 0:
        return list(actions)
    if len(actions) <= max_actions:
        return list(actions)
    kept = actions[: max_actions - 1]
    dropped = len(actions) - (max_actions - 1)
    sentinel = f"… ({dropped} additional actions omitted)"
    return [*kept, sentinel]


def read_transcript(
    path: Path,
) -> tuple[list[dict], int]:
    """Read and parse a JSONL transcript file.

    Opens *path*, iterates its lines, skips blanks, silently skips
    individual lines that fail ``json.loads``, and returns the
    successfully parsed entries together with the total non-blank
    line count.

    The non-blank count is used by ``run`` to distinguish an
    empty/whitespace-only file (exit 2) from a file that has content
    but none of it parses (exit 3).

    Args:
        path: Absolute or relative path to the JSONL transcript file.

    Returns:
        A 2-tuple ``(entries, non_blank_lines)`` where *entries* is
        the list of successfully parsed dicts and *non_blank_lines*
        is the count of non-empty, non-whitespace lines seen.

    Raises:
        OSError: Any subclass raised by ``open()`` or line iteration
            (``FileNotFoundError``, ``PermissionError``, etc.).
    """
    entries: list[dict] = []
    non_blank_lines = 0
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            non_blank_lines += 1
            try:
                entries.append(json.loads(stripped))
            except json.JSONDecodeError:
                pass  # tolerate individual-line failures
    return entries, non_blank_lines


def build_session_summary(
    entries: list[dict],
    *,
    project_slug_fallback: str | None = None,
    max_actions: int = DEFAULT_MAX_ACTIONS,
) -> SessionSummary:
    """Build a SessionSummary from already-parsed transcript entries.

    Pure function — no I/O. The caller (run()) is responsible for reading
    the file and parsing JSONL; this function only classifies, derives,
    and renders.

    Args:
        entries: Parsed JSONL entries (already filtered for successfully
            decoded objects).
        project_slug_fallback: Optional transcript-directory slug passed
            through to ``_derive_project`` for the ``decode_project_hash``
            fallback when no ``cwd`` field appears on any entry.
        max_actions: Soft cap on emitted actions; 0 disables the cap.

    Returns:
        Fully-populated SessionSummary.
    """
    project = _derive_project(entries, project_slug_fallback)
    intent = _derive_intent(entries, project)
    records = _collect_tool_uses(entries)
    stopped_naturally = _derive_stopped_naturally(entries)

    # Render ActionRecords to strings, then apply the cap.
    action_strings_full = [r.summary for r in records]
    action_strings = _apply_max_actions_cap(action_strings_full, max_actions)

    return SessionSummary(
        project=project,
        intent=intent,
        actions=action_strings,
        stopped_naturally=stopped_naturally,
    )


def _summary_to_dict(summary: SessionSummary) -> dict:
    """Convert a SessionSummary to an ordered dict matching the JSON contract.

    Key order matches the spec: project → intent → actions →
    stoppedNaturally.  Python 3.7+ preserves dict insertion order,
    making ``json.dumps`` output deterministic across runs.

    Args:
        summary: The session summary dataclass instance to convert.

    Returns:
        An ordered dict with camelCase keys ready for ``json.dumps``.
        Keys: ``project``, ``intent``, ``actions``,
        ``stoppedNaturally``.
    """
    return {
        "project": summary.project,
        "intent": summary.intent,
        "actions": summary.actions,
        "stoppedNaturally": summary.stopped_naturally,
    }


def render_json(summary: SessionSummary) -> str:
    """Render a SessionSummary as a pretty-printed JSON string.

    Produces the exact wire format consumed by the ``/whats-next``
    skill.  Uses ``indent=2`` and ``ensure_ascii=False`` per spec.
    Key order is deterministic: project, intent, actions,
    stoppedNaturally.

    Does **not** append a trailing newline — the caller (``run``)
    adds exactly one before printing to stdout, ensuring the
    stdout/stderr discipline invariant.

    Args:
        summary: The session summary dataclass instance.

    Returns:
        A JSON string without a trailing newline.
    """
    return json.dumps(_summary_to_dict(summary), indent=2, ensure_ascii=False)


def _tri_state_to_word(value: bool | None) -> str:
    """Convert a tri-state boolean to a display word.

    Args:
        value: ``True``, ``False``, or ``None``.

    Returns:
        ``"yes"`` for ``True``, ``"no"`` for ``False``,
        ``"unknown"`` for ``None``.
    """
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def render_text(summary: SessionSummary) -> str:
    """Render a SessionSummary as a human-readable debug string.

    Intended for ``--format text`` — not consumed by ``/whats-next``.
    Useful for manual inspection and debugging.

    Output template::

        Project: {project}
        Intent: {intent}
        Stopped naturally: {yes|no|unknown}

        Actions:
          - {action 1}
          - {action 2}
          ...

    Args:
        summary: The session summary dataclass instance.

    Returns:
        Multi-line string.  Does not end with a trailing newline —
        the caller (``run``) adds exactly one.
    """
    lines = [
        f"Project: {summary.project}",
        f"Intent: {summary.intent}",
        f"Stopped naturally: {_tri_state_to_word(summary.stopped_naturally)}",
        "",
        "Actions:",
    ]
    for action in summary.actions:
        lines.append(f"  - {action}")
    return "\n".join(lines)


def build_parser(
    parent: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    """Register the 'session-summary' subparser and return it.

    Args:
        parent: The subparsers action from the top-level parser.

    Returns:
        The configured session-summary ArgumentParser.
    """
    p = parent.add_parser(
        "session-summary",
        help="Emit a deterministic JSON recap of a Claude Code transcript.",
    )
    p.add_argument(
        "--path",
        required=True,
        help="Path to the transcript JSONL file.",
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "text"],
        default="json",
        help="Output format: 'json' (default) or 'text' (debug view).",
    )
    p.add_argument(
        "--max-actions",
        type=int,
        default=DEFAULT_MAX_ACTIONS,
        dest="max_actions",
        help=(
            "Soft cap on emitted actions. 0 disables the cap. "
            f"Default: {DEFAULT_MAX_ACTIONS}."
        ),
    )
    return p


def run(args: argparse.Namespace) -> int:
    """Entry point for the session-summary subcommand.

    Dispatches ``--path`` through the full parse → summarise → render
    pipeline, printing JSON (or text) to stdout on success and a
    single diagnostic line to stderr on failure.

    Args:
        args: Parsed CLI namespace.  Expected attributes:
            ``args.path`` (str), ``args.output_format`` (str),
            ``args.max_actions`` (int).

    Returns:
        Integer exit code (one of ``EXIT_OK``, ``EXIT_IO_FAILURE``,
        ``EXIT_NO_USER_TURNS``, ``EXIT_NOT_JSONL``).
    """
    path = Path(args.path)

    # ── Phase 4.1: IO failure ────────────────────────────────────────
    try:
        entries, non_blank_lines = read_transcript(path)
    except OSError as exc:
        print(
            f"session-summary: cannot read transcript at '{path}': "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_IO_FAILURE

    # ── Phase 4.3: not JSONL ─────────────────────────────────────────
    # Condition: file had parseable-attempt content (non_blank_lines > 0)
    # but zero entries survived json.loads.
    # NOTE: non_blank_lines == 0 means empty/whitespace-only → fall
    # through to the no-user-turns check (exit 2), not here.
    if not entries and non_blank_lines > 0:
        print(
            f"session-summary: transcript '{path}' is not valid JSONL",
            file=sys.stderr,
        )
        return EXIT_NOT_JSONL

    # ── Phase 4.2: no user turns ─────────────────────────────────────
    has_user_turns = any(
        entry.get("type") == "user" and entry.get("userType") == "external"
        for entry in entries
    )
    if not has_user_turns:
        print(
            f"session-summary: transcript '{path}' contains no user turns",
            file=sys.stderr,
        )
        return EXIT_NO_USER_TURNS

    # ── Success path (exit 0) ────────────────────────────────────────
    # Non-fatal warning: malformed lines were skipped.
    skipped = non_blank_lines - len(entries)
    if skipped > 0:
        print(
            f"session-summary: skipped {skipped} malformed line(s) in '{path}'",
            file=sys.stderr,
        )

    # run() is the single I/O site. Pass already-parsed entries so
    # build_session_summary performs no file I/O.
    slug = path.parent.name if path.parent.name else None
    summary = build_session_summary(
        entries,
        project_slug_fallback=slug,
        max_actions=args.max_actions,
    )

    if args.output_format == "json":
        output = render_json(summary)
    else:
        output = render_text(summary)

    # Exactly one trailing newline — the JSON/text contract.
    print(output, flush=True)
    return EXIT_OK
