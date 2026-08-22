"""The closed recovery-action enum and its mapping from remediation class.

Every action this project's policy layer can ever emit is one of the seven
members of :class:`Action`. Nothing outside that enum is ever produced --
:mod:`reflow.eval.policy`'s full-corpus run asserts this directly by
tallying every :class:`~reflow.policy.decision.Decision.final_action`
against :class:`Action`'s own membership.

**Why there is no ``RETRY_PAYMENT`` action.** Verified live and recorded in
``BUILD_LOG.md``: Razorpay's Payments API can fetch or capture an
already-authorised payment, but it has no endpoint that re-attempts a
failed authorisation. There is nothing in this project's action set that
means "call the Payments API again" for that reason -- recovery for a
customer-actionable failure always goes through a fresh Payment Link
(:attr:`Action.RECOVERY_LINK_NOW`, :attr:`Action.RECOVERY_LINK_BACKOFF`, or
:attr:`Action.SWITCH_METHOD`), never a retry call that does not exist.

**The remediation-class mapping is a pure function of
:class:`~reflow.taxonomy.remediation.RemediationClass` alone**
(:func:`base_action_for`) -- it never inspects the reason code, the
event's amount, or which tier (deterministic table or LLM) produced the
diagnosis. That is deliberate: the phase brief requires "the policy layer
must not care which tier produced the input," and the cleanest way to
guarantee that is to give the base mapping nothing *but* the class to look
at. Every reason-code-specific judgment call (the duplicate/already-paid
carve-out that produces :attr:`Action.RECONCILE`, the taxonomy's own
`TERMINAL` class) is a guardrail's job
(:class:`reflow.policy.guardrails.TerminalReasonGuardrail`), not this
module's, precisely so that judgment is recorded in the audit trail as a
guardrail firing rather than buried, invisibly, in a lookup table.

**Grounding for each mapping decision:**

- ``RETRY_SAME`` -> ``RECOVERY_LINK_NOW``: nothing needs fixing; give the
  customer a fresh link to reattempt the same method immediately.
- ``WAIT`` -> ``RECOVERY_LINK_BACKOFF``: the vendored text's own
  recommendation is "retry after some time," which *is* a backoff, not an
  immediate send.
- ``CUSTOMER_FIX`` -> ``RECOVERY_LINK_NOW``: the customer must correct one
  input (CVV, OTP, mobile number); a fresh link is what lets them do that.
- ``DIFFERENT_INSTRUMENT`` -> ``RECOVERY_LINK_NOW``: verified live
  (2026-08-23) against Razorpay's Payment Links "Customise Payment
  Methods" documentation
  (<https://razorpay.com/docs/api/payments/payment-links/customise-payment-methods/>),
  the only lever the Payment Links API exposes is a boolean per *method*
  (``options.checkout.method.{card,netbanking,upi,wallet}``) -- there is no
  parameter to force a specific card/instrument. A plain, unrestricted link
  is therefore the closest honest action; the API cannot enforce "use a
  different card" the way it can enforce "do not use UPI again."
- ``DIFFERENT_METHOD`` -> ``SWITCH_METHOD``: the same verified mechanism
  *can* disable the specific method that just failed, which is exactly
  what this class's vendored text recommends.
- ``DIFFERENT_INSTRUMENT_OR_METHOD`` -> ``SWITCH_METHOD``: of the two
  alternatives the vendored text offers, method-switching is the one the
  API can actually enforce, so it is the stronger, verifiable half of the
  disjunction.
- ``CUSTOMER_CONTACT_ISSUER_BANK`` -> ``RECOVERY_LINK_NOW``: the
  underlying fix (the customer resolving something with their own bank) is
  outside this project's automation boundary; sending a plain link costs
  nothing extra and does not preclude the customer also contacting their
  bank. Recorded here as a reasoned default, not a taxonomy-verified fact --
  see ``docs/design.md``'s Phase 5 ADR for the alternative considered and
  rejected (routing this class to ``NO_ACTION`` instead).
- ``MERCHANT_ACTION`` -> ``ESCALATE_HUMAN``: the vendored text puts the
  ball in the *merchant's* integration/configuration/ops court -- no
  customer-facing or bank-facing action resolves an invalid order id, a
  disabled UPI flow, or a pending internal approval. A human on the
  merchant's side needs to look at it.
- ``MERCHANT_CONTACT_RAZORPAY`` -> ``ESCALATE_HUMAN``: same reasoning --
  the vendored text says the merchant must contact Razorpay support, which
  is a human process this project does not automate.
- ``TERMINAL`` -> ``NO_ACTION``: by the taxonomy's own accounting, zero of
  110 reason codes are actually classified ``TERMINAL`` today
  (:mod:`reflow.taxonomy.remediation` module docstring); the mapping exists
  for forward-compatibility with a future taxonomy update, and "no action"
  is definitionally correct for a reason this project cannot ever
  legitimately act on.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from reflow.taxonomy.remediation import RemediationClass


class Action(StrEnum):
    """The closed set of recovery actions this project's policy can emit.

    No code path anywhere in :mod:`reflow.policy` constructs an ``Action``
    value outside this enum's membership -- every guardrail and the
    escalation ladder only ever select among these seven.
    """

    NO_ACTION = "no_action"
    WAIT_BANK_RECOVERY = "wait_bank_recovery"
    RECOVERY_LINK_NOW = "recovery_link_now"
    RECOVERY_LINK_BACKOFF = "recovery_link_backoff"
    SWITCH_METHOD = "switch_method"
    ESCALATE_HUMAN = "escalate_human"
    RECONCILE = "reconcile"


CHASE_ACTIONS: Final[frozenset[Action]] = frozenset(
    {Action.RECOVERY_LINK_NOW, Action.RECOVERY_LINK_BACKOFF, Action.SWITCH_METHOD}
)
"""Actions that mean "the customer is contacted, now or on a schedule."
Every guardrail whose job is to prevent over-contacting a customer
(:class:`~reflow.policy.guardrails.ContactCapGuardrail`,
:class:`~reflow.policy.guardrails.CooldownGuardrail`) is scoped to exactly
this set -- :attr:`Action.ESCALATE_HUMAN` is deliberately excluded, since it
means a human takes over, not that the customer receives another message."""

RECONCILE_REASONS: Final[frozenset[str]] = frozenset(
    {"order_already_paid", "duplicate_request", "duplicate_refund_id"}
)
"""Reason codes whose own vendored name denotes a duplicate or
already-settled payment -- read directly off the taxonomy's reason-code
strings, not invented. Deliberately excludes ``duplicate_rrn_found``
despite its name: :mod:`reflow.taxonomy.remediation` classifies that row's
vendored ``Next Steps`` text as ``RETRY_SAME``, not a duplicate/already
-settled case, and this project trusts the taxonomy's own text-derived
classification over a naive reading of a reason code's name. Consumed by
:class:`reflow.policy.guardrails.TerminalReasonGuardrail`, which is the
only place in the whole policy pipeline that looks at a reason code
directly rather than only at its remediation class -- see that class's
docstring for why this is a guardrail's job, not this module's."""

_BASE_ACTION_BY_CLASS: Final[dict[RemediationClass, Action]] = {
    RemediationClass.RETRY_SAME: Action.RECOVERY_LINK_NOW,
    RemediationClass.WAIT: Action.RECOVERY_LINK_BACKOFF,
    RemediationClass.CUSTOMER_FIX: Action.RECOVERY_LINK_NOW,
    RemediationClass.DIFFERENT_INSTRUMENT: Action.RECOVERY_LINK_NOW,
    RemediationClass.DIFFERENT_METHOD: Action.SWITCH_METHOD,
    RemediationClass.DIFFERENT_INSTRUMENT_OR_METHOD: Action.SWITCH_METHOD,
    RemediationClass.CUSTOMER_CONTACT_ISSUER_BANK: Action.RECOVERY_LINK_NOW,
    RemediationClass.MERCHANT_ACTION: Action.ESCALATE_HUMAN,
    RemediationClass.MERCHANT_CONTACT_RAZORPAY: Action.ESCALATE_HUMAN,
    RemediationClass.TERMINAL: Action.NO_ACTION,
}


class UnmappedRemediationClassError(ValueError):
    """Raised when a :class:`RemediationClass` has no entry in the base map.

    Guards against a future addition to :class:`RemediationClass` silently
    falling through to a ``KeyError`` with no context -- this project
    enumerates every class exhaustively (see
    ``tests/policy/test_actions.py``), so reaching this error means the
    enum grew without this module being updated to match.
    """


def base_action_for(remediation_class: RemediationClass) -> Action:
    """Map a remediation class to its base recovery action.

    A pure function of ``remediation_class`` alone -- see module docstring
    for why reason-code-specific judgment (the duplicate/already-paid
    carve-out, the ``TERMINAL`` blocklist) belongs to
    :class:`reflow.policy.guardrails.TerminalReasonGuardrail` instead of
    here.

    Args:
        remediation_class: The remediation class a diagnosis resolved to,
            regardless of whether Tier 1 (deterministic table) or Tier 2
            (LLM) produced it.

    Returns:
        The base :class:`Action` for this class, before the escalation
        ladder (:mod:`reflow.policy.ladder`) or any guardrail
        (:mod:`reflow.policy.guardrails`) has run.

    Raises:
        UnmappedRemediationClassError: If ``remediation_class`` has no
            entry in the base mapping.
    """
    try:
        return _BASE_ACTION_BY_CLASS[remediation_class]
    except KeyError as exc:
        raise UnmappedRemediationClassError(
            f"RemediationClass {remediation_class!r} has no base action mapping."
        ) from exc
