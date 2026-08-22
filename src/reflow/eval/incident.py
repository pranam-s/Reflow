"""The Phase 3 incident-detection benchmark harness.

Runs every candidate in :mod:`reflow.incident.detectors` against the same
corpus, on the train and held-out test splits separately, and reports
whether temporal/entity burst detection recovers the correlated-outage
incidents Phase 2 established that text clustering cannot (see
``docs/design.md`` ADR-0002 and ADR-0003).

**What this harness computes, end to end:**

1. Generates one corpus (:func:`reflow.corpus.generator.generate_corpus`)
   and splits it by :attr:`~reflow.corpus.events.PaymentEvent.split`.
2. For each split, aggregates events into per-entity bucket-count series
   (:func:`reflow.incident.aggregate.build_entity_series`) and runs every
   detector (:mod:`reflow.incident.detectors`), merging bursts into
   incidents (:func:`reflow.incident.windows.run_detector`).
3. Scores each detector against ground-truth windows reconstructed from
   event labels (:func:`reflow.incident.attribution.reconstruct_true_windows`),
   producing incident-level precision/recall/F1, time-to-detect, event
   attribution accuracy, background false-positive rate, and runtime.
4. Selects a winner by test-split F1 (ties broken by the lower background
   false-positive rate -- a detector that achieves the same recall with
   fewer false alarms is preferred when the primary metric ties), then
   re-runs *that same detector's algorithm* at ``(method, bank, reason)``
   granularity (:func:`reflow.incident.aggregate.reason_scoped_entity_key`)
   as the ``GROUP BY reason`` comparison baseline's strongest form: the
   same statistical test, only a finer entity key, which is exactly what a
   naive per-reason-code monitor would be limited to. This is decided
   *after* the winner is known and is not, and could not be, chosen to
   flatter any particular outcome -- it is mechanically always "whichever
   candidate won," and the point of the comparison is the effect of
   granularity, not of the underlying statistic.
5. Measures the cross-reason claim directly against ground truth,
   independent of detection (:func:`reflow.incident.attribution.summarize_cross_reason`),
   for the whole corpus and for each split.
6. Runs a downtime-correlation demonstration
   (:func:`_run_downtime_correlation_demo`): synthetic
   :class:`~reflow.incident.downtime_api.Downtime` records are built from
   the test split's own ground-truth windows (restricted to the three
   methods Razorpay's Downtime API can express -- Card, Netbanking, UPI --
   see :mod:`reflow.incident.downtime_api`), and the winning detector's
   test-split incidents are correlated against them
   (:func:`reflow.incident.correlate.correlate_downtimes`). **This is a
   mechanism and API-coverage demonstration, not an independent accuracy
   validation**: the "declared" downtimes are derived from the same
   ground truth being detected, so of course a correctly detected
   incident on a correlatable method corroborates near-perfectly. The one
   genuine, non-fabricated finding it produces is the *coverage* gap --
   how many detected incidents are on methods (Wallet, Cardless EMI,
   Emandate) Razorpay's real Downtime API can never declare in the first
   place, which is a fact about the verified live API, not an artefact of
   this simulation.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from reflow.corpus.events import PaymentEvent
from reflow.corpus.generator import generate_corpus
from reflow.corpus.split import TEST, TRAIN
from reflow.incident.aggregate import (
    EntityKey,
    EntitySeries,
    build_entity_series,
    entity_key,
    reason_scoped_entity_key,
)
from reflow.incident.attribution import (
    CrossReasonSummary,
    DetectorEvaluation,
    TrueWindow,
    compute_reason_breakdown,
    evaluate_detector,
    reconstruct_true_windows,
    summarize_cross_reason,
)
from reflow.incident.correlate import correlate_downtimes
from reflow.incident.detectors import (
    EwmaZScoreDetector,
    FixedThresholdDetector,
    IncidentDetector,
    PoissonSurpriseDetector,
    RollingZScoreDetector,
)
from reflow.incident.downtime_api import Downtime, DowntimeMethod, DowntimeSeverity, DowntimeStatus
from reflow.incident.windows import DetectedIncident, run_detector
from reflow.taxonomy.methods import PaymentMethod

DEFAULT_SEED: Final[int] = 20260822
DEFAULT_N_EVENTS: Final[int] = 50_000

SPLITS: Final[tuple[str, ...]] = (TRAIN, TEST)

GROUPBY_REASON_LABEL_PREFIX: Final[str] = "groupby_reason+"
"""Prefix for the ``GROUP BY reason`` baseline's row label, e.g.
``"groupby_reason+poisson_surprise"`` when Poisson surprise wins."""

CORRELATABLE_METHODS: Final[frozenset[PaymentMethod]] = frozenset(
    {PaymentMethod.CARD, PaymentMethod.NETBANKING, PaymentMethod.UPI}
)
"""The payment methods Razorpay's real Downtime API can express (see
:mod:`reflow.incident.downtime_api`). Notably excludes Emandate, despite
Emandate being one of :data:`reflow.incident.aggregate.BANK_SCOPED_METHODS`
internally -- Razorpay declares no downtime at all for Emandate, Wallet,
or Cardless EMI."""

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

PROVENANCE_NOTES: Final[tuple[str, ...]] = (
    "Bucket width is fixed at 15 minutes for every detector and split -- see "
    "reflow.incident.aggregate module docstring for the justification.",
    "The GROUP BY reason baseline reruns the single detector that wins the "
    "entity-level comparison (by test-split F1) at (method, bank, reason) "
    "granularity, decided after that winner is known -- see this module's "
    "docstring for why that is the fair, not a flattering, choice.",
    "The downtime-correlation demonstration synthesises declared downtimes "
    "from this corpus's own ground-truth test-split windows; it is a "
    "mechanism/API-coverage demonstration, not an independent validation "
    "against real Razorpay declarations -- see _run_downtime_correlation_demo.",
    "Every reported window-level statistic (precision/recall/F1, time-to-detect) "
    "on the test split is computed over a small number of true windows "
    "(order 10 at the default corpus size); read its distribution, not only "
    "its point estimate.",
)


def _detectors() -> tuple[IncidentDetector, ...]:
    """Build one fresh instance of each Phase 3 detector candidate.

    Returns:
        ``(FixedThresholdDetector(), RollingZScoreDetector(),
        PoissonSurpriseDetector(), EwmaZScoreDetector())``, every one at
        its documented default hyperparameters.
    """
    return (
        FixedThresholdDetector(),
        RollingZScoreDetector(),
        PoissonSurpriseDetector(),
        EwmaZScoreDetector(),
    )


@dataclass(frozen=True, slots=True)
class TimeToDetectDistribution:
    """Summary statistics of a set of time-to-detect measurements, in minutes.

    Reported as a distribution, not only a mean, per phase brief: every
    field is ``None`` when there are zero underlying measurements (no
    ground-truth window was ever detected).

    Attributes:
        n: Number of underlying measurements.
        minimum: Smallest time-to-detect.
        p25: 25th percentile (linear interpolation between order statistics).
        median: 50th percentile.
        p75: 75th percentile.
        maximum: Largest time-to-detect.
        mean: Arithmetic mean.
    """

    n: int
    minimum: float | None
    p25: float | None
    median: float | None
    p75: float | None
    maximum: float | None
    mean: float | None


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Compute a percentile of already-sorted data via linear interpolation.

    Args:
        sorted_values: Values sorted ascending; must be non-empty.
        fraction: Desired percentile as a fraction in ``[0, 1]``.

    Returns:
        The interpolated percentile value.
    """
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def summarize_time_to_detect(values: Sequence[float]) -> TimeToDetectDistribution:
    """Summarise a collection of time-to-detect measurements.

    Args:
        values: Time-to-detect measurements, in minutes, in any order.

    Returns:
        The populated :class:`TimeToDetectDistribution`.
    """
    if not values:
        return TimeToDetectDistribution(0, None, None, None, None, None, None)
    ordered = sorted(values)
    return TimeToDetectDistribution(
        n=len(ordered),
        minimum=ordered[0],
        p25=_percentile(ordered, 0.25),
        median=_percentile(ordered, 0.5),
        p75=_percentile(ordered, 0.75),
        maximum=ordered[-1],
        mean=sum(ordered) / len(ordered),
    )


@dataclass(frozen=True, slots=True)
class DetectorReportRow:
    """One detector's full result on one split, ready for reporting.

    Attributes:
        evaluation: The underlying :class:`~reflow.incident.attribution.DetectorEvaluation`.
        time_to_detect: The time-to-detect distribution.
        n_entities: Number of distinct entities this run scored.
    """

    evaluation: DetectorEvaluation
    time_to_detect: TimeToDetectDistribution
    n_entities: int


def _run_detector_on_series(
    series_by_entity: dict[EntityKey, EntitySeries], detector: IncidentDetector
) -> tuple[list[DetectedIncident], float]:
    """Run one detector across every entity in a pre-built series map.

    Args:
        series_by_entity: Per-entity series, e.g. from
            :func:`reflow.incident.aggregate.build_entity_series`.
        detector: The detector to run.

    Returns:
        A tuple of (every detected incident, pooled across every entity;
        total wall-clock seconds spent in
        :func:`~reflow.incident.windows.run_detector` calls).
    """
    detected: list[DetectedIncident] = []
    start = time.perf_counter()
    for series in series_by_entity.values():
        detected.extend(run_detector(series, detector))
    runtime = time.perf_counter() - start
    return detected, runtime


def _select_winner(rows: Sequence[DetectorReportRow]) -> str:
    """Pick the winning detector by test-split F1.

    Args:
        rows: Every entity-level :class:`DetectorReportRow` (all splits).

    Returns:
        The name of the detector with the highest test-split
        :attr:`~reflow.incident.attribution.IncidentMatchStats.f1`, ties
        broken by the lower
        :attr:`~reflow.incident.attribution.DetectorEvaluation.background_false_positive_rate`.

    Raises:
        ValueError: If no row for the test split is present.
    """
    test_rows = [row for row in rows if row.evaluation.split == TEST]
    if not test_rows:
        raise ValueError("No test-split rows to select a winner from.")

    def sort_key(row: DetectorReportRow) -> tuple[float, float]:
        f1 = row.evaluation.match_stats.f1
        fpr = row.evaluation.background_false_positive_rate
        return (-(f1 if f1 is not None else -1.0), fpr if fpr is not None else 1.0)

    return min(test_rows, key=sort_key).evaluation.detector


def _synthetic_declared_downtimes(true_windows: Sequence[TrueWindow]) -> list[Downtime]:
    """Build synthetic declared downtimes from ground-truth windows.

    See module docstring, step 6, for why this is a mechanism/coverage
    demonstration rather than independent validation data.

    Args:
        true_windows: Ground-truth windows to derive declarations from.

    Returns:
        One :class:`~reflow.incident.downtime_api.Downtime` per window
        whose entity's method is in :data:`CORRELATABLE_METHODS`; windows
        on any other method produce no declaration at all, matching
        Razorpay's real API coverage.
    """
    declared: list[Downtime] = []
    for window in true_windows:
        method, bank, _ = window.entity
        if method not in CORRELATABLE_METHODS:
            continue
        duration = window.end - window.start
        if duration >= timedelta(hours=2):
            severity = DowntimeSeverity.HIGH
        elif duration >= timedelta(hours=1):
            severity = DowntimeSeverity.MEDIUM
        else:
            severity = DowntimeSeverity.LOW
        begin = window.start.replace(tzinfo=UTC)
        end = window.end.replace(tzinfo=UTC)
        declared.append(
            Downtime(
                id=f"down_{window.window_id}",
                method=DowntimeMethod(method.value),
                begin=begin,
                end=end,
                status=DowntimeStatus.RESOLVED,
                scheduled=False,
                severity=severity,
                instrument=({"bank": bank} if bank is not None else {}),
                created_at=begin,
                updated_at=end,
            )
        )
    return declared


@dataclass(frozen=True, slots=True)
class DowntimeCorrelationDemo:
    """Result of correlating detected incidents against declared downtimes.

    Attributes:
        n_declared_downtimes: Synthetic declared downtimes built.
        n_detected_incidents: Winning detector's test-split incidents
            evaluated.
        n_correlatable_incidents: Of those, how many are on a method in
            :data:`CORRELATABLE_METHODS` (i.e. could, in principle, be
            corroborated at all).
        n_never_correlatable: Detected incidents on a method Razorpay's
            real Downtime API cannot express (Wallet, Cardless EMI,
            Emandate).
        n_corroborated: Detected incidents matched to a declared downtime.
        corroboration_rate_among_correlatable: ``n_corroborated /
            n_correlatable_incidents``, or ``None`` if there were none.
    """

    n_declared_downtimes: int
    n_detected_incidents: int
    n_correlatable_incidents: int
    n_never_correlatable: int
    n_corroborated: int
    corroboration_rate_among_correlatable: float | None


def _run_downtime_correlation_demo(
    test_events: Sequence[PaymentEvent], winner: IncidentDetector
) -> DowntimeCorrelationDemo:
    """Run the downtime-correlation demonstration on the test split.

    Args:
        test_events: The test split's events.
        winner: The winning detector.

    Returns:
        The populated :class:`DowntimeCorrelationDemo`.
    """
    true_windows = reconstruct_true_windows(test_events)
    declared = _synthetic_declared_downtimes(true_windows)
    series = build_entity_series(test_events, key_fn=entity_key)
    detected, _runtime = _run_detector_on_series(series, winner)
    correlations = correlate_downtimes(detected, declared)

    n_correlatable = sum(
        1 for correlation in correlations if correlation.detected.entity[0] in CORRELATABLE_METHODS
    )
    n_corroborated = sum(
        1 for correlation in correlations if correlation.matched_downtime is not None
    )
    rate = n_corroborated / n_correlatable if n_correlatable else None
    return DowntimeCorrelationDemo(
        n_declared_downtimes=len(declared),
        n_detected_incidents=len(detected),
        n_correlatable_incidents=n_correlatable,
        n_never_correlatable=len(correlations) - n_correlatable,
        n_corroborated=n_corroborated,
        corroboration_rate_among_correlatable=rate,
    )


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to attribute and reproduce a benchmark run.

    Attributes:
        generated_at: UTC ISO-8601 timestamp of report generation.
        seed: The corpus seed used.
        n_events: The corpus size used.
        splits: The splits evaluated.
        command: The command that produced this report.
        library_versions: Installed version of every library whose
            behaviour materially affects the result.
        notes: Free-text disclosures (see :data:`PROVENANCE_NOTES`).
    """

    generated_at: str
    seed: int
    n_events: int
    splits: tuple[str, ...]
    command: str
    library_versions: dict[str, str]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IncidentReport:
    """The complete Phase 3 incident-detection benchmark result.

    Attributes:
        provenance: See :class:`Provenance`.
        detector_rows: One :class:`DetectorReportRow` per (detector, split).
        groupby_reason_rows: One :class:`DetectorReportRow` per split for
            the ``GROUP BY reason`` baseline (the winning detector rerun at
            reason-scoped granularity).
        winner: The winning detector's name.
        cross_reason_by_scope: Ground-truth cross-reason summaries, keyed
            by ``"all"``, ``"train"``, ``"test"``.
        downtime_correlation_demo: See :class:`DowntimeCorrelationDemo`.
    """

    provenance: Provenance
    detector_rows: tuple[DetectorReportRow, ...]
    groupby_reason_rows: tuple[DetectorReportRow, ...]
    winner: str
    cross_reason_by_scope: dict[str, CrossReasonSummary]
    downtime_correlation_demo: DowntimeCorrelationDemo


def run_benchmark(seed: int = DEFAULT_SEED, n_events: int = DEFAULT_N_EVENTS) -> IncidentReport:
    """Run the full Phase 3 incident-detection benchmark.

    Args:
        seed: Corpus seed.
        n_events: Corpus size.

    Returns:
        The complete :class:`IncidentReport`.
    """
    events = list(generate_corpus(seed=seed, n_events=n_events))
    events_by_split = {
        split: [event for event in events if event.split == split] for split in SPLITS
    }

    detector_rows: list[DetectorReportRow] = []
    series_by_split: dict[str, dict[EntityKey, EntitySeries]] = {}
    true_windows_by_split: dict[str, list[TrueWindow]] = {}
    for split in SPLITS:
        split_events = events_by_split[split]
        series = build_entity_series(split_events, key_fn=entity_key)
        series_by_split[split] = series
        true_windows = reconstruct_true_windows(split_events)
        true_windows_by_split[split] = true_windows
        for detector in _detectors():
            detected, runtime = _run_detector_on_series(series, detector)
            evaluation = evaluate_detector(
                detector.name, split, split_events, true_windows, detected, runtime
            )
            detector_rows.append(
                DetectorReportRow(
                    evaluation=evaluation,
                    time_to_detect=summarize_time_to_detect(
                        evaluation.match_stats.time_to_detect_minutes
                    ),
                    n_entities=len(series),
                )
            )

    winner_name = _select_winner(detector_rows)
    winner = next(detector for detector in _detectors() if detector.name == winner_name)

    groupby_rows: list[DetectorReportRow] = []
    for split in SPLITS:
        split_events = events_by_split[split]
        reason_series = build_entity_series(split_events, key_fn=reason_scoped_entity_key)
        detected, runtime = _run_detector_on_series(reason_series, winner)
        label = f"{GROUPBY_REASON_LABEL_PREFIX}{winner_name}"
        evaluation = evaluate_detector(
            label, split, split_events, true_windows_by_split[split], detected, runtime
        )
        groupby_rows.append(
            DetectorReportRow(
                evaluation=evaluation,
                time_to_detect=summarize_time_to_detect(
                    evaluation.match_stats.time_to_detect_minutes
                ),
                n_entities=len(reason_series),
            )
        )

    cross_reason_by_scope = {
        "all": summarize_cross_reason(
            [compute_reason_breakdown(window) for window in reconstruct_true_windows(events)]
        ),
        TRAIN: summarize_cross_reason(
            [compute_reason_breakdown(window) for window in true_windows_by_split[TRAIN]]
        ),
        TEST: summarize_cross_reason(
            [compute_reason_breakdown(window) for window in true_windows_by_split[TEST]]
        ),
    }

    downtime_demo = _run_downtime_correlation_demo(events_by_split[TEST], winner)

    provenance = Provenance(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seed=seed,
        n_events=n_events,
        splits=SPLITS,
        command="uv run python -m reflow.eval.incident",
        library_versions=_library_versions(),
        notes=PROVENANCE_NOTES,
    )
    return IncidentReport(
        provenance=provenance,
        detector_rows=tuple(detector_rows),
        groupby_reason_rows=tuple(groupby_rows),
        winner=winner_name,
        cross_reason_by_scope=cross_reason_by_scope,
        downtime_correlation_demo=downtime_demo,
    )


def _library_versions() -> dict[str, str]:
    """Look up the installed version of every result-relevant library.

    Returns:
        A mapping from distribution name to installed version string.
    """
    versions = {"pydantic": importlib.metadata.version("pydantic")}
    versions["python"] = platform.python_version()
    versions["reflow"] = importlib.metadata.version("reflow")
    return versions


def _match_stats_to_dict(row: DetectorReportRow) -> dict[str, object]:
    """Serialise one :class:`DetectorReportRow` to a JSON-safe dict.

    Args:
        row: The row to serialise.

    Returns:
        A nested plain-value dict.
    """
    stats = row.evaluation.match_stats
    return {
        "detector": row.evaluation.detector,
        "split": row.evaluation.split,
        "n_entities": row.n_entities,
        "n_true_windows": stats.n_true_windows,
        "n_detected_incidents": stats.n_detected_incidents,
        "n_true_positive_windows": stats.n_true_positive_windows,
        "n_true_positive_incidents": stats.n_true_positive_incidents,
        "precision": stats.precision,
        "recall": stats.recall,
        "f1": stats.f1,
        "event_attribution_accuracy": row.evaluation.event_attribution_accuracy,
        "background_false_positive_rate": row.evaluation.background_false_positive_rate,
        "runtime_seconds": row.evaluation.runtime_seconds,
        "time_to_detect_minutes": asdict(row.time_to_detect),
        "fragmentation": asdict(row.evaluation.fragmentation),
    }


def to_json_dict(report: IncidentReport) -> dict[str, object]:
    """Serialise an :class:`IncidentReport` to a JSON-safe nested dict.

    Args:
        report: The report to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``.
    """
    return {
        "provenance": asdict(report.provenance),
        "detector_rows": [_match_stats_to_dict(row) for row in report.detector_rows],
        "groupby_reason_rows": [_match_stats_to_dict(row) for row in report.groupby_reason_rows],
        "winner": report.winner,
        "cross_reason_by_scope": {
            scope: asdict(summary) for scope, summary in report.cross_reason_by_scope.items()
        },
        "downtime_correlation_demo": asdict(report.downtime_correlation_demo),
    }


def _format_optional(value: float | None, digits: int = 3) -> str:
    """Format an optional float for a markdown table cell.

    Args:
        value: The value to format, or ``None``.
        digits: Number of decimal places.

    Returns:
        ``"n/a"`` if ``value`` is ``None``, otherwise ``value`` formatted
        to ``digits`` decimal places.
    """
    return "n/a" if value is None else f"{value:.{digits}f}"


def _row_to_markdown_line(row: DetectorReportRow) -> str:
    """Render one :class:`DetectorReportRow` as a markdown table row.

    Args:
        row: The row to render.

    Returns:
        A single ``| ... |`` markdown table line.
    """
    stats = row.evaluation.match_stats
    ttd = row.time_to_detect
    frag = row.evaluation.fragmentation
    return (
        f"| {row.evaluation.detector} | {row.evaluation.split} | {row.n_entities} | "
        f"{stats.n_true_windows} | {stats.n_detected_incidents} | "
        f"{_format_optional(stats.precision)} | {_format_optional(stats.recall)} | "
        f"{_format_optional(stats.f1)} | "
        f"{_format_optional(row.evaluation.event_attribution_accuracy)} | "
        f"{_format_optional(row.evaluation.background_false_positive_rate)} | "
        f"{_format_optional(ttd.median)} | {_format_optional(ttd.mean)} | "
        f"{_format_optional(frag.mean_fragments_per_window, digits=2)} | "
        f"{_format_optional(frag.fraction_windows_fragmented)} | "
        f"{row.evaluation.runtime_seconds:.4f} |"
    )


def to_markdown(report: IncidentReport) -> str:
    """Render a human-readable markdown summary of an :class:`IncidentReport`.

    Args:
        report: The report to render.

    Returns:
        A markdown document: a provenance header, the full detector
        results table, the ``GROUP BY reason`` baseline table, the
        cross-reason summary, and the downtime-correlation demonstration.
    """
    lines: list[str] = []
    provenance = report.provenance
    lines.append("# Phase 3 incident-detection benchmark results")
    lines.append("")
    lines.append(f"- Generated at: {provenance.generated_at}")
    lines.append(f"- Command: `{provenance.command}`")
    lines.append(f"- Seed: {provenance.seed}")
    lines.append(f"- Corpus size: {provenance.n_events}")
    lines.append(f"- Splits: {list(provenance.splits)}")
    version_items = sorted(provenance.library_versions.items())
    versions_text = ", ".join(f"{name}={version}" for name, version in version_items)
    lines.append(f"- Library versions: {versions_text}")
    for note in provenance.notes:
        lines.append(f"- Note: {note}")
    lines.append(f"- Winner (by test-split F1): **{report.winner}**")
    lines.append("")

    header = (
        "| detector | split | n_entities | n_true_windows | n_detected | precision | recall | f1 | "
        "event_attr_acc | background_fpr | ttd_median_min | ttd_mean_min | "
        "mean_fragments_per_window | fraction_windows_fragmented | runtime_s |"
    )
    lines.append("## Detector results")
    lines.append("")
    lines.append(header)
    lines.append("|" + " --- |" * 15)
    for row in report.detector_rows:
        lines.append(_row_to_markdown_line(row))
    lines.append("")

    lines.append("## GROUP BY reason baseline (winning detector, reason-scoped granularity)")
    lines.append("")
    lines.append(header)
    lines.append("|" + " --- |" * 15)
    for row in report.groupby_reason_rows:
        lines.append(_row_to_markdown_line(row))
    lines.append("")

    lines.append("## Cross-reason claim (ground truth, detector-independent)")
    lines.append("")
    lines.append(
        "| scope | n_windows | n_multi_reason | multi_reason_fraction | "
        "mean_invisible_fraction | median_invisible_fraction | overall_invisible_fraction |"
    )
    lines.append("|" + " --- |" * 7)
    for scope, summary in report.cross_reason_by_scope.items():
        lines.append(
            f"| {scope} | {summary.n_windows} | {summary.n_multi_reason_windows} | "
            f"{summary.multi_reason_fraction:.3f} | "
            f"{_format_optional(summary.mean_invisible_event_fraction)} | "
            f"{_format_optional(summary.median_invisible_event_fraction)} | "
            f"{_format_optional(summary.overall_invisible_event_fraction)} |"
        )
    lines.append("")

    demo = report.downtime_correlation_demo
    lines.append("## Downtime-correlation demonstration (test split, winning detector)")
    lines.append("")
    lines.append(
        "Synthetic declared downtimes are derived from this corpus's own ground-truth "
        "test-split windows -- a mechanism/API-coverage demonstration, not an "
        "independent validation. See this module's docstring."
    )
    lines.append("")
    lines.append(f"- Declared downtimes synthesised: {demo.n_declared_downtimes}")
    lines.append(f"- Detected incidents evaluated: {demo.n_detected_incidents}")
    lines.append(f"- Detected incidents on a correlatable method: {demo.n_correlatable_incidents}")
    lines.append(
        f"- Detected incidents Razorpay's Downtime API cannot ever declare "
        f"(Wallet/Cardless EMI/Emandate): {demo.n_never_correlatable}"
    )
    lines.append(f"- Corroborated by a declared downtime: {demo.n_corroborated}")
    lines.append(
        f"- Corroboration rate among correlatable incidents: "
        f"{_format_optional(demo.corroboration_rate_among_correlatable)}"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:  # pragma: no cover
    """Run the full benchmark and write JSON + markdown reports.

    CLI entry point: argument parsing and file writing are glue code, not
    core logic, so this function is excluded from the coverage floor per
    :mod:`CLAUDE.md`'s CLI-glue carve-out. Writes
    ``docs/reports/phase3_incident_detection.json`` and
    ``docs/reports/phase3_incident_detection.md``.
    """
    parser = argparse.ArgumentParser(description="Run the Phase 3 incident-detection benchmark.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-events", type=int, default=DEFAULT_N_EVENTS)
    parser.add_argument("--output-dir", type=Path, default=_REPO_ROOT / "docs" / "reports")
    args = parser.parse_args()

    report = run_benchmark(seed=args.seed, n_events=args.n_events)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase3_incident_detection.json").write_text(
        json.dumps(to_json_dict(report), indent=2), encoding="utf-8"
    )
    (args.output_dir / "phase3_incident_detection.md").write_text(
        to_markdown(report), encoding="utf-8"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
