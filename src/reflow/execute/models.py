"""Request/response/outcome shapes the bounded executor and audit trail share.

Every dataclass here is a plain, JSON-serialisable shape by construction
(only ``str``, ``int``, ``float``, ``bool``, ``None``, and nested
``dict``/``list`` of those), matching the same design goal
:mod:`reflow.policy.decision` states for :class:`~reflow.policy.decision.Decision`:
no bespoke handling is ever needed for an enum, a
:class:`~datetime.datetime`, or a :class:`~datetime.timedelta` when
:mod:`reflow.audit` persists one of these.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from reflow.policy.actions import Action


class ExecutionOutcome(StrEnum):
    """The terminal outcome of attempting to execute one policy decision."""

    NO_OP = "no_op"
    DRY_RUN = "dry_run"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PaymentLinkRequest:
    """The Payment Link creation request one chase-worthy decision resolves to.

    Attributes:
        amount: Amount in paise, carried over from the original failed
            payment.
        currency: ISO currency code (always ``"INR"`` for this project's
            corpus).
        description: Human-readable description shown on the checkout
            page.
        reference_id: The deterministic idempotency key (see
            :func:`reflow.execute.reference.derive_reference_id`), always
            at most :data:`reflow.execute.reference.REFERENCE_ID_MAX_LENGTH`
            characters.
        customer_name: The customer's display name.
        customer_contact: The customer's phone number, in ``+91...``
            format.
        customer_email: The customer's email address.
        notify_sms: Whether Razorpay should SMS the link on creation.
        notify_email: Whether Razorpay should email the link on creation.
        disallowed_method: The single payment method to disable via
            ``options.checkout.method`` (see
            :mod:`reflow.policy.actions` module docstring for why this is
            the verified, enforceable mechanism behind
            :attr:`~reflow.policy.actions.Action.SWITCH_METHOD`), or
            ``None`` for an unrestricted link.
        unrestrictable_note: Populated only when ``disallowed_method``
            names a method Razorpay's Payment Links API has no toggle for
            at all (:data:`reflow.execute.gateway.RESTRICTABLE_METHODS`),
            explaining why the resulting request carries no ``options``
            restriction despite the decision asking for one. ``None``
            otherwise.
    """

    amount: int
    currency: str
    description: str
    reference_id: str
    customer_name: str
    customer_contact: str
    customer_email: str
    notify_sms: bool
    notify_email: bool
    disallowed_method: str | None
    unrestrictable_note: str | None


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """The complete, auditable outcome of executing one policy decision.

    Attributes:
        outcome: The terminal :class:`ExecutionOutcome`.
        action: The :class:`~reflow.policy.actions.Action` this record
            executes (a decision's ``final_action``).
        dry_run: Whether this record was produced in dry-run mode.
        reference_id: The deterministic idempotency key, or ``None`` when
            ``outcome`` is :attr:`ExecutionOutcome.NO_OP`.
        request: The redacted request payload that was sent, or would have
            been sent, or ``None`` for a no-op.
        request_headers: The redacted request headers of the attempt that
            settled this record, or an empty mapping.
        response: The Razorpay response body, present only for
            :attr:`ExecutionOutcome.EXECUTED`.
        short_url: The Payment Link's public URL, present only for
            :attr:`ExecutionOutcome.EXECUTED`.
        payment_link_id: The Payment Link's Razorpay-assigned id, present
            only for :attr:`ExecutionOutcome.EXECUTED`.
        http_status: The settling attempt's HTTP status code, present for
            :attr:`ExecutionOutcome.EXECUTED`/:attr:`ExecutionOutcome.FAILED`.
        latency_ms: Wall-clock time of the settling attempt, in
            milliseconds, or ``None`` for a no-op or dry run.
        retry_count: How many retries were attempted before settling
            (``0`` for a no-op or dry run).
        idempotent_replay: ``True`` when Razorpay reported this
            ``reference_id`` as already used and this record recovered the
            pre-existing Payment Link instead of creating a duplicate --
            see :mod:`reflow.execute.gateway` module docstring for the
            live-verified evidence behind this path.
        error_message: A human-readable failure summary, present only for
            :attr:`ExecutionOutcome.FAILED`.
        error_detail: The full transport-captured error body -- including
            any ``field``/``source``/``step``/``reason``/``metadata`` the
            installed SDK's own exception classes discard -- present only
            for :attr:`ExecutionOutcome.FAILED`.
        note: A free-text disclosure, e.g. why a no-op action needed no API
            call, or why a requested method restriction could not be
            honoured.
    """

    outcome: ExecutionOutcome
    action: Action
    dry_run: bool
    reference_id: str | None
    request: dict[str, Any] | None
    request_headers: dict[str, str]
    response: dict[str, Any] | None
    short_url: str | None
    payment_link_id: str | None
    http_status: int | None
    latency_ms: float | None
    retry_count: int
    idempotent_replay: bool
    error_message: str | None
    error_detail: dict[str, Any] | None
    note: str | None


def execution_record_to_dict(record: ExecutionRecord) -> dict[str, Any]:
    """Serialise an :class:`ExecutionRecord` to a JSON-safe dict.

    Args:
        record: The record to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``.
    """
    return {
        "outcome": record.outcome.value,
        "action": record.action.value,
        "dry_run": record.dry_run,
        "reference_id": record.reference_id,
        "request": record.request,
        "request_headers": record.request_headers,
        "response": record.response,
        "short_url": record.short_url,
        "payment_link_id": record.payment_link_id,
        "http_status": record.http_status,
        "latency_ms": record.latency_ms,
        "retry_count": record.retry_count,
        "idempotent_replay": record.idempotent_replay,
        "error_message": record.error_message,
        "error_detail": record.error_detail,
        "note": record.note,
    }
