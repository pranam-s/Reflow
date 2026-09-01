"""Loading every number ``reflow demo`` shows, entirely from committed artefacts.

Every figure printed by :mod:`reflow.demo.narrative` is read here from an
already-committed Phase 2/3/4/6/7 report or the committed audit trail
sample -- never computed fresh, never sampled, never the product of a
network or LLM call. This is what makes the demo's output identical on
every run in the same checked-out environment: the inputs are static
files already in the repository, and this module does nothing but parse
and select fields from them.

:data:`PINNED_GUARDRAIL_PAYMENT_ID` is fixed at module load, not derived
or randomly sampled, so the demo's centrepiece beat -- a real payment
where :class:`~reflow.policy.guardrails.ActiveIncidentGuardrail` blocked a
chase because its ``(method, bank)`` was mid-outage -- is stable across
every run and every reviewer's clone, not merely reproducible given a
seed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reflow.audit.record import AuditRecord
from reflow.audit.replay import find_records_for_payment
from reflow.taxonomy.provenance import EXPECTED_DATA_ROW_COUNT

_REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_PHASE2_REPORT_PATH: Path = (
    _REPO_ROOT / "docs" / "reports" / "phase2_clustering_bakeoff.json"
)
DEFAULT_PHASE3_REPORT_PATH: Path = (
    _REPO_ROOT / "docs" / "reports" / "phase3_incident_detection.json"
)
DEFAULT_PHASE4_REPORT_PATH: Path = _REPO_ROOT / "docs" / "reports" / "phase4_diagnosis.json"
DEFAULT_PHASE7_EVALUATION_REPORT_PATH: Path = (
    _REPO_ROOT / "docs" / "reports" / "phase7_evaluation.json"
)
DEFAULT_AUDIT_TRAIL_PATH: Path = _REPO_ROOT / "docs" / "reports" / "phase6_audit_trail.jsonl"

PINNED_GUARDRAIL_PAYMENT_ID: str = "pay_7g3rVMw8NZ8DwS"
"""A real payment from the committed audit-trail sample
(``docs/reports/phase6_audit_trail.jsonl``, sequence 204): a UPI payment
against ICICI Bank, reason ``pin_not_set``, whose deterministic diagnosis
proposes ``recovery_link_now`` and whose
:class:`~reflow.policy.guardrails.ActiveIncidentGuardrail` blocks it to
``wait_bank_recovery`` because ``poisson_surprise`` had an active incident
open on ``(upi, ICICI Bank)`` at this event's timestamp. Picked, and
pinned, because it is a complete, legible instance of Deliverable 1's
single most consequential guardrail actually firing on real corpus data,
not a synthetic example built to illustrate the point."""

_CORPUS_SEED: int = 20260822
"""The fixed seed every Phase 2-7 report this module reads was generated
under -- shown in the demo's provenance line, never recomputed."""


@dataclass(frozen=True, slots=True)
class ClusterMetrics:
    """One clusterer's purity/NMI/ARI on one stratum, one arm, one richness level.

    Attributes:
        purity: Cluster purity against ground truth (0-1, higher better;
            inflated by over-fragmentation -- see
            :func:`reflow.eval.metrics.cluster_purity`).
        nmi: Normalised mutual information against ground truth (0-1).
        ari: Adjusted Rand index against ground truth (-1 to 1).
    """

    purity: float
    nmi: float
    ari: float


@dataclass(frozen=True, slots=True)
class CorpusData:
    """Facts about the generated corpus and the taxonomy it is grounded in.

    Attributes:
        n_events: Total generated failed-payment events.
        taxonomy_row_count: Rows in the vendored Razorpay error-reasons
            spreadsheet (:data:`reflow.taxonomy.provenance.EXPECTED_DATA_ROW_COUNT`).
        distinct_reasons_seen: Distinct ``error_reason`` codes observed in
            the corpus.
    """

    n_events: int
    taxonomy_row_count: int
    distinct_reasons_seen: int


@dataclass(frozen=True, slots=True)
class RootCauseData:
    """The GROUP BY-vs-clustering bake-off numbers Beat 2 reports.

    Attributes:
        narrow_purity: ``GROUP BY``'s purity on the narrow stratum
            (transparent arm, richness 1 -- arm-invariant for ``GROUP BY``
            by construction, since it never reads text).
        narrow_nmi: As above, NMI.
        narrow_ari: As above, ARI.
        narrow_n_true_clusters: True distinct reasons in the narrow stratum.
        narrow_n_predicted_clusters: ``GROUP BY``'s predicted group count
            there.
        catchall_groupby: ``GROUP BY``'s catch-all-stratum metrics, opaque
            arm, richness 1 -- the realistic condition (ADR-0002).
        catchall_drain3: Drain3's catch-all metrics, same arm/richness.
        catchall_template_hash: Template hashing's catch-all metrics, same
            arm/richness.
        catchall_tfidf_hdbscan: TF-IDF+HDBSCAN's catch-all metrics, same
            arm/richness.
    """

    narrow_purity: float
    narrow_nmi: float
    narrow_ari: float
    narrow_n_true_clusters: int
    narrow_n_predicted_clusters: int
    catchall_groupby: ClusterMetrics
    catchall_drain3: ClusterMetrics
    catchall_template_hash: ClusterMetrics
    catchall_tfidf_hdbscan: ClusterMetrics


@dataclass(frozen=True, slots=True)
class IncidentData:
    """The incident-detection numbers Beat 3 reports.

    Attributes:
        poisson_train_precision: ``poisson_surprise``'s train-split
            precision.
        poisson_train_recall: As above, recall.
        poisson_train_f1: As above, F1.
        poisson_test_precision: ``poisson_surprise``'s test-split precision.
        poisson_test_recall: As above, recall.
        poisson_test_f1: As above, F1.
        groupby_reason_fragments_train_mean: Mean number of separate alerts
            ``GROUP BY reason`` (run at the winning detector's own
            algorithm, per ADR-0003) splits one true incident window into,
            on the train split.
        groupby_reason_fragments_test_mean: As above, test split.
    """

    poisson_train_precision: float
    poisson_train_recall: float
    poisson_train_f1: float
    poisson_test_precision: float
    poisson_test_recall: float
    poisson_test_f1: float
    groupby_reason_fragments_train_mean: float
    groupby_reason_fragments_test_mean: float


@dataclass(frozen=True, slots=True)
class RoutingData:
    """The Tier 1/Tier 2 routing-split numbers Beat 4 reports.

    Attributes:
        total_events: Total events in the corpus.
        deterministic_events: Events resolved in Tier 1, zero LLM calls.
        llm_events: Events whose reason code escalated to Tier 2.
        deterministic_fraction: ``deterministic_events / total_events``.
        n_escalated_reasons: Distinct reason codes that escalate to Tier 2.
        ambiguous_reason_calls: Live LLM calls for ambiguous reasons
            (cached per reason code, paid at most once ever).
        incident_diagnosis_calls: Live, uncached LLM calls, one per
            detected incident.
    """

    total_events: int
    deterministic_events: int
    llm_events: int
    deterministic_fraction: float
    n_escalated_reasons: int
    ambiguous_reason_calls: int
    incident_diagnosis_calls: int

    @property
    def total_llm_calls(self) -> int:
        """Total live LLM calls this corpus's diagnosis run actually made.

        Returns:
            :attr:`ambiguous_reason_calls` plus :attr:`incident_diagnosis_calls`.
        """
        return self.ambiguous_reason_calls + self.incident_diagnosis_calls


@dataclass(frozen=True, slots=True)
class ResultsData:
    """The reflow-vs-baselines numbers Beat 6 reports (central sensitivity band).

    Attributes:
        reflow_money_rupees: Rupees reflow recovered, per the simulation.
        notify_all_money_rupees: Rupees the unbounded ``notify_all``
            baseline recovered.
        notify_all_once_money_rupees: Rupees the single-shot
            ``notify_all_once`` baseline recovered.
        do_nothing_money_rupees: Rupees recovered with no policy at all.
        reflow_as_fraction_of_notify_all_money: ``reflow_money_rupees /
            notify_all_money_rupees``.
        reflow_contacts: Customer contacts reflow sent.
        notify_all_contacts: Customer contacts ``notify_all`` sent.
        notify_all_once_contacts: Customer contacts the single-shot
            ``notify_all_once`` baseline sent.
    """

    reflow_money_rupees: float
    notify_all_money_rupees: float
    notify_all_once_money_rupees: float
    do_nothing_money_rupees: float
    reflow_as_fraction_of_notify_all_money: float
    reflow_contacts: int
    notify_all_contacts: int
    notify_all_once_contacts: int

    @property
    def reflow_contacts_as_fraction_of_notify_all(self) -> float:
        """The fraction of ``notify_all``'s contact volume reflow sent.

        Returns:
            ``reflow_contacts / notify_all_contacts``.
        """
        return self.reflow_contacts / self.notify_all_contacts


@dataclass(frozen=True, slots=True)
class LimitationsData:
    """The guardrail-opportunity-cost numbers Beat 7 reports (central band).

    Attributes:
        guardrail_blocked_events: Escalatable candidate actions a guardrail
            downgraded to a non-escalatable final action.
        would_have_recovered_events: Of those, how many the same
            deterministic oracle draw says would have recovered under the
            pre-guardrail action.
        orders_never_recovered: Distinct orders that never recovered by any
            other path in the simulation as a result.
    """

    guardrail_blocked_events: int
    would_have_recovered_events: int
    orders_never_recovered: int


@dataclass(frozen=True, slots=True)
class DemoData:
    """Every fact ``reflow demo`` needs, loaded once before the demo runs.

    Attributes:
        seed: The fixed corpus seed every source report was generated
            under.
        corpus: See :class:`CorpusData`.
        root_cause: See :class:`RootCauseData`.
        incident: See :class:`IncidentData`.
        routing: See :class:`RoutingData`.
        results: See :class:`ResultsData`.
        limitations: See :class:`LimitationsData`.
        guardrail_payment_id: The pinned payment id for Beat 5.
        guardrail_records: That payment's full audit-trail record(s), in
            trail order, from :func:`reflow.audit.replay.find_records_for_payment`.
    """

    seed: int
    corpus: CorpusData
    root_cause: RootCauseData
    incident: IncidentData
    routing: RoutingData
    results: ResultsData
    limitations: LimitationsData
    guardrail_payment_id: str
    guardrail_records: tuple[AuditRecord, ...]


def _load_json(path: Path) -> dict[str, Any]:
    """Load and parse one committed JSON report.

    Args:
        path: Filesystem path to the report.

    Returns:
        The parsed JSON document as a dict.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        json.JSONDecodeError: If ``path`` is not valid JSON.
    """
    with path.open(encoding="utf-8") as handle:
        loaded: Any = json.load(handle)
    return dict(loaded)


def _find_run(
    runs: list[dict[str, Any]], *, candidate: str, richness: int, arm: str
) -> dict[str, Any]:
    """Find one clustering bake-off run by its (candidate, richness, arm) key.

    Args:
        runs: The report's ``runs`` list.
        candidate: The clusterer name (e.g. ``"groupby_reason"``).
        richness: The variant-richness level.
        arm: ``"transparent"`` or ``"opaque"``.

    Returns:
        The matching run dict.

    Raises:
        LookupError: If no run matches.
    """
    for run in runs:
        if run["candidate"] == candidate and run["richness"] == richness and run["arm"] == arm:
            return dict(run)
    raise LookupError(
        f"No bake-off run for candidate={candidate!r}, richness={richness}, arm={arm!r}."
    )


def _find_stratum(run: dict[str, Any], stratum: str) -> dict[str, Any]:
    """Find one stratum entry within a clustering bake-off run.

    Args:
        run: A run dict, as returned by :func:`_find_run`.
        stratum: ``"narrow"`` or ``"catchall"``.

    Returns:
        The matching stratum dict.

    Raises:
        LookupError: If no stratum matches.
    """
    for entry in run["strata"]:
        if entry["stratum"] == stratum:
            return dict(entry)
    raise LookupError(f"No stratum {stratum!r} in run {run.get('candidate')!r}.")


def _cluster_metrics(stratum_entry: dict[str, Any]) -> ClusterMetrics:
    """Extract :class:`ClusterMetrics` from a bake-off stratum entry.

    Args:
        stratum_entry: A stratum dict, as returned by :func:`_find_stratum`.

    Returns:
        The extracted metrics.
    """
    metrics = stratum_entry["metrics"]
    return ClusterMetrics(
        purity=float(metrics["purity"]), nmi=float(metrics["nmi"]), ari=float(metrics["ari"])
    )


def _load_root_cause_data(phase2_report: dict[str, Any]) -> RootCauseData:
    """Build :class:`RootCauseData` from the Phase 2 clustering bake-off report.

    Args:
        phase2_report: The parsed ``phase2_clustering_bakeoff.json`` document.

    Returns:
        The populated :class:`RootCauseData`.
    """
    runs = list(phase2_report["runs"])
    narrow = _find_stratum(
        _find_run(runs, candidate="groupby_reason", richness=1, arm="transparent"), "narrow"
    )
    narrow_metrics = _cluster_metrics(narrow)
    catchall_groupby = _find_stratum(
        _find_run(runs, candidate="groupby_reason", richness=1, arm="opaque"), "catchall"
    )
    catchall_drain3 = _find_stratum(
        _find_run(runs, candidate="drain3", richness=1, arm="opaque"), "catchall"
    )
    catchall_template_hash = _find_stratum(
        _find_run(runs, candidate="template_hash", richness=1, arm="opaque"), "catchall"
    )
    catchall_tfidf_hdbscan = _find_stratum(
        _find_run(runs, candidate="tfidf_hdbscan", richness=1, arm="opaque"), "catchall"
    )
    return RootCauseData(
        narrow_purity=narrow_metrics.purity,
        narrow_nmi=narrow_metrics.nmi,
        narrow_ari=narrow_metrics.ari,
        narrow_n_true_clusters=int(narrow["metrics"]["n_true_clusters"]),
        narrow_n_predicted_clusters=int(narrow["metrics"]["n_predicted_clusters"]),
        catchall_groupby=_cluster_metrics(catchall_groupby),
        catchall_drain3=_cluster_metrics(catchall_drain3),
        catchall_template_hash=_cluster_metrics(catchall_template_hash),
        catchall_tfidf_hdbscan=_cluster_metrics(catchall_tfidf_hdbscan),
    )


def _find_detector_row(rows: list[dict[str, Any]], *, detector: str, split: str) -> dict[str, Any]:
    """Find one incident-detector benchmark row by (detector, split).

    Args:
        rows: A list of per-run detector rows (either the report's
            ``detector_rows`` or ``groupby_reason_rows``).
        detector: The detector's name.
        split: ``"train"`` or ``"test"``.

    Returns:
        The matching row dict.

    Raises:
        LookupError: If no row matches.
    """
    for row in rows:
        if row["detector"] == detector and row["split"] == split:
            return dict(row)
    raise LookupError(f"No detector row for detector={detector!r}, split={split!r}.")


def _load_incident_data(phase3_report: dict[str, Any]) -> IncidentData:
    """Build :class:`IncidentData` from the Phase 3 incident-detection report.

    Args:
        phase3_report: The parsed ``phase3_incident_detection.json`` document.

    Returns:
        The populated :class:`IncidentData`.
    """
    detector_rows = list(phase3_report["detector_rows"])
    groupby_rows = list(phase3_report["groupby_reason_rows"])
    poisson_train = _find_detector_row(detector_rows, detector="poisson_surprise", split="train")
    poisson_test = _find_detector_row(detector_rows, detector="poisson_surprise", split="test")
    groupby_train = _find_detector_row(
        groupby_rows, detector="groupby_reason+fixed_threshold", split="train"
    )
    groupby_test = _find_detector_row(
        groupby_rows, detector="groupby_reason+fixed_threshold", split="test"
    )
    return IncidentData(
        poisson_train_precision=float(poisson_train["precision"]),
        poisson_train_recall=float(poisson_train["recall"]),
        poisson_train_f1=float(poisson_train["f1"]),
        poisson_test_precision=float(poisson_test["precision"]),
        poisson_test_recall=float(poisson_test["recall"]),
        poisson_test_f1=float(poisson_test["f1"]),
        groupby_reason_fragments_train_mean=float(
            groupby_train["fragmentation"]["mean_fragments_per_window"]
        ),
        groupby_reason_fragments_test_mean=float(
            groupby_test["fragmentation"]["mean_fragments_per_window"]
        ),
    )


def _load_routing_data(phase4_report: dict[str, Any]) -> RoutingData:
    """Build :class:`RoutingData` from the Phase 4 diagnosis report.

    Args:
        phase4_report: The parsed ``phase4_diagnosis.json`` document.

    Returns:
        The populated :class:`RoutingData`.
    """
    routing = phase4_report["routing"]
    cost = phase4_report["cost"]
    return RoutingData(
        total_events=int(routing["total_events"]),
        deterministic_events=int(routing["deterministic_events"]),
        llm_events=int(routing["llm_events"]),
        deterministic_fraction=float(routing["deterministic_fraction"]),
        n_escalated_reasons=len(routing["escalated_reasons"]),
        ambiguous_reason_calls=int(cost["ambiguous_reason_calls"]),
        incident_diagnosis_calls=int(cost["incident_diagnosis_calls"]),
    )


def _load_results_and_limitations_data(
    phase7_evaluation_report: dict[str, Any],
) -> tuple[ResultsData, LimitationsData]:
    """Build :class:`ResultsData` and :class:`LimitationsData` from the Phase 7 evaluation report.

    Args:
        phase7_evaluation_report: The parsed ``phase7_evaluation.json``
            document.

    Returns:
        A ``(results, limitations)`` tuple, both at the central sensitivity
        band.
    """
    band = phase7_evaluation_report["headline_comparison_central_band"]
    results = ResultsData(
        reflow_money_rupees=float(band["reflow_money_rupees"]),
        notify_all_money_rupees=float(band["notify_all_money_rupees"]),
        notify_all_once_money_rupees=float(band["notify_all_once_money_rupees"]),
        do_nothing_money_rupees=float(band["do_nothing_money_rupees"]),
        reflow_as_fraction_of_notify_all_money=float(
            band["reflow_as_fraction_of_notify_all_money"]
        ),
        reflow_contacts=int(band["reflow_contacts"]),
        notify_all_contacts=int(band["notify_all_contacts"]),
        notify_all_once_contacts=int(band["notify_all_once_contacts"]),
    )
    opportunity_cost = phase7_evaluation_report["guardrail_opportunity_cost_analysis"]["central"]
    limitations = LimitationsData(
        guardrail_blocked_events=int(opportunity_cost["guardrail_blocked_events"]),
        would_have_recovered_events=int(
            opportunity_cost["events_where_the_blocked_action_would_have_recovered_per_oracle"]
        ),
        orders_never_recovered=int(opportunity_cost["orders_never_recovered_by_any_other_path"]),
    )
    return results, limitations


def load_demo_data(
    *,
    phase2_report_path: Path = DEFAULT_PHASE2_REPORT_PATH,
    phase3_report_path: Path = DEFAULT_PHASE3_REPORT_PATH,
    phase4_report_path: Path = DEFAULT_PHASE4_REPORT_PATH,
    phase7_evaluation_report_path: Path = DEFAULT_PHASE7_EVALUATION_REPORT_PATH,
    audit_trail_path: Path = DEFAULT_AUDIT_TRAIL_PATH,
    guardrail_payment_id: str = PINNED_GUARDRAIL_PAYMENT_ID,
) -> DemoData:
    """Load every fact ``reflow demo`` needs from committed artefacts.

    Performs only local filesystem reads of already-committed JSON/JSONL
    reports: no network access, no credential lookup, no LLM call, and no
    corpus regeneration.

    Args:
        phase2_report_path: Path to the Phase 2 clustering bake-off report.
        phase3_report_path: Path to the Phase 3 incident-detection report.
        phase4_report_path: Path to the Phase 4 diagnosis report.
        phase7_evaluation_report_path: Path to the Phase 7 evaluation
            report.
        audit_trail_path: Path to the committed audit-trail JSONL sample.
        guardrail_payment_id: The pinned payment id for Beat 5.

    Returns:
        The fully populated :class:`DemoData`.

    Raises:
        FileNotFoundError: If any report or the audit trail is missing.
        reflow.audit.replay.PaymentNotFoundError: If ``guardrail_payment_id``
            has no record in the audit trail.
    """
    phase2_report = _load_json(phase2_report_path)
    phase3_report = _load_json(phase3_report_path)
    phase4_report = _load_json(phase4_report_path)
    phase7_evaluation_report = _load_json(phase7_evaluation_report_path)
    results, limitations = _load_results_and_limitations_data(phase7_evaluation_report)
    guardrail_records = tuple(find_records_for_payment(audit_trail_path, guardrail_payment_id))
    return DemoData(
        seed=_CORPUS_SEED,
        corpus=CorpusData(
            n_events=int(phase4_report["routing"]["total_events"]),
            taxonomy_row_count=EXPECTED_DATA_ROW_COUNT,
            distinct_reasons_seen=int(phase4_report["routing"]["distinct_reasons_seen"]),
        ),
        root_cause=_load_root_cause_data(phase2_report),
        incident=_load_incident_data(phase3_report),
        routing=_load_routing_data(phase4_report),
        results=results,
        limitations=limitations,
        guardrail_payment_id=guardrail_payment_id,
        guardrail_records=guardrail_records,
    )
