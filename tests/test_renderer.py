"""Tests for the HTML dashboard renderer, including responsiveness."""

from __future__ import annotations

import json
from pathlib import Path

from claude_usage.aggregator import AggregateResult, aggregate
from claude_usage.parser import parse_sessions
from claude_usage.renderer import render

# U+2192 RIGHTWARDS ARROW — the candidate separator for nested agent path keys.
# Phase 0 Task 0.1 settles whether this character survives the renderer's
# Jinja autoescape pass intact (or as an HTML entity) and whether it appears
# verbatim in the embedded JSON payload that the dashboard JS reads.
_ARROW = "→"


def _minimal_result() -> AggregateResult:
    """Build a minimal AggregateResult with no sessions."""
    return AggregateResult()


def _render_html(tmp_path: Path, result: AggregateResult | None = None) -> str:
    """Render the dashboard and return the HTML string.

    Args:
        tmp_path: Pytest temporary directory.
        result: Aggregate result to render. Defaults to a minimal result.

    Returns:
        Rendered HTML as a string.
    """
    if result is None:
        result = _minimal_result()
    output = tmp_path / "dashboard.html"
    render(result, output_path=output, open_browser=False)
    return output.read_text(encoding="utf-8")


class TestResponsiveness:
    """Verify the rendered dashboard HTML is responsive."""

    def test_rendered_html_contains_media_query(self, tmp_path: Path) -> None:
        """Rendered dashboard must contain at least one @media query.

        Without @media queries the layout cannot adapt to narrow viewports.
        This is the minimal gate for a responsive dashboard.
        """
        html = _render_html(tmp_path)
        assert "@media" in html, (
            "Rendered dashboard HTML must contain at least one @media query "
            "so the layout adapts to different viewport sizes."
        )

    def test_viewport_meta_tag_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain a viewport meta tag.

        The viewport meta tag is required so mobile browsers scale the
        layout to the device width rather than rendering a zoomed-out
        desktop view.
        """
        html = _render_html(tmp_path)
        assert (
            'name="viewport"' in html
        ), "Rendered HTML must contain a viewport meta tag."
        assert (
            "width=device-width" in html
        ), "Viewport meta tag must include width=device-width."

    def test_gauge_grid_uses_auto_fill(self, tmp_path: Path) -> None:
        """Gauge grid must use auto-fill or responsive grid-template-columns.

        A fixed ``repeat(3, 1fr)`` column definition will not wrap on narrow
        screens. The fix uses ``repeat(auto-fill, minmax(...))`` or media
        queries to allow the grid to collapse.
        """
        html = _render_html(tmp_path)
        has_autofill = "auto-fill" in html or "auto-fit" in html
        has_gauge_media = "@media" in html and ".gauges" in html
        assert has_autofill or has_gauge_media, (
            "Gauge grid must use auto-fill/auto-fit or a media query so it "
            "collapses from 3 columns to fewer on narrow screens."
        )

    def test_grid2_collapses_on_narrow_screens(self, tmp_path: Path) -> None:
        """Two-column card sections must collapse to one column via @media.

        The .grid-2 class currently uses a fixed two-column layout. On
        screens below ~800 px it must become a single column.
        """
        html = _render_html(tmp_path)
        # The template must define a breakpoint that makes .grid-2
        # single-column. We accept any media query that references grid-2.
        assert "@media" in html and "grid-2" in html, (
            "A @media query targeting .grid-2 must be present to collapse "
            "the two-column layout on narrow screens."
        )

    def test_session_list_responsive(self, tmp_path: Path) -> None:
        """Session list must be responsive: stacked cards or scroll container.

        The fixed grid-template-columns on .session-row forces horizontal
        overflow at narrow widths. The fix must either switch to a stacked
        card layout via @media, or wrap the list in an overflow-x:auto
        container so scrolling is contained rather than page-wide.
        """
        html = _render_html(tmp_path)
        has_session_media = "@media" in html and "session" in html
        has_overflow_scroll = (
            "overflow-x" in html or "overflow: auto" in html or "overflow:auto" in html
        )
        assert has_session_media or has_overflow_scroll, (
            "Session list must handle narrow viewports: either use a @media "
            "query to reflow as stacked cards, or use overflow-x:auto on a "
            "containing element."
        )


def test_path_keys_render_through(tmp_path: Path) -> None:
    """Separator U+2192 in by_agent keys survives the renderer intact.

    Phase 0 Task 0.1 — empirically settles the separator choice before any
    fixture or downstream test is written against it.

    **Empirical finding (captured at Phase 0 Task 0.1 execution):**

    ``json.dumps`` uses ``ensure_ascii=True`` by default, so U+2192 is
    serialised as the JSON Unicode escape ``\\u2192`` rather than the raw
    UTF-8 byte sequence.  The HTML therefore contains the string literal
    ``"general-purpose\\u2192code-writer"`` (8 ASCII chars, not 1 Unicode
    char) inside the ``const DATA = ...`` block.

    This is *transparent* to the browser: ``JSON.parse`` decodes ``\\u2192``
    back to the ``→`` codepoint, so
    ``DATA.by_agent["general-purpose→code-writer"]`` resolves correctly in JS.
    The separator round-trips correctly; no production code changes are
    required.

    Two independent assertions confirm the round-trip:

    1. **JSON escape form present in raw HTML**: the literal ASCII sequence
       ``\\u2192`` (or the raw UTF-8 ``→``) appears inside the embedded DATA
       block.  The HTML-entity forms ``&#8594;`` and ``&rarr;`` are also
       accepted for completeness, though neither is produced by the current
       renderer.

    2. **JSON round-trip**: parsing the embedded DATA object via
       ``json.JSONDecoder`` yields the original path key as a Python string,
       proving the browser will see the same key.

    This test is a permanent regression gate: if a future change causes the
    separator to be HTML-entity-escaped *inside* the JSON payload (which
    would make ``JSON.parse`` yield ``&rarr;`` rather than ``→``), or
    stripped entirely, this test will fail before any downstream fixture is
    affected.
    """
    # Build a synthetic AggregateResult whose by_agent contains a path-keyed
    # entry.  No parser or aggregator changes are involved — the dict is
    # constructed directly to test only the renderer.
    path_key = f"general-purpose{_ARROW}code-writer"
    result = AggregateResult()
    result.by_agent[path_key] = {
        "total_tokens": 100,
        "primary_model": "opus",
        "session_count": 1,
    }

    output = tmp_path / "dashboard.html"
    render(result, output_path=output, open_browser=False)
    html = output.read_text(encoding="utf-8")

    # --- Assertion 1: separator present in HTML source in a readable form ---
    # json.dumps(ensure_ascii=True) replaces U+2192 with the 6-char ASCII
    # sequence backslash-u-2-1-9-2.  Jinja's autoescape with | safe leaves
    # this JSON content untouched, so the HTML source contains the ASCII
    # escape form verbatim.
    # Accept any of: raw UTF-8 char, JSON Unicode escape, or HTML entities.
    #
    # Derive the JSON-escaped key form programmatically to avoid hardcoding
    # the backslash-u sequence (which is fragile under copy-paste and editor
    # normalisation).  json.dumps strips the surrounding double-quotes.
    json_escaped_key = json.dumps(path_key)[1:-1]  # e.g. general-purpose→code-writer
    raw_in_html = path_key in html
    json_escaped_in_html = json_escaped_key in html
    entity_decimal_in_html = "general-purpose&#8594;code-writer" in html
    entity_named_in_html = "general-purpose&rarr;code-writer" in html

    assert (
        raw_in_html
        or json_escaped_in_html
        or entity_decimal_in_html
        or entity_named_in_html
    ), (
        f"Rendered HTML does not contain the path key in any recognisable "
        f"form. Expected one of: raw U+2192, JSON \\u2192 escape, "
        f"&#8594;, or &rarr;. "
        f"Key was: {path_key!r}, "
        f"JSON-escaped form was: {json_escaped_key!r}"
    )

    # --- Assertion 2: JSON payload round-trip ---
    # Parse the embedded DATA block to confirm the key decodes back to the
    # original Python string (U+2192 codepoint, not a literal backslash-u).
    # The template renders: const DATA = {{ data_json | safe }};
    # json.JSONDecoder.raw_decode handles \uXXXX escapes transparently.
    data_line_marker = "const DATA = "
    data_start = html.index(data_line_marker) + len(data_line_marker)
    decoder = json.JSONDecoder()
    data_obj, _ = decoder.raw_decode(html, data_start)

    assert path_key in data_obj["by_agent"], (
        f"Parsed DATA.by_agent does not contain the path key {path_key!r}. "
        f"json.JSONDecoder did not decode \\u2192 back to U+2192. "
        f"Keys present: {list(data_obj['by_agent'].keys())}"
    )
    assert (
        data_obj["by_agent"][path_key]["total_tokens"] == 100
    ), "Round-tripped by_agent entry must preserve the total_tokens value."


def test_real_data_depth3_renders_correct_by_agent_values(
    nested_session_dir: Path, tmp_path: Path
) -> None:
    """Real depth-3 aggregator output renders correct by_agent values for leaf.

    Plan Task 4.3 regression — ``test_path_keys_render_through`` uses a
    synthetic ``AggregateResult`` built directly.  This test runs the full
    ``parse_sessions(nested_session_dir) → aggregate → render`` pipeline and
    verifies the embedded ``DATA.by_agent`` entry for the depth-3 leaf key
    ``"general-purpose→project-planner→Explore"`` matches the values the
    aggregator actually computed.

    Expected values (derived from the ``nested_session_dir`` fixture in
    ``conftest.py`` and confirmed by
    ``TestAggregateByAgentPath.test_depth_three_uses_full_path_key``):

    - ``total_tokens``:  600  (400 input + 200 output for the Explore agent)
    - ``primary_model``: ``"haiku"``  (``claude-haiku-4-5`` → short name)
    - ``session_count``: 1

    This is a permanent regression gate: if a future change causes real
    aggregator output to be embedded incorrectly in the HTML (e.g. the
    renderer serialises a stale or partial result), this test will fail
    independently of the synthetic-data guard in
    ``test_path_keys_render_through``.
    """
    sessions = parse_sessions(nested_session_dir)
    result = aggregate(sessions)

    output = tmp_path / "dashboard-depth3.html"
    render(result, output_path=output, open_browser=False)
    html = output.read_text(encoding="utf-8")

    # Extract the embedded DATA JSON payload the same way test_path_keys_render_through
    # does — raw_decode handles the → JSON-escape transparently.
    data_line_marker = "const DATA = "
    data_start = html.index(data_line_marker) + len(data_line_marker)
    decoder = json.JSONDecoder()
    data_obj, _ = decoder.raw_decode(html, data_start)

    leaf_key = "general-purpose→project-planner→Explore"

    assert leaf_key in data_obj["by_agent"], (
        f"DATA.by_agent must contain the depth-3 leaf key {leaf_key!r}. "
        f"Keys present: {sorted(data_obj['by_agent'])}"
    )

    entry = data_obj["by_agent"][leaf_key]

    assert entry["total_tokens"] == 600, (
        f"Depth-3 leaf total_tokens must be 600 (400 input + 200 output). "
        f"Got: {entry['total_tokens']!r}"
    )
    assert entry["primary_model"] == "haiku", (
        f"Depth-3 leaf primary_model must be 'haiku' (claude-haiku-4-5). "
        f"Got: {entry['primary_model']!r}"
    )
    assert entry["session_count"] == 1, (
        f"Depth-3 leaf session_count must be 1. " f"Got: {entry['session_count']!r}"
    )
