"""Tests for :mod:`reflow.cluster.template_hash`."""

from reflow.cluster.base import ClusterInput
from reflow.cluster.template_hash import TemplateHashClusterer
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep


def _item(text: str) -> ClusterInput:
    return ClusterInput(
        masked_description=text,
        code=ErrorCode.BAD_REQUEST_ERROR,
        source=ErrorSource.CUSTOMER,
        step=ErrorStep.PAYMENT_INITIATION,
        reason="card_declined",
    )


def test_template_hash_groups_identical_text() -> None:
    inputs = [_item("<BANK> declined payment <PAYMENT_ID>.")] * 2
    labels = TemplateHashClusterer().fit_predict(inputs)
    assert labels[0] == labels[1]


def test_template_hash_tolerates_whitespace_and_case_differences() -> None:
    inputs = [
        _item("<BANK>  declined   payment <PAYMENT_ID>."),
        _item("<bank> declined payment <payment_id>."),
    ]
    labels = TemplateHashClusterer().fit_predict(inputs)
    assert labels[0] == labels[1]


def test_template_hash_splits_on_any_other_difference() -> None:
    inputs = [
        _item("<BANK> declined payment <PAYMENT_ID>."),
        _item("<BANK> rejected payment <PAYMENT_ID>."),
    ]
    labels = TemplateHashClusterer().fit_predict(inputs)
    assert labels[0] != labels[1]


def test_template_hash_never_emits_noise() -> None:
    inputs = [_item("a"), _item("b"), _item("c")]
    labels = TemplateHashClusterer().fit_predict(inputs)
    assert all(label >= 0 for label in labels)


def test_template_hash_handles_empty_input() -> None:
    assert TemplateHashClusterer().fit_predict([]) == []


def test_template_hash_name() -> None:
    assert TemplateHashClusterer().name == "template_hash"
