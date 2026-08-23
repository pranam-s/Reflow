"""Shared PaymentEvent/Decision factories for reflow.execute tests.

Not a test module itself (no ``test_`` prefix): mirrors
``tests/policy/factories.py``'s pattern of a plain helper other test
modules import, extended with :func:`make_decision` since
:mod:`reflow.execute.executor` operates on a full
:class:`~reflow.policy.decision.Decision`, not only a
:class:`~reflow.corpus.events.PaymentEvent`.
"""

from __future__ import annotations

from datetime import datetime

from reflow.corpus.events import PaymentEvent
from reflow.policy.actions import Action
from reflow.policy.decision import Decision, LadderTerminalState, classify_ladder_terminal_state
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
) -> PaymentEvent:
    """Build a fully-populated :class:`PaymentEvent` for an execute test.

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
        is_outlier=False,
        downtime_window_id=None,
        split="train",
    )


def make_decision(
    *,
    event: PaymentEvent | None = None,
    final_action: Action = Action.RECOVERY_LINK_NOW,
    candidate_action: Action | None = None,
    disallowed_method: str | None = None,
    remediation_class: str = "retry_same",
    diagnosis_tier: str = "deterministic",
    diagnosis_confidence: str = "high",
    in_active_incident: bool = False,
) -> Decision:
    """Build a fully-populated :class:`Decision` for an execute test.

    Args:
        event: The event this decision was made for. Defaults to
            :func:`make_event`.
        final_action: The decision's final action.
        candidate_action: The escalation ladder's candidate action.
            Defaults to ``final_action``.
        disallowed_method: The method to disable, for a
            :attr:`~reflow.policy.actions.Action.SWITCH_METHOD` decision.
        remediation_class: The resolved remediation class, as a string.
        diagnosis_tier: Which tier produced the diagnosis.
        diagnosis_confidence: The diagnosis's confidence, as a string.
        in_active_incident: Whether this event was attributed to an
            active incident.

    Returns:
        A fully populated :class:`Decision`, with an empty guardrail
        chain (this factory is for :mod:`reflow.execute` tests, which do
        not exercise guardrail behaviour).
    """
    resolved_event = event if event is not None else make_event()
    resolved_candidate = candidate_action if candidate_action is not None else final_action
    ladder_terminal_state: LadderTerminalState = classify_ladder_terminal_state(final_action, ())
    return Decision(
        payment_id=resolved_event.payment_id,
        order_id=resolved_event.order_id,
        customer_id=resolved_event.customer_id,
        method=resolved_event.method.value,
        bank=resolved_event.bank,
        amount=resolved_event.amount,
        created_at=resolved_event.created_at.isoformat(),
        attempt_number=resolved_event.attempt_number,
        error_reason=resolved_event.error_reason,
        remediation_class=remediation_class,
        diagnosis_tier=diagnosis_tier,
        diagnosis_confidence=diagnosis_confidence,
        in_active_incident=in_active_incident,
        base_action=final_action,
        candidate_action=resolved_candidate,
        guardrail_evaluations=(),
        final_action=final_action,
        ladder_terminal_state=ladder_terminal_state,
        scheduled_delay_seconds=None,
        disallowed_method=disallowed_method,
        justification="test decision",
    )
