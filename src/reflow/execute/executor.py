"""The bounded executor: turns a Decision into a real or simulated Payment Link call.

:class:`BoundedExecutor` is the orchestrator :mod:`reflow.execute` exists to
provide: given one :class:`~reflow.policy.decision.Decision` (Phase 5's
output) and the :class:`~reflow.corpus.events.PaymentEvent` it was decided
for, it produces exactly one :class:`~reflow.execute.models.ExecutionRecord`
-- the shape :mod:`reflow.audit` persists as the last link in one payment's
audit chain.

**Dry run is the default.** ``dry_run=True`` (the dataclass default) never
imports credentials, never constructs a
:class:`~reflow.execute.gateway.RazorpayGateway`, and never opens a
network connection: it builds the exact request payload a live call would
send and records it as evidence of intent, nothing more. Live execution
requires both ``dry_run=False`` *and* a configured gateway -- two
independent, explicit opt-ins, per this phase's brief.

**Only the three chase actions ever call the API.**
:data:`~reflow.policy.actions.CHASE_ACTIONS` (``recovery_link_now``,
``recovery_link_backoff``, ``switch_method``) are the only final actions
that mean "send the customer something" -- every other action in the
closed seven-member set (``no_action``, ``wait_bank_recovery``,
``escalate_human``, ``reconcile``) is a deliberate decision *not* to call
Razorpay at all, and is recorded as such
(:attr:`~reflow.execute.models.ExecutionOutcome.NO_OP`) rather than
silently skipped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Final

from reflow.corpus.events import PaymentEvent
from reflow.execute.errors import (
    ApiCallFailedError,
    GatewayNotConfiguredError,
    LiveCallBudgetExceededError,
)
from reflow.execute.gateway import RESTRICTABLE_METHODS, GatewayCallResult, PaymentLinkGateway
from reflow.execute.models import ExecutionOutcome, ExecutionRecord, PaymentLinkRequest
from reflow.execute.reference import derive_reference_id
from reflow.policy.actions import CHASE_ACTIONS, Action
from reflow.policy.decision import Decision
from reflow.taxonomy.methods import PaymentMethod

_CURRENCY: Final[str] = "INR"
_EMAIL_DOMAIN: Final[str] = "example.com"


def _synthetic_customer(customer_id: str) -> tuple[str, str, str]:
    """Derive placeholder customer contact details for a Payment Link.

    :mod:`reflow.corpus` embeds no real names, phone numbers, or email
    addresses anywhere (see ``reflow.corpus.tokens`` module docstring), so
    there is nothing real to forward to Razorpay's ``customer`` object,
    which Payment Link creation requires when ``notify.sms``/``notify.email``
    is requested. This derives synthetic, valid-*format* contact details
    deterministically from ``customer_id`` -- stable across repeated runs,
    and safe by construction: the email domain is ``example.com``, reserved
    by RFC 2606 to never resolve, and the phone number, while
    format-valid (a ``+91`` country code followed by a leading ``9`` and
    nine further digits, matching real Indian mobile numbering), is
    entirely hash-derived rather than a real subscriber number.

    Args:
        customer_id: The synthetic customer id
            (:attr:`reflow.corpus.events.PaymentEvent.customer_id`).

    Returns:
        A ``(name, contact, email)`` tuple.
    """
    digest = hashlib.sha256(customer_id.encode("utf-8")).hexdigest()
    mobile_digits = "".join(str(int(character, 16) % 10) for character in digest[:9])
    contact = f"+919{mobile_digits}"
    name = f"Reflow Customer {customer_id}"
    email = f"reflow.{customer_id}@{_EMAIL_DOMAIN}"
    return name, contact, email


def _description_for(event: PaymentEvent) -> str:
    """Render the Payment Link's customer-facing description.

    Args:
        event: The event the recovery link is being sent for.

    Returns:
        A short, honest description naming the order and the amount, in
        rupees, without exposing any internal reason code or diagnosis
        detail to the customer.
    """
    rupees = event.amount / 100
    return f"Complete your payment of INR {rupees:.2f} for order {event.order_id}."


def build_payment_link_request(decision: Decision, event: PaymentEvent) -> PaymentLinkRequest:
    """Build the Payment Link request one chase-worthy decision resolves to.

    Args:
        decision: The decision to execute. Must be chase-worthy
            (``decision.final_action`` in
            :data:`~reflow.policy.actions.CHASE_ACTIONS`); callers check
            this before calling (see :meth:`BoundedExecutor.execute`).
        event: The diagnosed event the decision was made for.

    Returns:
        The populated :class:`~reflow.execute.models.PaymentLinkRequest`.
        When ``decision.disallowed_method`` names a payment method
        Razorpay's Payment Links API has no restriction toggle for
        (:data:`reflow.execute.gateway.RESTRICTABLE_METHODS`), the
        returned request carries no method restriction at all rather than
        a fabricated one, and ``unrestrictable_note`` explains why.
    """
    name, contact, email = _synthetic_customer(event.customer_id)
    disallowed_method = decision.disallowed_method
    unrestrictable_note: str | None = None
    restrictable = (
        disallowed_method is not None and PaymentMethod(disallowed_method) in RESTRICTABLE_METHODS
    )
    if disallowed_method is not None and not restrictable:
        unrestrictable_note = (
            f"final_action=switch_method requested disabling method {disallowed_method!r}, but "
            "Razorpay's Payment Links API has no options.checkout.method toggle for this "
            "method -- the created link is left unrestricted (see "
            "reflow.execute.gateway.RESTRICTABLE_METHODS)."
        )
        disallowed_method = None
    return PaymentLinkRequest(
        amount=event.amount,
        currency=_CURRENCY,
        description=_description_for(event),
        reference_id=derive_reference_id(event.payment_id),
        customer_name=name,
        customer_contact=contact,
        customer_email=email,
        notify_sms=True,
        notify_email=True,
        disallowed_method=disallowed_method,
        unrestrictable_note=unrestrictable_note,
    )


def payment_link_request_to_wire(request: PaymentLinkRequest) -> dict[str, Any]:
    """Render a :class:`PaymentLinkRequest` into Razorpay's documented wire shape.

    The ``options.checkout.method`` shape is verified live, 2026-08-23,
    against
    <https://razorpay.com/docs/api/payments/payment-links/customise-payment-methods/>.

    Args:
        request: The request to render.

    Returns:
        A JSON-safe dict suitable as the ``data`` argument to
        ``razorpay.Client.payment_link.create``. Includes an ``options``
        key, restricting every payment method except
        ``request.disallowed_method``, only when that field is set.
    """
    data: dict[str, Any] = {
        "amount": request.amount,
        "currency": request.currency,
        "description": request.description,
        "reference_id": request.reference_id,
        "customer": {
            "name": request.customer_name,
            "contact": request.customer_contact,
            "email": request.customer_email,
        },
        "notify": {"sms": request.notify_sms, "email": request.notify_email},
    }
    if request.disallowed_method is not None:
        data["options"] = {
            "checkout": {
                "method": {
                    method.value: method.value != request.disallowed_method
                    for method in sorted(RESTRICTABLE_METHODS)
                }
            }
        }
    return data


def _no_op_record(action: Action) -> ExecutionRecord:
    """Build the record for a decision that never calls the Razorpay API.

    Args:
        action: The decision's final action.

    Returns:
        A populated :attr:`~reflow.execute.models.ExecutionOutcome.NO_OP`
        record.
    """
    return ExecutionRecord(
        outcome=ExecutionOutcome.NO_OP,
        action=action,
        dry_run=True,
        reference_id=None,
        request=None,
        request_headers={},
        response=None,
        short_url=None,
        payment_link_id=None,
        http_status=None,
        latency_ms=None,
        retry_count=0,
        idempotent_replay=False,
        error_message=None,
        error_detail=None,
        note=f"final_action={action.value} does not call the Razorpay API.",
    )


def _dry_run_record(
    action: Action, request: PaymentLinkRequest, wire: dict[str, Any]
) -> ExecutionRecord:
    """Build the record for a simulated (never-sent) chase action.

    Args:
        action: The decision's final action.
        request: The request that would have been sent.
        wire: ``request`` rendered to Razorpay's wire shape.

    Returns:
        A populated :attr:`~reflow.execute.models.ExecutionOutcome.DRY_RUN`
        record.
    """
    return ExecutionRecord(
        outcome=ExecutionOutcome.DRY_RUN,
        action=action,
        dry_run=True,
        reference_id=request.reference_id,
        request=wire,
        request_headers={},
        response=None,
        short_url=None,
        payment_link_id=None,
        http_status=None,
        latency_ms=None,
        retry_count=0,
        idempotent_replay=False,
        error_message=None,
        error_detail=None,
        note=request.unrestrictable_note,
    )


def _string_or_none(value: object) -> str | None:
    """Narrow an arbitrary JSON value to ``str | None``.

    Args:
        value: A value read from a Razorpay response body.

    Returns:
        ``value`` unchanged if it is a ``str``, otherwise ``None``.
    """
    return value if isinstance(value, str) else None


def _executed_record(
    action: Action,
    request: PaymentLinkRequest,
    wire: dict[str, Any],
    result: GatewayCallResult,
) -> ExecutionRecord:
    """Build the record for a chase action that was actually sent.

    Args:
        action: The decision's final action.
        request: The request that was sent.
        wire: ``request`` rendered to Razorpay's wire shape.
        result: The gateway's successful call result.

    Returns:
        A populated :attr:`~reflow.execute.models.ExecutionOutcome.EXECUTED`
        record.
    """
    response = result.response
    note = request.unrestrictable_note
    if result.recovered_existing:
        recovered_note = (
            f"reference_id {request.reference_id!r} already existed from a prior execution "
            "attempt; recovered the existing Payment Link instead of creating a duplicate."
        )
        note = recovered_note if note is None else f"{note} {recovered_note}"
    return ExecutionRecord(
        outcome=ExecutionOutcome.EXECUTED,
        action=action,
        dry_run=False,
        reference_id=request.reference_id,
        request=wire,
        request_headers=result.request_headers,
        response=response,
        short_url=_string_or_none(response.get("short_url")),
        payment_link_id=_string_or_none(response.get("id")),
        http_status=result.http_status,
        latency_ms=result.latency_ms,
        retry_count=result.retry_count,
        idempotent_replay=result.recovered_existing,
        error_message=None,
        error_detail=None,
        note=note,
    )


def _failed_record(
    action: Action,
    request: PaymentLinkRequest,
    wire: dict[str, Any],
    error: ApiCallFailedError,
) -> ExecutionRecord:
    """Build the record for a chase action whose live call ultimately failed.

    Args:
        action: The decision's final action.
        request: The request that was attempted.
        wire: ``request`` rendered to Razorpay's wire shape.
        error: The exhausted or non-retryable failure.

    Returns:
        A populated :attr:`~reflow.execute.models.ExecutionOutcome.FAILED`
        record.
    """
    return ExecutionRecord(
        outcome=ExecutionOutcome.FAILED,
        action=action,
        dry_run=False,
        reference_id=request.reference_id,
        request=wire,
        request_headers={},
        response=None,
        short_url=None,
        payment_link_id=None,
        http_status=error.status_code,
        latency_ms=None,
        retry_count=error.retry_count,
        idempotent_replay=False,
        error_message=str(error),
        error_detail=error.error_body,
        note=request.unrestrictable_note,
    )


@dataclass(slots=True)
class BoundedExecutor:
    """Executes one :class:`~reflow.policy.decision.Decision` at a time.

    Attributes:
        gateway: The live gateway to call when ``dry_run`` is ``False``.
            May be left ``None`` when every call in this executor's
            lifetime will be a dry run, which needs no credentials at all.
        dry_run: Whether to simulate every call. Defaults to ``True``,
            matching this phase's "dry-run is the default; real calls
            require explicit opt-in" requirement.
        live_call_budget: Hard cap on how many real API calls this
            executor instance will ever make across its lifetime. ``None``
            means no cap beyond whatever the caller enforces externally.
    """

    gateway: PaymentLinkGateway | None = None
    dry_run: bool = True
    live_call_budget: int | None = None
    _live_calls_made: int = field(default=0, init=False)

    @property
    def live_calls_made(self) -> int:
        """How many real API calls this executor has made so far.

        Returns:
            The running count of live calls attempted (successful or
            failed), never incremented for a dry run or a no-op.
        """
        return self._live_calls_made

    def execute(self, decision: Decision, event: PaymentEvent) -> ExecutionRecord:
        """Execute one decision, dry-run or live according to configuration.

        Args:
            decision: The decision to execute (``decision.payment_id`` must
                match ``event.payment_id``).
            event: The diagnosed event the decision was made for.

        Returns:
            The populated :class:`~reflow.execute.models.ExecutionRecord`.

        Raises:
            GatewayNotConfiguredError: If ``dry_run`` is ``False`` and no
                ``gateway`` was configured.
            LiveCallBudgetExceededError: If ``live_call_budget`` would be
                exceeded by this call.
        """
        if decision.final_action not in CHASE_ACTIONS:
            return _no_op_record(decision.final_action)

        request = build_payment_link_request(decision, event)
        wire = payment_link_request_to_wire(request)

        if self.dry_run:
            return _dry_run_record(decision.final_action, request, wire)

        if self.gateway is None:
            raise GatewayNotConfiguredError(
                "Live execution was requested (dry_run=False) but no RazorpayGateway was "
                "configured on this BoundedExecutor."
            )
        if self.live_call_budget is not None and self._live_calls_made >= self.live_call_budget:
            raise LiveCallBudgetExceededError(
                f"Live-call budget of {self.live_call_budget} would be exceeded executing "
                f"payment_id={event.payment_id!r}."
            )

        self._live_calls_made += 1
        try:
            result = self.gateway.create_payment_link(wire)
        except ApiCallFailedError as exc:
            return _failed_record(decision.final_action, request, wire, exc)
        return _executed_record(decision.final_action, request, wire, result)
