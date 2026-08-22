"""Shared PaymentEvent factory for reflow.policy tests.

Not a test module itself (no ``test_`` prefix, so pytest never collects
it): a plain helper other test modules import, building fully-populated
PaymentEvent instances directly rather than through the seeded corpus
generator, mirroring ``tests/incident/factories.py`` but exposing the
extra fields (``amount``, ``attempt_number``, ``customer_id``,
``order_id``) the policy layer's guardrails and ladder actually read.
"""

from __future__ import annotations

from datetime import datetime

from reflow.corpus.events import PaymentEvent
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep, PaymentMethod


def make_event(
    *,
    method: PaymentMethod = PaymentMethod.UPI,
    bank: str = "State Bank of India",
    created_at: datetime = datetime(2026, 1, 1, 12, 0, 0),
    error_reason: str = "payment_timed_out",
    amount: int = 100_000,
    attempt_number: int = 1,
    customer_id: str = "cust_test00001",
    order_id: str = "order_test0000001",
    payment_id: str = "pay_test0000000001",
    downtime_window_id: str | None = None,
    is_outlier: bool = False,
    split: str = "train",
) -> PaymentEvent:
    """Build a fully-populated :class:`PaymentEvent` for a policy test.

    Args:
        method: The payment method.
        bank: The counterparty bank name.
        created_at: The event's timestamp.
        error_reason: The vendored reason code.
        amount: The transaction amount, in paise.
        attempt_number: The 1-based attempt number for this order.
        customer_id: The synthetic customer id.
        order_id: The synthetic order id.
        payment_id: The synthetic payment id.
        downtime_window_id: The outage window id, if any.
        is_outlier: Ground-truth outlier flag.
        split: ``"train"`` or ``"test"``.

    Returns:
        A fully populated :class:`PaymentEvent`.
    """
    return PaymentEvent(
        payment_id=payment_id,
        order_id=order_id,
        amount=amount,
        method=method,
        created_at=created_at,
        customer_id=customer_id,
        attempt_number=attempt_number,
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
