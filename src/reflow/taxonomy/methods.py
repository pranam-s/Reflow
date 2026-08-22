"""Payment-method-scoped error vocabulary.

Razorpay's error object carries a top-level ``code`` drawn from a small,
method-independent set, plus ``source`` and ``step`` values whose legal
vocabulary depends on which payment method the failed payment used. This
module encodes that vocabulary as verified on
<https://razorpay.com/docs/errors/payments/payment-methods-error-parameters/>.

Verification notes (spot-checked 2026-08-22 against the live page via
fetch, since :mod:`CLAUDE.md` requires live-doc confirmation rather than
recall):

- The ``source`` enumeration for every method below (Cards, UPI, Netbanking,
  Wallet, Cardless EMI, Emandate) matches the brief's starting point exactly;
  the live page lists these as plain bullet lists and they were reproduced
  verbatim.
- The ``step`` enumeration is **not** independently verifiable from the live
  page: Razorpay renders per-method steps as flow diagrams (images), not as
  extractable text, so the fetched page yielded no bullet list to check
  against. The step lists below are therefore taken from the brief's
  starting point as given, not independently re-derived from a second
  source. This is called out explicitly rather than silently presented as
  independently verified.
- The live UPI documentation additionally states that NPCI is deprecating
  the UPI Collect flow for new integrations effective 2026-02-28 (i.e.
  already past, relative to this repository's 2026-08-22 build date), in
  favour of UPI Intent. :mod:`reflow.corpus` reflects this by weighting
  Collect-flow events far below Intent-flow events rather than treating the
  two as equally likely.
- One live-fetched sample webhook payload in Razorpay's own docs uses
  ``"error_source": "bank"`` for what reads as a generic/illustrative
  example. ``"bank"`` is not a valid ``source`` value for any method except
  Emandate (which distinguishes ``bank`` from ``issuer_bank``). This
  suggests Razorpay's own example payloads are not always drawn from a
  method-consistent enumeration; :mod:`reflow.taxonomy.signal` therefore
  does not attempt to hard-validate ``source``/``step`` against the
  per-method sets in this module -- it only validates that the two wire
  shapes normalise to one internal shape, per the Phase 1 brief.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ErrorCode(StrEnum):
    """Top-level ``error.code`` values, method-independent.

    Verified 2026-08-22 against <https://razorpay.com/docs/errors/common/>
    (documents ``BAD_REQUEST_ERROR`` and ``SERVER_ERROR`` explicitly) and a
    web search of Razorpay's own error documentation corroborating
    ``GATEWAY_ERROR`` ("occurs when the request could not be completed due
    to an error at the payment gateway or downstream bank"), which the
    ``/errors/common/`` page itself does not enumerate. No fourth value was
    found in any consulted source.
    """

    BAD_REQUEST_ERROR = "BAD_REQUEST_ERROR"
    GATEWAY_ERROR = "GATEWAY_ERROR"
    SERVER_ERROR = "SERVER_ERROR"


class PaymentMethod(StrEnum):
    """Payment methods with a distinct ``source``/``step`` vocabulary."""

    CARD = "card"
    UPI = "upi"
    NETBANKING = "netbanking"
    WALLET = "wallet"
    CARDLESS_EMI = "cardless_emi"
    EMANDATE = "emandate"


class ErrorSource(StrEnum):
    """Union of every ``source`` value used by any payment method.

    Membership in a specific method's vocabulary is given by
    :data:`SOURCES_BY_METHOD`, not by this enum alone.
    """

    CUSTOMER = "customer"
    BUSINESS = "business"
    INTERNAL = "internal"
    GATEWAY = "gateway"
    ISSUER_BANK = "issuer_bank"
    CUSTOMER_PSP = "customer_psp"
    NETWORK = "network"
    BENEFICIARY_BANK = "beneficiary_bank"
    ISSUER = "issuer"
    BANK = "bank"


class ErrorStep(StrEnum):
    """Union of every ``step`` value used by any payment method or flow.

    Membership in a specific method's (or UPI flow's) vocabulary is given by
    :data:`STEPS_BY_METHOD` and :data:`UPI_STEPS_BY_FLOW`, not by this enum
    alone.
    """

    PAYMENT_INITIATION = "payment_initiation"
    CARD_ENROLLMENT_CHECK = "card_enrollment_check"
    PAYMENT_AUTHENTICATION = "payment_authentication"
    PAYMENT_AUTHORIZATION = "payment_authorization"
    PAYMENT_CAPTURE = "payment_capture"
    MANDATE_CREATION = "mandate_creation"
    PAYMENT_CREATION = "payment_creation"
    PAYMENT_REQUEST = "payment_request"
    PAYMENT_REQUEST_BENEFICIARY_DETAILS = "payment_request_beneficiary_details"
    PAYMENT_RESPONSE_BENEFICIARY_DETAILS = "payment_response_beneficiary_details"
    PAYMENT_DEBIT_REQUEST = "payment_debit_request"
    PAYMENT_DEBIT_RESPONSE = "payment_debit_response"
    PAYMENT_CREDIT_REQUEST = "payment_credit_request"
    PAYMENT_CREDIT_RESPONSE = "payment_credit_response"
    PAYMENT_STATUS_REQUEST = "payment_status_request"
    PAYMENT_STATUS_RESPONSE = "payment_status_response"
    PAYMENT_RESPONSE = "payment_response"
    REFUND_REQUEST = "refund_request"
    PAYMENT_AUTHENTICATION_REQUEST = "payment_authentication_request"
    PAYMENT_AUTHENTICATION_RESPONSE = "payment_authentication_response"
    PAYMENT_ELIGIBILITY_CHECK = "payment_eligibility_check"


class UpiFlow(StrEnum):
    """UPI-specific sub-flows, which use slightly different step vocabularies."""

    INTENT = "intent"
    COLLECT = "collect"


SOURCES_BY_METHOD: Final[dict[PaymentMethod, frozenset[ErrorSource]]] = {
    PaymentMethod.CARD: frozenset(
        {
            ErrorSource.CUSTOMER,
            ErrorSource.BUSINESS,
            ErrorSource.INTERNAL,
            ErrorSource.GATEWAY,
            ErrorSource.ISSUER_BANK,
        }
    ),
    PaymentMethod.UPI: frozenset(
        {
            ErrorSource.CUSTOMER,
            ErrorSource.BUSINESS,
            ErrorSource.INTERNAL,
            ErrorSource.CUSTOMER_PSP,
            ErrorSource.GATEWAY,
            ErrorSource.NETWORK,
            ErrorSource.ISSUER_BANK,
            ErrorSource.BENEFICIARY_BANK,
        }
    ),
    PaymentMethod.NETBANKING: frozenset(
        {
            ErrorSource.CUSTOMER,
            ErrorSource.BUSINESS,
            ErrorSource.INTERNAL,
            ErrorSource.ISSUER_BANK,
        }
    ),
    PaymentMethod.WALLET: frozenset(
        {
            ErrorSource.CUSTOMER,
            ErrorSource.BUSINESS,
            ErrorSource.INTERNAL,
            ErrorSource.ISSUER,
        }
    ),
    PaymentMethod.CARDLESS_EMI: frozenset(
        {
            ErrorSource.CUSTOMER,
            ErrorSource.BUSINESS,
            ErrorSource.INTERNAL,
            ErrorSource.NETWORK,
            ErrorSource.ISSUER,
        }
    ),
    PaymentMethod.EMANDATE: frozenset(
        {
            ErrorSource.CUSTOMER,
            ErrorSource.BANK,
            ErrorSource.BUSINESS,
            ErrorSource.INTERNAL,
            ErrorSource.GATEWAY,
            ErrorSource.ISSUER_BANK,
        }
    ),
}

STEPS_BY_METHOD: Final[dict[PaymentMethod, frozenset[ErrorStep]]] = {
    PaymentMethod.CARD: frozenset(
        {
            ErrorStep.PAYMENT_INITIATION,
            ErrorStep.CARD_ENROLLMENT_CHECK,
            ErrorStep.PAYMENT_AUTHENTICATION,
            ErrorStep.PAYMENT_AUTHORIZATION,
            ErrorStep.PAYMENT_CAPTURE,
        }
    ),
    PaymentMethod.NETBANKING: frozenset(
        {
            ErrorStep.PAYMENT_INITIATION,
            ErrorStep.PAYMENT_AUTHENTICATION,
            ErrorStep.PAYMENT_AUTHORIZATION,
        }
    ),
    PaymentMethod.WALLET: frozenset(
        {
            ErrorStep.PAYMENT_INITIATION,
            ErrorStep.PAYMENT_ELIGIBILITY_CHECK,
            ErrorStep.PAYMENT_AUTHENTICATION,
            ErrorStep.PAYMENT_AUTHORIZATION,
        }
    ),
    PaymentMethod.CARDLESS_EMI: frozenset(
        {
            ErrorStep.PAYMENT_INITIATION,
            ErrorStep.PAYMENT_ELIGIBILITY_CHECK,
            ErrorStep.PAYMENT_AUTHENTICATION,
            ErrorStep.PAYMENT_AUTHORIZATION,
        }
    ),
    PaymentMethod.EMANDATE: frozenset(
        {
            ErrorStep.PAYMENT_INITIATION,
            ErrorStep.PAYMENT_AUTHENTICATION,
            ErrorStep.PAYMENT_AUTHORIZATION,
        }
    ),
}
"""Step vocabulary per method, for every method except UPI.

UPI's step vocabulary additionally depends on the Collect-vs-Intent flow, so
it is modelled separately in :data:`UPI_STEPS_BY_FLOW` rather than folded
into this dict under a single :attr:`PaymentMethod.UPI` key.
"""

_UPI_COMMON_STEPS: Final[frozenset[ErrorStep]] = frozenset(
    {
        ErrorStep.MANDATE_CREATION,
        ErrorStep.PAYMENT_INITIATION,
        ErrorStep.PAYMENT_CREATION,
        ErrorStep.PAYMENT_REQUEST,
        ErrorStep.PAYMENT_REQUEST_BENEFICIARY_DETAILS,
        ErrorStep.PAYMENT_RESPONSE_BENEFICIARY_DETAILS,
        ErrorStep.PAYMENT_DEBIT_REQUEST,
        ErrorStep.PAYMENT_DEBIT_RESPONSE,
        ErrorStep.PAYMENT_CREDIT_REQUEST,
        ErrorStep.PAYMENT_CREDIT_RESPONSE,
        ErrorStep.PAYMENT_STATUS_REQUEST,
        ErrorStep.PAYMENT_STATUS_RESPONSE,
        ErrorStep.PAYMENT_RESPONSE,
        ErrorStep.REFUND_REQUEST,
    }
)

UPI_STEPS_BY_FLOW: Final[dict[UpiFlow, frozenset[ErrorStep]]] = {
    UpiFlow.INTENT: _UPI_COMMON_STEPS | {ErrorStep.PAYMENT_AUTHENTICATION},
    UpiFlow.COLLECT: _UPI_COMMON_STEPS
    | {
        ErrorStep.PAYMENT_AUTHENTICATION_REQUEST,
        ErrorStep.PAYMENT_AUTHENTICATION_RESPONSE,
    },
}
"""UPI step vocabulary, keyed by sub-flow.

Per the brief: "UPI Collect substitutes payment_authentication_request /
payment_authentication_response for payment_authentication" relative to the
Intent flow; every other UPI step is shared between the two flows.
"""


def steps_for_method(
    method: PaymentMethod, upi_flow: UpiFlow | None = None
) -> frozenset[ErrorStep]:
    """Return the valid ``step`` vocabulary for a payment method.

    Args:
        method: The payment method whose step vocabulary is requested.
        upi_flow: Required when ``method`` is :attr:`PaymentMethod.UPI`,
            since UPI's step vocabulary depends on whether the payment used
            the Collect or Intent flow. Ignored for every other method.

    Returns:
        The frozenset of :class:`ErrorStep` values valid for ``method``
        (and, for UPI, ``upi_flow``).

    Raises:
        ValueError: If ``method`` is :attr:`PaymentMethod.UPI` and
            ``upi_flow`` is ``None``.
    """
    if method is PaymentMethod.UPI:
        if upi_flow is None:
            raise ValueError("upi_flow is required when method is PaymentMethod.UPI.")
        return UPI_STEPS_BY_FLOW[upi_flow]
    return STEPS_BY_METHOD[method]
