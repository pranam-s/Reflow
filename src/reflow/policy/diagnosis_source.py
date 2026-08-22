"""Building a full reason-code diagnosis table at zero marginal LLM cost.

This phase's brief is explicit: no live LLM call is permitted here, and
spend must be $0. :mod:`reflow.diagnose.tier1`'s deterministic table
already resolves 95 of 110 reason codes for free (a dict lookup). The
remaining 15 were already resolved, for real, by Phase 4's live benchmark
run, and that run's output is committed at
``docs/reports/phase4_diagnosis.json``. This module reads that file --
never calls an LLM -- to recover those 15 reasons' already-paid-for
diagnoses, and merges them with the deterministic table into one
``reason -> EventDiagnosis`` mapping the policy engine can look up for any
event in the corpus that produced that report.

**Why reuse the committed report rather than re-deciding these 15
reasons some other way.** The phase brief states plainly: "Where Tier 2
(LLM) supplied the diagnosis, the same mapping applies -- the policy
layer must not care which tier produced the input." Loading Phase 4's own
recorded output is the most literal, least invented way to honour that:
the policy layer receives exactly the diagnosis Tier 2 already produced,
with zero new spend, rather than silently re-deciding an ambiguous
reason's remediation class by some other heuristic that would diverge from
the diagnosis Phase 4's own judge already reviewed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisTier, EventDiagnosis
from reflow.diagnose.tier1 import DeterministicTable
from reflow.taxonomy.remediation import RemediationClass

DEFAULT_PHASE4_REPORT_PATH: Path = (
    Path(__file__).resolve().parents[3] / "docs" / "reports" / "phase4_diagnosis.json"
)


@dataclass(frozen=True, slots=True)
class AmbiguousDiagnosisRecord:
    """One escalated reason code's already-produced Tier 2 diagnosis.

    Attributes:
        reason: The reason code.
        remediation_class: The resolved remediation class, as its string
            value.
        confidence: The model's self-reported confidence, as its string
            value.
        rationale: The model's rationale.
    """

    reason: str
    remediation_class: str
    confidence: str
    rationale: str


class MissingAmbiguousDiagnosisError(ValueError):
    """Raised when a deterministic table's escalated reason has no committed diagnosis.

    Indicates the loaded Phase 4 report does not cover an escalated reason
    the current taxonomy needs -- most likely because the report was
    generated from a different corpus seed or a stale vendored
    spreadsheet. Raised rather than silently defaulting, since a silent
    default here would mean the policy layer decides an ambiguous
    reason's remediation class with no LLM involvement at all, which is
    exactly what this module exists to avoid.
    """


def load_ambiguous_diagnosis_records(
    report_path: Path = DEFAULT_PHASE4_REPORT_PATH,
) -> dict[str, AmbiguousDiagnosisRecord]:
    """Load every escalated reason's already-committed Tier 2 diagnosis.

    Args:
        report_path: Path to a Phase 4 diagnosis report JSON file (see
            :mod:`reflow.eval.diagnose`). Performs only a local file read
            -- never a network call.

    Returns:
        A mapping from reason code to :class:`AmbiguousDiagnosisRecord`,
        built from the report's ``ambiguous_reason_results`` list.
    """
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    records: dict[str, AmbiguousDiagnosisRecord] = {}
    for entry in payload["ambiguous_reason_results"]:
        records[entry["reason"]] = AmbiguousDiagnosisRecord(
            reason=entry["reason"],
            remediation_class=entry["remediation_class"],
            confidence=entry["confidence"],
            rationale=entry["rationale"],
        )
    return records


def build_offline_diagnoses(
    table: DeterministicTable, ambiguous_records: dict[str, AmbiguousDiagnosisRecord]
) -> dict[str, EventDiagnosis]:
    """Merge the deterministic table and committed ambiguous diagnoses.

    Args:
        table: The reason-code-level deterministic routing table (see
            :func:`reflow.diagnose.tier1.default_deterministic_table`).
        ambiguous_records: Every escalated reason's already-committed
            diagnosis, e.g. from :func:`load_ambiguous_diagnosis_records`.

    Returns:
        A mapping from every reason code ``table`` has ever seen (both
        deterministic and escalated) to its :class:`~reflow.diagnose.router.EventDiagnosis`.
        Deterministic reasons carry
        :attr:`~reflow.diagnose.router.DiagnosisTier.DETERMINISTIC` and
        :attr:`~reflow.diagnose.models.Confidence.HIGH`, matching
        :meth:`reflow.diagnose.router.DiagnosisRouter.diagnose_reason`'s
        own behaviour exactly. Escalated reasons carry
        :attr:`~reflow.diagnose.router.DiagnosisTier.LLM` and the
        confidence/rationale Phase 4's live run actually produced.

    Raises:
        MissingAmbiguousDiagnosisError: If ``table`` has an escalated
            reason with no entry in ``ambiguous_records``.
    """
    diagnoses: dict[str, EventDiagnosis] = {}
    for reason, remediation_class in table.deterministic.items():
        diagnoses[reason] = EventDiagnosis(
            reason=reason,
            tier=DiagnosisTier.DETERMINISTIC,
            remediation_class=remediation_class,
            confidence=Confidence.HIGH,
            rationale=None,
        )
    for reason in table.escalated:
        record = ambiguous_records.get(reason)
        if record is None:
            raise MissingAmbiguousDiagnosisError(
                f"Escalated reason {reason!r} has no committed Phase 4 diagnosis; the loaded "
                "report does not cover this taxonomy's escalated reason set."
            )
        diagnoses[reason] = EventDiagnosis(
            reason=reason,
            tier=DiagnosisTier.LLM,
            remediation_class=RemediationClass(record.remediation_class),
            confidence=Confidence(record.confidence),
            rationale=record.rationale,
        )
    return diagnoses


def diagnose_reason(reason: str, diagnoses: dict[str, EventDiagnosis]) -> EventDiagnosis:
    """Look up one reason code's offline-built diagnosis.

    Args:
        reason: The reason code to look up.
        diagnoses: The merged table from :func:`build_offline_diagnoses`.

    Returns:
        The reason's :class:`~reflow.diagnose.router.EventDiagnosis`.

    Raises:
        KeyError: If ``reason`` is not present in ``diagnoses`` -- this
            project treats an unseen reason code as a hard failure rather
            than a silent default, since a policy decision with no
            grounded diagnosis behind it would be worse than an explicit
            crash.
    """
    return diagnoses[reason]
