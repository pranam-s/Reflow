"""Tests for reflow.taxonomy.methods."""

import pytest

from reflow.taxonomy.methods import (
    SOURCES_BY_METHOD,
    STEPS_BY_METHOD,
    UPI_STEPS_BY_FLOW,
    ErrorCode,
    ErrorSource,
    ErrorStep,
    PaymentMethod,
    UpiFlow,
    steps_for_method,
)


def test_error_code_has_exactly_three_members() -> None:
    assert {member.value for member in ErrorCode} == {
        "BAD_REQUEST_ERROR",
        "GATEWAY_ERROR",
        "SERVER_ERROR",
    }


@pytest.mark.parametrize(
    ("method", "expected_sources"),
    [
        (
            PaymentMethod.CARD,
            {"customer", "business", "internal", "gateway", "issuer_bank"},
        ),
        (
            PaymentMethod.UPI,
            {
                "customer",
                "business",
                "internal",
                "customer_psp",
                "gateway",
                "network",
                "issuer_bank",
                "beneficiary_bank",
            },
        ),
        (
            PaymentMethod.NETBANKING,
            {"customer", "business", "internal", "issuer_bank"},
        ),
        (
            PaymentMethod.WALLET,
            {"customer", "business", "internal", "issuer"},
        ),
        (
            PaymentMethod.CARDLESS_EMI,
            {"customer", "business", "internal", "network", "issuer"},
        ),
        (
            PaymentMethod.EMANDATE,
            {"customer", "bank", "business", "internal", "gateway", "issuer_bank"},
        ),
    ],
)
def test_sources_by_method_matches_verified_brief(
    method: PaymentMethod, expected_sources: set[str]
) -> None:
    assert {source.value for source in SOURCES_BY_METHOD[method]} == expected_sources


def test_steps_for_method_non_upi_methods() -> None:
    assert {step.value for step in steps_for_method(PaymentMethod.CARD)} == {
        "payment_initiation",
        "card_enrollment_check",
        "payment_authentication",
        "payment_authorization",
        "payment_capture",
    }
    assert {step.value for step in steps_for_method(PaymentMethod.NETBANKING)} == {
        "payment_initiation",
        "payment_authentication",
        "payment_authorization",
    }


def test_steps_for_method_upi_requires_flow() -> None:
    with pytest.raises(ValueError, match="upi_flow is required"):
        steps_for_method(PaymentMethod.UPI)


def test_upi_intent_and_collect_share_common_steps_but_differ_on_auth() -> None:
    intent_steps = steps_for_method(PaymentMethod.UPI, upi_flow=UpiFlow.INTENT)
    collect_steps = steps_for_method(PaymentMethod.UPI, upi_flow=UpiFlow.COLLECT)

    assert ErrorStep.PAYMENT_AUTHENTICATION in intent_steps
    assert ErrorStep.PAYMENT_AUTHENTICATION not in collect_steps
    assert ErrorStep.PAYMENT_AUTHENTICATION_REQUEST in collect_steps
    assert ErrorStep.PAYMENT_AUTHENTICATION_RESPONSE in collect_steps
    assert ErrorStep.PAYMENT_AUTHENTICATION_REQUEST not in intent_steps

    shared = intent_steps & collect_steps
    assert ErrorStep.MANDATE_CREATION in shared
    assert ErrorStep.REFUND_REQUEST in shared


def test_steps_by_method_has_no_entry_for_upi() -> None:
    assert PaymentMethod.UPI not in STEPS_BY_METHOD


def test_upi_steps_by_flow_has_both_flows() -> None:
    assert set(UPI_STEPS_BY_FLOW) == {UpiFlow.INTENT, UpiFlow.COLLECT}


def test_error_source_and_step_are_str_enums() -> None:
    assert ErrorSource.CUSTOMER.value == "customer"
    assert ErrorStep.PAYMENT_INITIATION.value == "payment_initiation"
    assert isinstance(ErrorSource.CUSTOMER, str)
    assert isinstance(ErrorStep.PAYMENT_INITIATION, str)
