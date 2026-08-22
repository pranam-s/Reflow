"""Tests for :mod:`reflow.cluster.base`."""

from reflow.cluster.base import NOISE_LABEL, Clusterer, ClusterInput
from reflow.cluster.groupby_reason import GroupByReasonClusterer
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep


def test_noise_label_is_negative_one() -> None:
    assert NOISE_LABEL == -1


def test_cluster_input_is_a_frozen_dataclass() -> None:
    item = ClusterInput(
        masked_description="<BANK> declined the payment.",
        code=ErrorCode.BAD_REQUEST_ERROR,
        source=ErrorSource.CUSTOMER,
        step=ErrorStep.PAYMENT_INITIATION,
        reason="card_declined",
    )
    assert item.masked_description == "<BANK> declined the payment."
    assert item.reason == "card_declined"


def test_groupby_reason_clusterer_satisfies_the_clusterer_protocol() -> None:
    assert isinstance(GroupByReasonClusterer(), Clusterer)
