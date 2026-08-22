"""Tests for :mod:`reflow.cluster.drain3_clusterer`."""

from reflow.cluster.base import ClusterInput
from reflow.cluster.drain3_clusterer import Drain3Clusterer
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep


def _item(text: str) -> ClusterInput:
    return ClusterInput(
        masked_description=text,
        code=ErrorCode.BAD_REQUEST_ERROR,
        source=ErrorSource.CUSTOMER,
        step=ErrorStep.PAYMENT_INITIATION,
        reason="card_declined",
    )


def test_drain3_groups_identical_messages() -> None:
    inputs = [_item("<BANK> declined payment <PAYMENT_ID> for <AMOUNT>.")] * 3
    labels = Drain3Clusterer().fit_predict(inputs)
    assert len(set(labels)) == 1


def test_drain3_groups_messages_that_differ_only_in_a_masked_token() -> None:
    inputs = [
        _item("<BANK> declined payment <PAYMENT_ID> for <AMOUNT>."),
        _item("<BANK> declined payment <PAYMENT_ID> for <AMOUNT>."),
    ]
    labels = Drain3Clusterer().fit_predict(inputs)
    assert labels[0] == labels[1]


def test_drain3_separates_messages_with_different_token_counts() -> None:
    inputs = [
        _item("Short message here."),
        _item("This is a considerably longer message with many more tokens in it."),
    ]
    labels = Drain3Clusterer().fit_predict(inputs)
    assert labels[0] != labels[1]


def test_drain3_never_emits_noise() -> None:
    inputs = [_item("alpha beta"), _item("gamma delta epsilon"), _item("zeta")]
    labels = Drain3Clusterer().fit_predict(inputs)
    assert all(label >= 0 for label in labels)


def test_drain3_handles_empty_input() -> None:
    assert Drain3Clusterer().fit_predict([]) == []


def test_drain3_is_order_dependent_but_deterministic_for_a_fixed_order() -> None:
    inputs = [
        _item("<BANK> declined payment <PAYMENT_ID>."),
        _item("<BANK> rejected payment <PAYMENT_ID>."),
        _item("<BANK> declined payment <PAYMENT_ID>."),
    ]
    first_run = Drain3Clusterer().fit_predict(inputs)
    second_run = Drain3Clusterer().fit_predict(inputs)
    assert first_run == second_run


def test_drain3_name() -> None:
    assert Drain3Clusterer().name == "drain3"
