"""Bake-off metrics: purity, NMI, ARI, cluster counts, and noise handling.

Also hosts the Axis C (catch-all share) machinery: :func:`blended_metric`
computes what a metric would be for a system that routes catch-all traffic
to one path and narrow traffic to another, at an assumed catch-all share,
and :func:`find_crossover_share` finds the smallest such share at which a
candidate's blended metric first overtakes a baseline's.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from reflow.cluster.base import NOISE_LABEL


def cluster_purity(true_labels: Sequence[str], pred_labels: Sequence[int]) -> float:
    """Compute cluster purity.

    Each predicted cluster (including the noise "cluster", if any) is
    scored by the fraction of its members sharing its single most common
    true label; purity is the size-weighted average of those per-cluster
    scores, i.e. the overall fraction of points whose predicted cluster's
    majority true label matches their own.

    Args:
        true_labels: Ground-truth label per point.
        pred_labels: Predicted cluster label per point, in the same order.
            :data:`~reflow.cluster.base.NOISE_LABEL` is treated as an
            ordinary cluster label, not specially excluded -- a method
            that calls many points noise is scored on how internally
            consistent its noise bucket happens to be, exactly as any
            other predicted cluster is.

    Returns:
        A value in ``[0, 1]``, or ``float("nan")`` if ``true_labels`` is
        empty.

    Raises:
        ValueError: If ``true_labels`` and ``pred_labels`` have different
            lengths.
    """
    if len(true_labels) != len(pred_labels):
        raise ValueError("true_labels and pred_labels must have the same length.")
    total = len(true_labels)
    if total == 0:
        return float("nan")

    members_by_cluster: dict[int, list[str]] = {}
    for true_label, pred_label in zip(true_labels, pred_labels, strict=True):
        members_by_cluster.setdefault(pred_label, []).append(true_label)

    correct = sum(Counter(members).most_common(1)[0][1] for members in members_by_cluster.values())
    return correct / total


@dataclass(frozen=True, slots=True)
class ClusteringMetrics:
    """The core separability metrics for one clustering run.

    Attributes:
        purity: See :func:`cluster_purity`.
        nmi: Normalised mutual information between true and predicted
            labels (``sklearn.metrics.normalized_mutual_info_score``).
        ari: Adjusted Rand index between true and predicted labels
            (``sklearn.metrics.adjusted_rand_score``).
        n_predicted_clusters: Number of distinct predicted labels,
            excluding :data:`~reflow.cluster.base.NOISE_LABEL`.
        n_true_clusters: Number of distinct true labels.
        n_events: Number of points the metrics were computed over.
    """

    purity: float
    nmi: float
    ari: float
    n_predicted_clusters: int
    n_true_clusters: int
    n_events: int


def compute_metrics(true_labels: Sequence[str], pred_labels: Sequence[int]) -> ClusteringMetrics:
    """Compute every core separability metric for one clustering run.

    Args:
        true_labels: Ground-truth label per point.
        pred_labels: Predicted cluster label per point, in the same order.

    Returns:
        The populated :class:`ClusteringMetrics`.

    Raises:
        ValueError: If ``true_labels`` and ``pred_labels`` have different
            lengths, or both are empty.
    """
    if len(true_labels) != len(pred_labels):
        raise ValueError("true_labels and pred_labels must have the same length.")
    if len(true_labels) == 0:
        raise ValueError("Cannot compute clustering metrics over zero events.")

    purity = cluster_purity(true_labels, pred_labels)
    nmi = float(normalized_mutual_info_score(true_labels, pred_labels))
    ari = float(adjusted_rand_score(true_labels, pred_labels))
    n_predicted = len({label for label in pred_labels if label != NOISE_LABEL})
    n_true = len(set(true_labels))
    return ClusteringMetrics(
        purity=purity,
        nmi=nmi,
        ari=ari,
        n_predicted_clusters=n_predicted,
        n_true_clusters=n_true,
        n_events=len(true_labels),
    )


@dataclass(frozen=True, slots=True)
class NoiseHandling:
    """How well a candidate's noise label lines up with true outliers.

    Only a candidate that can emit :data:`~reflow.cluster.base.NOISE_LABEL`
    (in this bake-off, only
    :class:`~reflow.cluster.tfidf_hdbscan.TfidfHdbscanClusterer`) can score
    anything other than zero recall here -- candidates that never emit
    noise force every true outlier into some cluster, which is exactly the
    asymmetry this phase's brief calls out as itself a finding.

    Attributes:
        n_true_outliers: Number of points genuinely flagged
            ``is_outlier=True`` in the input.
        n_predicted_noise: Number of points the candidate labelled noise.
        n_true_outliers_correctly_noised: True outliers the candidate also
            labelled noise.
        n_true_outliers_forced_into_cluster: True outliers the candidate
            placed in some cluster instead of calling noise.
    """

    n_true_outliers: int
    n_predicted_noise: int
    n_true_outliers_correctly_noised: int
    n_true_outliers_forced_into_cluster: int

    @property
    def recall(self) -> float | None:
        """Fraction of true outliers the candidate correctly called noise.

        Returns:
            ``n_true_outliers_correctly_noised / n_true_outliers``, or
            ``None`` if there were no true outliers to recall.
        """
        if self.n_true_outliers == 0:
            return None
        return self.n_true_outliers_correctly_noised / self.n_true_outliers

    @property
    def precision(self) -> float | None:
        """Fraction of the candidate's noise calls that were true outliers.

        Returns:
            ``n_true_outliers_correctly_noised / n_predicted_noise``, or
            ``None`` if the candidate never called anything noise.
        """
        if self.n_predicted_noise == 0:
            return None
        return self.n_true_outliers_correctly_noised / self.n_predicted_noise


def compute_noise_handling(is_outlier: Sequence[bool], pred_labels: Sequence[int]) -> NoiseHandling:
    """Compute noise-handling agreement between true outliers and predictions.

    Args:
        is_outlier: Ground-truth outlier flag per point.
        pred_labels: Predicted cluster label per point, in the same order.

    Returns:
        The populated :class:`NoiseHandling`.

    Raises:
        ValueError: If ``is_outlier`` and ``pred_labels`` have different
            lengths.
    """
    if len(is_outlier) != len(pred_labels):
        raise ValueError("is_outlier and pred_labels must have the same length.")
    n_true_outliers = sum(1 for outlier in is_outlier if outlier)
    n_predicted_noise = sum(1 for label in pred_labels if label == NOISE_LABEL)
    n_correct = sum(
        1
        for outlier, label in zip(is_outlier, pred_labels, strict=True)
        if outlier and label == NOISE_LABEL
    )
    return NoiseHandling(
        n_true_outliers=n_true_outliers,
        n_predicted_noise=n_predicted_noise,
        n_true_outliers_correctly_noised=n_correct,
        n_true_outliers_forced_into_cluster=n_true_outliers - n_correct,
    )


def blended_metric(catchall_share: float, catchall_metric: float, narrow_metric: float) -> float:
    """Linearly blend a catch-all-stratum metric with a narrow-stratum metric.

    Args:
        catchall_share: Assumed fraction of overall traffic that is
            catch-all, in ``[0, 1]``.
        catchall_metric: The metric value observed on the catch-all
            stratum.
        narrow_metric: The metric value observed on the narrow stratum.

    Returns:
        ``catchall_share * catchall_metric + (1 - catchall_share) * narrow_metric``.

    Raises:
        ValueError: If ``catchall_share`` is outside ``[0, 1]``.
    """
    if not 0.0 <= catchall_share <= 1.0:
        raise ValueError("catchall_share must be within [0, 1].")
    return catchall_share * catchall_metric + (1 - catchall_share) * narrow_metric


def find_crossover_share(
    candidate_catchall_metric: float,
    candidate_narrow_metric: float,
    baseline_catchall_metric: float,
    baseline_narrow_metric: float,
    resolution: int = 1001,
) -> float | None:
    """Find the smallest catch-all share at which a candidate overtakes a baseline.

    Scans ``catchall_share`` from 0 to 1 at fixed resolution rather than
    solving the blend equation directly, so this function stays correct
    even if a caller later blends with something other than a straight
    line between the two stratum metrics.

    Args:
        candidate_catchall_metric: The candidate's metric on the catch-all
            stratum.
        candidate_narrow_metric: The candidate's metric on the narrow
            stratum.
        baseline_catchall_metric: The baseline's metric on the catch-all
            stratum.
        baseline_narrow_metric: The baseline's metric on the narrow
            stratum.
        resolution: Number of evenly spaced points in ``[0, 1]`` to scan.

    Returns:
        The smallest scanned ``catchall_share`` at which
        ``blended_metric(share, candidate_catchall_metric,
        candidate_narrow_metric)`` strictly exceeds
        ``blended_metric(share, baseline_catchall_metric,
        baseline_narrow_metric)``, or ``None`` if the candidate never
        overtakes the baseline anywhere in ``[0, 1]``.

    Raises:
        ValueError: If ``resolution`` is less than 2.
    """
    if resolution < 2:
        raise ValueError("resolution must be at least 2.")
    for step in range(resolution):
        share = step / (resolution - 1)
        candidate_value = blended_metric(share, candidate_catchall_metric, candidate_narrow_metric)
        baseline_value = blended_metric(share, baseline_catchall_metric, baseline_narrow_metric)
        if candidate_value > baseline_value:
            return share
    return None
