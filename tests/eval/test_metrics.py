"""Tests for :mod:`reflow.eval.metrics`."""

import pytest

from reflow.cluster.base import NOISE_LABEL
from reflow.eval.metrics import (
    ClusteringMetrics,
    cluster_purity,
    compute_metrics,
    compute_noise_handling,
    find_crossover_share,
)
from reflow.eval.metrics import blended_metric as blend


def test_cluster_purity_perfect_match() -> None:
    true_labels = ["a", "a", "b", "b"]
    pred_labels = [0, 0, 1, 1]
    assert cluster_purity(true_labels, pred_labels) == 1.0


def test_cluster_purity_worst_case_single_cluster() -> None:
    true_labels = ["a", "a", "b", "b"]
    pred_labels = [0, 0, 0, 0]
    assert cluster_purity(true_labels, pred_labels) == pytest.approx(0.5)


def test_cluster_purity_over_fragmentation_is_trivially_pure() -> None:
    true_labels = ["a", "a", "b", "b"]
    pred_labels = [0, 1, 2, 3]
    assert cluster_purity(true_labels, pred_labels) == 1.0


def test_cluster_purity_treats_noise_label_as_an_ordinary_cluster() -> None:
    true_labels = ["a", "b"]
    pred_labels = [NOISE_LABEL, NOISE_LABEL]
    assert cluster_purity(true_labels, pred_labels) == pytest.approx(0.5)


def test_cluster_purity_empty_input_is_nan() -> None:
    assert cluster_purity([], []) != cluster_purity([], [])


def test_cluster_purity_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        cluster_purity(["a"], [0, 1])


def test_compute_metrics_perfect_match() -> None:
    metrics = compute_metrics(["a", "a", "b", "b"], [0, 0, 1, 1])
    assert isinstance(metrics, ClusteringMetrics)
    assert metrics.purity == 1.0
    assert metrics.nmi == pytest.approx(1.0)
    assert metrics.ari == pytest.approx(1.0)
    assert metrics.n_predicted_clusters == 2
    assert metrics.n_true_clusters == 2
    assert metrics.n_events == 4


def test_compute_metrics_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="zero events"):
        compute_metrics([], [])


def test_compute_metrics_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        compute_metrics(["a"], [0, 1])


def test_compute_metrics_excludes_noise_from_predicted_cluster_count() -> None:
    metrics = compute_metrics(["a", "a", "b"], [0, 0, NOISE_LABEL])
    assert metrics.n_predicted_clusters == 1


def test_compute_noise_handling_perfect_recall_and_precision() -> None:
    is_outlier = [True, False, False]
    pred_labels = [NOISE_LABEL, 0, 0]
    handling = compute_noise_handling(is_outlier, pred_labels)
    assert handling.n_true_outliers == 1
    assert handling.n_predicted_noise == 1
    assert handling.n_true_outliers_correctly_noised == 1
    assert handling.n_true_outliers_forced_into_cluster == 0
    assert handling.recall == pytest.approx(1.0)
    assert handling.precision == pytest.approx(1.0)


def test_compute_noise_handling_candidate_that_never_emits_noise() -> None:
    is_outlier = [True, True, False]
    pred_labels = [0, 1, 2]
    handling = compute_noise_handling(is_outlier, pred_labels)
    assert handling.recall == pytest.approx(0.0)
    assert handling.precision is None
    assert handling.n_true_outliers_forced_into_cluster == 2


def test_compute_noise_handling_no_true_outliers() -> None:
    handling = compute_noise_handling([False, False], [0, NOISE_LABEL])
    assert handling.recall is None
    assert handling.precision == pytest.approx(0.0)


def test_compute_noise_handling_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        compute_noise_handling([True], [0, 1])


def test_blended_metric_at_extremes() -> None:
    assert blend(0.0, 0.9, 0.1) == pytest.approx(0.1)
    assert blend(1.0, 0.9, 0.1) == pytest.approx(0.9)
    assert blend(0.5, 0.9, 0.1) == pytest.approx(0.5)


def test_blended_metric_rejects_out_of_range_share() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        blend(1.5, 0.5, 0.5)


def test_find_crossover_share_immediate_when_candidate_always_better() -> None:
    share = find_crossover_share(
        candidate_catchall_metric=0.9,
        candidate_narrow_metric=0.5,
        baseline_catchall_metric=0.4,
        baseline_narrow_metric=0.5,
    )
    assert share == pytest.approx(0.001, abs=1e-3)


def test_find_crossover_share_never_when_candidate_always_worse() -> None:
    share = find_crossover_share(
        candidate_catchall_metric=0.3,
        candidate_narrow_metric=0.5,
        baseline_catchall_metric=0.9,
        baseline_narrow_metric=0.5,
    )
    assert share is None


def test_find_crossover_share_never_on_a_tie() -> None:
    share = find_crossover_share(
        candidate_catchall_metric=0.5,
        candidate_narrow_metric=0.5,
        baseline_catchall_metric=0.5,
        baseline_narrow_metric=0.5,
    )
    assert share is None


def test_find_crossover_share_rejects_low_resolution() -> None:
    with pytest.raises(ValueError, match="resolution"):
        find_crossover_share(0.9, 0.5, 0.1, 0.5, resolution=1)
