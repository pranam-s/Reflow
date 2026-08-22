"""Tests for reflow.taxonomy.signal."""

import pytest
from pydantic import ValidationError

from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep
from reflow.taxonomy.signal import FailureSignal


def test_from_webhook_payment_entity_normalises_error_prefixed_keys() -> None:
    entity = {
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Authentication failed due to incorrect otp.",
        "error_source": "customer",
        "error_step": "payment_authentication",
        "error_reason": "incorrect_otp",
    }
    signal = FailureSignal.from_webhook_payment_entity(entity)
    assert signal.code is ErrorCode.BAD_REQUEST_ERROR
    assert signal.description == "Authentication failed due to incorrect otp."
    assert signal.source is ErrorSource.CUSTOMER
    assert signal.step is ErrorStep.PAYMENT_AUTHENTICATION
    assert signal.reason == "incorrect_otp"
    assert signal.field is None
    assert signal.metadata is None


def test_from_api_error_normalises_short_keys_with_field_and_metadata() -> None:
    error = {
        "code": "GATEWAY_ERROR",
        "description": "Payment failed due to a technical error at the gateway.",
        "source": "gateway",
        "step": "payment_authorization",
        "reason": "gateway_technical_error",
        "field": None,
        "metadata": {"payment_id": "pay_ABC123"},
    }
    signal = FailureSignal.from_api_error(error)
    assert signal.code is ErrorCode.GATEWAY_ERROR
    assert signal.source is ErrorSource.GATEWAY
    assert signal.step is ErrorStep.PAYMENT_AUTHORIZATION
    assert signal.reason == "gateway_technical_error"
    assert signal.metadata == {"payment_id": "pay_ABC123"}


def test_model_validate_accepts_canonical_keys_directly() -> None:
    signal = FailureSignal.model_validate(
        {
            "code": "SERVER_ERROR",
            "description": "Technical error at Razorpay's server.",
            "source": "internal",
            "step": "payment_capture",
            "reason": "server_error",
        }
    )
    assert signal.code is ErrorCode.SERVER_ERROR


def test_both_wire_shapes_produce_equal_canonical_signals() -> None:
    webhook_shape = FailureSignal.from_webhook_payment_entity(
        {
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "The customer must enter correct authentication details.",
            "error_source": "customer",
            "error_step": "payment_authentication",
            "error_reason": "authentication_failed",
        }
    )
    api_shape = FailureSignal.from_api_error(
        {
            "code": "BAD_REQUEST_ERROR",
            "description": "The customer must enter correct authentication details.",
            "source": "customer",
            "step": "payment_authentication",
            "reason": "authentication_failed",
        }
    )
    assert webhook_shape == api_shape


def test_failure_signal_is_frozen() -> None:
    signal = FailureSignal.model_validate(
        {
            "code": "SERVER_ERROR",
            "description": "x",
            "source": "internal",
            "step": "payment_capture",
            "reason": "server_error",
        }
    )
    with pytest.raises(ValidationError):
        signal.reason = "something_else"


def test_failure_signal_rejects_unknown_code() -> None:
    with pytest.raises(ValidationError):
        FailureSignal.model_validate(
            {
                "code": "NOT_A_REAL_CODE",
                "description": "x",
                "source": "internal",
                "step": "payment_capture",
                "reason": "server_error",
            }
        )


def test_failure_signal_rejects_empty_reason() -> None:
    with pytest.raises(ValidationError):
        FailureSignal.model_validate(
            {
                "code": "SERVER_ERROR",
                "description": "x",
                "source": "internal",
                "step": "payment_capture",
                "reason": "",
            }
        )
