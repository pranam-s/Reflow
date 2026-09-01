"""Reconstructing and rendering one payment's complete decision chain.

Deliverable 3's brief names this the centrepiece of the demo: ``reflow
replay <payment_id>`` must read nothing but the append-only audit trail
(:mod:`reflow.audit.store`) and print a readable, well-structured account
of every stage a payment went through -- the event and its ``(code,
source, step, reason)`` group, any incident correlation, the diagnosis,
every guardrail evaluated (blocked *and* passed), the final action, and
the execution outcome. Nothing here re-derives a decision; it only
reconstructs and formats what :mod:`reflow.audit.record` already
persisted, which is the whole point of an append-only trail being
"replayable."

Rendering uses ``rich`` (:class:`rich.console.Console`), which already
degrades gracefully when its output is not a terminal -- colour escape
codes are omitted automatically once ``Console.is_terminal`` is ``False``
(e.g. output piped to a file or captured in a test), verified directly
against the installed ``rich`` source rather than assumed. Every visual
cue this module adds is paired with an explicit word (``"BLOCKED"`` /
``"PASSED"``, ``"YES"`` / ``"NO"``), never colour alone, so the same
information survives redirection or a screen reader exactly as it reads
on a colour terminal.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from reflow.audit.record import AuditRecord
from reflow.audit.store import iter_audit_records

_BOX_STYLE = box.ASCII
"""Plain ASCII table/panel borders (``+``, ``-``, ``|``), used everywhere
in this module instead of ``rich``'s default Unicode box-drawing
characters. This is not a cosmetic choice: a redirected or piped output
stream on Windows inherits the process's legacy code page (verified
directly -- capturing this module's own output through a non-console
pipe on this project's Windows development machine raised
``UnicodeEncodeError`` under ``rich``'s default box style, since PEP
528's console-aware UTF-8 handling only applies to a real attached
console, not a pipe or redirect), while plain ASCII renders identically
and correctly everywhere -- a real terminal, a piped/redirected file, or
a screen reader -- which matters more here than the cosmetic upgrade a
Unicode box would give a real terminal."""


_SECTION_TITLES: tuple[str, ...] = (
    "Payment",
    "Root cause -- (code, source, step, reason)",
    "Diagnosis",
    "Guardrail chain (every guardrail evaluated, blocked or passed)",
    "Decision",
    "Execution outcome",
)
"""The six section names every replay renders, in order, independent of
how each section is numbered (see :func:`render_replay`'s
``section_numbers`` argument)."""

_DEFAULT_SECTION_NUMBERS: tuple[str, ...] = ("1", "2", "3", "4", "5", "6")
"""``reflow replay``'s own standalone numbering: plain ``1`` through
``6``, unchanged from every prior phase."""


class PaymentNotFoundError(ValueError):
    """Raised when a payment id has no record in the given audit trail."""


def find_records_for_payment(path: Path, payment_id: str) -> list[AuditRecord]:
    """Find every audit record for one payment id, in trail order.

    Args:
        path: The audit trail JSONL file to search.
        payment_id: The payment id to look up.

    Returns:
        Every matching :class:`~reflow.audit.record.AuditRecord`, in the
        order they appear in the trail (almost always exactly one record,
        since this project executes each generated payment event's
        decision once; a list is returned rather than a single record so
        a payment re-diagnosed by a later run is not silently collapsed).

    Raises:
        PaymentNotFoundError: If no record in ``path`` matches
            ``payment_id``.
        FileNotFoundError: If ``path`` does not exist.
    """
    records = [record for record in iter_audit_records(path) if record.payment_id == payment_id]
    if not records:
        raise PaymentNotFoundError(
            f"No audit record found for payment_id={payment_id!r} in {path}."
        )
    return records


def _verdict_text(blocked: bool) -> Text:
    """Render a guardrail verdict as an explicit, colour-paired word.

    Args:
        blocked: Whether the guardrail blocked the action.

    Returns:
        ``"BLOCKED"`` in bold red if ``blocked``, otherwise ``"PASSED"`` in
        bold green -- the word itself carries the meaning; colour is
        decoration, never the only signal.
    """
    return Text("BLOCKED", style="bold red") if blocked else Text("PASSED", style="bold green")


def _yes_no(value: bool) -> Text:
    """Render a boolean as an explicit ``"YES"``/``"NO"`` word.

    Args:
        value: The boolean to render.

    Returns:
        ``"YES"`` in bold yellow if ``value``, otherwise ``"NO"``.
    """
    return Text("YES", style="bold yellow") if value else Text("NO")


def _header_table(record: AuditRecord) -> Table:
    """Build the payment identity/context table.

    Args:
        record: The record to render.

    Returns:
        A borderless two-column ``rich`` table.
    """
    table = Table(show_header=False, box=_BOX_STYLE, padding=(0, 1, 0, 0))
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("Payment", record.payment_id)
    table.add_row("Order", record.order_id)
    table.add_row("Customer", record.customer_id)
    table.add_row("Method / Bank", f"{record.method} / {record.bank or 'n/a'}")
    table.add_row("Amount", f"INR {record.amount / 100:.2f}")
    table.add_row("Created at", record.created_at)
    table.add_row("Attempt #", str(record.attempt_number))
    table.add_row("Recorded at", record.recorded_at)
    return table


def _error_group_table(record: AuditRecord) -> Table:
    """Build the ``(code, source, step, reason)`` root-cause table.

    Args:
        record: The record to render.

    Returns:
        A borderless two-column ``rich`` table.
    """
    table = Table(show_header=False, box=_BOX_STYLE, padding=(0, 1, 0, 0))
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("Code", record.error_code)
    table.add_row("Source", record.error_source)
    table.add_row("Step", record.error_step)
    table.add_row("Reason", record.error_reason)
    table.add_row("In active incident?", _yes_no(record.in_active_incident))
    return table


def _diagnosis_table(record: AuditRecord) -> Table:
    """Build the diagnosis table.

    Args:
        record: The record to render.

    Returns:
        A borderless two-column ``rich`` table.
    """
    table = Table(show_header=False, box=_BOX_STYLE, padding=(0, 1, 0, 0))
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("Tier", record.diagnosis_tier)
    table.add_row("Remediation class", record.remediation_class)
    table.add_row("Confidence", record.diagnosis_confidence)
    table.add_row("Rationale", record.diagnosis_rationale or "n/a (deterministic lookup)")
    return table


def _guardrail_table(record: AuditRecord) -> Table:
    """Build the full guardrail-chain table, blocks and passes alike.

    Args:
        record: The record to render.

    Returns:
        A ``rich`` table with one row per guardrail evaluated, in
        evaluation order.
    """
    table = Table(show_header=True, header_style="bold", box=_BOX_STYLE)
    table.add_column("Guardrail", overflow="fold")
    table.add_column("Verdict")
    table.add_column("Action before -> after", overflow="fold")
    table.add_column("Reason", overflow="fold")
    for evaluation in record.guardrail_evaluations:
        table.add_row(
            str(evaluation["name"]),
            _verdict_text(bool(evaluation["blocked"])),
            f"{evaluation['action_before']} -> {evaluation['action_after']}",
            str(evaluation["reason"]),
        )
    return table


def _decision_table(record: AuditRecord) -> Table:
    """Build the base/candidate/final action summary table.

    Args:
        record: The record to render.

    Returns:
        A borderless two-column ``rich`` table.
    """
    table = Table(show_header=False, box=_BOX_STYLE, padding=(0, 1, 0, 0))
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("Base action", record.base_action)
    table.add_row("Ladder candidate", record.candidate_action)
    table.add_row("Final action", Text(record.final_action, style="bold"))
    table.add_row("Ladder terminal state", record.ladder_terminal_state)
    table.add_row("Justification", record.justification)
    return table


def _execution_table(record: AuditRecord) -> Table:
    """Build the execution-outcome table.

    Args:
        record: The record to render.

    Returns:
        A borderless two-column ``rich`` table, reporting "no execution
        record" plainly rather than rendering an empty table when
        ``record.execution`` is ``None``.
    """
    table = Table(show_header=False, box=_BOX_STYLE, padding=(0, 1, 0, 0))
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    execution = record.execution
    if execution is None:
        table.add_row("Outcome", "n/a (no execution record for this decision)")
        return table
    table.add_row("Outcome", str(execution["outcome"]).upper())
    table.add_row("Dry run?", _yes_no(bool(execution["dry_run"])))
    table.add_row("Reference id", str(execution["reference_id"] or "n/a"))
    table.add_row("Idempotent replay?", _yes_no(bool(execution["idempotent_replay"])))
    if execution["short_url"]:
        table.add_row("Short URL", str(execution["short_url"]))
    if execution["payment_link_id"]:
        table.add_row("Payment Link id", str(execution["payment_link_id"]))
    if execution["http_status"] is not None:
        table.add_row("HTTP status", str(execution["http_status"]))
    if execution["latency_ms"] is not None:
        table.add_row("Latency", f"{execution['latency_ms']:.1f} ms")
    table.add_row("Retry count", str(execution["retry_count"]))
    if execution["error_message"]:
        table.add_row("Error", Text(str(execution["error_message"]), style="bold red"))
    if execution["note"]:
        table.add_row("Note", str(execution["note"]))
    return table


def render_replay(
    console: Console,
    records: list[AuditRecord],
    *,
    section_numbers: Sequence[str] = _DEFAULT_SECTION_NUMBERS,
) -> None:
    """Print one payment's complete decision chain to ``console``.

    Args:
        console: The ``rich`` console to render to. Callers control
            terminal detection entirely through how this console was
            constructed (see :func:`reflow.cli.replay_command`).
        records: The payment's audit records, in trail order (from
            :func:`find_records_for_payment`).
        section_numbers: The six panel-title prefixes to use, one per
            entry of :data:`_SECTION_TITLES`, in order. Defaults to plain
            ``"1"``-``"6"``, which is what standalone ``reflow replay``
            always uses. :mod:`reflow.demo.runner` passes sub-lettered
            values (``"5a"``-``"5f"``) instead, so this same rendering,
            embedded inside the demo's own numbered beat 5, cannot be
            mistaken for a second, independently-numbered "1" through "6"
            sequence on screen.

    Raises:
        ValueError: If ``section_numbers`` does not have exactly six
            entries, one per :data:`_SECTION_TITLES`.
    """
    if len(section_numbers) != len(_SECTION_TITLES):
        raise ValueError(
            f"section_numbers must have exactly {len(_SECTION_TITLES)} entries, "
            f"got {len(section_numbers)}."
        )
    titles = [
        f"{number}. {title}" for number, title in zip(section_numbers, _SECTION_TITLES, strict=True)
    ]
    for index, record in enumerate(records):
        if len(records) > 1:
            console.print(f"[bold]-- record {index + 1} of {len(records)} --[/bold]")
        console.print(
            Panel(_header_table(record), title=titles[0], border_style="cyan", box=_BOX_STYLE)
        )
        console.print(
            Panel(_error_group_table(record), title=titles[1], border_style="cyan", box=_BOX_STYLE)
        )
        console.print(
            Panel(_diagnosis_table(record), title=titles[2], border_style="cyan", box=_BOX_STYLE)
        )
        console.print(
            Panel(_guardrail_table(record), title=titles[3], border_style="cyan", box=_BOX_STYLE)
        )
        console.print(
            Panel(_decision_table(record), title=titles[4], border_style="cyan", box=_BOX_STYLE)
        )
        console.print(
            Panel(_execution_table(record), title=titles[5], border_style="cyan", box=_BOX_STYLE)
        )
