"""Per-method reason pools, Zipf-shaped weights, and catch-all sub-causes.

This module turns the 110 unique reason codes in the vendored taxonomy
(114 rows, 4 repeated codes -- see :mod:`reflow.taxonomy.reasons`) into,
for each payment method, a Zipf-like weighted distribution suitable for
sampling a synthetic corpus. Two design decisions matter enough to justify
here rather than only in code comments (which this repository forbids):

**Method affinity.** Roughly 60% of the 110 reasons name a specific
payment method or an unambiguous method-specific mechanism in their
vendored ``Explanation`` text (e.g. "This error occurs in Cardless EMI
payments", or PIN-retry language that only makes sense for a physical
card). Those are grouped into explicit, hand-reviewed, dominance-ordered
tuples per method below. The remaining ~40% describe a mechanism with no
method-specific signal in the text (timeouts, validation failures,
duplicate requests, risk holds, ...) and are treated as **generic**:
available to every method, appended as the long tail after each method's
specific reasons. A handful of vendored reasons use generic "bank account"
/ "beneficiary" language that plausibly applies to either Netbanking or
Emandate with no textual way to tell which -- these are pooled under both
rather than arbitrarily assigned to one.

**Catch-all reasons and latent sub-causes.** Per the corpus design
addendum: a `GROUP BY reason` baseline can trivially separate every
*narrow* reason (one mechanism each, by construction -- see module
docstring of :mod:`reflow.corpus.descriptions`). It structurally cannot
separate the sub-causes hiding inside a handful of *catch-all* reasons,
because the vendored spreadsheet itself collapses several distinct
mechanisms into one reason code. Two of the vendored ``Explanation`` texts
say this outright -- ``card_declined`` ("multiple checks at their end...
exact reason is not shared with Razorpay") and ``payment_declined``
("due to business or technical reasons... not communicated to Razorpay")
-- and four more describe a generic technical failure with no further
detail (``payment_failed``, ``server_error``, ``bank_technical_error``,
``gateway_technical_error``). ``issuer_technical_error`` and
``debit_declined`` round out the set on the same basis (generic
issuer-side technical failure; bank decline with only one example cause
given, "one of the reasons can be ..."). :data:`CATCH_ALL_REASONS` is
exactly these 8 of 110 unique reasons (7.3%) -- **not** tuned to make
clustering look good; it is exactly the set the vendored text itself marks
as coarse. Every other reason is narrow by the vendored text's own
account, and is given exactly one implicit sub-cause rather than invented
ambiguity.

**Second addendum: discriminating between clustering approaches, not just
beating the ``GROUP BY`` baseline.** :data:`NARROW_REASON_ALT_PHRASINGS`
and each catch-all sub-cause's optional ``paraphrase`` add paraphrase and
clause-reordering variants (see :class:`DescriptionVariant`). A further
property -- "distinct sub-causes with heavy vocabulary overlap" -- needed
no new code: it already occurs naturally among several narrow reasons,
because the vendored spreadsheet itself gives near-duplicate ``Explanation``
text to genuinely different reason codes. Concretely: ``credit_not_permitted``
and ``credit_failed`` differ by a single word ("has not allowed" is
identical; "TPV account mismatch" vs "the TPV account mismatch"; the
reason names differ but the rendered descriptions barely do);
``otp_attempts_exceeded`` and ``pin_attempts_exceeded`` share their entire
sentence structure and differ only in "OTP" vs "PIN"; and
``mandate_creation_declined`` / ``_expired`` / ``_failed`` / ``_timeout``
are four distinct reasons whose vendored ``Explanation`` text differs by
one word each ("failed" / "expired" / "declined" / "timed out"). These are
not manufactured -- they are exactly what the vendored data already
contains, surfaced rather than smoothed over. See the Phase 1 report for
the full accounting of which discriminating properties this corpus
implements, at what share, and an honest assessment of whether it is
enough to separate three clustering algorithms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from reflow.taxonomy.methods import PaymentMethod
from reflow.taxonomy.reasons import ReasonRecord

CARD_ONLY: Final[tuple[str, ...]] = (
    "card_declined",
    "incorrect_cvv",
    "incorrect_pin",
    "card_expired",
    "incorrect_card_expiry_date",
    "card_number_invalid",
    "incorrect_card_details",
    "otp_attempts_exceeded",
    "pin_attempts_exceeded",
    "debit_instrument_blocked",
    "debit_instrument_inactive",
    "transaction_limit_exceeded",
    "transaction_daily_limit_exceeded",
    "transaction_daily_count_exceeded",
    "incorrect_cardholder_name",
    "card_not_enrolled",
    "card_type_invalid",
    "capture_failed",
    "card_network_not_enabled",
)
"""Card-only reasons, most-plausible-first. ``card_declined`` leads because
issuer risk declines are, in practice, the single most common card failure
mode; PIN/CVV/expiry entry errors follow as the next most common
customer-input mistakes."""

UPI_ONLY: Final[tuple[str, ...]] = (
    "psp_not_available",
    "invalid_vpa",
    "pin_not_set",
    "authorisation_declined_by_psp",
    "transaction_on_vpa_restricted",
    "vpa_resolution_failed",
    "upi_app_technical_error",
    "psp_app_not_supported",
    "psp_not_registered",
    "psp_app_ not_available",
    "mobile_number_invalid",
    "collect_request_pending",
    "payment_collect_request_expired",
    "invalid_device",
    "transaction_frequency_limit_exceeded",
    "mcc_amount_limit_exceeded",
    "collect_on_mcc_blocked",
    "incorrect_atm_pin",
    "upi_collect_not_enabled",
    "upi_intent_not_enabled",
    "upi_autopay_not_supported_on_psp",
    "mandate_creation_failed",
    "mandate_creation_declined",
    "mandate_creation_expired",
    "mandate_creation_timeout",
    "reqauth_mandate_not_acknowledged",
    "funds_blocked_by_mandate",
)
"""UPI-only reasons, most-plausible-first. PSP-app downtime and VPA
mistakes dominate real UPI failure traffic; UPI Autopay/OTM mandate
mechanics form a smaller, rarer long tail within UPI itself."""

WALLET_ONLY: Final[tuple[str, ...]] = ("invalid_mobile_number",)
"""The single reason whose vendored Explanation names Wallet payments
explicitly."""

CARDLESS_EMI_ONLY: Final[tuple[str, ...]] = (
    "user_not_eligible",
    "credit_limit_exceeded",
    "emi_plan_unavailable",
    "credit_limit_inactive",
    "credit_limit_expired",
    "credit_limit_not_approved",
    "emi_greater_than_max_amount",
)
"""Cardless EMI reasons, most-plausible-first: eligibility and credit-limit
checks are the dominant real-world failure point for this method."""

BANK_METHODS: Final[tuple[str, ...]] = (
    "bank_not_available",
    "bank_technical_error",
    "bank_account_invalid",
    "debit_declined",
    "bank_cutoff_in_progress",
    "credit_failed",
    "credit_not_permitted",
    "bank_account_validation_failed",
    "user_not_registered_for_netbanking",
    "beneficiary_account_does_not_exist",
    "beneficiary_account_dormant",
    "bank_not_enabled",
    "mismatch_in_transaction_details",
)
"""Reasons pooled for both Netbanking and Emandate, since their vendored
text uses generic "bank account" / "beneficiary" / "CBS" language with no
way to tell the two direct-bank-debit methods apart. One reason in this
tuple, ``user_not_registered_for_netbanking``, is strictly Netbanking-only
by name; it is still pooled here for Emandate too on the basis that an
equivalent "not registered for this bank-debit method" failure is
realistic for Emandate as well, even though the vendored text does not
name it -- a documented simplification, not a discovered fact."""

CATCH_ALL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "payment_failed",
        "server_error",
        "bank_technical_error",
        "gateway_technical_error",
        "card_declined",
        "payment_declined",
        "issuer_technical_error",
        "debit_declined",
    }
)
"""The 8 of 110 unique reasons (7.3%) whose vendored text is itself coarse
-- see module docstring for the textual justification for each."""


@dataclass(frozen=True, slots=True)
class DescriptionVariant:
    """One alternate surface wording for an otherwise-fixed ground truth.

    Used to implement two of the discriminating properties the Phase 1
    corpus-design addendum requires: paraphrasing (different vocabulary,
    same meaning) and clause reordering (same vocabulary, different
    order). Both keep the underlying ground truth (reason, or
    ``latent_subcause_id``) identical -- only the rendered text and this
    variant's ``label`` differ.

    Attributes:
        text: A ``str.format``-style description template.
        label: ``"paraphrase_wording"`` or ``"paraphrase_reordered"``,
            recorded on the generated event as ``description_variant`` so
            later phases can slice evaluation by which surface phenomenon
            was exercised.
    """

    text: str
    label: str


@dataclass(frozen=True, slots=True)
class LatentSubcause:
    """One hidden mechanism behind a catch-all reason.

    Attributes:
        subcause_id: Stable identifier, unique within one catch-all
            reason's sub-cause tuple. Recorded as ground truth on
            generated events so later phases can measure whether
            clustering recovers this split.
        weight: Relative sampling weight among sibling sub-causes for the
            same reason. Not required to be uniform: real latent causes
            are not equally likely either.
        template: A ``str.format``-style description template, rendered
            via :func:`reflow.corpus.descriptions.render_subcause_description`.
            Deliberately shares sentence structure and vocabulary with its
            sibling templates (see module docstring of
            :mod:`reflow.corpus.descriptions`) so that separability is a
            function of masking quality, not of trivially distinct wording.
        paraphrase: An optional alternate wording of the same sub-cause
            (see :class:`DescriptionVariant`), rendered instead of
            ``template`` a minority of the time. ``None`` for sub-causes
            that are always rendered canonically.
    """

    subcause_id: str
    weight: float
    template: str
    paraphrase: DescriptionVariant | None = None


CATCH_ALL_SUBCAUSES: Final[dict[str, tuple[LatentSubcause, ...]]] = {
    "payment_failed": (
        LatentSubcause(
            "gateway_no_response",
            0.35,
            "Payment processing failed because the gateway received no response "
            "from {bank} for payment {payment_id} within the expected window, so "
            "the request timed out before authorization completed.",
            paraphrase=DescriptionVariant(
                "For payment {payment_id}, the gateway received no response from "
                "{bank} within the expected window before authorization could "
                "complete, so the request timed out.",
                "paraphrase_reordered",
            ),
        ),
        LatentSubcause(
            "bank_soft_decline",
            0.30,
            "Payment processing failed after {bank} returned a decline for "
            "payment {payment_id} without a specific reason code; the gateway "
            "received only a generic failure status from the bank.",
        ),
        LatentSubcause(
            "network_drop",
            0.20,
            "Payment processing failed because the customer's connection dropped "
            "during authorization for payment {payment_id}; the gateway could "
            "not confirm whether {bank} completed the debit before the session "
            "ended.",
        ),
        LatentSubcause(
            "risk_engine_block",
            0.15,
            "Payment processing failed because an automated risk check flagged "
            "payment {payment_id} for {amount_display} as suspicious, and the "
            "gateway declined it before the request reached {bank}.",
        ),
    ),
    "server_error": (
        LatentSubcause(
            "db_timeout",
            0.30,
            "A technical error occurred at Razorpay's server while processing "
            "payment {payment_id}: the payment-state datastore did not "
            "acknowledge the write within the configured timeout.",
            paraphrase=DescriptionVariant(
                "Razorpay's server hit a technical fault handling payment "
                "{payment_id}: the payment-state database failed to confirm the "
                "write before the timeout elapsed.",
                "paraphrase_wording",
            ),
        ),
        LatentSubcause(
            "queue_backlog",
            0.28,
            "A technical error occurred at Razorpay's server while processing "
            "payment {payment_id}: the internal processing queue was backlogged "
            "and the request was dropped after retries were exhausted.",
        ),
        LatentSubcause(
            "deploy_blip",
            0.22,
            "A technical error occurred at Razorpay's server while processing "
            "payment {payment_id}: a routine service deployment briefly "
            "interrupted request handling.",
        ),
        LatentSubcause(
            "dependency_failure",
            0.20,
            "A technical error occurred at Razorpay's server while processing "
            "payment {payment_id}: an internal dependency service returned an "
            "unexpected error and the request could not be completed.",
        ),
    ),
    "bank_technical_error": (
        LatentSubcause(
            "cbs_timeout",
            0.35,
            "{bank}'s core banking system did not respond to the debit request "
            "for payment {payment_id} within the timeout window.",
            paraphrase=DescriptionVariant(
                "For payment {payment_id}, {bank}'s core banking system failed to "
                "respond to the debit request inside the timeout window.",
                "paraphrase_reordered",
            ),
        ),
        LatentSubcause(
            "cbs_maintenance",
            0.25,
            "{bank}'s core banking system rejected the debit request for payment "
            "{payment_id} during an unscheduled maintenance cycle.",
        ),
        LatentSubcause(
            "cbs_overload",
            0.25,
            "{bank}'s core banking system returned a technical failure for "
            "payment {payment_id} while processing an unusually high "
            "transaction volume.",
        ),
        LatentSubcause(
            "cbs_partial_outage",
            0.15,
            "{bank} reported a technical error for payment {payment_id} from "
            "one core banking system node while other nodes continued "
            "processing normally.",
        ),
    ),
    "gateway_technical_error": (
        LatentSubcause(
            "gateway_conn_reset",
            0.30,
            "The payment gateway closed the connection to {bank} unexpectedly "
            "before authorization completed for payment {payment_id}.",
            paraphrase=DescriptionVariant(
                "For payment {payment_id}, the connection to {bank} was "
                "unexpectedly closed by the payment gateway before authorization "
                "could finish.",
                "paraphrase_wording",
            ),
        ),
        LatentSubcause(
            "gateway_cert_issue",
            0.25,
            "The payment gateway encountered a certificate validation error "
            "while establishing a secure connection to {bank} for payment "
            "{payment_id}.",
        ),
        LatentSubcause(
            "gateway_rate_limited",
            0.25,
            "The payment gateway was rate-limited by {bank} and could not "
            "complete authorization for payment {payment_id}.",
        ),
        LatentSubcause(
            "gateway_malformed_response",
            0.20,
            "The payment gateway received a malformed response from {bank} and "
            "could not parse the authorization result for payment {payment_id}.",
        ),
    ),
    "card_declined": (
        LatentSubcause(
            "issuer_risk_hold",
            0.30,
            "The issuing bank declined the card (BIN {card_bin}) for payment "
            "{payment_id} citing an internal risk hold; no further detail was "
            "shared with Razorpay.",
            paraphrase=DescriptionVariant(
                "Payment {payment_id} was declined by the issuing bank (card BIN "
                "{card_bin}) due to an internal risk hold, with no further detail "
                "shared with Razorpay.",
                "paraphrase_wording",
            ),
        ),
        LatentSubcause(
            "issuer_velocity_block",
            0.28,
            "The issuing bank declined the card (BIN {card_bin}) for payment "
            "{payment_id} due to a velocity check on recent transactions; the "
            "exact threshold was not disclosed.",
        ),
        LatentSubcause(
            "issuer_expired_or_limit",
            0.22,
            "The issuing bank declined the card (BIN {card_bin}) for payment "
            "{payment_id} without specifying whether the cause was an expired "
            "card or an exhausted limit.",
        ),
        LatentSubcause(
            "issuer_generic_decline",
            0.20,
            "The issuing bank declined the card (BIN {card_bin}) for payment "
            "{payment_id} with a generic decline code Razorpay cannot map to a "
            "specific reason.",
        ),
    ),
    "payment_declined": (
        LatentSubcause(
            "business_rule_decline",
            0.30,
            "{bank} or the gateway declined payment {payment_id} for "
            "undisclosed business reasons; Razorpay received no further detail.",
            paraphrase=DescriptionVariant(
                "For payment {payment_id}, undisclosed business reasons led "
                "{bank} or the gateway to decline the transaction; no further "
                "detail was received by Razorpay.",
                "paraphrase_reordered",
            ),
        ),
        LatentSubcause(
            "technical_decline",
            0.28,
            "{bank} or the gateway declined payment {payment_id} citing an "
            "internal technical issue, without specifying which system was "
            "responsible.",
        ),
        LatentSubcause(
            "compliance_hold_decline",
            0.22,
            "{bank} or the gateway declined payment {payment_id}, possibly due "
            "to a compliance hold; the decline reason was not communicated to "
            "Razorpay.",
        ),
        LatentSubcause(
            "capacity_decline",
            0.20,
            "{bank} or the gateway declined payment {payment_id} during a "
            "period of high processing load; the specific cause was not "
            "communicated to Razorpay.",
        ),
    ),
    "issuer_technical_error": (
        LatentSubcause(
            "issuer_auth_timeout",
            0.30,
            "{bank} experienced a technical error while authenticating payment "
            "{payment_id}, and the authentication request timed out.",
            paraphrase=DescriptionVariant(
                "Authentication for payment {payment_id} timed out after {bank} "
                "encountered a technical error during the process.",
                "paraphrase_wording",
            ),
        ),
        LatentSubcause(
            "issuer_core_glitch",
            0.28,
            "{bank} experienced a technical error in its authorization system "
            "while processing payment {payment_id}.",
        ),
        LatentSubcause(
            "issuer_connectivity",
            0.22,
            "{bank} experienced a connectivity issue with the network while "
            "authorizing payment {payment_id}.",
        ),
        LatentSubcause(
            "issuer_upi_glitch",
            0.20,
            "{bank}, acting as the issuer for payment {payment_id}, returned a "
            "technical error during the authorization step.",
        ),
    ),
    "debit_declined": (
        LatentSubcause(
            "account_blocked",
            0.30,
            "{bank} declined the debit request for payment {payment_id}; the "
            "account may have been blocked for suspected fraud.",
            paraphrase=DescriptionVariant(
                "For payment {payment_id}, {bank} declined the debit request; "
                "the account may have been blocked due to suspected fraud.",
                "paraphrase_reordered",
            ),
        ),
        LatentSubcause(
            "account_frozen_kyc",
            0.28,
            "{bank} declined the debit request for payment {payment_id}; the "
            "account may be frozen pending a KYC update.",
        ),
        LatentSubcause(
            "mandate_hold",
            0.22,
            "{bank} declined the debit request for payment {payment_id} due to "
            "an internal hold that Razorpay could not identify.",
        ),
        LatentSubcause(
            "generic_bank_decline",
            0.20,
            "{bank} declined the debit request for payment {payment_id} without "
            "specifying a reason.",
        ),
    ),
}

NARROW_REASON_ALT_PHRASINGS: Final[dict[str, DescriptionVariant]] = {
    "authentication_failed": DescriptionVariant(
        "Authentication could not be completed for this payment; the 3D secure or OTP step failed.",
        "paraphrase_wording",
    ),
    "incorrect_otp": DescriptionVariant(
        "To complete the payment, the customer entered an OTP that was incorrect.",
        "paraphrase_reordered",
    ),
    "card_expired": DescriptionVariant(
        "This payment was attempted using a card that has already expired.",
        "paraphrase_wording",
    ),
    "insufficient_funds": DescriptionVariant(
        "To complete the payment, sufficient funds were not available in the customer's account.",
        "paraphrase_reordered",
    ),
    "invalid_vpa": DescriptionVariant(
        "The VPA used for this payment is invalid or not registered with any bank.",
        "paraphrase_wording",
    ),
    "bank_not_available": DescriptionVariant(
        "Due to a downtime or technical issue, the bank could not be reached for this payment.",
        "paraphrase_reordered",
    ),
    "user_not_eligible": DescriptionVariant(
        "This customer did not pass the credit eligibility check for Cardless EMI.",
        "paraphrase_wording",
    ),
    "invalid_mobile_number": DescriptionVariant(
        "For this transaction, the mobile number used was either unregistered or invalid.",
        "paraphrase_reordered",
    ),
}
"""A deliberate minority (8 of 110) of narrow reasons that also get an
alternate phrasing at render time, implementing two of the Phase 1
corpus-design addendum's discriminating properties for a subset of narrow
(single-sub-cause) reasons, not only for catch-all sub-causes: paraphrasing
(different vocabulary, same meaning -- ``authentication_failed``,
``card_expired``, ``invalid_vpa``, ``user_not_eligible``) and clause
reordering (same vocabulary, different order -- ``incorrect_otp``,
``insufficient_funds``, ``bank_not_available``, ``invalid_mobile_number``).
One reason is drawn from each of the four method-specific buckets plus
generic reasons, so the property is not confined to one payment method.
The remaining 102 narrow reasons are deliberately left with exactly one
canonical wording each -- see :mod:`reflow.corpus.descriptions` module
docstring for why that is correct, not an oversight."""

_EXPLICIT_BUCKETS: Final[tuple[tuple[str, ...], ...]] = (
    CARD_ONLY,
    UPI_ONLY,
    WALLET_ONLY,
    CARDLESS_EMI_ONLY,
    BANK_METHODS,
)

_METHOD_SPECIFIC_ORDER: Final[dict[PaymentMethod, tuple[str, ...]]] = {
    PaymentMethod.CARD: CARD_ONLY,
    PaymentMethod.UPI: UPI_ONLY,
    PaymentMethod.WALLET: WALLET_ONLY,
    PaymentMethod.CARDLESS_EMI: CARDLESS_EMI_ONLY,
    PaymentMethod.NETBANKING: BANK_METHODS,
    PaymentMethod.EMANDATE: BANK_METHODS,
}


def unique_reason_records(records: list[ReasonRecord]) -> list[ReasonRecord]:
    """Deduplicate parsed reason records by reason code, keeping the first.

    Args:
        records: All 114 parsed reason records, in file order.

    Returns:
        One :class:`ReasonRecord` per unique reason code, in first-seen
        file order. For the 4 reason codes that repeat, the first row's
        explanation is kept as the representative text.
    """
    seen: dict[str, ReasonRecord] = {}
    for record in records:
        seen.setdefault(record.reason, record)
    return list(seen.values())


def generic_reasons(records: list[ReasonRecord]) -> tuple[str, ...]:
    """Compute the generic (method-agnostic) reason codes.

    Args:
        records: All 114 parsed reason records, in file order.

    Returns:
        Every unique reason code not present in any of
        :data:`CARD_ONLY`, :data:`UPI_ONLY`, :data:`WALLET_ONLY`,
        :data:`CARDLESS_EMI_ONLY`, or :data:`BANK_METHODS`, in file order.
        Computed from the live parsed records (not hard-coded) so that a
        typo or omission in the explicit buckets cannot silently misclassify
        a reason as generic without a test noticing.
    """
    explicit = {reason for bucket in _EXPLICIT_BUCKETS for reason in bucket}
    return tuple(
        record.reason for record in unique_reason_records(records) if record.reason not in explicit
    )


def reason_pool_for_method(method: PaymentMethod, records: list[ReasonRecord]) -> list[str]:
    """Build one method's full, dominance-ordered reason pool.

    Args:
        method: The payment method to build a pool for.
        records: All 114 parsed reason records, in file order.

    Returns:
        The method's specific reasons (hand-ordered, most-plausible-first)
        followed by the generic reasons (file order) as the long tail.
    """
    specific = _METHOD_SPECIFIC_ORDER[method]
    return [*specific, *generic_reasons(records)]


def zipf_weights(n: int, s: float = 1.2) -> list[float]:
    """Compute normalised Zipf-like weights for ``n`` ranked items.

    Args:
        n: Number of items to weight (rank 1..n).
        s: Zipf exponent. Higher values concentrate more probability mass
            on the earliest ranks. 1.2 gives a pronounced but not extreme
            head/tail split, appropriate for "a handful of dominant modes
            plus a long tail" rather than a near-uniform or near-degenerate
            distribution.

    Returns:
        A list of ``n`` weights summing to 1.0, monotonically decreasing.
    """
    raw = [1.0 / (rank**s) for rank in range(1, n + 1)]
    total = sum(raw)
    return [weight / total for weight in raw]
