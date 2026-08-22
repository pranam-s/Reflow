"""The synthetic failed-payment event model and its core assembly logic.

:func:`build_event` is the single function that turns a drawn
``(method, reason)`` pair plus a timestamp into a fully populated
:class:`PaymentEvent`, including a plausible ``(code, source, step)``
attribution and a rendered, noisy description. It is deliberately kept
separate from *scheduling* (deciding how many events, at what times, with
which reasons -- see :mod:`reflow.corpus.generator`), so that determinism
and streaming behaviour live in one place and event content lives in
another.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime

from reflow.corpus.descriptions import (
    generate_noise_tokens,
    render_narrow_description,
    render_subcause_description,
)
from reflow.corpus.reasons import CATCH_ALL_SUBCAUSES
from reflow.corpus.tokens import random_amount_paise, random_card_bin, random_vpa
from reflow.taxonomy.methods import (
    ErrorCode,
    ErrorSource,
    ErrorStep,
    PaymentMethod,
    UpiFlow,
    steps_for_method,
)
from reflow.taxonomy.reasons import ReasonRecord
from reflow.taxonomy.remediation import RemediationClass

_SYSTEM_SIDE_SOURCE_BY_METHOD: dict[PaymentMethod, ErrorSource] = {
    PaymentMethod.CARD: ErrorSource.ISSUER_BANK,
    PaymentMethod.UPI: ErrorSource.NETWORK,
    PaymentMethod.NETBANKING: ErrorSource.ISSUER_BANK,
    PaymentMethod.WALLET: ErrorSource.ISSUER,
    PaymentMethod.CARDLESS_EMI: ErrorSource.ISSUER,
    PaymentMethod.EMANDATE: ErrorSource.ISSUER_BANK,
}
"""Best available same-method analog for "the failure is attributable to a
system on the payment rail, not to the customer, merchant, or Razorpay"."""

_CUSTOMER_ATTRIBUTED_CLASSES = frozenset(
    {RemediationClass.CUSTOMER_FIX, RemediationClass.CUSTOMER_CONTACT_ISSUER_BANK}
)


def infer_error_code(reason: str, explanation: str) -> ErrorCode:
    """Infer a plausible top-level ``code`` for a reason.

    Args:
        reason: The reason code.
        explanation: The reason's vendored ``Explanation`` text.

    Returns:
        :attr:`ErrorCode.SERVER_ERROR` for ``server_error`` itself or any
        explanation naming Razorpay's own server; :attr:`ErrorCode.GATEWAY_ERROR`
        for explanations describing a technical failure at the gateway, an
        issuing/beneficiary bank, or a core banking system; otherwise
        :attr:`ErrorCode.BAD_REQUEST_ERROR` (the default for customer-input
        and merchant-integration reasons, which is also Razorpay's own
        documented default for client-side request issues).
    """
    lowered = explanation.lower()
    if reason == "server_error" or "razorpay's server" in lowered:
        return ErrorCode.SERVER_ERROR
    technical_markers = ("technical error", "downtime", "gateway", "core banking system", "cbs")
    if any(marker in lowered for marker in technical_markers):
        return ErrorCode.GATEWAY_ERROR
    return ErrorCode.BAD_REQUEST_ERROR


def infer_source(remediation_class: RemediationClass | None, method: PaymentMethod) -> ErrorSource:
    """Infer a plausible ``source`` attribution for a reason.

    Args:
        remediation_class: The reason's unambiguous remediation class, or
            ``None`` if the taxonomy found it ambiguous.
        method: The payment method of the event.

    Returns:
        :attr:`ErrorSource.CUSTOMER` for customer-attributed remediation
        classes, :attr:`ErrorSource.BUSINESS` for merchant-integration
        fixes, :attr:`ErrorSource.INTERNAL` for reasons requiring Razorpay
        contact, and the method's system-side analog
        (:data:`_SYSTEM_SIDE_SOURCE_BY_METHOD`) for everything else,
        including ambiguous reasons -- the corpus does not guess which of
        an ambiguous reason's candidate classes applies.
    """
    if remediation_class in _CUSTOMER_ATTRIBUTED_CLASSES:
        return ErrorSource.CUSTOMER
    if remediation_class is RemediationClass.MERCHANT_ACTION:
        return ErrorSource.BUSINESS
    if remediation_class is RemediationClass.MERCHANT_CONTACT_RAZORPAY:
        return ErrorSource.INTERNAL
    return _SYSTEM_SIDE_SOURCE_BY_METHOD[method]


_STEP_KEYWORD_RULES: tuple[tuple[str, ErrorStep], ...] = (
    ("capture", ErrorStep.PAYMENT_CAPTURE),
    ("enroll", ErrorStep.CARD_ENROLLMENT_CHECK),
    ("eligib", ErrorStep.PAYMENT_ELIGIBILITY_CHECK),
    ("mandate", ErrorStep.MANDATE_CREATION),
    ("authoris", ErrorStep.PAYMENT_AUTHORIZATION),
    ("authoriz", ErrorStep.PAYMENT_AUTHORIZATION),
    ("authenticat", ErrorStep.PAYMENT_AUTHENTICATION),
    ("otp", ErrorStep.PAYMENT_AUTHENTICATION),
    ("pin", ErrorStep.PAYMENT_AUTHENTICATION),
    ("refund", ErrorStep.REFUND_REQUEST),
)
"""Ordered keyword -> step rules, checked against the lowercased
explanation text. Order matters: more specific keywords are listed first.
This is a modelling heuristic, not a documented Razorpay mapping --
Razorpay does not publish a reason-to-step table, so this repository
cannot verify it against a source of truth (see Phase 1 report)."""


def infer_step(explanation: str, method: PaymentMethod, upi_flow: UpiFlow | None) -> ErrorStep:
    """Infer a plausible ``step`` for a reason, valid for ``method``.

    Args:
        explanation: The reason's vendored ``Explanation`` text.
        method: The payment method of the event.
        upi_flow: The UPI sub-flow, required and only used when
            ``method`` is :attr:`PaymentMethod.UPI`.

    Returns:
        The first keyword-matched :class:`ErrorStep` that is valid for
        ``method`` (and ``upi_flow``, for UPI's Collect-vs-Intent
        authentication step naming), or :attr:`ErrorStep.PAYMENT_INITIATION`
        if no keyword matches or the matched step is not valid for the
        method -- a safe default, since every method's step vocabulary
        includes it.
    """
    valid_steps = steps_for_method(method, upi_flow=upi_flow)
    lowered = explanation.lower()
    for keyword, step in _STEP_KEYWORD_RULES:
        if keyword not in lowered:
            continue
        if step is ErrorStep.PAYMENT_AUTHENTICATION and method is PaymentMethod.UPI:
            if upi_flow is UpiFlow.COLLECT:
                return ErrorStep.PAYMENT_AUTHENTICATION_REQUEST
            return ErrorStep.PAYMENT_AUTHENTICATION
        if step in valid_steps:
            return step
    return ErrorStep.PAYMENT_INITIATION


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    """One synthetic failed Razorpay payment.

    Attributes:
        payment_id: Razorpay-style payment id.
        order_id: Razorpay-style order id.
        amount: Transaction amount, in paise.
        method: The payment method used.
        created_at: When the payment attempt was made.
        customer_id: Synthetic customer id (repeats across retries).
        attempt_number: 1-based attempt number for this customer/order.
        bank: Counterparty institution name, populated for every event
            (see :mod:`reflow.corpus.descriptions` for the documented
            simplification of reusing bank names as a generic institution
            stand-in for Wallet/Cardless EMI).
        vpa: Synthetic UPI VPA, populated only when ``method`` is UPI.
        card_bin: Synthetic card BIN, populated only when ``method`` is Card.
        error_code: Top-level error classification (ground truth).
        error_source: Error source attribution (ground truth).
        error_step: Payment lifecycle step (ground truth).
        error_reason: The vendored reason code (ground truth).
        description: Rendered, noisy failure description.
        latent_subcause_id: Ground-truth hidden sub-cause id, populated
            only when ``error_reason`` is one of
            :data:`reflow.corpus.reasons.CATCH_ALL_REASONS`; ``None`` for
            narrow reasons, which genuinely have only one cause.
        description_variant: Ground truth for which surface wording
            produced ``description``: ``"canonical"``,
            ``"paraphrase_wording"``, ``"paraphrase_reordered"``, or,
            when ``variant_richness`` was requested for a catch-all
            reason's latent sub-cause, additionally
            ``"paraphrase_verbose"`` or ``"paraphrase_terse"``. See
            :mod:`reflow.corpus.descriptions` module docstring.
        is_outlier: Ground truth marking this event's ``(method,
            error_reason)`` as a genuine singleton/rare occurrence in the
            generated corpus -- a real one-off failure a density-based
            method could legitimately call noise, not a cluster. Never
            ``True`` for a :data:`reflow.corpus.reasons.CATCH_ALL_REASONS`
            reason, since those are deliberately substantial, multi-cause
            clusters by construction, not one-offs.
        downtime_window_id: Ground-truth id of the outage window this
            event belongs to, or ``None`` for an ordinary, uncorrelated
            failure.
        split: ``"train"`` or ``"test"``, assigned by
            :mod:`reflow.corpus.split`.
    """

    payment_id: str
    order_id: str
    amount: int
    method: PaymentMethod
    created_at: datetime
    customer_id: str
    attempt_number: int
    bank: str
    vpa: str | None
    card_bin: str | None
    error_code: ErrorCode
    error_source: ErrorSource
    error_step: ErrorStep
    error_reason: str
    description: str
    latent_subcause_id: str | None
    description_variant: str
    is_outlier: bool
    downtime_window_id: str | None
    split: str

    @property
    def ground_truth(self) -> tuple[ErrorCode, ErrorSource, ErrorStep, str]:
        """The ``(code, source, step, reason)`` ground-truth tuple.

        Returns:
            The four-element tuple later phases can use as the trivial
            ``GROUP BY`` baseline to beat.
        """
        return (self.error_code, self.error_source, self.error_step, self.error_reason)


def build_event(
    rng: random.Random,
    reason_record: ReasonRecord,
    remediation_class: RemediationClass | None,
    method: PaymentMethod,
    upi_flow: UpiFlow | None,
    created_at: datetime,
    customer_id: str,
    attempt_number: int,
    downtime_window_id: str | None,
    forced_bank: str | None = None,
    forced_order_id: str | None = None,
    is_outlier: bool = False,
    variant_richness: int | None = None,
) -> PaymentEvent:
    """Assemble one fully populated :class:`PaymentEvent`.

    Args:
        rng: Deterministic random source.
        reason_record: The reason record (code + explanation) this event
            represents.
        remediation_class: The reason's unambiguous remediation class, or
            ``None`` if ambiguous; used only to inform :func:`infer_source`.
        method: The payment method for this event.
        upi_flow: The UPI sub-flow, required when ``method`` is UPI.
        created_at: This event's timestamp.
        customer_id: The customer this event is attributed to.
        attempt_number: 1-based attempt number for this customer/order.
        downtime_window_id: The outage window id this event belongs to, or
            ``None`` for an ordinary background failure.
        forced_bank: When given, overrides the randomly drawn institution
            name. Used so every event inside one downtime window
            consistently names the same bank, rather than each event in a
            single incident randomly naming a different one.
        forced_order_id: When given, overrides the randomly drawn order
            id. Used so a retry chain (``attempt_number`` > 1) reuses the
            same order id as the attempt it is retrying.
        is_outlier: Ground-truth flag computed by the scheduler
            (:mod:`reflow.corpus.generator`) from this event's realized
            ``(method, reason)`` frequency across the whole generated
            corpus; passed through unchanged onto the returned event.
        variant_richness: Forwarded to
            :func:`reflow.corpus.descriptions.render_subcause_description`
            when ``reason_record.reason`` is a catch-all reason; ignored
            for narrow reasons. ``None`` (the default) reproduces
            pre-Phase-1b rendering exactly.

    Returns:
        A fully populated :class:`PaymentEvent` with ``split`` left unset
        (set later by :mod:`reflow.corpus.split`, which needs the full
        generated sequence to assign consistently); callers should treat
        the returned event's ``split`` field as a placeholder value of
        ``"unassigned"``.
    """
    amount = random_amount_paise(rng)
    noise = generate_noise_tokens(rng, created_at=created_at, amount_paise=amount)
    if forced_bank is not None:
        noise = replace(noise, bank=forced_bank)
    if forced_order_id is not None:
        noise = replace(noise, order_id=forced_order_id)

    reason = reason_record.reason
    if reason in CATCH_ALL_SUBCAUSES:
        subcauses = CATCH_ALL_SUBCAUSES[reason]
        subcause = rng.choices(subcauses, weights=[s.weight for s in subcauses], k=1)[0]
        description, description_variant = render_subcause_description(
            subcause, noise, rng, variant_richness=variant_richness
        )
        latent_subcause_id = subcause.subcause_id
    else:
        description, description_variant = render_narrow_description(
            reason, reason_record.explanation, method, noise, rng
        )
        latent_subcause_id = None

    error_code = infer_error_code(reason, reason_record.explanation)
    error_source = infer_source(remediation_class, method)
    error_step = infer_step(reason_record.explanation, method, upi_flow)

    return PaymentEvent(
        payment_id=noise.payment_id,
        order_id=noise.order_id,
        amount=amount,
        method=method,
        created_at=created_at,
        customer_id=customer_id,
        attempt_number=attempt_number,
        bank=noise.bank,
        vpa=random_vpa(rng) if method is PaymentMethod.UPI else None,
        card_bin=random_card_bin(rng) if method is PaymentMethod.CARD else None,
        error_code=error_code,
        error_source=error_source,
        error_step=error_step,
        error_reason=reason,
        description=description,
        latent_subcause_id=latent_subcause_id,
        description_variant=description_variant,
        is_outlier=is_outlier,
        downtime_window_id=downtime_window_id,
        split="unassigned",
    )
