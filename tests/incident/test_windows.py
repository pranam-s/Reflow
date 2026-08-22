"""Tests for reflow.incident.windows."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from reflow.incident.aggregate import BucketGrid, EntitySeries
from reflow.incident.detectors import BurstCall
from reflow.incident.windows import run_detector
from reflow.taxonomy.methods import PaymentMethod

_ORIGIN = datetime(2026, 1, 1)
_WIDTH = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class _StubDetector:
    calls: list[BurstCall]
    name: str = "stub"

    def detect(self, counts: Sequence[int]) -> list[BurstCall]:
        return self.calls


def _make_series(
    counts: list[int], event_indices: dict[int, tuple[int, ...]] | None = None
) -> EntitySeries:
    grid = BucketGrid(origin=_ORIGIN, bucket_width=_WIDTH, n_buckets=len(counts))
    return EntitySeries(
        entity=(PaymentMethod.UPI, "HDFC Bank", None),
        grid=grid,
        counts=tuple(counts),
        event_indices_by_bucket=event_indices or {},
        reason_counts_by_bucket={},
    )


def test_run_detector_no_bursts_yields_no_incidents() -> None:
    series = _make_series([0, 0, 0])
    calls = [BurstCall(False, 0.0) for _ in range(3)]
    incidents = run_detector(series, _StubDetector(calls))
    assert incidents == []


def test_run_detector_single_isolated_burst() -> None:
    series = _make_series([0, 5, 0])
    calls = [BurstCall(False, 0.0), BurstCall(True, 5.0), BurstCall(False, 0.0)]
    incidents = run_detector(series, _StubDetector(calls))
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.start == _ORIGIN + _WIDTH
    assert incident.end == _ORIGIN + 2 * _WIDTH
    assert incident.total_count == 5
    assert incident.peak_score == 5.0
    assert incident.bucket_starts == (_ORIGIN + _WIDTH,)


def test_run_detector_bridges_single_bucket_gap() -> None:
    series = _make_series([3, 0, 3])
    calls = [BurstCall(True, 3.0), BurstCall(False, 0.0), BurstCall(True, 3.0)]
    incidents = run_detector(series, _StubDetector(calls), max_gap_buckets=1)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.total_count == 6
    assert len(incident.bucket_starts) == 3


def test_run_detector_does_not_bridge_gap_exceeding_tolerance() -> None:
    series = _make_series([3, 0, 0, 3])
    calls = [
        BurstCall(True, 3.0),
        BurstCall(False, 0.0),
        BurstCall(False, 0.0),
        BurstCall(True, 3.0),
    ]
    incidents = run_detector(series, _StubDetector(calls), max_gap_buckets=1)
    assert len(incidents) == 2
    assert incidents[0].total_count == 3
    assert incidents[1].total_count == 3


def test_run_detector_trailing_gap_never_extends_incident() -> None:
    series = _make_series([5, 0, 0])
    calls = [BurstCall(True, 5.0), BurstCall(False, 0.0), BurstCall(False, 0.0)]
    incidents = run_detector(series, _StubDetector(calls), max_gap_buckets=1)
    assert len(incidents) == 1
    assert incidents[0].bucket_starts == (_ORIGIN,)
    assert incidents[0].end == _ORIGIN + _WIDTH


def test_run_detector_aggregates_event_indices_including_bridged_bucket() -> None:
    series = _make_series(
        [1, 0, 1],
        event_indices={0: (10,), 2: (11,)},
    )
    calls = [BurstCall(True, 1.0), BurstCall(False, 0.0), BurstCall(True, 1.0)]
    incidents = run_detector(series, _StubDetector(calls), max_gap_buckets=1)
    assert len(incidents) == 1
    assert incidents[0].event_indices == (10, 11)


def test_run_detector_peak_score_is_max_across_span() -> None:
    series = _make_series([1, 0, 4])
    calls = [BurstCall(True, 1.0), BurstCall(False, 0.0), BurstCall(True, 4.0)]
    incidents = run_detector(series, _StubDetector(calls), max_gap_buckets=1)
    assert incidents[0].peak_score == 4.0


def test_run_detector_entity_and_detector_name_propagate() -> None:
    series = _make_series([9])
    calls = [BurstCall(True, 9.0)]
    incidents = run_detector(series, _StubDetector(calls, name="my_detector"))
    assert incidents[0].entity == (PaymentMethod.UPI, "HDFC Bank", None)
    assert incidents[0].detector == "my_detector"
