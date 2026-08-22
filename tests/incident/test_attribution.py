"""Tests for reflow.incident.attribution."""

from datetime import datetime, timedelta

import pytest

from reflow.corpus.events import PaymentEvent
from reflow.incident.aggregate import EntityKey
from reflow.incident.attribution import (
    background_false_positive_rate,
    compute_fragmentation,
    compute_reason_breakdown,
    evaluate_detector,
    evaluate_incidents,
    event_attribution_accuracy,
    reconstruct_true_windows,
    summarize_cross_reason,
)
from reflow.incident.windows import DetectedIncident
from reflow.taxonomy.methods import PaymentMethod
from tests.incident.factories import make_event


def _incident(
    entity: EntityKey,
    start: datetime,
    end: datetime,
    event_indices: tuple[int, ...] = (),
    detector: str = "stub",
) -> DetectedIncident:
    return DetectedIncident(
        entity=entity,
        detector=detector,
        start=start,
        end=end,
        bucket_starts=(start,),
        total_count=len(event_indices),
        peak_score=1.0,
        event_indices=event_indices,
    )


def test_reconstruct_true_windows_computes_span_and_reason_counts() -> None:
    events = [
        make_event(
            method=PaymentMethod.UPI,
            bank="HDFC Bank",
            created_at=datetime(2026, 1, 1, 0, 0),
            error_reason="psp_not_available",
            downtime_window_id="dtw_1",
            payment_id="pay_1",
        ),
        make_event(
            method=PaymentMethod.UPI,
            bank="HDFC Bank",
            created_at=datetime(2026, 1, 1, 0, 20),
            error_reason="upi_app_technical_error",
            downtime_window_id="dtw_1",
            payment_id="pay_2",
        ),
        make_event(
            method=PaymentMethod.UPI,
            bank="ICICI Bank",
            created_at=datetime(2026, 1, 1, 5, 0),
            downtime_window_id=None,
            payment_id="pay_bg",
        ),
    ]
    windows = reconstruct_true_windows(events)
    assert len(windows) == 1
    window = windows[0]
    assert window.window_id == "dtw_1"
    assert window.entity == (PaymentMethod.UPI, "HDFC Bank", None)
    assert window.start == datetime(2026, 1, 1, 0, 0)
    assert window.end > datetime(2026, 1, 1, 0, 20)
    assert window.event_indices == (0, 1)
    assert window.reason_counts == {"psp_not_available": 1, "upi_app_technical_error": 1}


def test_reconstruct_true_windows_wallet_events_share_one_entity_despite_random_bank() -> None:
    events = [
        make_event(
            method=PaymentMethod.WALLET,
            bank="State Bank of India",
            created_at=datetime(2026, 1, 1, 0, 0),
            downtime_window_id="dtw_wallet",
            payment_id="pay_1",
        ),
        make_event(
            method=PaymentMethod.WALLET,
            bank="Axis Bank",
            created_at=datetime(2026, 1, 1, 0, 5),
            downtime_window_id="dtw_wallet",
            payment_id="pay_2",
        ),
    ]
    windows = reconstruct_true_windows(events)
    assert len(windows) == 1
    assert windows[0].entity == (PaymentMethod.WALLET, None, None)


def test_reconstruct_true_windows_rejects_a_window_spanning_two_entities() -> None:
    events = [
        make_event(
            method=PaymentMethod.UPI,
            bank="HDFC Bank",
            created_at=datetime(2026, 1, 1, 0, 0),
            downtime_window_id="dtw_broken",
            payment_id="pay_1",
        ),
        make_event(
            method=PaymentMethod.CARD,
            bank="HDFC Bank",
            created_at=datetime(2026, 1, 1, 0, 5),
            downtime_window_id="dtw_broken",
            payment_id="pay_2",
        ),
    ]
    with pytest.raises(ValueError, match="more than one entity"):
        reconstruct_true_windows(events)


def test_reconstruct_true_windows_ignores_background_events() -> None:
    events = [make_event(downtime_window_id=None)]
    assert reconstruct_true_windows(events) == []


def test_compute_reason_breakdown_majority_and_share() -> None:
    events = [
        make_event(
            downtime_window_id="dtw_1",
            error_reason="a",
            created_at=datetime(2026, 1, 1, 0, 0),
            payment_id="p1",
        ),
        make_event(
            downtime_window_id="dtw_1",
            error_reason="a",
            created_at=datetime(2026, 1, 1, 0, 1),
            payment_id="p2",
        ),
        make_event(
            downtime_window_id="dtw_1",
            error_reason="b",
            created_at=datetime(2026, 1, 1, 0, 2),
            payment_id="p3",
        ),
    ]
    (window,) = reconstruct_true_windows(events)
    breakdown = compute_reason_breakdown(window)
    assert breakdown.n_events == 3
    assert breakdown.n_distinct_reasons == 2
    assert breakdown.majority_reason == "a"
    assert breakdown.majority_reason_share == pytest.approx(2 / 3)


def _single_reason_window_events() -> list[PaymentEvent]:
    return [
        make_event(
            downtime_window_id="dtw_single",
            error_reason="only_reason",
            created_at=datetime(2026, 1, 1, 0, 0),
            payment_id="p1",
        ),
        make_event(
            downtime_window_id="dtw_single",
            error_reason="only_reason",
            created_at=datetime(2026, 1, 1, 0, 5),
            payment_id="p2",
        ),
    ]


def test_summarize_cross_reason_single_reason_window_is_not_multi() -> None:
    windows = reconstruct_true_windows(_single_reason_window_events())
    summary = summarize_cross_reason([compute_reason_breakdown(w) for w in windows])
    assert summary.n_windows == 1
    assert summary.n_multi_reason_windows == 0
    assert summary.multi_reason_fraction == 0.0
    assert summary.mean_invisible_event_fraction is None
    assert summary.overall_invisible_event_fraction is None


def test_summarize_cross_reason_multi_reason_window_computes_invisible_fraction() -> None:
    events = [
        make_event(
            downtime_window_id="dtw_multi",
            error_reason="a",
            created_at=datetime(2026, 1, 1, 0, 0),
            payment_id="p1",
        ),
        make_event(
            downtime_window_id="dtw_multi",
            error_reason="a",
            created_at=datetime(2026, 1, 1, 0, 1),
            payment_id="p2",
        ),
        make_event(
            downtime_window_id="dtw_multi",
            error_reason="a",
            created_at=datetime(2026, 1, 1, 0, 2),
            payment_id="p3",
        ),
        make_event(
            downtime_window_id="dtw_multi",
            error_reason="b",
            created_at=datetime(2026, 1, 1, 0, 3),
            payment_id="p4",
        ),
    ]
    windows = reconstruct_true_windows(events)
    summary = summarize_cross_reason([compute_reason_breakdown(w) for w in windows])
    assert summary.n_multi_reason_windows == 1
    assert summary.multi_reason_fraction == 1.0
    assert summary.invisible_event_fractions == pytest.approx((0.25,))
    assert summary.overall_invisible_event_fraction == pytest.approx(0.25)
    assert summary.total_invisible_events == 1


def test_summarize_cross_reason_empty_input() -> None:
    summary = summarize_cross_reason([])
    assert summary.n_windows == 0
    assert summary.multi_reason_fraction == 0.0
    assert summary.mean_invisible_event_fraction is None


def test_evaluate_incidents_perfect_match_and_time_to_detect() -> None:
    events = _single_reason_window_events()
    (window,) = reconstruct_true_windows(events)
    entity = window.entity
    detected = [_incident(entity, window.start + timedelta(minutes=2), window.end)]
    stats = evaluate_incidents([window], detected)
    assert stats.precision == 1.0
    assert stats.recall == 1.0
    assert stats.f1 == pytest.approx(1.0)
    assert stats.time_to_detect_minutes == (2.0,)


def test_evaluate_incidents_missed_window_hurts_recall() -> None:
    events = _single_reason_window_events()
    (window,) = reconstruct_true_windows(events)
    stats = evaluate_incidents([window], [])
    assert stats.recall == 0.0
    assert stats.precision is None
    assert stats.time_to_detect_minutes == ()


def test_evaluate_incidents_false_positive_hurts_precision() -> None:
    events = _single_reason_window_events()
    (window,) = reconstruct_true_windows(events)
    unrelated_entity = (PaymentMethod.CARD, "Some Other Bank", None)
    false_positive = _incident(unrelated_entity, datetime(2026, 6, 1), datetime(2026, 6, 1, 1))
    stats = evaluate_incidents([window], [false_positive])
    assert stats.precision == 0.0
    assert stats.recall == 0.0


def test_evaluate_incidents_time_to_detect_floored_at_zero() -> None:
    events = _single_reason_window_events()
    (window,) = reconstruct_true_windows(events)
    detected = [_incident(window.entity, window.start - timedelta(minutes=1), window.end)]
    stats = evaluate_incidents([window], detected)
    assert stats.time_to_detect_minutes == (0.0,)


def test_evaluate_incidents_no_true_windows_recall_is_none() -> None:
    stats = evaluate_incidents([], [])
    assert stats.recall is None
    assert stats.precision is None
    assert stats.f1 is None


def test_compute_fragmentation_single_fragment_per_window() -> None:
    events = _single_reason_window_events()
    (window,) = reconstruct_true_windows(events)
    detected = [_incident(window.entity, window.start, window.end)]
    stats = compute_fragmentation([window], detected)
    assert stats.fragments_per_window == (1,)
    assert stats.mean_fragments_per_window == pytest.approx(1.0)
    assert stats.fraction_windows_fragmented == 0.0


def test_compute_fragmentation_counts_multiple_overlapping_detections() -> None:
    events = _single_reason_window_events()
    (window,) = reconstruct_true_windows(events)
    detected = [
        _incident(window.entity, window.start, window.start + timedelta(minutes=1)),
        _incident(window.entity, window.start + timedelta(minutes=2), window.end),
    ]
    stats = compute_fragmentation([window], detected)
    assert stats.fragments_per_window == (2,)
    assert stats.fraction_windows_fragmented == 1.0
    assert stats.max_fragments_per_window == 2


def test_compute_fragmentation_empty_windows() -> None:
    stats = compute_fragmentation([], [])
    assert stats.n_windows == 0
    assert stats.mean_fragments_per_window is None


def test_event_attribution_accuracy_full_and_partial_and_none() -> None:
    events = _single_reason_window_events()
    (window,) = reconstruct_true_windows(events)
    full = _incident(window.entity, window.start, window.end, event_indices=(0, 1))
    assert event_attribution_accuracy([window], [full]) == pytest.approx(1.0)

    partial = _incident(window.entity, window.start, window.end, event_indices=(0,))
    assert event_attribution_accuracy([window], [partial]) == pytest.approx(0.5)

    assert event_attribution_accuracy([], []) is None


def test_background_false_positive_rate() -> None:
    events = [
        make_event(downtime_window_id=None, created_at=datetime(2026, 1, 1, 0, 0), payment_id="p1"),
        make_event(
            downtime_window_id=None, created_at=datetime(2026, 1, 1, 0, 20), payment_id="p2"
        ),
    ]
    entity = events[0].method, events[0].bank, None
    incident = _incident(entity, datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 0, 15), (0,))
    rate = background_false_positive_rate(events, [incident])
    assert rate == pytest.approx(0.5)


def test_background_false_positive_rate_no_background_is_none() -> None:
    events = [make_event(downtime_window_id="dtw_1")]
    assert background_false_positive_rate(events, []) is None


def test_evaluate_detector_assembles_full_evaluation() -> None:
    events = _single_reason_window_events()
    (window,) = reconstruct_true_windows(events)
    detected = [_incident(window.entity, window.start, window.end, event_indices=(0, 1))]
    evaluation = evaluate_detector("stub", "test", events, [window], detected, runtime_seconds=0.5)
    assert evaluation.detector == "stub"
    assert evaluation.split == "test"
    assert evaluation.match_stats.recall == 1.0
    assert evaluation.event_attribution_accuracy == pytest.approx(1.0)
    assert evaluation.runtime_seconds == 0.5
    assert evaluation.fragmentation.fragments_per_window == (1,)
