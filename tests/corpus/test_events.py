"""Tests for reflow.corpus.events."""

import random
from datetime import datetime
from pathlib import Path

import pytest

from reflow.corpus.events import build_event, infer_error_code, infer_source, infer_step
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep, PaymentMethod, UpiFlow
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import parse_reason_records
from reflow.taxonomy.remediation import RemediationClass, classify_reasons

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDS = parse_reason_records(resolve_vendored_path(REPO_ROOT))
RECORD_BY_REASON = {record.reason: record for record in RECORDS}
REMEDIATION_BY_REASON = {c.reason: c.remediation_class for c in classify_reasons(RECORDS)}


def test_infer_error_code_server_error() -> None:
    assert infer_error_code("server_error", RECORD_BY_REASON["server_error"].explanation) is (
        ErrorCode.SERVER_ERROR
    )


def test_infer_error_code_technical_reason_is_gateway_error() -> None:
    explanation = RECORD_BY_REASON["gateway_technical_error"].explanation
    assert infer_error_code("gateway_technical_error", explanation) is ErrorCode.GATEWAY_ERROR


def test_infer_error_code_defaults_to_bad_request() -> None:
    explanation = RECORD_BY_REASON["incorrect_cvv"].explanation
    assert infer_error_code("incorrect_cvv", explanation) is ErrorCode.BAD_REQUEST_ERROR


def test_infer_source_customer_fix_is_customer() -> None:
    assert infer_source(RemediationClass.CUSTOMER_FIX, PaymentMethod.CARD) is ErrorSource.CUSTOMER


def test_infer_source_merchant_action_is_business() -> None:
    assert infer_source(RemediationClass.MERCHANT_ACTION, PaymentMethod.UPI) is ErrorSource.BUSINESS


def test_infer_source_merchant_contact_razorpay_is_internal() -> None:
    assert (
        infer_source(RemediationClass.MERCHANT_CONTACT_RAZORPAY, PaymentMethod.WALLET)
        is ErrorSource.INTERNAL
    )


def test_infer_source_ambiguous_falls_back_to_system_side() -> None:
    assert infer_source(None, PaymentMethod.WALLET) is ErrorSource.ISSUER
    assert infer_source(None, PaymentMethod.UPI) is ErrorSource.NETWORK


def test_infer_step_authentication_keyword() -> None:
    step = infer_step("Entered an incorrect OTP during authentication.", PaymentMethod.CARD, None)
    assert step is ErrorStep.PAYMENT_AUTHENTICATION


def test_infer_step_upi_collect_uses_request_variant() -> None:
    step = infer_step(
        "Authentication failed for the collect request.", PaymentMethod.UPI, UpiFlow.COLLECT
    )
    assert step is ErrorStep.PAYMENT_AUTHENTICATION_REQUEST


def test_infer_step_falls_back_to_initiation() -> None:
    step = infer_step("Something unrelated happened.", PaymentMethod.NETBANKING, None)
    assert step is ErrorStep.PAYMENT_INITIATION


@pytest.mark.parametrize(
    ("method", "upi_flow"),
    [(PaymentMethod.CARD, None), (PaymentMethod.UPI, UpiFlow.INTENT)],
)
def test_infer_step_always_returns_valid_step(
    method: PaymentMethod, upi_flow: UpiFlow | None
) -> None:
    from reflow.taxonomy.methods import steps_for_method

    for record in RECORDS:
        step = infer_step(record.explanation, method, upi_flow)
        assert step in steps_for_method(method, upi_flow=upi_flow)


def test_build_event_card_has_card_bin_not_vpa() -> None:
    rng = random.Random(1)
    event = build_event(
        rng=rng,
        reason_record=RECORD_BY_REASON["card_expired"],
        remediation_class=REMEDIATION_BY_REASON["card_expired"],
        method=PaymentMethod.CARD,
        upi_flow=None,
        created_at=datetime(2026, 1, 1),
        customer_id="cust_test",
        attempt_number=1,
        downtime_window_id=None,
    )
    assert event.card_bin is not None
    assert event.vpa is None
    assert event.latent_subcause_id is None
    assert event.ground_truth == (
        event.error_code,
        event.error_source,
        event.error_step,
        event.error_reason,
    )


def test_build_event_upi_has_vpa_not_card_bin() -> None:
    rng = random.Random(2)
    event = build_event(
        rng=rng,
        reason_record=RECORD_BY_REASON["invalid_vpa"],
        remediation_class=REMEDIATION_BY_REASON["invalid_vpa"],
        method=PaymentMethod.UPI,
        upi_flow=UpiFlow.INTENT,
        created_at=datetime(2026, 1, 1),
        customer_id="cust_test",
        attempt_number=1,
        downtime_window_id=None,
    )
    assert event.vpa is not None
    assert event.card_bin is None


def test_build_event_catch_all_reason_sets_latent_subcause() -> None:
    rng = random.Random(3)
    event = build_event(
        rng=rng,
        reason_record=RECORD_BY_REASON["payment_failed"],
        remediation_class=REMEDIATION_BY_REASON["payment_failed"],
        method=PaymentMethod.UPI,
        upi_flow=UpiFlow.INTENT,
        created_at=datetime(2026, 1, 1),
        customer_id="cust_test",
        attempt_number=1,
        downtime_window_id=None,
    )
    assert event.latent_subcause_id is not None


def test_build_event_forced_bank_and_order_id_are_applied() -> None:
    rng = random.Random(4)
    event = build_event(
        rng=rng,
        reason_record=RECORD_BY_REASON["bank_not_available"],
        remediation_class=REMEDIATION_BY_REASON["bank_not_available"],
        method=PaymentMethod.NETBANKING,
        upi_flow=None,
        created_at=datetime(2026, 1, 1),
        customer_id="cust_test",
        attempt_number=2,
        downtime_window_id="dtw_test",
        forced_bank="Test Bank",
        forced_order_id="order_forced1234",
    )
    assert event.bank == "Test Bank"
    assert event.order_id == "order_forced1234"
    assert event.downtime_window_id == "dtw_test"
    assert event.attempt_number == 2
    assert "Test Bank" in event.description


def test_build_event_variant_richness_one_forces_canonical() -> None:
    for seed in range(50):
        rng = random.Random(seed)
        event = build_event(
            rng=rng,
            reason_record=RECORD_BY_REASON["payment_failed"],
            remediation_class=REMEDIATION_BY_REASON["payment_failed"],
            method=PaymentMethod.UPI,
            upi_flow=UpiFlow.INTENT,
            created_at=datetime(2026, 1, 1),
            customer_id="cust_test",
            attempt_number=1,
            downtime_window_id=None,
            variant_richness=1,
        )
        assert event.description_variant == "canonical"


def test_build_event_variant_richness_none_matches_default() -> None:
    explicit = build_event(
        rng=random.Random(9),
        reason_record=RECORD_BY_REASON["payment_failed"],
        remediation_class=REMEDIATION_BY_REASON["payment_failed"],
        method=PaymentMethod.UPI,
        upi_flow=UpiFlow.INTENT,
        created_at=datetime(2026, 1, 1),
        customer_id="cust_test",
        attempt_number=1,
        downtime_window_id=None,
        variant_richness=None,
    )
    omitted = build_event(
        rng=random.Random(9),
        reason_record=RECORD_BY_REASON["payment_failed"],
        remediation_class=REMEDIATION_BY_REASON["payment_failed"],
        method=PaymentMethod.UPI,
        upi_flow=UpiFlow.INTENT,
        created_at=datetime(2026, 1, 1),
        customer_id="cust_test",
        attempt_number=1,
        downtime_window_id=None,
    )
    assert explicit == omitted


def test_build_event_is_deterministic_for_same_seed() -> None:
    def make() -> object:
        rng = random.Random(123)
        return build_event(
            rng=rng,
            reason_record=RECORD_BY_REASON["psp_not_available"],
            remediation_class=REMEDIATION_BY_REASON["psp_not_available"],
            method=PaymentMethod.UPI,
            upi_flow=UpiFlow.INTENT,
            created_at=datetime(2026, 1, 1),
            customer_id="cust_test",
            attempt_number=1,
            downtime_window_id=None,
        )

    assert make() == make()
