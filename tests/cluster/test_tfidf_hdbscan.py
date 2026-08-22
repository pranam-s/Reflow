"""Tests for :mod:`reflow.cluster.tfidf_hdbscan`."""

from reflow.cluster.base import NOISE_LABEL, ClusterInput
from reflow.cluster.tfidf_hdbscan import TfidfHdbscanClusterer
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep


def _item(text: str) -> ClusterInput:
    return ClusterInput(
        masked_description=text,
        code=ErrorCode.BAD_REQUEST_ERROR,
        source=ErrorSource.CUSTOMER,
        step=ErrorStep.PAYMENT_INITIATION,
        reason="card_declined",
    )


def test_tfidf_hdbscan_handles_empty_input() -> None:
    assert TfidfHdbscanClusterer().fit_predict([]) == []


def test_tfidf_hdbscan_handles_single_input_without_calling_it_noise() -> None:
    labels = TfidfHdbscanClusterer().fit_predict([_item("a lone description")])
    assert labels == [0]


def test_tfidf_hdbscan_groups_two_dense_repeated_clusters() -> None:
    cluster_a = [_item("the gateway timed out waiting for the bank to respond")] * 6
    cluster_b = [_item("the customer entered an incorrect one time password")] * 6
    labels = TfidfHdbscanClusterer(min_cluster_size=3).fit_predict(cluster_a + cluster_b)
    assert len(labels) == 12
    a_labels = set(labels[:6])
    b_labels = set(labels[6:])
    assert len(a_labels) == 1
    assert len(b_labels) == 1
    assert a_labels != b_labels


def test_tfidf_hdbscan_label_space_excludes_sub_negative_one_sentinels() -> None:
    cluster_a = [_item("the gateway timed out waiting for the bank to respond")] * 6
    cluster_b = [_item("the customer entered an incorrect one time password")] * 6
    labels = TfidfHdbscanClusterer(min_cluster_size=3).fit_predict(cluster_a + cluster_b)
    assert all(label == NOISE_LABEL or label >= 0 for label in labels)


def test_tfidf_hdbscan_can_call_a_lone_outlier_noise() -> None:
    dense = [_item("the gateway timed out waiting for the bank to respond")] * 10
    outlier = [_item("a completely unrelated one off sentence about weather")]
    labels = TfidfHdbscanClusterer(min_cluster_size=5).fit_predict(dense + outlier)
    assert labels[-1] == NOISE_LABEL


def test_tfidf_hdbscan_name() -> None:
    assert TfidfHdbscanClusterer().name == "tfidf_hdbscan"
