"""Shared PaymentEvent factory for reflow.incident tests.

Not a test module itself (no ``test_`` prefix, so pytest never collects
it): a plain helper other test modules import, building fully-populated
PaymentEvent instances directly rather than through the seeded corpus
generator, so incident-detection tests can control exactly the fields
that matter (method, bank, timestamp, reason, window id) without
depending on randomness.
"""

from __future__ import annotations

from datetime import datetime

from reflow.corpus.events import PaymentEvent
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep, PaymentMethod


def make_event(
    *,
    method: PaymentMethod = PaymentMethod.UPI,
    bank: str = "State Bank of India",
    created_at: datetime = datetime(2026, 1, 1, 0, 0, 0),
    error_reason: str = "payment_timed_out",
    downtime_window_id: str | None = None,
    is_outlier: bool = False,
    split: str = "train",
    payment_id: str = "pay_test0000000001",
) -> PaymentEvent:
    return PaymentEvent(
        payment_id=payment_id,
        order_id="order_test0000001",
        amount=10_000,
        method=method,
        created_at=created_at,
        customer_id="cust_test00001",
        attempt_number=1,
        bank=bank,
        vpa="tester.1@oksbi" if method is PaymentMethod.UPI else None,
        card_bin="411111" if method is PaymentMethod.CARD else None,
        error_code=ErrorCode.GATEWAY_ERROR,
        error_source=ErrorSource.NETWORK,
        error_step=ErrorStep.PAYMENT_INITIATION,
        error_reason=error_reason,
        description="a test description",
        latent_subcause_id=None,
        description_variant="canonical",
        is_outlier=is_outlier,
        downtime_window_id=downtime_window_id,
        split=split,
    )
