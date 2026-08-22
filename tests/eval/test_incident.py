"""Tests for :mod:`reflow.eval.incident`."""

import json
from datetime import datetime

import pytest

from reflow.corpus.split import TEST, TRAIN
from reflow.eval.incident import (
    CORRELATABLE_METHODS,
    GROUPBY_REASON_LABEL_PREFIX,
    DetectorReportRow,
    _percentile,
    _select_winner,
    _synthetic_declared_downtimes,
    run_benchmark,
    summarize_time_to_detect,
    to_json_dict,
    to_markdown,
)
from reflow.incident.attribution import (
    DetectorEvaluation,
    FragmentationStats,
    IncidentMatchStats,
    TrueWindow,
)
from reflow.incident.downtime_api import DowntimeMethod, DowntimeSeverity
from reflow.taxonomy.methods import PaymentMethod

_SMALL_N_EVENTS = 6_000
_SMALL_SEED = 4242


@pytest.fixture(scope="module")
def small_report():
    return run_benchmark(seed=_SMALL_SEED, n_events=_SMALL_N_EVENTS)


def test_run_benchmark_covers_every_detector_and_split(small_report) -> None:
    seen = {(row.evaluation.detector, row.evaluation.split) for row in small_report.detector_rows}
    detectors = {"fixed_threshold", "rolling_zscore", "poisson_surprise", "ewma_zscore"}
    for detector in detectors:
        for split in (TRAIN, TEST):
            assert (detector, split) in seen


def test_run_benchmark_winner_is_one_of_the_candidates(small_report) -> None:
    candidates = {"fixed_threshold", "rolling_zscore", "poisson_surprise", "ewma_zscore"}
    assert small_report.winner in candidates


def test_run_benchmark_groupby_reason_rows_cover_both_splits(small_report) -> None:
    labels = {row.evaluation.split for row in small_report.groupby_reason_rows}
    assert labels == {TRAIN, TEST}
    for row in small_report.groupby_reason_rows:
        assert row.evaluation.detector == f"{GROUPBY_REASON_LABEL_PREFIX}{small_report.winner}"


def test_run_benchmark_cross_reason_scopes_present(small_report) -> None:
    assert set(small_report.cross_reason_by_scope) == {"all", TRAIN, TEST}
    assert small_report.cross_reason_by_scope["all"].multi_reason_fraction == pytest.approx(1.0)


def test_run_benchmark_downtime_correlation_demo_is_internally_consistent(small_report) -> None:
    demo = small_report.downtime_correlation_demo
    assert demo.n_correlatable_incidents + demo.n_never_correlatable == demo.n_detected_incidents
    assert demo.n_corroborated <= demo.n_correlatable_incidents


def test_to_json_dict_round_trips_through_json(small_report) -> None:
    payload = to_json_dict(small_report)
    text = json.dumps(payload)
    reloaded = json.loads(text)
    assert reloaded["winner"] == small_report.winner


def test_to_markdown_contains_expected_sections(small_report) -> None:
    markdown = to_markdown(small_report)
    assert "# Phase 3 incident-detection benchmark results" in markdown
    assert "## Detector results" in markdown
    assert "## GROUP BY reason baseline" in markdown
    assert "## Cross-reason claim" in markdown
    assert "## Downtime-correlation demonstration" in markdown
    assert small_report.winner in markdown


def _fake_row(detector: str, split: str, f1: float | None, fpr: float | None) -> DetectorReportRow:
    match_stats = IncidentMatchStats(
        n_true_windows=1,
        n_detected_incidents=1,
        n_true_positive_windows=1,
        n_true_positive_incidents=1,
        precision=f1,
        recall=f1,
        f1=f1,
        time_to_detect_minutes=(),
    )
    fragmentation = FragmentationStats(1, (1,), 1.0, 1.0, 1, 0.0)
    evaluation = DetectorEvaluation(
        detector=detector,
        split=split,
        match_stats=match_stats,
        fragmentation=fragmentation,
        event_attribution_accuracy=1.0,
        background_false_positive_rate=fpr,
        runtime_seconds=0.01,
    )
    return DetectorReportRow(
        evaluation=evaluation, time_to_detect=summarize_time_to_detect(()), n_entities=1
    )


def test_select_winner_picks_highest_test_f1() -> None:
    rows = [
        _fake_row("a", TEST, 0.5, 0.1),
        _fake_row("b", TEST, 0.9, 0.1),
        _fake_row("a", TRAIN, 0.99, 0.0),
    ]
    assert _select_winner(rows) == "b"


def test_select_winner_breaks_ties_by_lower_false_positive_rate() -> None:
    rows = [
        _fake_row("a", TEST, 0.8, 0.5),
        _fake_row("b", TEST, 0.8, 0.1),
    ]
    assert _select_winner(rows) == "b"


def test_select_winner_raises_without_test_rows() -> None:
    with pytest.raises(ValueError, match="test"):
        _select_winner([_fake_row("a", TRAIN, 0.5, 0.1)])


def test_percentile_interpolates_between_order_statistics() -> None:
    values = [0.0, 10.0]
    assert _percentile(values, 0.5) == pytest.approx(5.0)
    assert _percentile(values, 0.0) == pytest.approx(0.0)
    assert _percentile(values, 1.0) == pytest.approx(10.0)


def test_percentile_single_value() -> None:
    assert _percentile([7.0], 0.25) == pytest.approx(7.0)


def test_summarize_time_to_detect_empty() -> None:
    distribution = summarize_time_to_detect(())
    assert distribution.n == 0
    assert distribution.mean is None


def test_summarize_time_to_detect_reports_full_distribution() -> None:
    distribution = summarize_time_to_detect([0.0, 5.0, 10.0, 15.0, 20.0])
    assert distribution.n == 5
    assert distribution.minimum == 0.0
    assert distribution.maximum == 20.0
    assert distribution.median == pytest.approx(10.0)
    assert distribution.mean == pytest.approx(10.0)


def test_synthetic_declared_downtimes_restricts_to_correlatable_methods() -> None:
    correlatable_window = TrueWindow(
        window_id="dtw_upi",
        entity=(PaymentMethod.UPI, "HDFC Bank", None),
        start=datetime(2026, 1, 1, 0, 0),
        end=datetime(2026, 1, 1, 3, 0),
        event_indices=(0, 1),
        reason_counts={"a": 1, "b": 1},
    )
    wallet_window = TrueWindow(
        window_id="dtw_wallet",
        entity=(PaymentMethod.WALLET, None, None),
        start=datetime(2026, 1, 1, 0, 0),
        end=datetime(2026, 1, 1, 0, 30),
        event_indices=(2,),
        reason_counts={"a": 1},
    )
    declared = _synthetic_declared_downtimes([correlatable_window, wallet_window])
    assert len(declared) == 1
    assert declared[0].method is DowntimeMethod.UPI
    assert declared[0].bank == "HDFC Bank"
    assert declared[0].severity is DowntimeSeverity.HIGH


def test_synthetic_declared_downtimes_severity_scales_with_duration() -> None:
    short_window = TrueWindow(
        window_id="dtw_short",
        entity=(PaymentMethod.CARD, "Axis Bank", None),
        start=datetime(2026, 1, 1, 0, 0),
        end=datetime(2026, 1, 1, 0, 20),
        event_indices=(0,),
        reason_counts={"a": 1},
    )
    (declared,) = _synthetic_declared_downtimes([short_window])
    assert declared.severity is DowntimeSeverity.LOW


def test_correlatable_methods_excludes_emandate_wallet_and_cardless_emi() -> None:
    assert (
        frozenset({PaymentMethod.CARD, PaymentMethod.NETBANKING, PaymentMethod.UPI})
        == CORRELATABLE_METHODS
    )


def _strip_non_deterministic_fields(report: dict[str, object]) -> dict[str, object]:
    provenance = report["provenance"]
    assert isinstance(provenance, dict)
    del provenance["generated_at"]
    for section in ("detector_rows", "groupby_reason_rows"):
        rows = report[section]
        assert isinstance(rows, list)
        for row in rows:
            assert isinstance(row, dict)
            del row["runtime_seconds"]
    return report


def test_run_benchmark_is_deterministic_for_same_seed() -> None:
    first = _strip_non_deterministic_fields(to_json_dict(run_benchmark(seed=99, n_events=1_500)))
    second = _strip_non_deterministic_fields(to_json_dict(run_benchmark(seed=99, n_events=1_500)))
    assert first == second
