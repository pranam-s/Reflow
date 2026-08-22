"""Tier 1: the deterministic remediation-class lookup, no LLM call.

:mod:`reflow.taxonomy.remediation` classifies 100 of the vendored
spreadsheet's 114 *rows* into a remediation class; 14 rows are flagged
ambiguous. A production event, however, carries only a bare
``error_reason`` code, never a spreadsheet row index (see
:attr:`reflow.corpus.events.PaymentEvent.error_reason`), and 4 reason codes
repeat across two rows each (``BUILD_LOG.md``, 2026-08-22). Two of those
repeats -- ``issuer_technical_error`` and ``payment_method_not_enabled`` --
carry *materially conflicting* remediation advice across their two rows.

This module reconciles rows to reason codes explicitly rather than picking
one row's answer and discarding the other (as
:func:`reflow.corpus.generator._build_reason_index` does for corpus
generation, via ``dict.setdefault`` on first occurrence -- an acceptable
simplification for synthesising plausible-looking events, but not an honest
routing table for real diagnosis). A reason code is resolved
deterministically here only when *every* row for that code is itself
unambiguous *and* every row agrees on the same class. Both
``issuer_technical_error`` (an ambiguous row conflicting with an
unambiguous one) and ``payment_method_not_enabled`` (two individually
unambiguous rows that disagree with each other) therefore escalate to
Tier 2 even though only the first is among the taxonomy's own 14
row-flagged-ambiguous rows -- one more distinct reason code than the "14
ambiguous reasons" the taxonomy module itself reports, discovered only by
reconciling at the reason-code granularity real events actually carry. This
is reported plainly in ``docs/reports/phase4_diagnosis.md`` rather than
silently rounded to 14 to match the phase brief's own framing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import ReasonRecord, parse_reason_records
from reflow.taxonomy.remediation import (
    ReasonClassification,
    RemediationClass,
    classify_reasons,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class ReasonRowContext:
    """The vendored text backing one row of a reason code, for LLM prompting.

    Attributes:
        explanation: The row's ``Explanation`` column, verbatim.
        next_steps: The row's ``Next Steps`` column, verbatim.
        candidate_classes: The remediation class(es) the row's text
            supports.
        ambiguity_note: The taxonomy's own rationale for why this row could
            not be resolved to a single class, if any.
    """

    explanation: str
    next_steps: str
    candidate_classes: frozenset[RemediationClass]
    ambiguity_note: str | None


@dataclass(frozen=True, slots=True)
class DeterministicTable:
    """Reason-code-level routing built by reconciling every vendored row.

    Attributes:
        deterministic: Mapping from reason code to its single agreed
            :class:`~reflow.taxonomy.remediation.RemediationClass`, for
            every code where every row for that code is unambiguous and
            every row agrees.
        escalated: Mapping from reason code to every :class:`ReasonRowContext`
            recorded for that code, for every code this table could not
            resolve deterministically -- the input Tier 2's LLM call needs.
    """

    deterministic: dict[str, RemediationClass]
    escalated: dict[str, tuple[ReasonRowContext, ...]]

    def lookup(self, reason: str) -> RemediationClass | None:
        """Look up a reason code's deterministic remediation class.

        Args:
            reason: The reason code to look up.

        Returns:
            The agreed :class:`~reflow.taxonomy.remediation.RemediationClass`
            if ``reason`` resolves deterministically, or ``None`` if it must
            be escalated to Tier 2 (including reason codes this table has
            never seen at all, which are treated conservatively as needing
            escalation rather than silently assumed safe).
        """
        return self.deterministic.get(reason)

    def is_escalated(self, reason: str) -> bool:
        """Whether a reason code requires Tier 2 escalation.

        Args:
            reason: The reason code to check.

        Returns:
            ``True`` if ``reason`` is not resolvable by :meth:`lookup`.
        """
        return reason not in self.deterministic


def build_deterministic_table(records: list[ReasonRecord]) -> DeterministicTable:
    """Reconcile every vendored row into a reason-code-level routing table.

    Args:
        records: Every parsed reason record, in file order, e.g. from
            :func:`reflow.taxonomy.reasons.parse_reason_records`.

    Returns:
        The populated :class:`DeterministicTable`.
    """
    classifications = classify_reasons(records)
    by_reason: dict[str, list[ReasonClassification]] = defaultdict(list)
    for classification in classifications:
        by_reason[classification.reason].append(classification)
    record_by_row_index = {record.row_index: record for record in records}

    deterministic: dict[str, RemediationClass] = {}
    escalated: dict[str, tuple[ReasonRowContext, ...]] = {}
    for reason, rows in by_reason.items():
        classes = {row.remediation_class for row in rows}
        resolved_classes = {cls for cls in classes if cls is not None}
        if len(classes) == 1 and len(resolved_classes) == 1:
            deterministic[reason] = next(iter(resolved_classes))
            continue
        contexts = []
        for row in rows:
            record = record_by_row_index[row.row_index]
            contexts.append(
                ReasonRowContext(
                    explanation=record.explanation,
                    next_steps=record.next_steps,
                    candidate_classes=row.candidate_classes,
                    ambiguity_note=row.ambiguity_note,
                )
            )
        escalated[reason] = tuple(contexts)

    return DeterministicTable(deterministic=deterministic, escalated=escalated)


@lru_cache(maxsize=1)
def default_deterministic_table() -> DeterministicTable:
    """Build the deterministic table from the vendored spreadsheet, once.

    Returns:
        The :class:`DeterministicTable` reconciled from
        ``data/razorpay_error_reasons.xlsx``. Cached: the vendored file
        never changes at runtime (``src/reflow/taxonomy`` and ``data`` are
        frozen), so re-parsing it on every lookup would be pure waste.
    """
    records = parse_reason_records(resolve_vendored_path(_REPO_ROOT))
    return build_deterministic_table(records)
