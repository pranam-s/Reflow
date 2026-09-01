"""Building the self-contained, accessible HTML pipeline report.

**Accessible by construction, not decoration.** Every requirement this
module satisfies is structural, not cosmetic, because neither of this
project's two reviewers can eyeball a rendered page: the submitter is a
screen-reader user, and his reviewing agent has no browser at all.

- Semantic HTML5 landmarks (``<header>``, ``<nav>``, ``<main>``,
  ``<section>``, ``<footer>``), a single ``<h1>``, and heading levels that
  never skip (``<h2>`` per section, ``<h3>`` for a subsection, never an
  ``<h3>`` with no enclosing ``<h2>``).
- Every ``<table>`` has a ``<caption>`` and every header cell an explicit
  ``scope="col"`` or ``scope="row"`` -- never a bare ``<th>`` a screen
  reader has to guess the orientation of.
- **Every chart is a ``<figure aria-hidden="true">`` immediately followed
  by a real, captioned ``<table>`` carrying the exact same numbers.** The
  figure is purely decorative CSS bars (no ``<img>``, no ``<canvas>``, no
  JavaScript): marking it ``aria-hidden`` means assistive technology skips
  it entirely and reads only the table, so no information ever exists
  *only* as a picture -- the literal requirement, not an approximation of
  it.
- No colour is ever the sole carrier of meaning. Every verdict this report
  states in colour (e.g. "WORSE than baseline", "BLOCKED") is spelled out
  in plain text in the same cell; colour is decoration layered on top of
  wording that already states the fact on its own.
- WCAG AA contrast: every colour pair used for text is declared once in
  :mod:`reflow.report.colors` and re-verified by
  :mod:`reflow.report.validate` via the WCAG 2.1 contrast formula against
  the exact hex values this module emits -- not a rendering-dependent
  guess.
- Self-contained: one file, inline ``<style>``, no external stylesheet,
  font, script, or CDN reference of any kind. Opens correctly from a local
  filesystem path with no network access.
"""

from __future__ import annotations

import html as html_stdlib

from reflow.demo.data import (
    ClusterMetrics,
    CorpusData,
    IncidentData,
    LimitationsData,
    ResultsData,
    RootCauseData,
    RoutingData,
)
from reflow.report import colors
from reflow.report.data import ActionDistribution, GuardrailFireRow, PolicyOutcomeRow, ReportData


def _esc(value: object) -> str:
    """Escape a value for safe inclusion in HTML text content or an attribute.

    Args:
        value: Any value; converted to ``str`` before escaping.

    Returns:
        The HTML-escaped string.
    """
    return html_stdlib.escape(str(value), quote=True)


def _bar_chart_figure(*, rows: list[tuple[str, float]], value_format: str, aria_label: str) -> str:
    """Build a purely decorative, ``aria-hidden`` horizontal-bar-chart figure.

    Args:
        rows: ``(label, value)`` pairs, in display order. Every value must
            be non-negative.
        value_format: A format spec (e.g. ``".3f"``, ``",.0f"``) applied to
            each value for the text printed beside its bar.
        aria_label: A human-readable description, set as the figure's
            ``aria-label`` even though the figure is hidden from assistive
            technology, so a sighted user inspecting the markup (or a
            future maintainer) still knows what it depicts.

    Returns:
        The figure's HTML markup. Carries no information not also present
        in the data table this project always renders immediately after
        calling this function -- see the module docstring.
    """
    max_value = max((value for _label, value in rows), default=0.0)
    bar_rows = []
    for label, value in rows:
        width_percent = 0.0 if max_value <= 0 else (value / max_value) * 100.0
        formatted_value = format(value, value_format)
        bar_rows.append(
            "<div class='bar-row'>"
            f"<span class='bar-label'>{_esc(label)}</span>"
            "<span class='bar-track'>"
            f"<span class='bar-fill' style='width:{width_percent:.2f}%'></span>"
            "</span>"
            f"<span class='bar-value'>{_esc(formatted_value)}</span>"
            "</div>"
        )
    body = "".join(bar_rows)
    label_attr = _esc(aria_label)
    return f"<figure class='bar-chart' aria-hidden='true' aria-label='{label_attr}'>{body}</figure>"


def _table(*, table_id: str, caption: str, column_headers: list[str], rows: list[list[str]]) -> str:
    """Build a fully captioned, header-scoped ``<table>``.

    Args:
        table_id: The table's ``id`` attribute, for in-page anchoring.
        caption: The table's ``<caption>`` text.
        column_headers: Column header labels, rendered with
            ``scope="col"``.
        rows: Table body rows; each row's first cell is rendered as a row
            header with ``scope="row"``, the rest as plain data cells.

    Returns:
        The table's HTML markup.
    """
    header_cells = "".join(f"<th scope='col'>{_esc(header)}</th>" for header in column_headers)
    body_rows = []
    for row in rows:
        first_cell = f"<th scope='row'>{row[0]}</th>"
        rest_cells = "".join(f"<td>{cell}</td>" for cell in row[1:])
        body_rows.append(f"<tr>{first_cell}{rest_cells}</tr>")
    body = "".join(body_rows)
    return (
        f"<table id='{_esc(table_id)}'>"
        f"<caption>{_esc(caption)}</caption>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
    )


def _chart_with_table(
    *,
    chart_rows: list[tuple[str, float]],
    value_format: str,
    aria_label: str,
    table_id: str,
    caption: str,
    column_headers: list[str],
    table_rows: list[list[str]],
    figcaption: str,
) -> str:
    """Build one chart, always immediately followed by its full data table.

    Args:
        chart_rows: The bar chart's ``(label, value)`` pairs.
        value_format: Format spec for the chart's own value labels.
        aria_label: The chart figure's ``aria-label``.
        table_id: The paired table's ``id``.
        caption: The paired table's ``<caption>`` text.
        column_headers: The paired table's column headers.
        table_rows: The paired table's body rows.
        figcaption: Visible caption printed under the chart, naming the
            table that carries its data.

    Returns:
        The combined chart-plus-table HTML markup.
    """
    figure = _bar_chart_figure(rows=chart_rows, value_format=value_format, aria_label=aria_label)
    caption_html = f"<p class='figcaption'>{_esc(figcaption)}</p>"
    table = _table(
        table_id=table_id, caption=caption, column_headers=column_headers, rows=table_rows
    )
    return f"{figure}{caption_html}{table}"


def _style_block() -> str:
    """Build the report's single inline ``<style>`` block.

    Returns:
        The ``<style>...</style>`` markup, using only the colours declared
        in :mod:`reflow.report.colors`.
    """
    return f"""<style>
  html {{ font-family: Georgia, "Times New Roman", serif; }}
  body {{
    background: {colors.COLOR_BACKGROUND}; color: {colors.COLOR_TEXT};
    margin: 0 auto; max-width: 62rem; padding: 1.5rem;
    line-height: 1.5; font-size: 16px;
  }}
  h1, h2, h3 {{ color: {colors.COLOR_HEADING}; line-height: 1.3; }}
  a {{ color: {colors.COLOR_LINK}; text-decoration: underline; }}
  header, footer {{ border-top: 1px solid {colors.COLOR_BORDER}; }}
  header {{ border-top: none; }}
  footer {{
    background: {colors.COLOR_FOOTER_BG}; color: {colors.COLOR_FOOTER_TEXT};
    padding: 1rem; margin-top: 2rem;
  }}
  nav ul {{ padding-left: 1.2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem 0; }}
  caption {{
    caption-side: top; text-align: left; font-weight: bold;
    color: {colors.COLOR_MUTED}; padding-bottom: 0.4rem;
  }}
  th, td {{ border: 1px solid {colors.COLOR_BORDER}; padding: 0.35rem 0.6rem; text-align: left; }}
  thead th {{
    background: {colors.COLOR_TABLE_HEADER_BG}; color: {colors.COLOR_TABLE_HEADER_TEXT};
  }}
  .figcaption {{ color: {colors.COLOR_MUTED}; font-style: italic; margin: 0.25rem 0 0.75rem 0; }}
  .bar-chart {{ margin: 0.5rem 0 0 0; }}
  .bar-row {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem; }}
  .bar-label {{ width: 14rem; flex-shrink: 0; }}
  .bar-track {{
    background: {colors.COLOR_BAR_TRACK}; flex-grow: 1; height: 1rem;
    border: 1px solid {colors.COLOR_BORDER};
  }}
  .bar-fill {{ background: {colors.COLOR_BAR_FILL}; height: 100%; display: block; }}
  .bar-value {{ width: 7rem; text-align: right; flex-shrink: 0; }}
  .verdict-danger {{ color: {colors.COLOR_DANGER}; font-weight: bold; }}
  .verdict-success {{ color: {colors.COLOR_SUCCESS}; font-weight: bold; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 0.2rem 1rem; }}
  dt {{ font-weight: bold; }}
</style>"""


def _provenance_section(data: ReportData) -> str:
    """Build the provenance ``<section>``: command, seed, date, versions.

    Args:
        data: The loaded :class:`~reflow.report.data.ReportData`.

    Returns:
        The section's HTML markup.
    """
    return f"""<section id="provenance">
  <h2>Provenance</h2>
  <dl>
    <dt>Regenerate with</dt><dd><code>{_esc(data.regenerate_command)}</code></dd>
    <dt>Corpus seed</dt><dd>{_esc(data.demo.seed)}</dd>
    <dt>Generated on</dt><dd>{_esc(data.generated_on)}</dd>
    <dt>reflow version</dt><dd>{_esc(data.reflow_version)}</dd>
    <dt>Requires Python</dt><dd>{_esc(data.python_requires)}</dd>
    <dt>pydantic version</dt><dd>{_esc(data.pydantic_version)}</dd>
    <dt>rich version</dt><dd>{_esc(data.rich_version)}</dd>
  </dl>
  <p>Every number below is read from committed Phase 2, 3, 4, 5, 6, and 7 report
  artefacts in <code>docs/reports/</code>. No network call, credential, or LLM call was
  made to produce this report.</p>
</section>"""


def _corpus_section(corpus: CorpusData) -> str:
    """Build the corpus/taxonomy ``<section>``.

    Args:
        corpus: The loaded :class:`~reflow.demo.data.CorpusData`.

    Returns:
        The section's HTML markup.
    """
    table = _table(
        table_id="corpus-facts",
        caption="Table 1. The corpus and the taxonomy it is grounded in.",
        column_headers=["Fact", "Value"],
        rows=[
            ["Failed payment events", f"{corpus.n_events:,}"],
            [
                "Grounded in",
                f"Razorpay's own {corpus.taxonomy_row_count}-row published error-reasons taxonomy",
            ],
            ["Distinct reason codes observed", str(corpus.distinct_reasons_seen)],
        ],
    )
    return f"""<section id="corpus">
  <h2>1. The corpus</h2>
  <p>Every event carries the same four fields Razorpay's own webhook reports: error
  code, source, step, and reason.</p>
  {table}
</section>"""


def _root_cause_section(root_cause: RootCauseData) -> str:
    """Build the root-cause bake-off ``<section>``.

    Args:
        root_cause: The loaded :class:`~reflow.demo.data.RootCauseData`.

    Returns:
        The section's HTML markup.
    """

    def _verdict(candidate_ari: float, groupby_ari: float) -> str:
        if candidate_ari < groupby_ari - 0.005:
            return "<span class='verdict-danger'>WORSE than baseline</span>"
        return "<span class='verdict-success'>TIES baseline (noise, not signal)</span>"

    groupby = root_cause.catchall_groupby
    candidates: list[tuple[str, ClusterMetrics]] = [
        ("GROUP BY (baseline)", groupby),
        ("Drain3", root_cause.catchall_drain3),
        ("Template hashing", root_cause.catchall_template_hash),
        ("TF-IDF + HDBSCAN", root_cause.catchall_tfidf_hdbscan),
    ]
    table_rows = [
        [
            _esc(name),
            f"{metrics.purity:.3f}",
            f"{metrics.nmi:.3f}",
            f"{metrics.ari:.3f}",
            "--" if name == "GROUP BY (baseline)" else _verdict(metrics.ari, groupby.ari),
        ]
        for name, metrics in candidates
    ]
    chart_table = _chart_with_table(
        chart_rows=[(name, metrics.ari) for name, metrics in candidates],
        value_format=".3f",
        aria_label="Adjusted Rand Index on the catch-all stratum, by candidate",
        table_id="catchall-bakeoff",
        caption=(
            "Table 2. Catch-all-stratum clustering bake-off (opaque arm, richness 1). "
            "Higher is better; GROUP BY is the production baseline."
        ),
        column_headers=["Candidate", "Purity", "NMI", "ARI", "Verdict vs. GROUP BY"],
        table_rows=table_rows,
        figcaption="Figure 1. Adjusted Rand Index (ARI) per candidate. Data in Table 2 below.",
    )
    return f"""<section id="root-cause">
  <h2>2. Root cause: GROUP BY, not clustering</h2>
  <p>GROUP BY (code, source, step, reason) is the production root-cause path. On the
  narrow stratum ({root_cause.narrow_n_true_clusters} true reasons,
  {root_cause.narrow_n_predicted_clusters} groups produced), it already scores purity
  {root_cause.narrow_purity:.3f}, NMI {root_cause.narrow_nmi:.3f}, ARI
  {root_cause.narrow_ari:.3f}.</p>
  <p>Three real clusterers were benchmarked against it on the hard part: the catch-all
  reasons where free text is the only clue, under the realistic condition that Razorpay's
  own documentation says it does not receive the sub-cause (ADR-0002,
  <code>docs/design.md</code>).</p>
  {chart_table}
  <p>Verdict: no clustering candidate is adopted for production catch-all root-causing.</p>
</section>"""


def _incident_section(incident: IncidentData) -> str:
    """Build the incident-detection ``<section>``.

    Args:
        incident: The loaded :class:`~reflow.demo.data.IncidentData`.

    Returns:
        The section's HTML markup.
    """
    table = _table(
        table_id="incident-detection-metrics",
        caption="Table 3. poisson_surprise incident-detector benchmark.",
        column_headers=["Split", "Precision", "Recall", "F1"],
        rows=[
            [
                "train",
                f"{incident.poisson_train_precision:.3f}",
                f"{incident.poisson_train_recall:.3f}",
                f"{incident.poisson_train_f1:.3f}",
            ],
            [
                "test",
                f"{incident.poisson_test_precision:.3f}",
                f"{incident.poisson_test_recall:.3f}",
                f"{incident.poisson_test_f1:.3f}",
            ],
        ],
    )
    return f"""<section id="incident-detection">
  <h2>3. Incident detection: Poisson surprise over (method, bank)</h2>
  <p>A bank outage spans 3-4 reason codes at once by construction. poisson_surprise
  correlates failure counts over (method, bank) and 15-minute buckets to find it.</p>
  {table}
  <p>A naive GROUP BY reason view, run at the same detector's own algorithm, fragments
  one true incident into {incident.groupby_reason_fragments_train_mean:.1f} to
  {incident.groupby_reason_fragments_test_mean:.1f} separate alerts on average
  (ADR-0003).</p>
</section>"""


def _routing_section(routing: RoutingData) -> str:
    """Build the Tier 1/Tier 2 routing-split ``<section>``.

    Args:
        routing: The loaded :class:`~reflow.demo.data.RoutingData`.

    Returns:
        The section's HTML markup.
    """
    chart_table = _chart_with_table(
        chart_rows=[
            ("Tier 1: deterministic", float(routing.deterministic_events)),
            (f"Tier 2: {routing.n_escalated_reasons} escalated reasons", float(routing.llm_events)),
        ],
        value_format=",.0f",
        aria_label="Events resolved by tier",
        table_id="routing-split",
        caption="Table 4. Deterministic-vs-LLM routing split.",
        column_headers=["Tier", "Events", "Share", "Live LLM calls"],
        table_rows=[
            [
                "Tier 1: deterministic lookup",
                f"{routing.deterministic_events:,}",
                f"{routing.deterministic_fraction * 100:.3f}%",
                "0",
            ],
            [
                f"Tier 2: {routing.n_escalated_reasons} escalated reason codes",
                f"{routing.llm_events:,}",
                f"{(routing.llm_events / routing.total_events) * 100:.3f}%",
                f"{routing.ambiguous_reason_calls} (cached per reason code, ever)",
            ],
        ],
        figcaption="Figure 2. Events resolved per tier. Data in Table 4 below.",
    )
    return f"""<section id="routing">
  <h2>4. The routing split</h2>
  {chart_table}
  <p>{routing.deterministic_fraction * 100:.3f}% of {routing.total_events:,} events need
  no model at all. Every detected incident gets one uncached call
  ({routing.incident_diagnosis_calls} of them here). Total:
  {routing.total_llm_calls} live LLM calls to diagnose {routing.total_events:,}
  events.</p>
</section>"""


def _guardrail_section(data: ReportData) -> str:
    """Build the guardrail beat and the guardrail-fire-count/action-distribution ``<section>``.

    Args:
        data: The loaded :class:`~reflow.report.data.ReportData`.

    Returns:
        The section's HTML markup.
    """
    record = data.demo.guardrail_records[0]
    guardrail_table_rows = []
    for evaluation in record.guardrail_evaluations:
        verdict_class = "verdict-danger" if evaluation["blocked"] else "verdict-success"
        verdict_word = "BLOCKED" if evaluation["blocked"] else "PASSED"
        guardrail_table_rows.append(
            [
                _esc(evaluation["name"]),
                f"<span class='{verdict_class}'>{verdict_word}</span>",
                f"{_esc(evaluation['action_before'])} -&gt; {_esc(evaluation['action_after'])}",
                _esc(evaluation["reason"]),
            ]
        )
    guardrail_chain_table = _table(
        table_id="guardrail-chain",
        caption=f"Table 5. Full guardrail chain for payment {record.payment_id}.",
        column_headers=["Guardrail", "Verdict", "Action before -> after", "Reason"],
        rows=guardrail_table_rows,
    )
    fire_rows: list[GuardrailFireRow] = list(data.guardrail_fires)
    fire_chart_table = _chart_with_table(
        chart_rows=[(row.name, float(row.fired)) for row in fire_rows],
        value_format=",.0f",
        aria_label="Guardrail fire counts across the full corpus",
        table_id="guardrail-fires",
        caption="Table 6. Per-guardrail fire/pass counts across all 50,000 events.",
        column_headers=["Guardrail", "Fired", "Passed"],
        table_rows=[[_esc(row.name), f"{row.fired:,}", f"{row.passed:,}"] for row in fire_rows],
        figcaption="Figure 3. Guardrail fire counts. Data in Table 6 below.",
    )
    distribution: ActionDistribution = data.action_distribution
    action_table = _table(
        table_id="action-distribution",
        caption=(
            "Table 7. Action distribution before (candidate) and after (final) the guardrail chain."
        ),
        column_headers=["Action", "Candidate count", "Final count"],
        rows=[
            [
                _esc(action),
                f"{distribution.candidate_counts.get(action, 0):,}",
                f"{distribution.final_counts.get(action, 0):,}",
            ]
            for action in sorted(distribution.final_counts)
        ],
    )
    return f"""<section id="guardrails">
  <h2>5. The guardrail refusing to act</h2>
  <p>Payment {_esc(record.payment_id)}: {_esc(record.method)} via {_esc(record.bank or "n/a")},
  reason {_esc(record.error_reason)}. Tier 1 resolves this deterministically to
  remediation class {_esc(record.remediation_class)}, base action
  {_esc(record.base_action)}. poisson_surprise had already flagged an active incident on
  this (method, bank) pair. ActiveIncidentGuardrail intervenes: the final action is
  {_esc(record.final_action)} -- reflow deliberately waits for bank-side recovery rather
  than chasing a customer whose bank is down.</p>
  <h3>Full decision chain for this payment</h3>
  {guardrail_chain_table}
  <h3>Guardrail fire counts across the full corpus</h3>
  {fire_chart_table}
  <h3>Action distribution</h3>
  {action_table}
  <p>The full guardrail chain sent {data.over_contact_reduction:,} fewer contacts
  ({data.over_contact_reduction_rate * 100:.2f}%) than the escalation ladder's own
  candidate action would have, with zero guardrails applied.</p>
</section>"""


def _results_section(results: ResultsData, policy_outcomes: tuple[PolicyOutcomeRow, ...]) -> str:
    """Build the results-vs-baselines ``<section>``.

    Args:
        results: The loaded :class:`~reflow.demo.data.ResultsData` (central
            sensitivity band).
        policy_outcomes: The full 12-row sensitivity-band outcome table.

    Returns:
        The section's HTML markup.
    """
    central_rows = [row for row in policy_outcomes if row.sensitivity_level == "central"]
    chart_table = _chart_with_table(
        chart_rows=[(row.policy, row.money_recovered_rupees) for row in central_rows],
        value_format=",.0f",
        aria_label="Money recovered by policy, central sensitivity estimate",
        table_id="central-results",
        caption="Table 8. Money recovered and contacts sent by policy (central estimate).",
        column_headers=["Policy", "Money recovered (INR)", "Contacts sent"],
        table_rows=[
            [_esc(row.policy), f"{row.money_recovered_rupees:,.0f}", f"{row.contacts_sent:,}"]
            for row in central_rows
        ],
        figcaption="Figure 4. Money recovered by policy (central estimate). Data in Table 8.",
    )
    full_band_table = _table(
        table_id="full-band-results",
        caption="Table 9. Full three-point sensitivity band (pessimistic/central/optimistic).",
        column_headers=["Policy", "Sensitivity level", "Money recovered (INR)", "Contacts sent"],
        rows=[
            [
                _esc(row.policy),
                _esc(row.sensitivity_level),
                f"{row.money_recovered_rupees:,.0f}",
                f"{row.contacts_sent:,}",
            ]
            for row in policy_outcomes
        ],
    )
    money_fraction = results.reflow_as_fraction_of_notify_all_money
    contact_fraction = results.reflow_contacts_as_fraction_of_notify_all
    do_nothing_multiple = results.reflow_money_rupees / results.do_nothing_money_rupees
    return f"""<section id="results">
  <h2>6. Results: reflow vs. three baselines</h2>
  {chart_table}
  <p>Said plainly: reflow recovers <strong>less</strong> absolute money than blanket
  spam (notify_all). It recovers {money_fraction * 100:.0f}% of notify_all's money at
  {contact_fraction * 100:.0f}% of notify_all's contact volume, and beats do_nothing by
  roughly {do_nothing_multiple:.1f}x. This is reported as the finding, not reframed
  (ADR-0007).</p>
  {full_band_table}
</section>"""


def _limitations_section(limitations: LimitationsData) -> str:
    """Build the honest-limitations ``<section>``.

    Args:
        limitations: The loaded :class:`~reflow.demo.data.LimitationsData`.

    Returns:
        The section's HTML markup.
    """
    table = _table(
        table_id="guardrail-opportunity-cost",
        caption="Table 10. Guardrail opportunity cost (central sensitivity estimate).",
        column_headers=["Quantity", "Value"],
        rows=[
            ["Guardrail-blocked events", f"{limitations.guardrail_blocked_events:,}"],
            [
                "Of those, would have recovered per the oracle",
                f"{limitations.would_have_recovered_events:,}",
            ],
            ["Orders never recovered by any other path", f"{limitations.orders_never_recovered:,}"],
        ],
    )
    return f"""<section id="limitations">
  <h2>7. Honest limitations</h2>
  <ul>
    <li>Every recovery outcome in this report is simulated by a seeded oracle, never
    observed from a real customer or a live Razorpay payment. Razorpay's test mode
    exposes only a binary pass/fail toggle, never a probability.</li>
    <li>The guardrails' caution has a real, measured cost, not a hidden one -- see
    Table 10.</li>
    <li>Webhook delivery deduplication has a tested primitive
    (<code>reflow.webhook.dedup</code>) but no live HTTP endpoint anywhere in this
    project: a production-readiness gap, stated as one, not a live bug.</li>
    <li>This report's own accessibility validator
    (<code>reflow.report.validate</code>) performs structural and colour-contrast
    checks; it is not a full axe-core/browser-based WCAG audit. See that module's
    docstring for exactly what it does and does not check.</li>
  </ul>
  {table}
</section>"""


def build_report_html(data: ReportData) -> str:
    """Build the complete, self-contained HTML pipeline report.

    Args:
        data: The loaded :class:`~reflow.report.data.ReportData`.

    Returns:
        The full HTML document as one string, with inline CSS and no
        external resource references of any kind.
    """
    sections = [
        _corpus_section(data.demo.corpus),
        _root_cause_section(data.demo.root_cause),
        _incident_section(data.demo.incident),
        _routing_section(data.demo.routing),
        _guardrail_section(data),
        _results_section(data.demo.results, data.policy_outcomes),
        _limitations_section(data.demo.limitations),
        _provenance_section(data),
    ]
    nav_items = [
        ("corpus", "1. The corpus"),
        ("root-cause", "2. Root cause"),
        ("incident-detection", "3. Incident detection"),
        ("routing", "4. Routing split"),
        ("guardrails", "5. The guardrail refusing to act"),
        ("results", "6. Results vs. baselines"),
        ("limitations", "7. Honest limitations"),
        ("provenance", "Provenance"),
    ]
    nav_list = "".join(
        f"<li><a href='#{anchor}'>{_esc(label)}</a></li>" for anchor, label in nav_items
    )
    body_sections = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>reflow -- Phase 8 full pipeline report</title>
{_style_block()}
</head>
<body>
<header>
  <h1>reflow: full pipeline report</h1>
  <p>Structured root-cause grouping, incident detection, two-tier diagnosis,
  guardrailed bounded recovery, and a replayable audit trail, for
  {data.demo.corpus.n_events:,} failed Razorpay payments.</p>
</header>
<nav aria-label="Report sections">
  <h2>Contents</h2>
  <ul>{nav_list}</ul>
</nav>
<main>
{body_sections}
</main>
<footer>
  <p>Generated on {_esc(data.generated_on)} by <code>{_esc(data.regenerate_command)}</code>,
  corpus seed {_esc(data.demo.seed)}. See <code>docs/design.md</code> for the full
  architecture decision records this report summarises.</p>
</footer>
</body>
</html>
"""
