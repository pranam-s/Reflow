"""Tests for :mod:`reflow.cluster.groupby_reason`."""

from reflow.cluster.base import ClusterInput
from reflow.cluster.groupby_reason import GroupByReasonClusterer
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep


def _item(reason: str, source: ErrorSource = ErrorSource.CUSTOMER) -> ClusterInput:
    return ClusterInput(
        masked_description="ignored text",
        code=ErrorCode.BAD_REQUEST_ERROR,
        source=source,
        step=ErrorStep.PAYMENT_INITIATION,
        reason=reason,
    )


def test_groupby_reason_assigns_the_same_label_to_identical_tuples() -> None:
    inputs = [_item("card_declined"), _item("card_declined")]
    labels = GroupByReasonClusterer().fit_predict(inputs)
    assert labels[0] == labels[1]


def test_groupby_reason_assigns_different_labels_to_different_reasons() -> None:
    inputs = [_item("card_declined"), _item("insufficient_funds")]
    labels = GroupByReasonClusterer().fit_predict(inputs)
    assert labels[0] != labels[1]


def test_groupby_reason_assigns_different_labels_when_only_source_differs() -> None:
    inputs = [
        _item("issuer_technical_error", source=ErrorSource.CUSTOMER),
        _item("issuer_technical_error", source=ErrorSource.ISSUER_BANK),
    ]
    labels = GroupByReasonClusterer().fit_predict(inputs)
    assert labels[0] != labels[1]


def test_groupby_reason_ignores_masked_description() -> None:
    a = ClusterInput(
        masked_description="completely different text A",
        code=ErrorCode.BAD_REQUEST_ERROR,
        source=ErrorSource.CUSTOMER,
        step=ErrorStep.PAYMENT_INITIATION,
        reason="card_declined",
    )
    b = ClusterInput(
        masked_description="completely different text B",
        code=ErrorCode.BAD_REQUEST_ERROR,
        source=ErrorSource.CUSTOMER,
        step=ErrorStep.PAYMENT_INITIATION,
        reason="card_declined",
    )
    labels = GroupByReasonClusterer().fit_predict([a, b])
    assert labels[0] == labels[1]


def test_groupby_reason_never_emits_noise() -> None:
    inputs = [_item("card_declined"), _item("payment_failed"), _item("server_error")]
    labels = GroupByReasonClusterer().fit_predict(inputs)
    assert all(label >= 0 for label in labels)


def test_groupby_reason_handles_empty_input() -> None:
    assert GroupByReasonClusterer().fit_predict([]) == []


def test_groupby_reason_name() -> None:
    assert GroupByReasonClusterer().name == "groupby_reason"
