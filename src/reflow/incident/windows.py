"""Merging per-bucket burst calls into contiguous detected incidents.

A detector (:mod:`reflow.incident.detectors`) flags individual buckets. An
incident spans several buckets, and real traffic is noisy enough that a
genuinely ongoing incident can produce one quiet bucket in the middle
(the underlying rate is elevated, not perfectly constant) without the
incident actually having ended. :func:`run_detector` bridges small gaps
between burst buckets into one incident rather than reporting several tiny
fragments, using a small, fixed, documented tolerance -- not tuned per
entity or per detector, so it cannot be a route to inflating any one
detector's apparent performance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from reflow.incident.aggregate import EntityKey, EntitySeries
from reflow.incident.detectors import BurstCall, IncidentDetector

MAX_GAP_BUCKETS: Final[int] = 1
"""At most one consecutive non-burst bucket (15 minutes, at the default
bucket width) between two burst buckets is bridged into a single incident.
Chosen as the smallest non-zero tolerance: it absorbs a single noisy quiet
bucket in the middle of an otherwise-continuous incident without merging
two genuinely separate incidents that merely happen to be close in time."""


@dataclass(frozen=True, slots=True)
class DetectedIncident:
    """One contiguous incident a detector flagged for one entity.

    Attributes:
        entity: The entity this incident was detected on. For the
            standard detectors this is a ``(method, bank, None)`` key
            (see :func:`reflow.incident.aggregate.entity_key`); for the
            ``GROUP BY reason`` baseline it is ``(method, bank, reason)``
            (see :func:`reflow.incident.aggregate.reason_scoped_entity_key`).
            Matching against ground-truth windows always compares only the
            first two elements (see
            :mod:`reflow.incident.attribution`), so both shapes can be
            evaluated uniformly.
        detector: The detector's :attr:`~reflow.incident.detectors.IncidentDetector.name`.
        start: The first bucket's start (inclusive) -- also this
            incident's detection time, since the first bucket in its span
            is, by construction, a bucket the detector actually flagged.
        end: The last bucket's end (exclusive), i.e. its start plus one
            bucket width.
        bucket_starts: Every bucket's start in ``[start, end)``, including
            any bridged non-burst bucket in the middle.
        total_count: Sum of failure counts across every bucket in
            ``bucket_starts``, including bridged buckets.
        peak_score: The highest :attr:`~reflow.incident.detectors.BurstCall.score`
            among this incident's buckets.
        event_indices: Indices (into the event sequence
            :func:`reflow.incident.aggregate.build_entity_series` was
            called with) of every event in ``bucket_starts``, including
            events in a bridged non-burst bucket.
    """

    entity: EntityKey
    detector: str
    start: datetime
    end: datetime
    bucket_starts: tuple[datetime, ...]
    total_count: int
    peak_score: float
    event_indices: tuple[int, ...]


def _finalize(
    series: EntitySeries,
    detector_name: str,
    calls: Sequence[BurstCall],
    start_idx: int,
    end_idx: int,
) -> DetectedIncident:
    """Build one :class:`DetectedIncident` from an inclusive bucket-index span.

    Args:
        series: The entity series the span was found in.
        detector_name: The detector's name.
        calls: The full per-bucket call sequence :func:`run_detector` is
            processing.
        start_idx: First bucket index in the incident (inclusive).
        end_idx: Last bucket index in the incident (inclusive).

    Returns:
        The populated :class:`DetectedIncident`.
    """
    bucket_starts = tuple(series.grid.start_of(i) for i in range(start_idx, end_idx + 1))
    total_count = sum(series.counts[start_idx : end_idx + 1])
    peak_score = max(call.score for call in calls[start_idx : end_idx + 1])
    event_indices = tuple(
        idx
        for i in range(start_idx, end_idx + 1)
        for idx in series.event_indices_by_bucket.get(i, ())
    )
    return DetectedIncident(
        entity=series.entity,
        detector=detector_name,
        start=bucket_starts[0],
        end=bucket_starts[-1] + series.grid.bucket_width,
        bucket_starts=bucket_starts,
        total_count=total_count,
        peak_score=peak_score,
        event_indices=event_indices,
    )


def run_detector(
    series: EntitySeries,
    detector: IncidentDetector,
    max_gap_buckets: int = MAX_GAP_BUCKETS,
) -> list[DetectedIncident]:
    """Run one detector on one entity series and merge bursts into incidents.

    Args:
        series: The entity series to score.
        detector: The detector to run.
        max_gap_buckets: Maximum number of consecutive non-burst buckets
            bridged between two burst buckets into one incident.

    Returns:
        Every :class:`DetectedIncident` found, in chronological order.
        Bridged non-burst buckets contribute their own counts and events
        to the surrounding incident; a trailing non-burst run that is
        never followed by another burst bucket is never included (an
        incident always starts and ends on an actual burst bucket).
    """
    calls = detector.detect(series.counts)
    n = len(calls)
    incidents: list[DetectedIncident] = []
    i = 0
    while i < n:
        if not calls[i].is_burst:
            i += 1
            continue
        start_idx = i
        last_burst_idx = i
        j = i + 1
        while j < n and (calls[j].is_burst or j - last_burst_idx <= max_gap_buckets):
            if calls[j].is_burst:
                last_burst_idx = j
            j += 1
        incidents.append(_finalize(series, detector.name, calls, start_idx, last_burst_idx))
        i = j
    return incidents
