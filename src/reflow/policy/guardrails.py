"""The seven independently testable, independently configurable guardrails.

Every guardrail here is a small, frozen, stateless class implementing
:class:`Guardrail`: given a :class:`GuardrailContext` (everything it might
need to decide, computed once per event by
:mod:`reflow.policy.engine` before any guardrail runs) and the action the
pipeline is currently proposing, it returns a :class:`GuardrailEvaluation`
naming itself, whether it blocked anything, the action before and after it
ran, and a human-readable reason -- **always**, whether or not it changed
anything. "A guardrail that silently drops an action is worse than no
guardrail" (phase brief); the mirror image is equally true for the audit
trail, so every guardrail below returns a populated, truthful
:class:`GuardrailEvaluation` on every call, including the common case
where it passes without touching anything.

**Why a sequential chain, not an independent verdict per guardrail.**
Recording "every guardrail evaluated with its verdict" (Deliverable 4)
does not require every guardrail to see the *same* input action -- it
requires every guardrail's own verdict, given whatever the pipeline had
decided by the time it ran, to be recorded. A chain
(:func:`default_guardrail_chain`, run in a fixed, documented order by
:class:`reflow.policy.engine.PolicyEngine`) makes each guardrail a small,
pure, independently unit-testable function of ``(context, action) ->
GuardrailEvaluation``, and makes "what would have happened without any
guardrails" a well-defined quantity (the pipeline's action before the
first guardrail ran) without needing a separate precedence-resolution
rule for guardrails that might otherwise disagree.

**Evaluation order, and why:** :class:`TerminalReasonGuardrail` first
(is this reason contact-worthy at all), then
:class:`ActiveIncidentGuardrail` (is the rail itself already known to be
down), then :class:`AmountFloorGuardrail` (is further spend economically
justified), then :class:`AttemptCapGuardrail` (have we already tried too
many times), then :class:`ContactCapGuardrail` and
:class:`CooldownGuardrail` (anti-spam), and :class:`QuietHoursGuardrail`
last, since it only ever *defers* a send within the same case rather than
cancelling it outright, so it should see whatever the rest of the chain
has already decided.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Protocol, runtime_checkable

from reflow.corpus.events import PaymentEvent
from reflow.policy.actions import CHASE_ACTIONS, RECONCILE_REASONS, Action
from reflow.policy.config import PolicyConfig
from reflow.taxonomy.remediation import RemediationClass

_ESCALATE_OR_CHASE: Final[frozenset[Action]] = CHASE_ACTIONS | {Action.ESCALATE_HUMAN}
_QUIET_HOURS_SENDS: Final[frozenset[Action]] = frozenset(
    {Action.RECOVERY_LINK_NOW, Action.SWITCH_METHOD}
)


@dataclass(frozen=True, slots=True)
class GuardrailContext:
    """Everything a guardrail might need, computed once per event.

    Attributes:
        event: The event being decided for.
        remediation_class: The event's resolved remediation class,
            regardless of which tier produced it.
        in_active_incident: Whether
            :func:`reflow.incident.detectors.PoissonSurpriseDetector`
            (the ADR-0003-recommended detector) attributed this event to
            an active incident on its ``(method, bank)`` entity.
        contacts_in_window: How many chase contacts
            (:data:`reflow.policy.actions.CHASE_ACTIONS`) this event's
            customer has already received within the trailing
            :attr:`~reflow.policy.config.PolicyConfig.contact_window` as
            of :attr:`~reflow.corpus.events.PaymentEvent.created_at`,
            excluding this event itself.
        time_since_last_contact: Elapsed time since this customer's most
            recent chase contact before this event, or ``None`` if this
            customer has never been contacted.
        config: The active :class:`~reflow.policy.config.PolicyConfig`.
    """

    event: PaymentEvent
    remediation_class: RemediationClass
    in_active_incident: bool
    contacts_in_window: int
    time_since_last_contact: timedelta | None
    config: PolicyConfig


@dataclass(frozen=True, slots=True)
class GuardrailEvaluation:
    """One guardrail's verdict on one event, for the audit trail.

    Attributes:
        name: The guardrail's stable identifier.
        blocked: Whether this guardrail changed the action.
        action_before: The action the pipeline proposed when this
            guardrail ran.
        action_after: The action after this guardrail ran -- equal to
            ``action_before`` whenever ``blocked`` is ``False``.
        reason: A human-readable explanation, populated whether or not
            this guardrail blocked anything -- "we checked and it was
            allowed" is recorded with the same care as a block.
    """

    name: str
    blocked: bool
    action_before: Action
    action_after: Action
    reason: str


def _pass(name: str, action: Action, reason: str) -> GuardrailEvaluation:
    """Build a passing :class:`GuardrailEvaluation` (action unchanged).

    Args:
        name: The guardrail's stable identifier.
        action: The action left unchanged.
        reason: Why this guardrail did not block anything.

    Returns:
        A :class:`GuardrailEvaluation` with ``blocked=False``.
    """
    return GuardrailEvaluation(
        name=name, blocked=False, action_before=action, action_after=action, reason=reason
    )


def _block(
    name: str, action_before: Action, action_after: Action, reason: str
) -> GuardrailEvaluation:
    """Build a blocking :class:`GuardrailEvaluation` (action overridden).

    Args:
        name: The guardrail's stable identifier.
        action_before: The action this guardrail overrode.
        action_after: The replacement action.
        reason: Why this guardrail blocked the original action.

    Returns:
        A :class:`GuardrailEvaluation` with ``blocked=True``.
    """
    return GuardrailEvaluation(
        name=name,
        blocked=True,
        action_before=action_before,
        action_after=action_after,
        reason=reason,
    )


@runtime_checkable
class Guardrail(Protocol):
    """Common interface every guardrail in :func:`default_guardrail_chain` implements."""

    @property
    def name(self) -> str:
        """A short, stable, human-readable identifier for this guardrail."""
        ...

    def evaluate(self, context: GuardrailContext, action: Action) -> GuardrailEvaluation:
        """Evaluate this guardrail against one event's current candidate action.

        Args:
            context: The event's precomputed :class:`GuardrailContext`.
            action: The action the pipeline currently proposes, i.e. either
                the escalation ladder's own output (for the first
                guardrail in the chain) or the previous guardrail's
                ``action_after`` (for every later one).

        Returns:
            This guardrail's :class:`GuardrailEvaluation`.
        """
        ...


@dataclass(frozen=True, slots=True)
class TerminalReasonGuardrail:
    """Blocks contact for reasons the taxonomy marks as not contact-worthy.

    The blocklist is derived from the taxonomy in two parts, never
    invented: :data:`reflow.policy.actions.RECONCILE_REASONS` (reason
    codes whose own vendored name denotes a duplicate or already-settled
    payment) and :attr:`~reflow.taxonomy.remediation.RemediationClass.TERMINAL`
    (kept in the taxonomy for forward-compatibility even though zero of
    110 reasons are currently classified into it -- see
    :mod:`reflow.taxonomy.remediation` module docstring). The second branch
    is exercised directly in ``tests/policy/test_guardrails.py`` with a
    synthetic ``TERMINAL``-classified context even though it cannot fire on
    the current corpus, so this guardrail's logic is proven correct
    independent of whether today's taxonomy happens to populate that class.

    Attributes:
        name: ``"terminal_reason_blocklist"``.
    """

    name: str = "terminal_reason_blocklist"

    def evaluate(self, context: GuardrailContext, action: Action) -> GuardrailEvaluation:
        """Redirect a duplicate/already-paid or TERMINAL case away from contact.

        Args:
            context: The event's precomputed context.
            action: The pipeline's current candidate action.

        Returns:
            A block to :attr:`Action.RECONCILE` for a reason in
            :data:`~reflow.policy.actions.RECONCILE_REASONS`, a block to
            :attr:`Action.NO_ACTION` for a
            :attr:`~reflow.taxonomy.remediation.RemediationClass.TERMINAL`
            case, or a pass otherwise -- including a pass when the
            candidate action is already compliant (e.g. already
            ``RECONCILE``), since there is then nothing left to block.
        """
        reason = context.event.error_reason
        if reason in RECONCILE_REASONS:
            if action == Action.RECONCILE:
                return _pass(
                    self.name,
                    action,
                    f"error_reason {reason!r} is a known duplicate/already-paid case, and the "
                    "candidate action is already reconcile.",
                )
            if action not in _ESCALATE_OR_CHASE:
                return _pass(
                    self.name,
                    action,
                    f"error_reason {reason!r} is a known duplicate/already-paid case, but the "
                    f"candidate action {action.value} does not involve contacting the customer "
                    "or a human, so no override is needed.",
                )
            return _block(
                self.name,
                action,
                Action.RECONCILE,
                f"error_reason {reason!r} is a known duplicate/already-paid case (derived from "
                "the reason code's own taxonomy semantics); continuing toward "
                f"{action.value} risks contacting the customer about a payment that does not "
                "need it, or a duplicate charge -- reconciliation is the correct action, not "
                "customer contact or human escalation.",
            )
        if context.remediation_class is RemediationClass.TERMINAL:
            if action == Action.NO_ACTION:
                return _pass(
                    self.name,
                    action,
                    "remediation class is TERMINAL and the candidate is already no_action.",
                )
            return _block(
                self.name,
                action,
                Action.NO_ACTION,
                "remediation class is TERMINAL: the taxonomy considers this reason not "
                "actionable, so no further contact or escalation is warranted.",
            )
        return _pass(
            self.name,
            action,
            f"error_reason {reason!r} is not on the terminal/reconcile blocklist.",
        )


@dataclass(frozen=True, slots=True)
class ActiveIncidentGuardrail:
    """Suppresses a chase action while an incident is active on the entity.

    The single most consequential guardrail in this project: it is what
    turns "an incident is active on this (method, bank)" into the agent
    deliberately choosing not to act
    (:attr:`~reflow.policy.actions.Action.WAIT_BANK_RECOVERY`) rather than
    spamming a customer whose payment is failing because the bank or rail
    itself is down, not because of anything specific to their payment.
    Scoped to :data:`~reflow.policy.actions.CHASE_ACTIONS` only --
    :attr:`~reflow.policy.actions.Action.ESCALATE_HUMAN` is not suppressed,
    since a ``MERCHANT_ACTION``/``MERCHANT_CONTACT_RAZORPAY`` case is a
    merchant-side integration matter unrelated to a bank-side incident.

    Attributes:
        name: ``"active_incident_suppression"``.
    """

    name: str = "active_incident_suppression"

    def evaluate(self, context: GuardrailContext, action: Action) -> GuardrailEvaluation:
        """Redirect a chase action to wait-for-bank-recovery during an incident.

        Args:
            context: The event's precomputed context.
            action: The pipeline's current candidate action.

        Returns:
            A block to :attr:`Action.WAIT_BANK_RECOVERY` when
            ``context.in_active_incident`` and ``action`` is a chase
            action, otherwise a pass.
        """
        if not context.in_active_incident:
            return _pass(
                self.name,
                action,
                "no active incident detected on this (method, bank) at this event's time.",
            )
        if action not in CHASE_ACTIONS:
            return _pass(
                self.name,
                action,
                f"an incident is active on this (method, bank), but the candidate action "
                f"{action.value} does not involve contacting the customer, so no suppression "
                "is needed.",
            )
        return _block(
            self.name,
            action,
            Action.WAIT_BANK_RECOVERY,
            "poisson_surprise (docs/design.md ADR-0003) detected an active incident on this "
            "(method, bank) at this event's time; chasing the customer while the bank or rail "
            "itself is down is wrong -- deliberately waiting for bank-side recovery instead.",
        )


@dataclass(frozen=True, slots=True)
class AmountFloorGuardrail:
    """Blocks further spend on a payment below the configured amount floor.

    Attributes:
        name: ``"amount_floor"``.
    """

    name: str = "amount_floor"

    def evaluate(self, context: GuardrailContext, action: Action) -> GuardrailEvaluation:
        """Block a chase or escalate action below the configured amount floor.

        Args:
            context: The event's precomputed context.
            action: The pipeline's current candidate action.

        Returns:
            A block to :attr:`Action.NO_ACTION` when ``action`` is a chase
            or escalate action and the event's amount is below
            :attr:`~reflow.policy.config.PolicyConfig.amount_floor_paise`,
            otherwise a pass.
        """
        floor = context.config.amount_floor_paise
        amount = context.event.amount
        if action not in _ESCALATE_OR_CHASE:
            return _pass(
                self.name,
                action,
                f"candidate action {action.value} does not represent further spend, so the "
                "amount floor does not apply.",
            )
        if amount >= floor:
            return _pass(
                self.name,
                action,
                f"amount {amount} paise is at or above the configured floor of {floor} paise.",
            )
        return _block(
            self.name,
            action,
            Action.NO_ACTION,
            f"amount {amount} paise is below the configured floor of {floor} paise; further "
            f"{action.value} spend is not economically justified for this payment.",
        )


@dataclass(frozen=True, slots=True)
class AttemptCapGuardrail:
    """Turns "we have tried enough times" into an explicit give-up.

    Attributes:
        name: ``"attempt_cap"``.
    """

    name: str = "attempt_cap"

    def evaluate(self, context: GuardrailContext, action: Action) -> GuardrailEvaluation:
        """Block a chase or escalate action once the attempt cap is exceeded.

        Args:
            context: The event's precomputed context.
            action: The pipeline's current candidate action.

        Returns:
            A block to :attr:`Action.NO_ACTION` when the event's
            ``attempt_number`` exceeds
            :attr:`~reflow.policy.config.PolicyConfig.attempt_cap` and
            ``action`` is a chase or escalate action, otherwise a pass.
        """
        cap = context.config.attempt_cap
        attempt = context.event.attempt_number
        if action not in _ESCALATE_OR_CHASE:
            return _pass(
                self.name,
                action,
                f"candidate action {action.value} is not a further attempt, so the attempt cap "
                "does not apply.",
            )
        if attempt <= cap:
            return _pass(self.name, action, f"attempt {attempt} is within the cap of {cap}.")
        return _block(
            self.name,
            action,
            Action.NO_ACTION,
            f"attempt {attempt} exceeds the configured cap of {cap}; the escalation ladder is "
            "exhausted and giving up is the correct terminal state, not silently retrying "
            "forever.",
        )


@dataclass(frozen=True, slots=True)
class ContactCapGuardrail:
    """Caps how many chase contacts one customer receives in a rolling window.

    Attributes:
        name: ``"per_customer_contact_cap"``.
    """

    name: str = "per_customer_contact_cap"

    def evaluate(self, context: GuardrailContext, action: Action) -> GuardrailEvaluation:
        """Block a chase action once the customer's contact cap is reached.

        Args:
            context: The event's precomputed context.
            action: The pipeline's current candidate action.

        Returns:
            A block to :attr:`Action.NO_ACTION` when ``action`` is a chase
            action and ``context.contacts_in_window`` is at or above
            :attr:`~reflow.policy.config.PolicyConfig.contact_cap`,
            otherwise a pass.
        """
        cap = context.config.contact_cap
        count = context.contacts_in_window
        window = context.config.contact_window
        if action not in CHASE_ACTIONS:
            return _pass(
                self.name,
                action,
                f"candidate action {action.value} does not contact the customer, so the "
                "contact cap does not apply.",
            )
        if count < cap:
            return _pass(
                self.name,
                action,
                f"customer has received {count} contact(s) in {window}, under cap {cap}.",
            )
        return _block(
            self.name,
            action,
            Action.NO_ACTION,
            f"customer has already received {count} contact(s) within the trailing {window}, "
            f"at or above the configured cap of {cap}; suppressing a further contact this round.",
        )


@dataclass(frozen=True, slots=True)
class CooldownGuardrail:
    """Enforces a minimum gap between successive contacts to one customer.

    Attributes:
        name: ``"contact_cooldown"``.
    """

    name: str = "contact_cooldown"

    def evaluate(self, context: GuardrailContext, action: Action) -> GuardrailEvaluation:
        """Block a chase action within the cooldown period of the last contact.

        Args:
            context: The event's precomputed context.
            action: The pipeline's current candidate action.

        Returns:
            A block to :attr:`Action.NO_ACTION` when ``action`` is a chase
            action and
            ``context.time_since_last_contact`` is shorter than
            :attr:`~reflow.policy.config.PolicyConfig.cooldown`, otherwise
            a pass.
        """
        cooldown = context.config.cooldown
        elapsed = context.time_since_last_contact
        if action not in CHASE_ACTIONS:
            return _pass(
                self.name,
                action,
                f"candidate action {action.value} does not contact the customer, so the "
                "cooldown does not apply.",
            )
        if elapsed is None:
            return _pass(self.name, action, "customer has never been contacted before.")
        if elapsed >= cooldown:
            return _pass(
                self.name,
                action,
                f"last contact was {elapsed} ago, at or beyond the configured cooldown of "
                f"{cooldown}.",
            )
        return _block(
            self.name,
            action,
            Action.NO_ACTION,
            f"last contact to this customer was {elapsed} ago, inside the configured cooldown "
            f"of {cooldown}; suppressing a further contact this round.",
        )


@dataclass(frozen=True, slots=True)
class QuietHoursGuardrail:
    """Defers a same-instant send that would land inside quiet hours.

    Never cancels a send outright -- it only converts an immediate
    customer-facing send into a scheduled
    :attr:`~reflow.policy.actions.Action.RECOVERY_LINK_BACKOFF`, deferred
    to the next moment quiet hours end (see
    :mod:`reflow.policy.config` for why the window itself is a documented
    policy default, not a cited legal threshold).

    Attributes:
        name: ``"quiet_hours"``.
    """

    name: str = "quiet_hours"

    def evaluate(self, context: GuardrailContext, action: Action) -> GuardrailEvaluation:
        """Defer an in-quiet-hours send to a backoff after quiet hours end.

        Args:
            context: The event's precomputed context.
            action: The pipeline's current candidate action.

        Returns:
            A block to :attr:`Action.RECOVERY_LINK_BACKOFF` when ``action``
            is an immediate customer-facing send
            (:attr:`Action.RECOVERY_LINK_NOW` or
            :attr:`Action.SWITCH_METHOD`) and the event's timestamp falls
            within the configured quiet-hours window, otherwise a pass.
        """
        if action not in _QUIET_HOURS_SENDS:
            return _pass(
                self.name,
                action,
                f"candidate action {action.value} is not an immediate send, so quiet hours do "
                "not apply.",
            )
        hour = context.event.created_at.hour
        start = context.config.quiet_hours_start_hour
        end = context.config.quiet_hours_end_hour
        if not _in_quiet_hours(hour, start, end):
            return _pass(
                self.name,
                action,
                f"event hour {hour} is outside the configured quiet-hours window [{start}, {end}).",
            )
        return _block(
            self.name,
            action,
            Action.RECOVERY_LINK_BACKOFF,
            f"event hour {hour} falls within the configured quiet-hours window [{start}, {end}) "
            "(policy default, not a cited legal threshold -- see reflow.policy.config module "
            "docstring); deferring the send rather than contacting the customer overnight.",
        )


def _in_quiet_hours(hour: int, start: int, end: int) -> bool:
    """Determine whether an hour-of-day falls within a wrapping quiet-hours window.

    Args:
        hour: The hour to check, ``0``-``23``.
        start: The quiet-hours start hour, inclusive.
        end: The quiet-hours end hour, exclusive.

    Returns:
        ``True`` if ``hour`` is inside ``[start, end)`` when the window
        wraps past midnight (``start > end``, true of every default this
        project ships), or inside the plain ``[start, end)`` interval
        otherwise.
    """
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


def default_guardrail_chain() -> tuple[Guardrail, ...]:
    """Build the seven guardrails in their documented evaluation order.

    Returns:
        A fresh tuple of guardrail instances (every guardrail here is
        immutable and stateless, so instances are freely shareable, but a
        fresh tuple is still returned per call to avoid any caller
        mutating a shared module-level tuple).
    """
    return (
        TerminalReasonGuardrail(),
        ActiveIncidentGuardrail(),
        AmountFloorGuardrail(),
        AttemptCapGuardrail(),
        ContactCapGuardrail(),
        CooldownGuardrail(),
        QuietHoursGuardrail(),
    )
