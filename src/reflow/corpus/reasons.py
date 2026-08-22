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

**Phase 1b addendum: surface-variation richness as a swept axis.** The
mechanisms above give each latent sub-cause at most a *binary* choice of
wording (canonical, or exactly one alternate, when one is authored at
all). That is enough to test coarse split-vs-merge behaviour but
under-stresses how Drain3, template hashing, and TF-IDF+HDBSCAN cope with
several simultaneous natural wordings of the same underlying cause. Every
:class:`LatentSubcause` below now also carries :attr:`LatentSubcause.variants`:
exactly 4 independently authored alternates (beyond the canonical
``template``), so a caller can request ``variant_richness`` 1 (canonical
only, the control), 3 (canonical + 2 alternates), or 5 (canonical + all 4
alternates) -- see :func:`subcause_wordings` and :func:`max_variant_richness`.
The 4 alternates per sub-cause are ordered ``paraphrase_wording`` (a
vocabulary swap), ``paraphrase_reordered`` (a clause reordering),
``paraphrase_verbose`` (a longer, more formal register), and
``paraphrase_terse`` (a short, clipped register), so that increasing
richness adds a genuinely new *kind* of surface variation each step,
not just more copies of the same phenomenon. Event-level sampling among
however many wordings are made available at a given richness uses
:func:`zipf_weights` -- the same non-uniform, most-common-first shape
already used for method/reason pools -- so higher richness fragments a
sub-cause's surface forms unevenly, as real phrasings would, rather than
splitting evenly. This axis is deliberately independent of, and does not
replace, the pre-existing ``paraphrase``/:data:`NARROW_REASON_ALT_PHRASINGS`
mechanism: when ``variant_richness`` is not requested, generation is
byte-for-byte identical to pre-Phase-1b behaviour.
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
            was exercised. :attr:`LatentSubcause.variants` also uses
            ``"paraphrase_verbose"`` and ``"paraphrase_terse"`` for the
            Phase 1b richness axis (see module docstring).

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
            that are always rendered canonically. Pre-Phase-1b mechanism,
            unaffected by and independent of ``variants``/``variant_richness``
            (see module docstring).
        variants: The Phase 1b richness axis's ordered pool of alternate
            wordings, independent of ``paraphrase``. Every catch-all
            sub-cause is authored with exactly 4 entries, ordered
            ``paraphrase_wording``, ``paraphrase_reordered``,
            ``paraphrase_verbose``, ``paraphrase_terse``, so that
            :func:`subcause_wordings` can serve ``variant_richness`` levels
            1 through 5. Only consulted when a caller passes an explicit
            ``variant_richness``; ignored otherwise.
    """

    subcause_id: str
    weight: float
    template: str
    paraphrase: DescriptionVariant | None = None
    variants: tuple[DescriptionVariant, ...] = ()


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
            variants=(
                DescriptionVariant(
                    "No reply was received from {bank} before the gateway's wait "
                    "window elapsed for payment {payment_id}, causing "
                    "authorization to time out.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Because {bank} did not respond in time during "
                    "authorization, the gateway timed out payment {payment_id} "
                    "without ever hearing back.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "The gateway waited for a response from {bank} while "
                    "attempting to authorize payment {payment_id}, but no "
                    "acknowledgement arrived within the allotted window, and the "
                    "transaction was therefore marked as timed out before "
                    "authorization could be confirmed.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "No response from {bank}. Payment {payment_id} timed out pre-authorization.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "bank_soft_decline",
            0.30,
            "Payment processing failed after {bank} returned a decline for "
            "payment {payment_id} without a specific reason code; the gateway "
            "received only a generic failure status from the bank.",
            variants=(
                DescriptionVariant(
                    "{bank} turned down payment {payment_id} without giving a "
                    "precise cause; only a generic failure status made it back "
                    "to the gateway.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Only a generic failure status reached the gateway for "
                    "payment {payment_id}, since {bank} declined it without "
                    "attaching any specific reason code.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "In processing payment {payment_id}, {bank} issued a decline "
                    "response that carried no specific reason code, leaving the "
                    "gateway with nothing more than an unqualified generic "
                    "failure status to act on.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank} declined payment {payment_id}. No reason code, just a generic failure.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "network_drop",
            0.20,
            "Payment processing failed because the customer's connection dropped "
            "during authorization for payment {payment_id}; the gateway could "
            "not confirm whether {bank} completed the debit before the session "
            "ended.",
            variants=(
                DescriptionVariant(
                    "The customer's session was interrupted mid-authorization "
                    "for payment {payment_id}, leaving the gateway unable to "
                    "verify whether {bank} had already processed the debit.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Whether {bank} finished the debit before the session closed "
                    "could not be confirmed by the gateway, because the "
                    "customer's connection dropped while payment {payment_id} "
                    "was being authorized.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "During the authorization step for payment {payment_id}, the "
                    "customer's network connection was lost before the process "
                    "could complete, and as a result the gateway had no way of "
                    "confirming whether {bank} had already debited the account "
                    "prior to the disconnection.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Connection dropped mid-authorization for payment "
                    "{payment_id}. Debit status at {bank} unknown.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "risk_engine_block",
            0.15,
            "Payment processing failed because an automated risk check flagged "
            "payment {payment_id} for {amount_display} as suspicious, and the "
            "gateway declined it before the request reached {bank}.",
            variants=(
                DescriptionVariant(
                    "An automated fraud screen marked payment {payment_id} "
                    "({amount_display}) as high-risk, so the gateway rejected it "
                    "before it could be forwarded to {bank}.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Before the request could reach {bank}, the gateway declined "
                    "payment {payment_id} for {amount_display} after its risk "
                    "engine flagged the transaction as suspicious.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "As part of its automated screening, the gateway's risk "
                    "engine evaluated payment {payment_id} for {amount_display} "
                    "and determined the transaction pattern to be suspicious, "
                    "resulting in the payment being declined internally before "
                    "ever being routed to {bank}.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Risk engine flagged payment {payment_id} ({amount_display}). "
                    "Declined before reaching {bank}.",
                    "paraphrase_terse",
                ),
            ),
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
            variants=(
                DescriptionVariant(
                    "Razorpay's server ran into an internal fault while handling "
                    "payment {payment_id}: the datastore holding payment state "
                    "never acknowledged the write inside the configured time "
                    "limit.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Within the configured timeout, the payment-state datastore "
                    "did not acknowledge the write for payment {payment_id}, "
                    "which is why a technical error occurred at Razorpay's "
                    "server.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "While Razorpay's server was processing payment "
                    "{payment_id}, an internal technical error arose because the "
                    "underlying payment-state datastore failed to send back a "
                    "write acknowledgement within the time period that had been "
                    "configured for it.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Server error on payment {payment_id}. Datastore write "
                    "unacknowledged, timeout exceeded.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "queue_backlog",
            0.28,
            "A technical error occurred at Razorpay's server while processing "
            "payment {payment_id}: the internal processing queue was backlogged "
            "and the request was dropped after retries were exhausted.",
            variants=(
                DescriptionVariant(
                    "Razorpay's server encountered an internal fault handling "
                    "payment {payment_id}: its processing queue had built up a "
                    "backlog, and the request was discarded once all retry "
                    "attempts were used up.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "After retries were exhausted on a backlogged internal "
                    "processing queue, the request for payment {payment_id} was "
                    "dropped, triggering a technical error at Razorpay's server.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "At the time payment {payment_id} was submitted, Razorpay's "
                    "internal processing queue had accumulated a significant "
                    "backlog; the server made repeated retry attempts to "
                    "process the request, but once those retries were exhausted "
                    "the request was ultimately dropped, producing a technical "
                    "error.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Payment {payment_id}: queue backlog, retries exhausted, request dropped.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "deploy_blip",
            0.22,
            "A technical error occurred at Razorpay's server while processing "
            "payment {payment_id}: a routine service deployment briefly "
            "interrupted request handling.",
            variants=(
                DescriptionVariant(
                    "While payment {payment_id} was being processed, Razorpay's "
                    "server suffered a brief technical glitch caused by an "
                    "ongoing routine deployment that momentarily interrupted "
                    "request handling.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Request handling for payment {payment_id} was briefly "
                    "interrupted by a routine service deployment, resulting in "
                    "a technical error at Razorpay's server.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "At the moment payment {payment_id} reached Razorpay's "
                    "server, a scheduled and routine deployment of a backend "
                    "service was in progress, and the brief interruption to "
                    "request handling that this caused was registered as a "
                    "technical error.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Payment {payment_id}: brief outage from routine deploy.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "dependency_failure",
            0.20,
            "A technical error occurred at Razorpay's server while processing "
            "payment {payment_id}: an internal dependency service returned an "
            "unexpected error and the request could not be completed.",
            variants=(
                DescriptionVariant(
                    "Razorpay's server could not complete payment {payment_id} "
                    "because one of its internal dependency services responded "
                    "with an unexpected error.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Because an internal dependency service returned an "
                    "unexpected error, the request for payment {payment_id} "
                    "could not be completed, and a technical error was logged "
                    "at Razorpay's server.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "During processing of payment {payment_id}, Razorpay's "
                    "server made a call to one of its internal dependency "
                    "services, which returned a response the server did not "
                    "expect, and consequently the payment request could not be "
                    "carried through to completion.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Payment {payment_id}: internal dependency error, request incomplete.",
                    "paraphrase_terse",
                ),
            ),
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
            variants=(
                DescriptionVariant(
                    "{bank}'s core banking platform gave no reply to the debit "
                    "request for payment {payment_id} before the timeout window "
                    "closed.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Inside the timeout window, no response to the debit "
                    "request came back from {bank}'s core banking system for "
                    "payment {payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "When the debit request for payment {payment_id} was sent "
                    "to {bank}, the core banking system on their end did not "
                    "return any response at all within the window of time that "
                    "had been allotted for the transaction to complete.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank} CBS: no response to debit for payment {payment_id}. Timed out.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "cbs_maintenance",
            0.25,
            "{bank}'s core banking system rejected the debit request for payment "
            "{payment_id} during an unscheduled maintenance cycle.",
            variants=(
                DescriptionVariant(
                    "The debit request for payment {payment_id} was turned down "
                    "by {bank}'s core banking system, which was undergoing an "
                    "unplanned maintenance cycle at the time.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "During an unscheduled maintenance cycle at {bank}, the "
                    "core banking system rejected the debit request for "
                    "payment {payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "At the time the debit request for payment {payment_id} was "
                    "submitted, {bank}'s core banking system happened to be "
                    "undergoing an unscheduled maintenance cycle, and as a "
                    "direct consequence the request was rejected outright.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank} CBS in unscheduled maintenance. Payment {payment_id} debit rejected.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "cbs_overload",
            0.25,
            "{bank}'s core banking system returned a technical failure for "
            "payment {payment_id} while processing an unusually high "
            "transaction volume.",
            variants=(
                DescriptionVariant(
                    "{bank}'s core banking system was handling an unusually "
                    "heavy transaction load and returned a technical failure "
                    "for payment {payment_id}.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "While an unusually high volume of transactions was being "
                    "processed, {bank}'s core banking system returned a "
                    "technical failure for payment {payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "At the moment payment {payment_id} was submitted for "
                    "processing, {bank}'s core banking system was under an "
                    "unusually high volume of transaction traffic, and it "
                    "returned a technical failure rather than completing the "
                    "debit.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank} CBS overloaded. Payment {payment_id}: technical failure.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "cbs_partial_outage",
            0.15,
            "{bank} reported a technical error for payment {payment_id} from "
            "one core banking system node while other nodes continued "
            "processing normally.",
            variants=(
                DescriptionVariant(
                    "A single core banking system node at {bank} returned a "
                    "technical error for payment {payment_id}, even though the "
                    "rest of its nodes kept processing transactions as usual.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "While other nodes continued to process transactions "
                    "normally, one core banking system node at {bank} reported "
                    "a technical error for payment {payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "{bank} operates its core banking system across multiple "
                    "nodes, and for payment {payment_id} one of those nodes "
                    "reported a technical error while every other node in the "
                    "cluster continued to process transactions without any "
                    "apparent disruption.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank} CBS: one node down, payment {payment_id} failed there.",
                    "paraphrase_terse",
                ),
            ),
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
            variants=(
                DescriptionVariant(
                    "Before authorization for payment {payment_id} could "
                    "finish, the gateway's connection to {bank} dropped "
                    "without warning.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Authorization for payment {payment_id} did not complete "
                    "because the gateway unexpectedly severed its connection "
                    "to {bank} beforehand.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "While the gateway was in the process of authorizing "
                    "payment {payment_id}, the network connection it had "
                    "established with {bank} was abruptly and unexpectedly "
                    "terminated, preventing the authorization step from being "
                    "carried through to completion.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Gateway connection to {bank} reset mid-auth for payment {payment_id}.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "gateway_cert_issue",
            0.25,
            "The payment gateway encountered a certificate validation error "
            "while establishing a secure connection to {bank} for payment "
            "{payment_id}.",
            variants=(
                DescriptionVariant(
                    "A certificate validation failure occurred at the payment "
                    "gateway when it tried to open a secure channel to {bank} "
                    "for payment {payment_id}.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "While setting up a secure connection to {bank} for "
                    "payment {payment_id}, the payment gateway ran into a "
                    "certificate validation error.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "As part of establishing an encrypted, secure connection "
                    "to {bank} in order to process payment {payment_id}, the "
                    "payment gateway attempted to validate the security "
                    "certificate involved and encountered an error that "
                    "prevented the handshake from succeeding.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Cert validation failed: gateway to {bank}, payment {payment_id}.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "gateway_rate_limited",
            0.25,
            "The payment gateway was rate-limited by {bank} and could not "
            "complete authorization for payment {payment_id}.",
            variants=(
                DescriptionVariant(
                    "{bank} imposed a rate limit on the payment gateway, which "
                    "prevented authorization for payment {payment_id} from "
                    "completing.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Authorization for payment {payment_id} could not complete "
                    "because {bank} rate-limited the payment gateway.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "When the payment gateway attempted to authorize payment "
                    "{payment_id}, it exceeded the request rate that {bank} "
                    "permits, and {bank} responded by throttling further "
                    "requests, which left the authorization unable to "
                    "complete.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Rate-limited by {bank}. Payment {payment_id} auth incomplete.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "gateway_malformed_response",
            0.20,
            "The payment gateway received a malformed response from {bank} and "
            "could not parse the authorization result for payment {payment_id}.",
            variants=(
                DescriptionVariant(
                    "A malformed response came back from {bank}, and the "
                    "payment gateway was unable to parse the authorization "
                    "outcome for payment {payment_id}.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "The authorization result for payment {payment_id} could "
                    "not be parsed by the payment gateway, because the response "
                    "it received from {bank} was malformed.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "In responding to the authorization request for payment "
                    "{payment_id}, {bank} sent back a response that did not "
                    "conform to the expected format, and the payment gateway's "
                    "parser was consequently unable to interpret the "
                    "authorization result contained within it.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Malformed response from {bank}. Cannot parse auth for payment {payment_id}.",
                    "paraphrase_terse",
                ),
            ),
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
            variants=(
                DescriptionVariant(
                    "An internal risk hold led the issuing bank to decline card "
                    "BIN {card_bin} on payment {payment_id}; Razorpay was not "
                    "given any additional detail.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "No further detail was shared with Razorpay when the "
                    "issuing bank declined payment {payment_id} on card BIN "
                    "{card_bin}, citing an internal risk hold.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "For payment {payment_id}, made using a card with BIN "
                    "{card_bin}, the issuing bank chose to decline the "
                    "transaction on account of an internal risk hold placed on "
                    "the account, and beyond naming that hold, no further "
                    "explanation was passed along to Razorpay.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Card BIN {card_bin}, payment {payment_id}: declined, risk hold, no detail.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "issuer_velocity_block",
            0.28,
            "The issuing bank declined the card (BIN {card_bin}) for payment "
            "{payment_id} due to a velocity check on recent transactions; the "
            "exact threshold was not disclosed.",
            variants=(
                DescriptionVariant(
                    "A velocity check on recent transactions caused the "
                    "issuing bank to decline card BIN {card_bin} for payment "
                    "{payment_id}; the specific threshold used was not "
                    "disclosed.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "The exact threshold was not disclosed when the issuing "
                    "bank declined payment {payment_id} on card BIN {card_bin} "
                    "following a velocity check on recent transactions.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "The issuing bank ran a velocity check against the recent "
                    "transaction history associated with card BIN {card_bin} "
                    "and, on the basis of that check, declined payment "
                    "{payment_id}, without disclosing the specific threshold "
                    "that triggered the decline.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Card BIN {card_bin}: velocity block, payment {payment_id} declined.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "issuer_expired_or_limit",
            0.22,
            "The issuing bank declined the card (BIN {card_bin}) for payment "
            "{payment_id} without specifying whether the cause was an expired "
            "card or an exhausted limit.",
            variants=(
                DescriptionVariant(
                    "It is unclear whether an expired card or an exhausted "
                    "limit was responsible, since the issuing bank declined "
                    "card BIN {card_bin} for payment {payment_id} without "
                    "specifying which.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Without specifying whether the card had expired or its "
                    "limit was exhausted, the issuing bank declined card BIN "
                    "{card_bin} on payment {payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "When payment {payment_id} was declined by the issuing "
                    "bank on card BIN {card_bin}, the decline response did not "
                    "indicate whether the underlying cause was the card having "
                    "expired or the available limit having been exhausted, "
                    "leaving the specific trigger unknown.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Card BIN {card_bin}, payment {payment_id}: declined, expiry or limit unclear.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "issuer_generic_decline",
            0.20,
            "The issuing bank declined the card (BIN {card_bin}) for payment "
            "{payment_id} with a generic decline code Razorpay cannot map to a "
            "specific reason.",
            variants=(
                DescriptionVariant(
                    "A generic decline code that Razorpay cannot map to any "
                    "specific reason was returned by the issuing bank when it "
                    "declined card BIN {card_bin} for payment {payment_id}.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Razorpay cannot map the decline to a specific reason, "
                    "because the issuing bank returned only a generic decline "
                    "code for card BIN {card_bin} on payment {payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "The issuing bank's response to payment {payment_id}, made "
                    "on card BIN {card_bin}, consisted of a generic decline "
                    "code that does not correspond to any of the specific "
                    "reason categories Razorpay is able to map decline codes "
                    "to.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Card BIN {card_bin}, payment {payment_id}: generic decline code, unmapped.",
                    "paraphrase_terse",
                ),
            ),
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
            variants=(
                DescriptionVariant(
                    "Payment {payment_id} was turned down by either {bank} or "
                    "the gateway for business reasons that were not disclosed, "
                    "and Razorpay received no additional information.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "No further detail was received by Razorpay after {bank} "
                    "or the gateway declined payment {payment_id} for reasons "
                    "tied to undisclosed business rules.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "In the case of payment {payment_id}, either {bank} or the "
                    "gateway made the decision to decline the transaction on "
                    "the basis of internal business considerations that were "
                    "never disclosed, and Razorpay was not given any further "
                    "information about what those considerations were.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Payment {payment_id} declined by {bank}/gateway. Business "
                    "reason, undisclosed.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "technical_decline",
            0.28,
            "{bank} or the gateway declined payment {payment_id} citing an "
            "internal technical issue, without specifying which system was "
            "responsible.",
            variants=(
                DescriptionVariant(
                    "An internal technical issue was cited when {bank} or the "
                    "gateway declined payment {payment_id}, though which system "
                    "was at fault was not specified.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Without specifying which system was responsible, {bank} "
                    "or the gateway declined payment {payment_id} citing an "
                    "internal technical issue.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "When payment {payment_id} was declined, the decline "
                    "notice from either {bank} or the gateway referenced an "
                    "internal technical issue as the cause, but it did not go "
                    "on to specify which of the two systems was actually "
                    "responsible for that issue.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Payment {payment_id} declined. Technical issue at {bank} "
                    "or gateway, system unspecified.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "compliance_hold_decline",
            0.22,
            "{bank} or the gateway declined payment {payment_id}, possibly due "
            "to a compliance hold; the decline reason was not communicated to "
            "Razorpay.",
            variants=(
                DescriptionVariant(
                    "A compliance hold may explain why {bank} or the gateway "
                    "declined payment {payment_id}, though the decline reason "
                    "was never communicated to Razorpay.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "The decline reason was not communicated to Razorpay when "
                    "{bank} or the gateway declined payment {payment_id}, "
                    "possibly because of a compliance hold.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "Payment {payment_id} was declined by either {bank} or the "
                    "gateway, and while the underlying cause may have been a "
                    "compliance-related hold placed on the transaction, no "
                    "such reason, nor any other, was ever communicated back to "
                    "Razorpay.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Payment {payment_id} declined by {bank}/gateway. Possibly "
                    "compliance hold, reason withheld.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "capacity_decline",
            0.20,
            "{bank} or the gateway declined payment {payment_id} during a "
            "period of high processing load; the specific cause was not "
            "communicated to Razorpay.",
            variants=(
                DescriptionVariant(
                    "During a spell of high processing load, payment "
                    "{payment_id} was declined by {bank} or the gateway, and "
                    "the specific cause was never communicated to Razorpay.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "The specific cause was not communicated to Razorpay "
                    "after {bank} or the gateway declined payment "
                    "{payment_id} during a period of high processing load.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "At a time when processing load was running unusually "
                    "high, either {bank} or the gateway declined payment "
                    "{payment_id}, and although the high load was the "
                    "apparent context, the specific cause behind the decline "
                    "itself was never communicated to Razorpay.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "Payment {payment_id} declined by {bank}/gateway during "
                    "peak load. Cause not shared.",
                    "paraphrase_terse",
                ),
            ),
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
            variants=(
                DescriptionVariant(
                    "A technical error at {bank} caused the authentication "
                    "request for payment {payment_id} to time out.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "The authentication request timed out for payment "
                    "{payment_id} because {bank} ran into a technical error "
                    "while authenticating it.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "While {bank} was in the process of authenticating "
                    "payment {payment_id}, it ran into a technical error on "
                    "its end, and as a result the authentication request was "
                    "never completed and ultimately timed out.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank}: technical error, auth timeout, payment {payment_id}.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "issuer_core_glitch",
            0.28,
            "{bank} experienced a technical error in its authorization system "
            "while processing payment {payment_id}.",
            variants=(
                DescriptionVariant(
                    "While processing payment {payment_id}, {bank}'s "
                    "authorization system ran into a technical error.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "In its authorization system, {bank} experienced a "
                    "technical error while processing payment {payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "As payment {payment_id} was being processed, the "
                    "authorization system operated by {bank} encountered an "
                    "internal technical error that prevented the transaction "
                    "from being handled normally.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank} authorization system glitch on payment {payment_id}.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "issuer_connectivity",
            0.22,
            "{bank} experienced a connectivity issue with the network while "
            "authorizing payment {payment_id}.",
            variants=(
                DescriptionVariant(
                    "A network connectivity issue at {bank} arose while "
                    "payment {payment_id} was being authorized.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "While authorizing payment {payment_id}, {bank} "
                    "experienced a connectivity issue with the network.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "During the authorization of payment {payment_id}, {bank} "
                    "lost network connectivity partway through, an issue on "
                    "its end that interrupted the normal authorization flow.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank}: network connectivity issue during auth, payment {payment_id}.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "issuer_upi_glitch",
            0.20,
            "{bank}, acting as the issuer for payment {payment_id}, returned a "
            "technical error during the authorization step.",
            variants=(
                DescriptionVariant(
                    "Acting as issuer for payment {payment_id}, {bank} "
                    "returned a technical error at the authorization step.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "During the authorization step for payment {payment_id}, "
                    "a technical error was returned by {bank} in its role as "
                    "issuer.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "In its capacity as the issuing bank for payment "
                    "{payment_id}, {bank} was responsible for the "
                    "authorization step of the transaction, and it was at "
                    "that step that {bank} returned a technical error rather "
                    "than an authorization outcome.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank} (issuer): technical error at authorization, payment {payment_id}.",
                    "paraphrase_terse",
                ),
            ),
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
            variants=(
                DescriptionVariant(
                    "The debit request for payment {payment_id} was declined "
                    "by {bank}, possibly because the account had been blocked "
                    "on suspicion of fraud.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Possibly due to the account being blocked for suspected "
                    "fraud, {bank} declined the debit request for payment "
                    "{payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "When the debit request for payment {payment_id} was "
                    "submitted to {bank}, it was declined, and one plausible "
                    "explanation is that the account in question had been "
                    "blocked as a precaution against suspected fraudulent "
                    "activity.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank}: debit declined, payment {payment_id}. Account "
                    "possibly blocked, fraud suspected.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "account_frozen_kyc",
            0.28,
            "{bank} declined the debit request for payment {payment_id}; the "
            "account may be frozen pending a KYC update.",
            variants=(
                DescriptionVariant(
                    "The debit request for payment {payment_id} was declined "
                    "by {bank}, possibly because the account is frozen while a "
                    "KYC update is pending.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Possibly pending a KYC update that has frozen the "
                    "account, {bank} declined the debit request for payment "
                    "{payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "{bank} declined the debit request associated with "
                    "payment {payment_id}, and one likely reason is that the "
                    "account remains frozen while the customer's KYC details "
                    "are being updated or re-verified.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank}: debit declined, payment {payment_id}. Account may "
                    "be frozen, KYC pending.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "mandate_hold",
            0.22,
            "{bank} declined the debit request for payment {payment_id} due to "
            "an internal hold that Razorpay could not identify.",
            variants=(
                DescriptionVariant(
                    "An internal hold that Razorpay was unable to identify "
                    "caused {bank} to decline the debit request for payment "
                    "{payment_id}.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "Due to an internal hold Razorpay could not identify, "
                    "{bank} declined the debit request for payment "
                    "{payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "{bank} declined the debit request for payment "
                    "{payment_id} on account of some internal hold placed on "
                    "the account or mandate, but the specific nature of that "
                    "hold could not be identified or confirmed by Razorpay.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank}: debit declined, payment {payment_id}. Internal hold, unidentified.",
                    "paraphrase_terse",
                ),
            ),
        ),
        LatentSubcause(
            "generic_bank_decline",
            0.20,
            "{bank} declined the debit request for payment {payment_id} without "
            "specifying a reason.",
            variants=(
                DescriptionVariant(
                    "Without giving a specific reason, {bank} declined the "
                    "debit request for payment {payment_id}.",
                    "paraphrase_wording",
                ),
                DescriptionVariant(
                    "No reason was specified when {bank} declined the debit "
                    "request for payment {payment_id}.",
                    "paraphrase_reordered",
                ),
                DescriptionVariant(
                    "{bank} declined the debit request that had been "
                    "submitted for payment {payment_id}, and the response "
                    "provided did not specify any particular reason for that "
                    "decline.",
                    "paraphrase_verbose",
                ),
                DescriptionVariant(
                    "{bank}: debit declined, payment {payment_id}. No reason given.",
                    "paraphrase_terse",
                ),
            ),
        ),
    ),
}

MIN_VARIANT_RICHNESS: Final[int] = 1
"""The lowest supported ``variant_richness`` level: the canonical wording
only, with zero manufactured surface variation. Serves as the Phase 1b
evaluation sweep's control condition."""

SUPPORTED_VARIANT_RICHNESS_LEVELS: Final[tuple[int, ...]] = (1, 3, 5)
"""The richness levels the Phase 1b corpus-design addendum requires the
sweep to cover: canonical-only, canonical + 2 alternates, and canonical + 4
alternates. :func:`subcause_wordings` accepts any integer in
``[MIN_VARIANT_RICHNESS, max_variant_richness()]``, not only these three;
every catch-all sub-cause is authored with exactly 4 alternates so these
three levels -- and every level in between -- are always satisfiable."""


def max_variant_richness() -> int:
    """Compute the highest ``variant_richness`` every latent sub-cause supports.

    Returns:
        ``1`` (the canonical wording) plus the smallest number of authored
        :attr:`LatentSubcause.variants` among every sub-cause in
        :data:`CATCH_ALL_SUBCAUSES`. Computed from the live data rather than
        hard-coded, so a future sub-cause authored with fewer alternates is
        caught by this bound silently shrinking, rather than a stale
        constant going out of sync with the data it describes.
    """
    return 1 + min(
        len(subcause.variants)
        for subcauses in CATCH_ALL_SUBCAUSES.values()
        for subcause in subcauses
    )


def subcause_wordings(
    subcause: LatentSubcause, variant_richness: int
) -> tuple[tuple[str, str], ...]:
    """Compute one sub-cause's candidate ``(template, variant label)`` pairs.

    Args:
        subcause: The latent sub-cause to compute wordings for.
        variant_richness: The number of distinct surface wordings to make
            available. ``1`` selects the canonical template only; each
            additional level adds the next :attr:`LatentSubcause.variants`
            entry, in authored order (``paraphrase_wording``,
            ``paraphrase_reordered``, ``paraphrase_verbose``,
            ``paraphrase_terse``).

    Returns:
        A tuple of ``variant_richness`` ``(template, label)`` pairs, the
        canonical template and ``"canonical"`` label always first, in the
        order :func:`reflow.corpus.descriptions.render_subcause_description`
        should weight most-to-least likely.

    Raises:
        ValueError: If ``variant_richness`` is below :data:`MIN_VARIANT_RICHNESS`
            or exceeds ``1 + len(subcause.variants)`` for this sub-cause.
    """
    available = 1 + len(subcause.variants)
    if variant_richness < MIN_VARIANT_RICHNESS or variant_richness > available:
        raise ValueError(
            f"variant_richness must be between {MIN_VARIANT_RICHNESS} and {available} "
            f"for sub-cause {subcause.subcause_id!r}, got {variant_richness}."
        )
    pairs: list[tuple[str, str]] = [(subcause.template, "canonical")]
    pairs.extend(
        (variant.text, variant.label) for variant in subcause.variants[: variant_richness - 1]
    )
    return tuple(pairs)


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
docstring for why that is correct, not an oversight. Unaffected by the
Phase 1b ``variant_richness`` axis, which is scoped to latent sub-causes
only -- see that module's addendum for why."""

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
