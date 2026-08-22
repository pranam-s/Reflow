"""The audit-trail record every policy evaluation emits.

:class:`Decision` is Deliverable 4: one structured, serialisable record per
diagnosed event, carrying the input diagnosis, the escalation ladder's
candidate action, every guardrail's verdict (blocked or passed, always
with a reason), the final action, and a human-readable justification.
Phase 6 will persist these as the audit trail; the shape here is designed
for that now, not retrofitted later -- every field is a plain string, int,
float, bool, or tuple of those (via :func:`to_dict`), so serialising a
:class:`Decision` never requires bespoke handling of an enum, a
:class:`~datetime.datetime`, or a :class:`~datetime.timedelta`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from reflow.policy.actions import Action
from reflow.policy.guardrails import GuardrailEvaluation


class LadderTerminalState(StrEnum):
    """A richer classification of a decision's final action, for reporting.

    Distinguishes *why* a case landed where it did in a way the flat
    :class:`~reflow.policy.actions.Action` distribution alone cannot: two
    events can both finish at
    :attr:`~reflow.policy.actions.Action.NO_ACTION` for entirely different
    reasons (an exhausted escalation ladder giving up, versus a
    duplicate-reason case that was never chase-worthy to begin with), and
    Deliverable 5 asks for the escalation ladder's terminal-state
    distribution specifically, not only the flat action counts.
    """

    IN_PROGRESS_LINK_NOW = "in_progress_link_now"
    IN_PROGRESS_BACKOFF = "in_progress_backoff"
    IN_PROGRESS_SWITCH_METHOD = "in_progress_switch_method"
    ESCALATED_TO_HUMAN = "escalated_to_human"
    GAVE_UP = "gave_up"
    RECONCILED = "reconciled"
    WAITING_ON_BANK = "waiting_on_bank"
    NO_ACTION_OTHER = "no_action_other"


_ATTEMPT_CAP_GUARDRAIL_NAME = "attempt_cap"


def classify_ladder_terminal_state(
    final_action: Action, guardrail_evaluations: tuple[GuardrailEvaluation, ...]
) -> LadderTerminalState:
    """Classify a decision's final action into a richer ladder-terminal-state label.

    Args:
        final_action: The decision's final action.
        guardrail_evaluations: Every guardrail evaluated for this decision,
            in evaluation order.

    Returns:
        :attr:`LadderTerminalState.GAVE_UP` if
        :attr:`~reflow.policy.actions.Action.NO_ACTION` was produced by
        :class:`~reflow.policy.guardrails.AttemptCapGuardrail` blocking;
        :attr:`LadderTerminalState.NO_ACTION_OTHER` for any other route to
        :attr:`~reflow.policy.actions.Action.NO_ACTION`; the direct
        one-to-one label for every other final action.
    """
    if final_action is Action.RECOVERY_LINK_NOW:
        return LadderTerminalState.IN_PROGRESS_LINK_NOW
    if final_action is Action.RECOVERY_LINK_BACKOFF:
        return LadderTerminalState.IN_PROGRESS_BACKOFF
    if final_action is Action.SWITCH_METHOD:
        return LadderTerminalState.IN_PROGRESS_SWITCH_METHOD
    if final_action is Action.ESCALATE_HUMAN:
        return LadderTerminalState.ESCALATED_TO_HUMAN
    if final_action is Action.RECONCILE:
        return LadderTerminalState.RECONCILED
    if final_action is Action.WAIT_BANK_RECOVERY:
        return LadderTerminalState.WAITING_ON_BANK
    gave_up = any(
        evaluation.name == _ATTEMPT_CAP_GUARDRAIL_NAME and evaluation.blocked
        for evaluation in guardrail_evaluations
    )
    return LadderTerminalState.GAVE_UP if gave_up else LadderTerminalState.NO_ACTION_OTHER


@dataclass(frozen=True, slots=True)
class Decision:
    """One event's complete, auditable policy evaluation.

    Attributes:
        payment_id: The diagnosed event's payment id.
        order_id: The diagnosed event's order id.
        customer_id: The diagnosed event's customer id.
        method: The payment method, as its string value.
        bank: The counterparty bank, or ``None``.
        amount: The payment amount, in paise.
        created_at: The event's timestamp, ISO-8601.
        attempt_number: The event's 1-based attempt number.
        error_reason: The diagnosed reason code.
        remediation_class: The resolved remediation class, as its string
            value.
        diagnosis_tier: Which tier produced the diagnosis
            (``"deterministic"`` or ``"llm"``) -- recorded for provenance
            only; every guardrail and the escalation ladder treat it
            identically, per the phase brief.
        diagnosis_confidence: The diagnosis's confidence, as its string
            value.
        in_active_incident: Whether this event was attributed to an active
            incident on its ``(method, bank)`` entity.
        base_action: The remediation-class-only action, before the
            escalation ladder or any guardrail.
        candidate_action: The escalation ladder's output for this event's
            attempt number -- the action every guardrail's first
            evaluation receives, and "what would have been sent without
            any guardrails" for the over-contact-reduction measurement.
        guardrail_evaluations: Every guardrail's verdict, in evaluation
            order, whether or not it blocked anything.
        final_action: The action remaining after every guardrail has run.
        ladder_terminal_state: See :func:`classify_ladder_terminal_state`.
        scheduled_delay_seconds: Populated only when ``final_action`` is
            :attr:`~reflow.policy.actions.Action.RECOVERY_LINK_BACKOFF`:
            how many seconds from ``created_at`` the recovery link should
            be sent.
        disallowed_method: Populated only when ``final_action`` is
            :attr:`~reflow.policy.actions.Action.SWITCH_METHOD`: the
            payment method the new recovery link should disable (the one
            that just failed), using the verified Payment Links
            per-method boolean toggle mechanism (see
            :mod:`reflow.policy.actions` module docstring) -- the policy
            layer deliberately does not name a specific alternate method
            to promote, only which one to exclude.
        justification: A human-readable prose summary of how
            ``final_action`` was reached.
    """

    payment_id: str
    order_id: str
    customer_id: str
    method: str
    bank: str | None
    amount: int
    created_at: str
    attempt_number: int
    error_reason: str
    remediation_class: str
    diagnosis_tier: str
    diagnosis_confidence: str
    in_active_incident: bool
    base_action: Action
    candidate_action: Action
    guardrail_evaluations: tuple[GuardrailEvaluation, ...]
    final_action: Action
    ladder_terminal_state: LadderTerminalState
    scheduled_delay_seconds: float | None
    disallowed_method: str | None
    justification: str


def to_dict(decision: Decision) -> dict[str, object]:
    """Serialise a :class:`Decision` to a JSON-safe nested dict.

    Args:
        decision: The decision to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``.
    """
    return {
        "payment_id": decision.payment_id,
        "order_id": decision.order_id,
        "customer_id": decision.customer_id,
        "method": decision.method,
        "bank": decision.bank,
        "amount": decision.amount,
        "created_at": decision.created_at,
        "attempt_number": decision.attempt_number,
        "error_reason": decision.error_reason,
        "remediation_class": decision.remediation_class,
        "diagnosis_tier": decision.diagnosis_tier,
        "diagnosis_confidence": decision.diagnosis_confidence,
        "in_active_incident": decision.in_active_incident,
        "base_action": decision.base_action.value,
        "candidate_action": decision.candidate_action.value,
        "guardrail_evaluations": [
            {
                "name": evaluation.name,
                "blocked": evaluation.blocked,
                "action_before": evaluation.action_before.value,
                "action_after": evaluation.action_after.value,
                "reason": evaluation.reason,
            }
            for evaluation in decision.guardrail_evaluations
        ],
        "final_action": decision.final_action.value,
        "ladder_terminal_state": decision.ladder_terminal_state.value,
        "scheduled_delay_seconds": decision.scheduled_delay_seconds,
        "disallowed_method": decision.disallowed_method,
        "justification": decision.justification,
    }
