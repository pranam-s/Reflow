"""Attributing events to incidents, and measuring the cross-reason claim.

This module answers the two questions Phase 3 exists to answer:

1. **Detection quality.** Given a detector's :class:`~reflow.incident.windows.DetectedIncident`
   list, how many ground-truth downtime windows did it find
   (:func:`evaluate_incidents`), how accurately are individual events
   attributed to the right incident (:func:`event_attribution_accuracy`),
   and how often does it cry wolf on ordinary background traffic
   (:func:`background_false_positive_rate`)?
2. **The cross-reason claim.** :func:`summarize_cross_reason` measures,
   directly against ground truth and independent of any detector, how many
   incidents span more than one reason code and what fraction of their
   events a ``GROUP BY reason`` view -- "the biggest reason-code bucket in
   a time window," given its strongest form -- would never see as
   belonging to the same cause.

**Why ground-truth windows are reconstructed from events, not read from
``reflow.corpus.downtime.DowntimeWindow``.** ``src/reflow/corpus/`` is
frozen, and :func:`reflow.corpus.generator.generate_corpus` -- deliberately
-- exposes only the event stream, never the internal
:class:`~reflow.corpus.downtime.DowntimeWindow` objects used to schedule
it. :func:`reconstruct_true_windows` rebuilds each window's *observed*
footprint (the span and entity of its own member events, via
``PaymentEvent.downtime_window_id``) instead. This is not a workaround: it
is also the only view of a "window" any real downstream consumer -- this
module included, and a production incident-detection system in general --
would ever actually have. Nobody downstream observes a
``DowntimeWindow``'s internal random start/end draw directly; they observe
the events it produced.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from reflow.corpus.events import PaymentEvent
from reflow.incident.aggregate import EntityKey, entity_key
from reflow.incident.windows import DetectedIncident

_EPSILON: timedelta = timedelta(microseconds=1)
"""Widens a reconstructed window's exclusive upper bound past its last
member event's exact timestamp, so the interval ``[start, end)`` genuinely
contains every member event rather than excluding the very last one."""


@dataclass(frozen=True, slots=True)
class TrueWindow:
    """One ground-truth downtime window, reconstructed from its member events.

    Attributes:
        window_id: The window's :attr:`~reflow.corpus.events.PaymentEvent.downtime_window_id`.
        entity: The ``(method, bank, None)`` entity every member event
            shares (see :func:`reflow.incident.aggregate.entity_key`).
        start: The earliest member event's timestamp.
        end: The latest member event's timestamp, plus a 1-microsecond
            epsilon so ``[start, end)`` contains every member event.
        event_indices: Indices, into the event sequence
            :func:`reconstruct_true_windows` was called with, of every
            member event.
        reason_counts: Count of ``error_reason`` values among member
            events.
    """

    window_id: str
    entity: EntityKey
    start: datetime
    end: datetime
    event_indices: tuple[int, ...]
    reason_counts: Mapping[str, int]


def reconstruct_true_windows(events: Sequence[PaymentEvent]) -> list[TrueWindow]:
    """Rebuild every ground-truth downtime window from event-level labels.

    Args:
        events: The events to scan. Only those with a non-``None``
            ``downtime_window_id`` contribute.

    Returns:
        One :class:`TrueWindow` per distinct ``downtime_window_id``, in no
        particular order.

    Raises:
        ValueError: If any window's member events do not share a single
            :func:`~reflow.incident.aggregate.entity_key` -- this would
            mean a downtime window was generated spanning more than one
            entity, which :mod:`reflow.corpus.downtime` never does; it
            would indicate either a corpus change this module has not been
            updated for, or a bug in :func:`~reflow.incident.aggregate.entity_key`'s
            method/bank-scoping rule.
    """
    indices_by_window: dict[str, list[int]] = defaultdict(list)
    for idx, event in enumerate(events):
        if event.downtime_window_id is not None:
            indices_by_window[event.downtime_window_id].append(idx)

    windows: list[TrueWindow] = []
    for window_id, indices in indices_by_window.items():
        members = [events[i] for i in indices]
        entities = {entity_key(event) for event in members}
        if len(entities) != 1:
            raise ValueError(
                f"Downtime window {window_id!r} spans more than one entity: {entities!r}."
            )
        (entity,) = entities
        timestamps = [event.created_at for event in members]
        reason_counts = Counter(event.error_reason for event in members)
        windows.append(
            TrueWindow(
                window_id=window_id,
                entity=entity,
                start=min(timestamps),
                end=max(timestamps) + _EPSILON,
                event_indices=tuple(indices),
                reason_counts=dict(reason_counts),
            )
        )
    return windows


@dataclass(frozen=True, slots=True)
class WindowReasonBreakdown:
    """How one ground-truth window's events split across reason codes.

    Attributes:
        window_id: The window's id.
        entity: The window's entity.
        n_events: Total member events.
        n_distinct_reasons: Number of distinct ``error_reason`` values
            among member events.
        reason_counts: Count of ``error_reason`` values among member
            events.
        majority_reason: The single most common reason code.
        majority_reason_share: ``count(majority_reason) / n_events`` --
            the fraction of this window's events a ``GROUP BY reason``
            view, taking only its single biggest reason-code bucket as
            "the incident," would actually see.
    """

    window_id: str
    entity: EntityKey
    n_events: int
    n_distinct_reasons: int
    reason_counts: Mapping[str, int]
    majority_reason: str
    majority_reason_share: float


def compute_reason_breakdown(window: TrueWindow) -> WindowReasonBreakdown:
    """Compute one window's reason-code breakdown.

    Args:
        window: The window to summarise.

    Returns:
        The populated :class:`WindowReasonBreakdown`.
    """
    total = sum(window.reason_counts.values())
    majority_reason, majority_count = max(window.reason_counts.items(), key=lambda kv: kv[1])
    return WindowReasonBreakdown(
        window_id=window.window_id,
        entity=window.entity,
        n_events=total,
        n_distinct_reasons=len(window.reason_counts),
        reason_counts=dict(window.reason_counts),
        majority_reason=majority_reason,
        majority_reason_share=majority_count / total,
    )


@dataclass(frozen=True, slots=True)
class CrossReasonSummary:
    """The headline cross-reason measurement, over every ground-truth window.

    Attributes:
        n_windows: Total ground-truth windows.
        n_multi_reason_windows: Windows spanning more than one reason code.
        multi_reason_fraction: ``n_multi_reason_windows / n_windows``.
        invisible_event_fractions: Per multi-reason window,
            ``1 - majority_reason_share`` -- the fraction of that window's
            events a ``GROUP BY reason`` view would not attribute to its
            single largest reason-code bucket.
        mean_invisible_event_fraction: Mean of
            :attr:`invisible_event_fractions`, or ``None`` if there are no
            multi-reason windows.
        median_invisible_event_fraction: Median of
            :attr:`invisible_event_fractions`, or ``None`` if there are no
            multi-reason windows.
        total_events_in_multi_reason_windows: Total member events across
            every multi-reason window.
        total_invisible_events: Total events, across every multi-reason
            window, not belonging to that window's own majority reason.
        overall_invisible_event_fraction: ``total_invisible_events /
            total_events_in_multi_reason_windows``, or ``None`` if there
            are no multi-reason windows. This is the pooled, event-weighted
            version of :attr:`mean_invisible_event_fraction` -- reported
            alongside it since a handful of large windows could otherwise
            dominate or be diluted by many small ones under a plain
            per-window average.
    """

    n_windows: int
    n_multi_reason_windows: int
    multi_reason_fraction: float
    invisible_event_fractions: tuple[float, ...]
    mean_invisible_event_fraction: float | None
    median_invisible_event_fraction: float | None
    total_events_in_multi_reason_windows: int
    total_invisible_events: int
    overall_invisible_event_fraction: float | None


def summarize_cross_reason(breakdowns: Sequence[WindowReasonBreakdown]) -> CrossReasonSummary:
    """Compute the cross-reason summary over every window's breakdown.

    Args:
        breakdowns: One :class:`WindowReasonBreakdown` per ground-truth
            window, e.g. ``[compute_reason_breakdown(w) for w in
            reconstruct_true_windows(events)]``.

    Returns:
        The populated :class:`CrossReasonSummary`.
    """
    n_windows = len(breakdowns)
    multi = [breakdown for breakdown in breakdowns if breakdown.n_distinct_reasons > 1]
    invisible_fractions = tuple(1.0 - breakdown.majority_reason_share for breakdown in multi)
    total_events = sum(breakdown.n_events for breakdown in multi)
    total_invisible = sum(
        breakdown.n_events - breakdown.reason_counts[breakdown.majority_reason]
        for breakdown in multi
    )

    mean_fraction: float | None = None
    median_fraction: float | None = None
    overall_fraction: float | None = None
    if invisible_fractions:
        sorted_fractions = sorted(invisible_fractions)
        mid = len(sorted_fractions) // 2
        median_fraction = (
            sorted_fractions[mid]
            if len(sorted_fractions) % 2
            else (sorted_fractions[mid - 1] + sorted_fractions[mid]) / 2
        )
        mean_fraction = sum(invisible_fractions) / len(invisible_fractions)
    if total_events:
        overall_fraction = total_invisible / total_events

    return CrossReasonSummary(
        n_windows=n_windows,
        n_multi_reason_windows=len(multi),
        multi_reason_fraction=(len(multi) / n_windows if n_windows else 0.0),
        invisible_event_fractions=invisible_fractions,
        mean_invisible_event_fraction=mean_fraction,
        median_invisible_event_fraction=median_fraction,
        total_events_in_multi_reason_windows=total_events,
        total_invisible_events=total_invisible,
        overall_invisible_event_fraction=overall_fraction,
    )


def _same_scope(entity_a: EntityKey, entity_b: EntityKey) -> bool:
    """Whether two entities share the same ``(method, bank)`` prefix.

    Ignores the third (reason) component of :data:`~reflow.incident.aggregate.EntityKey`
    entirely, so a ``GROUP BY reason`` baseline's finer-grained detected
    incidents (see :func:`reflow.incident.aggregate.reason_scoped_entity_key`)
    can be matched against a :class:`TrueWindow`'s coarser
    ``(method, bank, None)`` entity on equal footing.

    Args:
        entity_a: The first entity.
        entity_b: The second entity.

    Returns:
        ``True`` if ``entity_a`` and ``entity_b`` share the same first two
        elements.
    """
    return entity_a[0] == entity_b[0] and entity_a[1] == entity_b[1]


def _overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    """Whether two half-open intervals ``[start, end)`` overlap.

    Args:
        start_a: First interval's inclusive start.
        end_a: First interval's exclusive end.
        start_b: Second interval's inclusive start.
        end_b: Second interval's exclusive end.

    Returns:
        ``True`` if the intervals share any instant.
    """
    return start_a < end_b and start_b < end_a


@dataclass(frozen=True, slots=True)
class IncidentMatchStats:
    """Incident-level detection quality against ground-truth windows.

    A ground-truth window is a true positive if at least one detected
    incident on the same ``(method, bank)`` scope overlaps it in time. A
    detected incident is a true positive if it overlaps at least one
    ground-truth window on the same scope. This is a standard
    "range-based" definition for burst/anomaly detection: it does not
    require a strict one-to-one pairing (one window can be confirmed by
    several overlapping detections; one long detection can confirm several
    nearby windows), which is the right level of strictness for burst
    detection, where a slightly-too-early or slightly-too-late detection
    boundary is a timing question (:attr:`time_to_detect_minutes`), not a
    correctness question.

    Attributes:
        n_true_windows: Total ground-truth windows evaluated.
        n_detected_incidents: Total detected incidents evaluated.
        n_true_positive_windows: Ground-truth windows with at least one
            overlapping detected incident.
        n_true_positive_incidents: Detected incidents overlapping at least
            one ground-truth window.
        precision: ``n_true_positive_incidents / n_detected_incidents``, or
            ``None`` if nothing was detected.
        recall: ``n_true_positive_windows / n_true_windows``, or ``None``
            if there were no ground-truth windows.
        f1: Harmonic mean of :attr:`precision` and :attr:`recall`, or
            ``None`` if either is ``None`` or both are ``0``.
        time_to_detect_minutes: For every true-positive window, the delay
            in minutes between the window's reconstructed start and the
            earliest overlapping detected incident's start, floored at
            ``0`` (a detected incident's bucket can start fractionally
            before a window's first *event* timestamp purely from bucket
            alignment -- see :mod:`reflow.incident.aggregate` -- which is a
            measurement-resolution artefact, not genuine prediction of the
            future).
    """

    n_true_windows: int
    n_detected_incidents: int
    n_true_positive_windows: int
    n_true_positive_incidents: int
    precision: float | None
    recall: float | None
    f1: float | None
    time_to_detect_minutes: tuple[float, ...]


def evaluate_incidents(
    true_windows: Sequence[TrueWindow],
    detected: Sequence[DetectedIncident],
) -> IncidentMatchStats:
    """Match detected incidents against ground-truth windows.

    Args:
        true_windows: Ground-truth windows, e.g. from
            :func:`reconstruct_true_windows`.
        detected: A detector's incidents, e.g. from
            :func:`reflow.incident.windows.run_detector`, pooled across
            every entity.

    Returns:
        The populated :class:`IncidentMatchStats`.
    """
    n_true = len(true_windows)
    n_detected = len(detected)

    time_to_detect: list[float] = []
    n_tp_windows = 0
    for window in true_windows:
        overlapping = [
            candidate
            for candidate in detected
            if _same_scope(window.entity, candidate.entity)
            and _overlaps(window.start, window.end, candidate.start, candidate.end)
        ]
        if overlapping:
            n_tp_windows += 1
            earliest = min(overlapping, key=lambda candidate: candidate.start)
            delay_minutes = (earliest.start - window.start).total_seconds() / 60.0
            time_to_detect.append(max(0.0, delay_minutes))

    n_tp_incidents = 0
    for candidate in detected:
        if any(
            _same_scope(window.entity, candidate.entity)
            and _overlaps(window.start, window.end, candidate.start, candidate.end)
            for window in true_windows
        ):
            n_tp_incidents += 1

    precision = n_tp_incidents / n_detected if n_detected else None
    recall = n_tp_windows / n_true if n_true else None
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)

    return IncidentMatchStats(
        n_true_windows=n_true,
        n_detected_incidents=n_detected,
        n_true_positive_windows=n_tp_windows,
        n_true_positive_incidents=n_tp_incidents,
        precision=precision,
        recall=recall,
        f1=f1,
        time_to_detect_minutes=tuple(time_to_detect),
    )


@dataclass(frozen=True, slots=True)
class FragmentationStats:
    """How many separate detected incidents cover each ground-truth window.

    This is the concrete, countable form of "``GROUP BY reason`` shatters
    one acute incident into several chronic-looking buckets": range-based
    :class:`IncidentMatchStats` treats a window as "detected" the moment
    *any* overlapping detection exists, which is the right question for
    recall but hides how many *separate* alerts an on-call engineer would
    actually have to manually correlate back into one incident. Comparing
    this statistic between the entity-level winner (which should show
    close to one fragment per window, since it aggregates every reason
    together before detecting) and the ``GROUP BY reason`` baseline (which
    cannot aggregate across reasons by construction) is the operational
    cost :func:`event_attribution_accuracy` alone does not fully capture.

    Attributes:
        n_windows: Total ground-truth windows.
        fragments_per_window: Per window, the number of distinct detected
            incidents overlapping it (on the same entity scope), in the
            same order as the ``true_windows`` argument.
        mean_fragments_per_window: Mean of :attr:`fragments_per_window`, or
            ``None`` if there are no windows.
        median_fragments_per_window: Median of :attr:`fragments_per_window`,
            or ``None`` if there are no windows.
        max_fragments_per_window: Maximum of :attr:`fragments_per_window`,
            or ``None`` if there are no windows.
        fraction_windows_fragmented: Fraction of windows covered by more
            than one detected incident, or ``None`` if there are no
            windows.
    """

    n_windows: int
    fragments_per_window: tuple[int, ...]
    mean_fragments_per_window: float | None
    median_fragments_per_window: float | None
    max_fragments_per_window: int | None
    fraction_windows_fragmented: float | None


def compute_fragmentation(
    true_windows: Sequence[TrueWindow],
    detected: Sequence[DetectedIncident],
) -> FragmentationStats:
    """Count how many separate detected incidents cover each window.

    Args:
        true_windows: Ground-truth windows.
        detected: A detector's incidents, pooled across every entity.

    Returns:
        The populated :class:`FragmentationStats`.
    """
    fragments_per_window = tuple(
        sum(
            1
            for candidate in detected
            if _same_scope(window.entity, candidate.entity)
            and _overlaps(window.start, window.end, candidate.start, candidate.end)
        )
        for window in true_windows
    )
    n_windows = len(fragments_per_window)
    if n_windows == 0:
        return FragmentationStats(0, (), None, None, None, None)

    ordered = sorted(fragments_per_window)
    mid = n_windows // 2
    median = float(ordered[mid]) if n_windows % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    fragmented = sum(1 for count in fragments_per_window if count > 1)
    return FragmentationStats(
        n_windows=n_windows,
        fragments_per_window=fragments_per_window,
        mean_fragments_per_window=sum(fragments_per_window) / n_windows,
        median_fragments_per_window=median,
        max_fragments_per_window=max(fragments_per_window),
        fraction_windows_fragmented=fragmented / n_windows,
    )


def event_attribution_accuracy(
    true_windows: Sequence[TrueWindow],
    detected: Sequence[DetectedIncident],
) -> float | None:
    """Fraction of true-incident events correctly attributed to a detection.

    Args:
        true_windows: Ground-truth windows.
        detected: A detector's incidents, pooled across every entity.

    Returns:
        The fraction of every ground-truth window's member events that
        fall within some detected incident's ``event_indices``, or
        ``None`` if there are no ground-truth member events at all.
    """
    true_event_indices = {idx for window in true_windows for idx in window.event_indices}
    if not true_event_indices:
        return None
    detected_event_indices = {idx for incident in detected for idx in incident.event_indices}
    covered = true_event_indices & detected_event_indices
    return len(covered) / len(true_event_indices)


def background_false_positive_rate(
    events: Sequence[PaymentEvent],
    detected: Sequence[DetectedIncident],
) -> float | None:
    """Fraction of background events incorrectly swept into a detection.

    "Background" means an event whose ``downtime_window_id`` is ``None``
    -- an ordinary, uncorrelated failure with no incident to belong to.

    Args:
        events: The full event sequence detection was run over (the same
            sequence, in the same order, passed to
            :func:`reflow.incident.aggregate.build_entity_series`).
        detected: A detector's incidents, pooled across every entity.

    Returns:
        The fraction of background events falling within some detected
        incident's ``event_indices``, or ``None`` if there is no
        background traffic at all.
    """
    background_indices = {
        idx for idx, event in enumerate(events) if event.downtime_window_id is None
    }
    if not background_indices:
        return None
    detected_event_indices = {idx for incident in detected for idx in incident.event_indices}
    false_positive = background_indices & detected_event_indices
    return len(false_positive) / len(background_indices)


@dataclass(frozen=True, slots=True)
class DetectorEvaluation:
    """One detector's full evaluation on one split.

    Attributes:
        detector: The detector's name.
        split: ``"train"`` or ``"test"`` (see
            :mod:`reflow.corpus.split`), or ``"all"`` for an unsplit run.
        match_stats: Incident-level precision/recall/F1 and time-to-detect
            (see :class:`IncidentMatchStats`).
        fragmentation: How many separate detected incidents cover each
            window (see :class:`FragmentationStats`).
        event_attribution_accuracy: See :func:`event_attribution_accuracy`.
        background_false_positive_rate: See :func:`background_false_positive_rate`.
        runtime_seconds: Wall-clock time of every
            :meth:`~reflow.incident.detectors.IncidentDetector.detect` call
            this evaluation required, summed across every entity.
    """

    detector: str
    split: str
    match_stats: IncidentMatchStats
    fragmentation: FragmentationStats
    event_attribution_accuracy: float | None
    background_false_positive_rate: float | None
    runtime_seconds: float


def evaluate_detector(
    detector_name: str,
    split: str,
    events: Sequence[PaymentEvent],
    true_windows: Sequence[TrueWindow],
    detected: Sequence[DetectedIncident],
    runtime_seconds: float,
) -> DetectorEvaluation:
    """Assemble one detector's full :class:`DetectorEvaluation`.

    Args:
        detector_name: The detector's name.
        split: The split this evaluation covers.
        events: The full event sequence detection was run over.
        true_windows: Ground-truth windows for this split.
        detected: This detector's incidents for this split, pooled across
            every entity.
        runtime_seconds: Total wall-clock ``detect()`` time for this
            detector on this split.

    Returns:
        The populated :class:`DetectorEvaluation`.
    """
    return DetectorEvaluation(
        detector=detector_name,
        split=split,
        match_stats=evaluate_incidents(true_windows, detected),
        fragmentation=compute_fragmentation(true_windows, detected),
        event_attribution_accuracy=event_attribution_accuracy(true_windows, detected),
        background_false_positive_rate=background_false_positive_rate(events, detected),
        runtime_seconds=runtime_seconds,
    )
