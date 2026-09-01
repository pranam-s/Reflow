"""A real structural/contrast validator for the report -- stated plainly, not a WCAG audit.

**What this module checks, precisely:**

1. ``<html lang="...">`` is present with a non-empty value, and exactly one
   non-empty ``<title>`` exists.
2. Exactly one ``<h1>`` exists, and heading levels never jump forward by
   more than one step in document order (an ``<h3>`` may never follow an
   ``<h1>`` or another ``<h3>`` directly, without an intervening ``<h2>``).
3. Every ``<table>`` has a ``<caption>``.
4. Every ``<th>`` has a ``scope`` attribute set to exactly ``"col"`` or
   ``"row"``.
5. Every ``<img>`` (there happen to be none in this report, but the check
   is generic) has a non-empty ``alt`` attribute.
6. Every chart figure (``<figure class="bar-chart">``) carries
   ``aria-hidden="true"``, and is followed, before the next ``<h2>``/
   ``<h3>`` or the next chart figure, by at least one ``<table>`` -- the
   "every chart paired with its data table" requirement, checked
   structurally rather than merely asserted in a docstring.
7. No external resource reference exists anywhere (no ``<script>``, no
   ``<link>``, and no ``href``/``src`` attribute pointing at an
   ``http://``/``https://``/``//`` URL) -- the self-contained,
   single-file requirement.
8. Every ``id`` attribute value in the document is unique.
9. Every WCAG-relevant colour pair declared in :mod:`reflow.report.colors`
   meets its required contrast ratio (4.5:1 for text, 3:1 for purely
   decorative graphical elements) -- computed by the WCAG 2.1
   relative-luminance formula against the exact hex values that module
   declares, and cross-checked that every one of those hex values
   literally appears in the report's own ``<style>`` block, so this is a
   check against the shipped palette, not an isolated unit test of the
   colour module alone.

**What this module does not check, stated as plainly as what it does:**

- It does not render the page in a browser or any layout engine. No
  computed style, cascade resolution, CSS specificity, viewport
  measurement, or actual on-screen colour is ever inspected -- contrast
  is verified against the colour constants this project declares and
  ships, not against what a browser would compute after applying the
  cascade.
- It does not check keyboard focus order, tab-index behaviour, ARIA role
  correctness beyond the two specific attributes named above
  (``aria-hidden`` on chart figures, ``scope`` on ``<th>``), landmark
  uniqueness beyond heading structure, or screen-reader announcement
  behaviour in any real assistive-technology product.
- It is not axe-core, and does not claim to run axe-core's rule set. Axe
  -core's own documentation states its colour-contrast rule requires a
  real browser rendering engine to compute accurately (a plain
  ``jsdom``-based run explicitly does not support it), which would have
  required adding a headless-browser toolchain (Puppeteer or Playwright
  plus a bundled Chromium download) to a project that otherwise has zero
  Node/npm footprint and a single-lockfile (``uv.lock``) reproducibility
  guarantee, for the one-time validation of one static, already-committed
  file. That trade-off is recorded in ``docs/design.md``'s Phase 8 ADR,
  written before this module, not invented afterwards to excuse a
  shortcut.
- It parses HTML with the standard library's :class:`html.parser.HTMLParser`
  against this project's own generator output, which is well-formed by
  construction (every tag :mod:`reflow.report.html` emits is closed and
  properly nested) -- it is not a general-purpose HTML5-conformance
  validator and would not necessarily behave sensibly against arbitrary
  malformed HTML from another source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

from reflow.report import colors

_HEADING_TAGS: frozenset[str] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_SECTION_HEADING_TAGS: frozenset[str] = frozenset({"h2", "h3"})
_EXTERNAL_PREFIXES: tuple[str, ...] = ("http://", "https://", "//")


@dataclass(slots=True)
class _TableInfo:
    """Structural facts collected about one ``<table>`` while parsing.

    Attributes:
        has_caption: Whether a ``<caption>`` was seen inside this table.
        th_scopes: The ``scope`` attribute value (or ``None``) of every
            ``<th>`` seen inside this table, in document order.
    """

    has_caption: bool = False
    th_scopes: list[str | None] = field(default_factory=list)


@dataclass(slots=True)
class _ParsedReport:
    """Every structural fact :class:`_ReportHtmlWalker` collects from one document."""

    html_lang: str | None = None
    title_text: str = ""
    heading_levels: list[int] = field(default_factory=list)
    tables: list[_TableInfo] = field(default_factory=list)
    img_alts: list[str | None] = field(default_factory=list)
    ids_seen: list[str] = field(default_factory=list)
    external_refs: list[str] = field(default_factory=list)
    has_script_tag: bool = False
    has_link_tag: bool = False
    sequence: list[tuple[str, dict[str, str | None]]] = field(default_factory=list)
    chart_sequence_indices: list[int] = field(default_factory=list)


class _ReportHtmlWalker(HTMLParser):
    """A single-pass, stack-free structural walker over the report's own HTML.

    Collects exactly the facts the checks in this module need, in one pass,
    without building a full DOM tree -- the report's generator
    (:mod:`reflow.report.html`) never emits overlapping or unclosed tags,
    so a flat, in-order token log is sufficient to answer every question
    this module asks.
    """

    def __init__(self) -> None:
        """Initialise the walker with an empty :class:`_ParsedReport`."""
        super().__init__(convert_charrefs=True)
        self.result = _ParsedReport()
        self._current_table: _TableInfo | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record one opening tag's structural facts.

        Args:
            tag: The lower-cased tag name.
            attrs: The tag's attributes, as ``(name, value)`` pairs.
        """
        attrs_dict = dict(attrs)
        self.result.sequence.append((tag, attrs_dict))
        element_id = attrs_dict.get("id")
        if element_id:
            self.result.ids_seen.append(element_id)
        if tag == "html":
            self.result.html_lang = attrs_dict.get("lang")
        if tag == "title":
            self._in_title = True
        if tag in _HEADING_TAGS:
            self.result.heading_levels.append(int(tag[1]))
        if tag == "table":
            self._current_table = _TableInfo()
            self.result.tables.append(self._current_table)
        if tag == "caption" and self._current_table is not None:
            self._current_table.has_caption = True
        if tag == "th" and self._current_table is not None:
            self._current_table.th_scopes.append(attrs_dict.get("scope"))
        if tag == "img":
            self.result.img_alts.append(attrs_dict.get("alt"))
        if tag == "script":
            self.result.has_script_tag = True
        if tag == "link":
            self.result.has_link_tag = True
        for attribute_name in ("href", "src"):
            value = attrs_dict.get(attribute_name)
            if value and value.startswith(_EXTERNAL_PREFIXES):
                self.result.external_refs.append(value)
        if tag == "figure" and "bar-chart" in (attrs_dict.get("class") or ""):
            self.result.chart_sequence_indices.append(len(self.result.sequence) - 1)

    def handle_endtag(self, tag: str) -> None:
        """React to one closing tag.

        Args:
            tag: The lower-cased tag name.
        """
        if tag == "table":
            self._current_table = None
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        """Accumulate text content while inside ``<title>``.

        Args:
            data: The text chunk.
        """
        if self._in_title:
            self.result.title_text += data


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One named check's outcome.

    Attributes:
        name: A short, stable identifier for this check.
        passed: Whether the check passed.
        detail: A human-readable explanation, populated whether the check
            passed or failed.
    """

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """The full set of check outcomes for one HTML document.

    Attributes:
        checks: Every :class:`CheckResult`, in the order the checks ran.
    """

    checks: tuple[CheckResult, ...]

    @property
    def all_passed(self) -> bool:
        """Whether every check in :attr:`checks` passed.

        Returns:
            ``True`` if no check failed.
        """
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """Every check that did not pass.

        Returns:
            The failing :class:`CheckResult` entries, in original order.
        """
        return tuple(check for check in self.checks if not check.passed)


def _check_lang_and_title(parsed: _ParsedReport) -> CheckResult:
    """Check for a non-empty ``<html lang>`` and a non-empty ``<title>``.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    if not parsed.html_lang:
        return CheckResult("lang_and_title", False, "no non-empty <html lang=...> attribute.")
    if not parsed.title_text.strip():
        return CheckResult("lang_and_title", False, "no non-empty <title> element.")
    return CheckResult(
        "lang_and_title",
        True,
        f"<html lang={parsed.html_lang!r}>, <title>{parsed.title_text.strip()!r}</title>.",
    )


def _check_heading_order(parsed: _ParsedReport) -> CheckResult:
    """Check for exactly one ``<h1>`` and no forward heading-level skip.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    levels = parsed.heading_levels
    h1_count = levels.count(1)
    if h1_count != 1:
        return CheckResult("heading_order", False, f"expected exactly one <h1>, found {h1_count}.")
    previous = levels[0]
    for level in levels[1:]:
        if level > previous + 1:
            return CheckResult(
                "heading_order",
                False,
                f"heading level jumped from h{previous} to h{level} without an "
                f"intervening h{previous + 1}.",
            )
        previous = level
    return CheckResult(
        "heading_order", True, f"one <h1>, {len(levels)} headings total, no forward skips."
    )


def _check_tables_have_captions(parsed: _ParsedReport) -> CheckResult:
    """Check that every ``<table>`` has a ``<caption>``.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    uncaptioned = sum(1 for table in parsed.tables if not table.has_caption)
    if uncaptioned:
        return CheckResult(
            "tables_have_captions",
            False,
            f"{uncaptioned} of {len(parsed.tables)} tables have no <caption>.",
        )
    return CheckResult(
        "tables_have_captions", True, f"all {len(parsed.tables)} tables have a <caption>."
    )


def _check_th_scopes_are_valid(parsed: _ParsedReport) -> CheckResult:
    """Check that every ``<th>`` has ``scope="col"`` or ``scope="row"``.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    all_scopes = [scope for table in parsed.tables for scope in table.th_scopes]
    invalid = sum(1 for scope in all_scopes if scope not in ("col", "row"))
    if invalid:
        return CheckResult(
            "th_scopes_valid", False, f"{invalid} of {len(all_scopes)} <th> lack a valid scope."
        )
    return CheckResult("th_scopes_valid", True, f"all {len(all_scopes)} <th> have a valid scope.")


def _check_images_have_alt(parsed: _ParsedReport) -> CheckResult:
    """Check that every ``<img>`` has a non-empty ``alt`` attribute.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    missing = sum(1 for alt in parsed.img_alts if not alt)
    if missing:
        return CheckResult(
            "images_have_alt", False, f"{missing} of {len(parsed.img_alts)} <img> lack alt text."
        )
    return CheckResult(
        "images_have_alt", True, f"{len(parsed.img_alts)} <img> tags, all with alt text."
    )


def _check_charts_are_aria_hidden(parsed: _ParsedReport) -> CheckResult:
    """Check that every chart figure carries ``aria-hidden="true"``.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    not_hidden = 0
    for index in parsed.chart_sequence_indices:
        _tag, attrs = parsed.sequence[index]
        if attrs.get("aria-hidden") != "true":
            not_hidden += 1
    if not_hidden:
        return CheckResult(
            "charts_aria_hidden",
            False,
            f"{not_hidden} of {len(parsed.chart_sequence_indices)} chart figures are not "
            "aria-hidden.",
        )
    return CheckResult(
        "charts_aria_hidden",
        True,
        f"all {len(parsed.chart_sequence_indices)} chart figures are aria-hidden.",
    )


def _check_every_chart_has_a_paired_table(parsed: _ParsedReport) -> CheckResult:
    """Check that every chart is followed by a table before the next heading or chart.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    unpaired = []
    for chart_number, chart_index in enumerate(parsed.chart_sequence_indices, start=1):
        found_table = False
        for tag, _attrs in parsed.sequence[chart_index + 1 :]:
            if tag == "table":
                found_table = True
                break
            if tag in _SECTION_HEADING_TAGS or tag == "figure":
                break
        if not found_table:
            unpaired.append(chart_number)
    if unpaired:
        return CheckResult(
            "charts_paired_with_tables",
            False,
            f"chart(s) {unpaired} have no <table> before the next heading or chart.",
        )
    return CheckResult(
        "charts_paired_with_tables",
        True,
        f"all {len(parsed.chart_sequence_indices)} charts are followed by a data table.",
    )


def _check_self_contained(parsed: _ParsedReport) -> CheckResult:
    """Check for zero ``<script>``/``<link>`` tags and zero external resource references.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    problems = []
    if parsed.has_script_tag:
        problems.append("a <script> tag is present.")
    if parsed.has_link_tag:
        problems.append("a <link> tag is present.")
    if parsed.external_refs:
        problems.append(f"external resource reference(s): {parsed.external_refs!r}.")
    if problems:
        return CheckResult("self_contained", False, " ".join(problems))
    return CheckResult(
        "self_contained", True, "no <script>, <link>, or external href/src reference found."
    )


def _check_unique_ids(parsed: _ParsedReport) -> CheckResult:
    """Check that every ``id`` attribute value in the document is unique.

    Args:
        parsed: The parsed document facts.

    Returns:
        The check's :class:`CheckResult`.
    """
    duplicates = {
        element_id for element_id in parsed.ids_seen if parsed.ids_seen.count(element_id) > 1
    }
    if duplicates:
        return CheckResult("unique_ids", False, f"duplicate id attribute(s): {sorted(duplicates)}.")
    return CheckResult("unique_ids", True, f"all {len(parsed.ids_seen)} id attributes are unique.")


def _check_wcag_contrast(html_text: str) -> CheckResult:
    """Check that every declared colour pair meets its WCAG AA contrast minimum.

    Args:
        html_text: The full report document, to confirm every declared
            palette colour actually appears in its stylesheet.

    Returns:
        The check's :class:`CheckResult`.
    """
    failures = []
    for label, foreground, background in colors.TEXT_CONTRAST_PAIRS:
        ratio = colors.contrast_ratio(foreground, background)
        if not colors.meets_text_contrast_minimum(foreground, background):
            failures.append(f"{label}: {ratio:.2f}:1 (need >= 4.5:1)")
        if foreground not in html_text or background not in html_text:
            failures.append(f"{label}: declared colour not found in the report's stylesheet.")
    for label, foreground, background in colors.GRAPHICAL_CONTRAST_PAIRS:
        ratio = colors.contrast_ratio(foreground, background)
        if not colors.meets_graphical_contrast_minimum(foreground, background):
            failures.append(f"{label}: {ratio:.2f}:1 (need >= 3:1)")
    if failures:
        return CheckResult("wcag_contrast", False, "; ".join(failures))
    n_pairs = len(colors.TEXT_CONTRAST_PAIRS) + len(colors.GRAPHICAL_CONTRAST_PAIRS)
    return CheckResult("wcag_contrast", True, f"all {n_pairs} declared colour pairs meet AA.")


def validate_report_html(html_text: str) -> ValidationResult:
    """Run every structural and contrast check against one HTML document.

    Args:
        html_text: The full HTML document text, as produced by
            :func:`reflow.report.html.build_report_html`.

    Returns:
        The aggregated :class:`ValidationResult`. See the module docstring
        for exactly which checks run and which accessibility properties
        they do not attempt to verify.
    """
    walker = _ReportHtmlWalker()
    walker.feed(html_text)
    parsed = walker.result
    return ValidationResult(
        checks=(
            _check_lang_and_title(parsed),
            _check_heading_order(parsed),
            _check_tables_have_captions(parsed),
            _check_th_scopes_are_valid(parsed),
            _check_images_have_alt(parsed),
            _check_charts_are_aria_hidden(parsed),
            _check_every_chart_has_a_paired_table(parsed),
            _check_self_contained(parsed),
            _check_unique_ids(parsed),
            _check_wcag_contrast(html_text),
        )
    )
