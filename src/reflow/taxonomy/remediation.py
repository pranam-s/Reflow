"""Remediation-class taxonomy derived from the vendored ``Next Steps`` text.

Every one of the 114 rows in the vendored Razorpay error-reasons spreadsheet
was read by hand on 2026-08-22 and assigned to a remediation class based on
what its ``Next Steps`` column actually recommends (consulting the
``Explanation`` column only to disambiguate a handful of multi-branch
sentences, e.g. "if the risk check failed at the customer level ... if at
the merchant level ..."). The result is the hand-reviewed table
:data:`_ROW_SPECS` below, plus this module's public API for classifying
:class:`~reflow.taxonomy.reasons.ReasonRecord` objects and building an
honest coverage report over the result.

Class set
---------

The brief's starting suggestion was ``RETRY_SAME``, ``DIFFERENT_METHOD``,
``DIFFERENT_INSTRUMENT``, ``CUSTOMER_FIX``, ``MERCHANT_CONTACT_RAZORPAY``,
``WAIT``, ``TERMINAL``. Reading all 114 rows showed three further
distinctions the text draws consistently enough to deserve their own class,
and one class the text never actually populates:

- **DIFFERENT_INSTRUMENT_OR_METHOD**: a large, recurring, verbatim-ish
  phrasing pattern -- "a different card **or** method", "another bank
  account **or** another method", "a different instrument **or** wait" --
  offers *either* an instrument swap *or* a method swap as interchangeable
  alternatives. Forcing these into only ``DIFFERENT_INSTRUMENT`` or only
  ``DIFFERENT_METHOD`` would misrepresent text that explicitly offers both;
  splitting hairs on which the customer "really" should do would be
  inventing information the source does not contain.
- **CUSTOMER_CONTACT_ISSUER_BANK**: several rows ("reach out to Issuer Bank
  to get more details", "must reach out to the issuer bank", "has to check
  with their bank") route the customer to their own bank, not to Razorpay
  and not to a simple retry. This is a materially different, and much less
  automatable, remediation than ``CUSTOMER_FIX`` (correct a specific input)
  or ``MERCHANT_CONTACT_RAZORPAY`` (merchant contacts Razorpay support).
- **MERCHANT_ACTION**: rows whose ``Next Steps`` puts the ball in the
  merchant's court but does *not* say to contact Razorpay -- integration
  fixes ("Check your integration and payment request"), self-serve
  Dashboard actions ("Generate the live mode keys in Razorpay Dashboard"),
  and one internal-approval nudge ("reach out to the approver in your
  organization"). Lumping these into ``MERCHANT_CONTACT_RAZORPAY`` would
  misrepresent rows that explicitly do not require contacting Razorpay.
- **TERMINAL** is kept in the enum for forward-compatibility (a later
  phase's cluster/outcome analysis may find some reasons are unrecoverable
  in practice), but **zero of the 114 rows are text-classified as
  TERMINAL**: every ``Next Steps`` value recommends *some* action, even for
  structurally hard cases like a dormant beneficiary account (routed to
  ``MERCHANT_CONTACT_RAZORPAY``). This is reported honestly rather than
  forcing a row into ``TERMINAL`` to populate the class.

Ambiguity policy
----------------

A row is **ambiguous** (excluded from the clean per-class coverage counts,
listed separately) when either:

1. Its ``Next Steps`` text names more than one remediation class as
   alternatives (joined by "or", by "and", or by an if/then branch), so a
   single label would silently discard one of the two recommended paths; or
2. Its ``Next Steps`` text is a near-verbatim copy of a *different* row's
   text and does not semantically match its own ``Explanation`` -- a data
   defect in the vendored spreadsheet, not a genuine textual signal (see
   ``invalid_response_from_gateway`` and ``mismatch_in_transaction_details``
   below).

This module never resolves an ambiguity by guessing a single "most likely"
class: the coverage report's ambiguous list is the intended input to a
later LLM-routing decision, and silently picking one class per row would
make that list dishonest by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from reflow.taxonomy.reasons import ReasonRecord


class RemediationClass(StrEnum):
    """A bounded remediation action implied by a reason's ``Next Steps`` text."""

    RETRY_SAME = "retry_same"
    WAIT = "wait"
    CUSTOMER_FIX = "customer_fix"
    DIFFERENT_INSTRUMENT = "different_instrument"
    DIFFERENT_METHOD = "different_method"
    DIFFERENT_INSTRUMENT_OR_METHOD = "different_instrument_or_method"
    CUSTOMER_CONTACT_ISSUER_BANK = "customer_contact_issuer_bank"
    MERCHANT_ACTION = "merchant_action"
    MERCHANT_CONTACT_RAZORPAY = "merchant_contact_razorpay"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class _RowSpec:
    """One hand-reviewed classification decision, keyed by reason for cross-check.

    Attributes:
        reason: The reason code this spec was authored against. Used only to
            assert positional alignment with a freshly parsed spreadsheet at
            classification time.
        classes: The candidate remediation class(es) the ``Next Steps`` text
            supports. A single-element set means the row is unambiguous.
        note: Free-text rationale, populated only when this row is being
            forced into the ambiguous bucket for a reason other than "more
            than one candidate class" -- specifically, a suspected
            copy-paste data defect in the vendored spreadsheet.
    """

    reason: str
    classes: frozenset[RemediationClass]
    note: str | None = None


_RS = RemediationClass.RETRY_SAME
_WT = RemediationClass.WAIT
_CF = RemediationClass.CUSTOMER_FIX
_DI = RemediationClass.DIFFERENT_INSTRUMENT
_DM = RemediationClass.DIFFERENT_METHOD
_DIM = RemediationClass.DIFFERENT_INSTRUMENT_OR_METHOD
_CB = RemediationClass.CUSTOMER_CONTACT_ISSUER_BANK
_MA = RemediationClass.MERCHANT_ACTION
_MR = RemediationClass.MERCHANT_CONTACT_RAZORPAY


def _one(cls: RemediationClass) -> frozenset[RemediationClass]:
    """Wrap a single remediation class in the frozenset the table stores.

    Args:
        cls: The single unambiguous class for a row.

    Returns:
        A one-element frozenset containing ``cls``.
    """
    return frozenset({cls})


_ROW_SPECS: Final[tuple[_RowSpec, ...]] = (
    _RowSpec("amount_less_than_minimum_amount", _one(_MA)),
    _RowSpec("authentication_failed", _one(_CF)),
    _RowSpec(
        "authorisation_declined_by_psp",
        frozenset({_CF, _DI}),
        "Conditional: recheck VPA first; only 'if this is recurring' does it "
        "recommend switching PSP app -- two different classes gated on a "
        "condition the reason code alone does not carry.",
    ),
    _RowSpec("bank_account_invalid", _one(_DIM)),
    _RowSpec("bank_account_validation_failed", _one(_CF)),
    _RowSpec("bank_cutoff_in_progress", _one(_RS)),
    _RowSpec("bank_not_available", _one(_RS)),
    _RowSpec("bank_not_enabled", _one(_MR)),
    _RowSpec("bank_technical_error", _one(_DIM)),
    _RowSpec("beneficiary_account_does_not_exist", _one(_MR)),
    _RowSpec("beneficiary_account_dormant", _one(_MR)),
    _RowSpec("capture_failed", _one(_RS)),
    _RowSpec("card_declined", _one(_CB)),
    _RowSpec("card_expired", _one(_DIM)),
    _RowSpec("card_network_not_enabled", _one(_MR)),
    _RowSpec(
        "card_not_enrolled",
        frozenset({_CF, _DIM}),
        "Text offers two alternatives: enroll the card and retry (fix), or "
        "use a different card or method entirely.",
    ),
    _RowSpec("card_number_invalid", _one(_CF)),
    _RowSpec("card_type_invalid", _one(_CF)),
    _RowSpec("collect_on_mcc_blocked", _one(_DM)),
    _RowSpec("collect_request_pending", _one(_CF)),
    _RowSpec(
        "compliance_violation",
        frozenset({_CB, _MR}),
        "Text explicitly branches on the 'source' parameter (customer-level "
        "vs merchant-level risk check) into two different remediation "
        "classes; the Next Steps text itself cannot resolve which applies.",
    ),
    _RowSpec("credit_limit_exceeded", _one(_DM)),
    _RowSpec("credit_limit_expired", _one(_DM)),
    _RowSpec(
        "credit_limit_inactive",
        frozenset({_CF, _DM}),
        "Text offers two alternatives: activate the credit limit (fix), or "
        "retry using a different payment method.",
    ),
    _RowSpec("credit_limit_not_approved", _one(_DM)),
    _RowSpec("credit_not_permitted", _one(_CF)),
    _RowSpec("credit_failed", _one(_CF)),
    _RowSpec("debit_declined", _one(_CB)),
    _RowSpec("deemed_transaction", _one(_WT)),
    _RowSpec("debit_instrument_blocked", _one(_DIM)),
    _RowSpec("debit_instrument_inactive", _one(_DIM)),
    _RowSpec("duplicate_refund_id", _one(_MA)),
    _RowSpec("duplicate_request", _one(_MA)),
    _RowSpec("duplicate_rrn_found", _one(_RS)),
    _RowSpec("emi_greater_than_max_amount", _one(_DIM)),
    _RowSpec("emi_plan_unavailable", _one(_DIM)),
    _RowSpec("funds_blocked_by_mandate", _one(_CF)),
    _RowSpec("funds_blocked_by_mandate", _one(_CF)),
    _RowSpec(
        "gateway_technical_error",
        frozenset({_DM, _WT}),
        "Text offers two alternatives: retry with a different payment "
        "method, or retry after some time.",
    ),
    _RowSpec("incorrect_atm_pin", _one(_CF)),
    _RowSpec("incorrect_card_details", _one(_CF)),
    _RowSpec("incorrect_card_expiry_date", _one(_CF)),
    _RowSpec("incorrect_cardholder_name", _one(_CF)),
    _RowSpec("incorrect_cvv", _one(_CF)),
    _RowSpec("incorrect_otp", _one(_CF)),
    _RowSpec("incorrect_pin", _one(_CF)),
    _RowSpec(
        "input_validation_failed",
        frozenset({_MA, _MR}),
        "Text offers two alternatives: fix the integration/payment request "
        "yourself, or reach out to Razorpay.",
    ),
    _RowSpec("insufficient_funds", _one(_DIM)),
    _RowSpec("international_transaction_not_allowed", _one(_MR)),
    _RowSpec("invalid_amount", _one(_MA)),
    _RowSpec("invalid_currency", _one(_MR)),
    _RowSpec("invalid_device", _one(_CF)),
    _RowSpec("invalid_email", _one(_CF)),
    _RowSpec("invalid_mobile_number", _one(_CF)),
    _RowSpec("invalid_order_id", _one(_MA)),
    _RowSpec(
        "invalid_response_from_gateway",
        _one(_CF),
        "Suspected vendored-data defect: Next Steps text ('must retry with "
        "the correct ATM PIN') is a verbatim copy of incorrect_atm_pin's "
        "text and does not semantically match this row's own Explanation "
        "(an invalid gateway response, not a PIN-entry error). Flagged "
        "ambiguous rather than trusted at face value.",
    ),
    _RowSpec("invalid_request", _one(_MA)),
    _RowSpec("invalid_user_details", _one(_CF)),
    _RowSpec("invalid_vpa", _one(_CF)),
    _RowSpec(
        "issuer_technical_error",
        frozenset({_DM, _WT}),
        "Text offers two alternatives: retry with a different payment "
        "method, or retry after some time.",
    ),
    _RowSpec("issuer_technical_error", _one(_RS)),
    _RowSpec("live_mode_not_enabled", _one(_MA)),
    _RowSpec("mandate_creation_declined", _one(_RS)),
    _RowSpec("mandate_creation_expired", _one(_RS)),
    _RowSpec("mandate_creation_failed", _one(_RS)),
    _RowSpec("mandate_creation_timeout", _one(_RS)),
    _RowSpec("mcc_amount_limit_exceeded", _one(_MR)),
    _RowSpec("merchant_not_activated", _one(_MR)),
    _RowSpec(
        "mismatch_in_transaction_details",
        _one(_MR),
        "Suspected vendored-data defect: Next Steps text ('reach out to "
        "Razorpay to get the required card network enabled') is a verbatim "
        "copy of card_network_not_enabled's text and does not semantically "
        "match this row's own Explanation (merchant passed transaction "
        "details incorrectly, unrelated to card network enablement). "
        "Flagged ambiguous rather than trusted at face value.",
    ),
    _RowSpec(
        "mobile_number_invalid",
        frozenset({_CF, _CB}),
        "Text conjoins two different-class actions: check your own UPI "
        "mobile-number mapping, and reach out to your bank to correct it.",
    ),
    _RowSpec("order_already_paid", _one(_MA)),
    _RowSpec("order_payment_method_mismatch", _one(_MA)),
    _RowSpec("order_amount_mismatch", _one(_MA)),
    _RowSpec("otp_attempts_exceeded", _one(_DIM)),
    _RowSpec("otp_expired", _one(_CF)),
    _RowSpec("payment_amount_tampered", _one(_CF)),
    _RowSpec("payment_cancelled", _one(_RS)),
    _RowSpec("payment_collect_request_expired", _one(_RS)),
    _RowSpec("payment_declined", _one(_CB)),
    _RowSpec("payment_declined_due_to_high_traffic", _one(_RS)),
    _RowSpec("payment_failed", _one(_DM)),
    _RowSpec("payment_method_not_enabled", _one(_MR)),
    _RowSpec("payment_method_not_enabled", _one(_MA)),
    _RowSpec("payment_pending", _one(_WT)),
    _RowSpec("payment_pending_approval", _one(_MA)),
    _RowSpec("payment_risk_check_failed", _one(_DIM)),
    _RowSpec("payment_session_expired", _one(_RS)),
    _RowSpec("payment_timed_out", _one(_RS)),
    _RowSpec("pin_attempts_exceeded", _one(_DIM)),
    _RowSpec("pin_not_set", _one(_CF)),
    _RowSpec("psp_app_ not_available", _one(_DI)),
    _RowSpec("psp_app_not_supported", _one(_DI)),
    _RowSpec("psp_not_available", _one(_DI)),
    _RowSpec("psp_not_available", _one(_DI)),
    _RowSpec("psp_not_registered", _one(_DI)),
    _RowSpec("record_not_found", _one(_RS)),
    _RowSpec("recurring_payment_not_enabled", _one(_MR)),
    _RowSpec("refund_limit_crossed", _one(_MA)),
    _RowSpec("reqauth_mandate_not_acknowledged", _one(_RS)),
    _RowSpec("request_timed_out", _one(_RS)),
    _RowSpec(
        "server_error",
        frozenset({_WT, _MR}),
        "Text offers two alternatives: retry after some time, or reach out to Razorpay.",
    ),
    _RowSpec(
        "transaction_daily_count_exceeded",
        frozenset({_WT, _DIM}),
        "Text offers two alternatives: try after 24 hours (wait), or use a "
        "different card or another method.",
    ),
    _RowSpec(
        "transaction_daily_limit_exceeded",
        frozenset({_DI, _WT}),
        "Text offers two alternatives: retry using a different instrument, or wait 24 hours.",
    ),
    _RowSpec("transaction_limit_exceeded", _one(_DIM)),
    _RowSpec("transaction_frequency_limit_exceeded", _one(_DM)),
    _RowSpec("transaction_on_vpa_restricted", _one(_DI)),
    _RowSpec(
        "upi_app_technical_error",
        frozenset({_RS, _DI}),
        "Text encodes a retry-then-escalate policy ('retry the payment; if "
        "the error persists, use a different psp'), i.e. the class depends "
        "on attempt history rather than being resolvable from the reason "
        "alone.",
    ),
    _RowSpec("upi_autopay_not_supported_on_psp", _one(_DI)),
    _RowSpec("upi_collect_not_enabled", _one(_MA)),
    _RowSpec("upi_intent_not_enabled", _one(_MA)),
    _RowSpec("user_not_eligible", _one(_DM)),
    _RowSpec("user_not_registered_for_netbanking", _one(_CB)),
    _RowSpec("vpa_resolution_failed", _one(_DIM)),
    _RowSpec("verification_failed", _one(_RS)),
)


@dataclass(frozen=True, slots=True)
class ReasonClassification:
    """The remediation classification for one :class:`ReasonRecord`.

    Attributes:
        row_index: The originating record's :attr:`ReasonRecord.row_index`.
        reason: The originating record's reason code, verbatim.
        candidate_classes: The remediation class(es) supported by the
            reason's ``Next Steps`` text.
        ambiguity_note: Present only for rows forced into the ambiguous
            bucket for a reason other than "more than one candidate class"
            (see :class:`_RowSpec`).
    """

    row_index: int
    reason: str
    candidate_classes: frozenset[RemediationClass]
    ambiguity_note: str | None = None

    @property
    def is_ambiguous(self) -> bool:
        """Whether this row is excluded from the clean per-class counts.

        Returns:
            ``True`` if the row has more than one candidate class, or if it
            carries an explicit ambiguity note (a suspected data defect).
        """
        return len(self.candidate_classes) != 1 or self.ambiguity_note is not None

    @property
    def remediation_class(self) -> RemediationClass | None:
        """The single remediation class for this row, if unambiguous.

        Returns:
            The sole candidate class, or ``None`` if :attr:`is_ambiguous`.
        """
        if self.is_ambiguous:
            return None
        return next(iter(self.candidate_classes))


class TaxonomyDriftError(ValueError):
    """Raised when parsed reason records no longer match the reviewed table.

    This guards against silently misclassifying rows if Razorpay's vendored
    spreadsheet is ever re-fetched with reordered or renamed rows: the hand
    review recorded in :data:`_ROW_SPECS` is only valid against the exact
    row order it was written against.
    """


def classify_reasons(records: list[ReasonRecord]) -> list[ReasonClassification]:
    """Classify parsed reason records using the hand-reviewed table.

    Args:
        records: Reason records parsed by
            :func:`reflow.taxonomy.reasons.parse_reason_records`, in file
            order.

    Returns:
        One :class:`ReasonClassification` per input record, in the same
        order.

    Raises:
        TaxonomyDriftError: If the number of records, or any record's
            reason code, does not match the hand-reviewed table
            position-for-position.
    """
    if len(records) != len(_ROW_SPECS):
        raise TaxonomyDriftError(
            f"Parsed {len(records)} reason records but the reviewed "
            f"classification table has {len(_ROW_SPECS)} entries."
        )
    classifications: list[ReasonClassification] = []
    for record, spec in zip(records, _ROW_SPECS, strict=True):
        if record.reason != spec.reason:
            raise TaxonomyDriftError(
                f"Row {record.row_index}: parsed reason {record.reason!r} does "
                f"not match reviewed table reason {spec.reason!r}."
            )
        classifications.append(
            ReasonClassification(
                row_index=record.row_index,
                reason=record.reason,
                candidate_classes=spec.classes,
                ambiguity_note=spec.note,
            )
        )
    return classifications


@dataclass(frozen=True, slots=True)
class AmbiguousReason:
    """One reason whose remediation class could not be honestly resolved.

    Attributes:
        row_index: The originating record's row index.
        reason: The reason code.
        candidate_classes: The remediation class(es) the text supports.
        note: Human-readable explanation of why the row is ambiguous.
    """

    row_index: int
    reason: str
    candidate_classes: frozenset[RemediationClass]
    note: str | None


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Coverage of the 114 vendored reasons across remediation classes.

    Attributes:
        class_counts: Number of unambiguous reasons assigned to each
            remediation class. Classes with zero rows are still present
            (with a count of 0) so the report is honest about gaps rather
            than omitting them.
        ambiguous: The full list of reasons excluded from ``class_counts``
            because their ``Next Steps`` text was genuinely ambiguous or
            suspected of being a data defect.
        total_reasons: Total number of reasons the report was built from.
    """

    class_counts: dict[RemediationClass, int]
    ambiguous: list[AmbiguousReason]
    total_reasons: int

    def unambiguous_count(self) -> int:
        """Total number of reasons assigned exactly one remediation class.

        Returns:
            The sum of :attr:`class_counts` across all classes.
        """
        return sum(self.class_counts.values())


def build_coverage_report(classifications: list[ReasonClassification]) -> CoverageReport:
    """Build an honest coverage report from a list of classifications.

    Args:
        classifications: Output of :func:`classify_reasons`.

    Returns:
        A :class:`CoverageReport` tallying unambiguous reasons per class and
        listing every ambiguous reason explicitly, with its full candidate
        set and rationale.
    """
    class_counts: dict[RemediationClass, int] = dict.fromkeys(RemediationClass, 0)
    ambiguous: list[AmbiguousReason] = []
    for classification in classifications:
        if classification.is_ambiguous:
            ambiguous.append(
                AmbiguousReason(
                    row_index=classification.row_index,
                    reason=classification.reason,
                    candidate_classes=classification.candidate_classes,
                    note=classification.ambiguity_note,
                )
            )
            continue
        remediation_class = next(iter(classification.candidate_classes))
        class_counts[remediation_class] += 1
    return CoverageReport(
        class_counts=class_counts,
        ambiguous=ambiguous,
        total_reasons=len(classifications),
    )
