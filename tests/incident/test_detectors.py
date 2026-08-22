"""Tests for reflow.incident.detectors."""

import math
import random
import statistics

import pytest

from reflow.incident.detectors import (
    EwmaZScoreDetector,
    FixedThresholdDetector,
    IncidentDetector,
    PoissonSurpriseDetector,
    RollingZScoreDetector,
    _poisson_sf,
)


def test_incident_detector_protocol_recognizes_every_candidate() -> None:
    for detector in (
        FixedThresholdDetector(),
        RollingZScoreDetector(),
        PoissonSurpriseDetector(),
        EwmaZScoreDetector(),
    ):
        assert isinstance(detector, IncidentDetector)


def test_fixed_threshold_flags_strictly_above_threshold() -> None:
    detector = FixedThresholdDetector(threshold=3)
    calls = detector.detect([0, 3, 4, 10])
    assert [call.is_burst for call in calls] == [False, False, True, True]
    assert [call.score for call in calls] == [0.0, 3.0, 4.0, 10.0]


def test_fixed_threshold_has_no_cold_start() -> None:
    detector = FixedThresholdDetector(threshold=1)
    calls = detector.detect([5])
    assert calls[0].is_burst is True


def _naive_poisson_sf(k: int, lam: float) -> float:
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    cdf = sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(k))
    return max(0.0, min(1.0, 1.0 - cdf))


@pytest.mark.parametrize(
    ("k", "lam"), [(0, 2.0), (1, 0.001), (3, 1.5), (5, 0.0), (10, 20.0), (2, 0.5), (0, 0.0)]
)
def test_poisson_sf_matches_naive_direct_space_computation(k: int, lam: float) -> None:
    assert _poisson_sf(k, lam) == pytest.approx(_naive_poisson_sf(k, lam), abs=1e-9)


def test_poisson_sf_negative_k_is_always_one() -> None:
    assert _poisson_sf(-1, 5.0) == 1.0
    assert _poisson_sf(0, 5.0) == 1.0


def _reference_zscore(
    counts: list[int], window: int, min_periods: int, z_threshold: float
) -> list[tuple[bool, float]]:
    calls: list[tuple[bool, float]] = []
    for i in range(len(counts)):
        history = counts[max(0, i - window) : i]
        if len(history) < min_periods:
            calls.append((False, 0.0))
            continue
        mean = statistics.fmean(history)
        variance = statistics.pvariance(history, mu=mean)
        stdev = math.sqrt(variance)
        if stdev < 1e-9:
            calls.append((counts[i] > mean, counts[i] - mean))
        else:
            z_score = (counts[i] - mean) / stdev
            calls.append((z_score > z_threshold, z_score))
    return calls


def test_rolling_zscore_matches_reference_implementation() -> None:
    rng = random.Random(123)
    counts = [rng.randint(0, 5) for _ in range(60)]
    counts[45] = 80
    detector = RollingZScoreDetector(window=8, min_periods=4, z_threshold=3.0)
    calls = detector.detect(counts)
    reference = _reference_zscore(counts, window=8, min_periods=4, z_threshold=3.0)
    for call, (expected_burst, expected_score) in zip(calls, reference, strict=True):
        assert call.is_burst == expected_burst
        assert call.score == pytest.approx(expected_score, abs=1e-6)


def test_rolling_zscore_respects_cold_start() -> None:
    detector = RollingZScoreDetector(window=4, min_periods=2)
    calls = detector.detect([100, 100, 100])
    assert calls[0].is_burst is False
    assert calls[0].score == 0.0
    assert calls[1].is_burst is False


def test_rolling_zscore_degenerate_variance_fallback_flags_any_excess() -> None:
    detector = RollingZScoreDetector(window=4, min_periods=2)
    calls = detector.detect([0, 0, 0, 0, 0, 10])
    assert [call.is_burst for call in calls] == [False, False, False, False, False, True]
    assert calls[-1].score == pytest.approx(10.0)


def test_rolling_zscore_is_causal_current_bucket_excluded_from_its_own_baseline() -> None:
    detector = RollingZScoreDetector(window=4, min_periods=2)
    calls = detector.detect([0, 0, 100])
    assert calls[2].score != 0.0


def _reference_poisson_detect(
    counts: list[int], window: int, min_periods: int, p_threshold: float
) -> list[tuple[bool, float]]:
    calls: list[tuple[bool, float]] = []
    for i in range(len(counts)):
        history = counts[max(0, i - window) : i]
        if len(history) < min_periods:
            calls.append((False, 0.0))
            continue
        lam = (sum(history) + 1.0) / (len(history) + 1.0)
        p_value = _poisson_sf(counts[i], lam)
        score = -math.log(max(p_value, 1e-300))
        calls.append((p_value < p_threshold, score))
    return calls


def test_poisson_surprise_matches_reference_implementation() -> None:
    rng = random.Random(7)
    counts = [rng.randint(0, 3) for _ in range(50)]
    counts[30] = 40
    detector = PoissonSurpriseDetector(window=8, min_periods=4, p_threshold=1e-3)
    calls = detector.detect(counts)
    reference = _reference_poisson_detect(counts, window=8, min_periods=4, p_threshold=1e-3)
    for call, (expected_burst, expected_score) in zip(calls, reference, strict=True):
        assert call.is_burst == expected_burst
        assert call.score == pytest.approx(expected_score, rel=1e-6, abs=1e-6)


def test_poisson_surprise_respects_cold_start() -> None:
    detector = PoissonSurpriseDetector(window=4, min_periods=2)
    calls = detector.detect([50, 50])
    assert calls[0].is_burst is False
    assert calls[1].is_burst is False


def test_poisson_surprise_single_event_after_long_silence_is_not_flagged() -> None:
    detector = PoissonSurpriseDetector(window=16, min_periods=8, p_threshold=1e-3)
    counts = [0] * 16 + [1]
    calls = detector.detect(counts)
    assert calls[-1].is_burst is False


def test_poisson_surprise_flags_genuine_cluster_after_silence() -> None:
    detector = PoissonSurpriseDetector(window=16, min_periods=8, p_threshold=1e-3)
    counts = [0] * 16 + [25]
    calls = detector.detect(counts)
    assert calls[-1].is_burst is True


def _reference_ewma(
    counts: list[int], alpha: float, min_periods: int, z_threshold: float
) -> list[tuple[bool, float]]:
    calls: list[tuple[bool, float]] = []
    mean = 0.0
    variance = 0.0
    for n_seen, count in enumerate(counts):
        if n_seen < min_periods:
            calls.append((False, 0.0))
        else:
            stdev = math.sqrt(variance)
            if stdev < 1e-9:
                calls.append((count > mean, count - mean))
            else:
                z_score = (count - mean) / stdev
                calls.append((z_score > z_threshold, z_score))
        diff = count - mean
        mean += alpha * diff
        variance = (1 - alpha) * (variance + alpha * diff * diff)
    return calls


def test_ewma_zscore_matches_reference_implementation() -> None:
    rng = random.Random(99)
    counts = [rng.randint(0, 4) for _ in range(40)]
    counts[25] = 60
    detector = EwmaZScoreDetector(alpha=0.2, min_periods=8, z_threshold=3.0)
    calls = detector.detect(counts)
    reference = _reference_ewma(counts, alpha=0.2, min_periods=8, z_threshold=3.0)
    for call, (expected_burst, expected_score) in zip(calls, reference, strict=True):
        assert call.is_burst == expected_burst
        assert call.score == pytest.approx(expected_score, abs=1e-6)


def test_ewma_zscore_respects_cold_start() -> None:
    detector = EwmaZScoreDetector(min_periods=3)
    calls = detector.detect([9, 9, 9])
    assert all(call.is_burst is False for call in calls)


def test_ewma_zscore_updates_state_during_warmup() -> None:
    detector = EwmaZScoreDetector(alpha=0.5, min_periods=2)
    calls = detector.detect([10, 10, 10])
    assert calls[2].is_burst is False
