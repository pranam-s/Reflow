"""The escalation ladder: how a case's action intensifies across attempts.

Deliverable 3's brief asks for "a defined progression rather than a single
binary": automated recovery, then backoff, then a method switch, then
human escalation, then an explicit give-up. :data:`LADDER_ORDER` encodes
that progression as a single, monotonically increasing sequence of four
:class:`~reflow.policy.actions.Action` values; :func:`ladder_action` walks
a case forward along it as its attempt count grows.

**Why attempt number, not an internal action-history counter.** A live
Phase 6 deployment would track "how many times has *this policy* already
tried to recover this payment" directly, since its own past decisions are
observable. This phase evaluates the policy offline against a historical
corpus, where the policy has taken no actions yet -- there is no action
history to count. The best available proxy is
:attr:`~reflow.corpus.events.PaymentEvent.attempt_number`, which is itself
a real, ground-truth count of how many times this exact order has already
been attempted (see :mod:`reflow.corpus.generator`'s retry-chain
mechanism). Using it means the ladder's rung is driven by genuine
observed retry behaviour rather than a simulated counter this phase cannot
honestly maintain -- a limitation stated plainly rather than papered over
with a synthetic action-history simulation that this offline evaluation
has no way to validate.

**Why the ladder itself never produces a terminal "give up."** The ladder
is monotonic but bounded: past its fourth rung
(:attr:`~reflow.policy.actions.Action.ESCALATE_HUMAN`), asking for a fifth,
sixth, or later attempt just holds at ``ESCALATE_HUMAN`` forever --
clamping, not escalating further, since there is no fifth rung to escalate
to. Turning "we have escalated to a human and it is still not resolved"
into an explicit give-up is deliberately not this module's job: that is
:class:`reflow.policy.guardrails.AttemptCapGuardrail`'s responsibility, so
"giving up" is recorded in the audit trail as a guardrail firing with a
stated reason, not as a quiet clamp a reader of this module alone would
never notice.
"""

from __future__ import annotations

from typing import Final

from reflow.policy.actions import Action

LADDER_ORDER: Final[tuple[Action, ...]] = (
    Action.RECOVERY_LINK_NOW,
    Action.RECOVERY_LINK_BACKOFF,
    Action.SWITCH_METHOD,
    Action.ESCALATE_HUMAN,
)
"""The four rungs a chase-worthy case can climb through, in increasing
order of intensity. An action outside this tuple
(:attr:`~reflow.policy.actions.Action.RECONCILE`,
:attr:`~reflow.policy.actions.Action.NO_ACTION`,
:attr:`~reflow.policy.actions.Action.WAIT_BANK_RECOVERY`) never has a
"next rung": :func:`ladder_action` returns it unchanged regardless of
attempt number, since none of those three represent an escalatable
customer-recovery attempt in the first place."""


def ladder_action(base_action: Action, attempt_number: int) -> Action:
    """Advance a base action along the escalation ladder by attempt number.

    A case's :func:`~reflow.policy.actions.base_action_for` result names
    its *first*-attempt action (e.g. :attr:`Action.RECOVERY_LINK_NOW` for
    ``RETRY_SAME``, :attr:`Action.RECOVERY_LINK_BACKOFF` for ``WAIT``, since
    "retry after some time" is already a backoff even on a first attempt).
    Each additional attempt on the same order shifts one rung further along
    :data:`LADDER_ORDER`, clamped at its last rung
    (:attr:`Action.ESCALATE_HUMAN`) rather than raising or wrapping.

    Args:
        base_action: The action :func:`~reflow.policy.actions.base_action_for`
            produced for this case's remediation class.
        attempt_number: The 1-based attempt number for this order (see
            :attr:`reflow.corpus.events.PaymentEvent.attempt_number`).
            Values below ``1`` are treated as ``1`` (a defensive floor,
            since attempt numbers are 1-based by construction and a value
            below that would indicate an upstream bug, not a legitimate
            zeroth attempt).

    Returns:
        ``base_action`` unchanged if it is not in :data:`LADDER_ORDER`
        (there is no rung sequence to climb); otherwise the rung
        ``attempt_number - 1`` steps ahead of ``base_action``'s own rung,
        clamped at the last rung.
    """
    if base_action not in LADDER_ORDER:
        return base_action
    start_index = LADDER_ORDER.index(base_action)
    steps = max(attempt_number - 1, 0)
    shifted_index = min(start_index + steps, len(LADDER_ORDER) - 1)
    return LADDER_ORDER[shifted_index]
