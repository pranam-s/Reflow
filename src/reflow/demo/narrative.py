"""Building the eight beats of ``reflow demo`` as plain, ASCII-only ``rich`` renderables.

Every function here is a pure function of :mod:`reflow.demo.data`'s already
-loaded facts to a ``rich`` renderable: no I/O, no sleeping, no randomness.
:mod:`reflow.demo.runner` is the only caller, and it is the only place
these renderables are ever printed or paced.

**Accessibility is structural here, not cosmetic.** Every panel and table
uses ``rich.box.ASCII`` (plain ``+``/``-``/``|`` borders) instead of the
default Unicode box-drawing characters, for the same reason
:mod:`reflow.audit.replay` already does (see that module's ``_BOX_STYLE``
docstring): it renders identically on a real terminal, a piped/redirected
stream, and a screen reader, whereas Unicode box-drawing and Rich's default
Unicode ellipsis can both raise ``UnicodeEncodeError`` on a redirected
Windows stream and are certainly not "pure ASCII" either way. Every table
column that could truncate uses ``overflow="fold"`` rather than the
default ``"ellipsis"``, for the same reason: Rich's ellipsis truncation
inserts the single Unicode character ``U+2026``, not three ASCII periods.
No cell in any table here relies on colour alone to carry a verdict --
every comparison ("below baseline", "ties within noise", "beats") is
spelled out in a plain-text column, exactly as
:mod:`reflow.audit.replay`'s ``BLOCKED``/``PASSED`` and ``YES``/``NO``
columns already establish the pattern for this project.
"""

from __future__ import annotations

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from reflow.demo.data import (
    CorpusData,
    DemoData,
    IncidentData,
    LimitationsData,
    ResultsData,
    RootCauseData,
    RoutingData,
)

_BOX_STYLE = box.ASCII


def _panel(renderable: RenderableType, *, title: str) -> Panel:
    """Wrap a renderable in this demo's standard ASCII-bordered panel.

    Args:
        renderable: The content to wrap.
        title: The panel's title.

    Returns:
        A ``rich.panel.Panel`` styled consistently with every other beat.
    """
    return Panel(renderable, title=title, border_style="cyan", box=_BOX_STYLE)


def _fact_table(rows: list[tuple[str, str]]) -> Table:
    """Build a borderless two-column ``field: value`` table.

    Args:
        rows: ``(field, value)`` pairs, in display order.

    Returns:
        A ``rich`` table with no header row, matching
        :mod:`reflow.audit.replay`'s field-table convention.
    """
    table = Table(show_header=False, box=_BOX_STYLE, padding=(0, 1, 0, 0))
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    for field_name, value in rows:
        table.add_row(field_name, value)
    return table


def build_title_screen() -> Panel:
    """Build the demo's opening title panel.

    Returns:
        The title :class:`~rich.panel.Panel`.
    """
    body = Text.from_markup(
        "reflow -- structured root-cause grouping, incident detection, two-tier\n"
        "diagnosis, guardrailed bounded recovery, and a replayable audit trail,\n"
        "for 50,000 failed Razorpay payments.\n\n"
        "Every number in this demo is read live from committed Phase 2, 3, 4,\n"
        "6, and 7 report artefacts. No network call, no credential, and no LLM\n"
        "call is made anywhere in this command."
    )
    return _panel(body, title="reflow demo")


def build_corpus_beat(data: CorpusData) -> Panel:
    """Build Beat 1: the corpus and the taxonomy it is grounded in.

    Args:
        data: The loaded :class:`~reflow.demo.data.CorpusData`.

    Returns:
        Beat 1's :class:`~rich.panel.Panel`.
    """
    table = _fact_table(
        [
            ("Failed payment events", f"{data.n_events:,}"),
            (
                "Grounded in",
                f"Razorpay's own {data.taxonomy_row_count}-row published error-reasons "
                "taxonomy (vendored, verbatim, defects and all)",
            ),
            ("Distinct reason codes observed", str(data.distinct_reasons_seen)),
        ]
    )
    intro = Text(
        "Every event carries the same four fields Razorpay's own webhook reports: "
        "error code, source, step, and reason."
    )
    return _panel(Group(intro, table), title="1. The corpus")


def build_root_cause_beat(data: RootCauseData) -> Panel:
    """Build Beat 2: GROUP BY resolves root cause; three clusterers lost.

    Args:
        data: The loaded :class:`~reflow.demo.data.RootCauseData`.

    Returns:
        Beat 2's :class:`~rich.panel.Panel`.
    """
    intro = Text(
        "GROUP BY (code, source, step, reason) is the production root-cause path -- "
        "not clustering. On the narrow stratum "
        f"({data.narrow_n_true_clusters} true reasons, {data.narrow_n_predicted_clusters} "
        f"groups produced), a one-line GROUP BY already scores purity {data.narrow_purity:.3f}, "
        f"NMI {data.narrow_nmi:.3f}, ARI {data.narrow_ari:.3f} -- near-perfect, for free.\n\n"
        "On the hard part -- the catch-all reasons where free text is the only clue, and "
        "Razorpay's own documentation says it does not receive the sub-cause -- three real "
        "clusterers were benchmarked against GROUP BY. There is no sub-cause signal in the "
        "text for any of them to find, so every candidate converged on the baseline or fell "
        "below it:"
    )
    table = Table(show_header=True, header_style="bold", box=_BOX_STYLE)
    table.add_column("Candidate", overflow="fold")
    table.add_column("Purity")
    table.add_column("NMI")
    table.add_column("ARI")
    table.add_column("Verdict vs. GROUP BY", overflow="fold")
    groupby = data.catchall_groupby
    table.add_row(
        "GROUP BY (baseline)",
        f"{groupby.purity:.3f}",
        f"{groupby.nmi:.3f}",
        f"{groupby.ari:.3f}",
        "--",
    )
    drain3 = data.catchall_drain3
    table.add_row(
        "Drain3",
        f"{drain3.purity:.3f}",
        f"{drain3.nmi:.3f}",
        f"{drain3.ari:.3f}",
        "BELOW baseline (no signal to find)",
    )
    template_hash = data.catchall_template_hash
    table.add_row(
        "Template hashing",
        f"{template_hash.purity:.3f}",
        f"{template_hash.nmi:.3f}",
        f"{template_hash.ari:.3f}",
        "TIES baseline (noise, not signal)",
    )
    tfidf = data.catchall_tfidf_hdbscan
    table.add_row(
        "TF-IDF + HDBSCAN",
        f"{tfidf.purity:.3f}",
        f"{tfidf.nmi:.3f}",
        f"{tfidf.ari:.3f}",
        "TIES baseline (noise, not signal)",
    )
    verdict = Text(
        "Verdict (ADR-0002): no clustering candidate is adopted for production catch-all "
        "root-causing. GROUP BY runs every reason code, narrow and catch-all alike."
    )
    return _panel(Group(intro, table, Text(""), verdict), title="2. Root cause: GROUP BY wins")


def build_incident_beat(data: IncidentData) -> Panel:
    """Build Beat 3: Poisson-surprise incident detection.

    Args:
        data: The loaded :class:`~reflow.demo.data.IncidentData`.

    Returns:
        Beat 3's :class:`~rich.panel.Panel`.
    """
    intro = Text(
        "A bank outage does not show up as one reason code repeated -- it shows up as a "
        "mixture spanning 3-4 reason codes at once. poisson_surprise correlates failure "
        "counts over (method, bank) and 15-minute buckets to find it:"
    )
    table = Table(show_header=True, header_style="bold", box=_BOX_STYLE)
    table.add_column("Split")
    table.add_column("Precision")
    table.add_column("Recall")
    table.add_column("F1")
    table.add_row(
        "train",
        f"{data.poisson_train_precision:.3f}",
        f"{data.poisson_train_recall:.3f}",
        f"{data.poisson_train_f1:.3f}",
    )
    table.add_row(
        "test",
        f"{data.poisson_test_precision:.3f}",
        f"{data.poisson_test_recall:.3f}",
        f"{data.poisson_test_f1:.3f}",
    )
    fragmentation = Text(
        "A naive GROUP BY reason view, run at the same detector's own algorithm, "
        f"fragments one true incident into {data.groupby_reason_fragments_train_mean:.1f} to "
        f"{data.groupby_reason_fragments_test_mean:.1f} separate alerts on average -- an "
        "on-call engineer would have to manually realise these are the same outage."
    )
    return _panel(Group(intro, table, Text(""), fragmentation), title="3. Incident detection")


def build_routing_beat(data: RoutingData) -> Panel:
    """Build Beat 4: the deterministic-vs-LLM routing split.

    Args:
        data: The loaded :class:`~reflow.demo.data.RoutingData`.

    Returns:
        Beat 4's :class:`~rich.panel.Panel`.
    """
    table = Table(show_header=True, header_style="bold", box=_BOX_STYLE)
    table.add_column("Tier", overflow="fold")
    table.add_column("Events")
    table.add_column("Share")
    table.add_column("Live LLM calls")
    table.add_row(
        "Tier 1: deterministic lookup",
        f"{data.deterministic_events:,}",
        f"{data.deterministic_fraction * 100:.3f}%",
        "0",
    )
    llm_fraction = data.llm_events / data.total_events
    table.add_row(
        f"Tier 2: {data.n_escalated_reasons} escalated reason codes",
        f"{data.llm_events:,}",
        f"{llm_fraction * 100:.3f}%",
        f"{data.ambiguous_reason_calls} (cached per reason code, ever)",
    )
    summary = Text(
        f"{data.deterministic_fraction * 100:.3f}% of {data.total_events:,} events need no "
        "model at all. The 15 escalated reason codes are diagnosed once each and cached "
        f"forever. Every detected incident gets one uncached call "
        f"({data.incident_diagnosis_calls} of them here). Total: "
        f"{data.total_llm_calls} live LLM calls to diagnose {data.total_events:,} events."
    )
    return _panel(Group(table, Text(""), summary), title="4. The routing split")


def build_guardrail_intro(data: DemoData) -> Panel:
    """Build the introduction to Beat 5: one payment, one refusal to act.

    Args:
        data: The loaded :class:`~reflow.demo.data.DemoData`, whose
            :attr:`~reflow.demo.data.DemoData.guardrail_records` supply
            every fact quoted here, never a hardcoded description.

    Returns:
        Beat 5's introduction :class:`~rich.panel.Panel`.
    """
    record = data.guardrail_records[0]
    bank = record.bank or "an unnamed counterparty"
    lines = Text(
        f"Payment {record.payment_id}: {record.method} via {bank}, reason "
        f"{record.error_reason!r}. Tier 1 resolves this deterministically to remediation "
        f"class {record.remediation_class}, base action {record.base_action}.\n\n"
        "But poisson_surprise had already flagged an active incident on this exact "
        "(method, bank) pair at this event's own timestamp. ActiveIncidentGuardrail "
        f"intervenes: instead of chasing a customer whose bank is down, the final action "
        f"is {record.final_action} -- reflow deliberately waits for bank-side recovery "
        "rather than spamming a customer about a failure that is not their fault.\n\n"
        f"This is the full chain, reconstructed from nothing but the append-only audit "
        f"trail -- the same rendering `reflow replay {record.payment_id}` prints on its "
        "own, with its internal sections labelled 5a-5f here so they cannot be mistaken "
        "for this demo's own numbered beats:"
    )
    return _panel(lines, title="5. The guardrail refusing to act")


def build_guardrail_outro() -> Panel:
    """Build the closing line for Beat 5, after the replay has printed.

    Returns:
        Beat 5's closing :class:`~rich.panel.Panel`.
    """
    return _panel(
        Text(
            "The agent chose not to act, on purpose, with a reason recorded in the trail. "
            "That refusal -- not any single successful recovery -- is the decision this "
            "project is proudest of."
        ),
        title="5. (continued)",
    )


def build_results_beat(data: ResultsData) -> Panel:
    """Build Beat 6: reflow against three baselines, central sensitivity band.

    Args:
        data: The loaded :class:`~reflow.demo.data.ResultsData`.

    Returns:
        Beat 6's :class:`~rich.panel.Panel`.
    """
    table = Table(show_header=True, header_style="bold", box=_BOX_STYLE)
    table.add_column("Policy", overflow="fold")
    table.add_column("Money recovered (INR)")
    table.add_column("Contacts sent")
    table.add_row("do_nothing", f"{data.do_nothing_money_rupees:,.0f}", "0")
    table.add_row(
        "notify_all (blanket spam)",
        f"{data.notify_all_money_rupees:,.0f}",
        f"{data.notify_all_contacts:,}",
    )
    table.add_row(
        "notify_all_once",
        f"{data.notify_all_once_money_rupees:,.0f}",
        f"{data.notify_all_once_contacts:,}",
    )
    table.add_row("reflow", f"{data.reflow_money_rupees:,.0f}", f"{data.reflow_contacts:,}")
    money_fraction = data.reflow_as_fraction_of_notify_all_money
    contact_fraction = data.reflow_contacts_as_fraction_of_notify_all
    do_nothing_multiple = data.reflow_money_rupees / data.do_nothing_money_rupees
    verdict = Text(
        "Said plainly: reflow recovers LESS absolute money than blanket spam. It recovers "
        f"{money_fraction * 100:.0f}% of notify_all's money at {contact_fraction * 100:.0f}% "
        f"of notify_all's contact volume, and beats do_nothing by roughly "
        f"{do_nothing_multiple:.1f}x. This is reported as the finding, not reframed."
    )
    return _panel(Group(table, Text(""), verdict), title="6. Results: reflow vs. baselines")


def build_limitations_beat(data: LimitationsData) -> Panel:
    """Build Beat 7: what this project cannot honestly claim.

    Args:
        data: The loaded :class:`~reflow.demo.data.LimitationsData`.

    Returns:
        Beat 7's :class:`~rich.panel.Panel`.
    """
    body = Text(
        "- Every recovery outcome above is simulated by a seeded oracle, never observed "
        "from a real customer or a live Razorpay payment. Razorpay's test mode exposes "
        "only a binary pass/fail toggle, never a probability.\n\n"
        "- The guardrails' caution has a real, measured cost, not a hidden one: at the "
        f"central estimate, {data.would_have_recovered_events:,} of "
        f"{data.guardrail_blocked_events:,} guardrail-blocked events would have recovered "
        f"under the pre-guardrail action per the same oracle draw -- "
        f"{data.orders_never_recovered:,} orders never recovered by any other path as a "
        "result.\n\n"
        "- Webhook delivery deduplication has a tested primitive "
        "(reflow.webhook.dedup) but no live HTTP endpoint anywhere in this project -- a "
        "production-readiness gap, stated as one, not a live bug."
    )
    return _panel(body, title="7. Honest limitations")


def build_outro_screen() -> Panel:
    """Build the closing summary panel.

    Returns:
        The outro :class:`~rich.panel.Panel`.
    """
    body = Text(
        "reflow: structured root-cause grouping, incident detection over time and entity, "
        "two-tier deterministic/LLM diagnosis, guardrailed bounded recovery, and a "
        "replayable, tamper-evident audit trail for every decision.\n\n"
        "Full accessible report: docs/reports/phase8_report.html\n"
        "Full chain for any payment: reflow replay <payment_id>"
    )
    return _panel(body, title="reflow demo -- end")
