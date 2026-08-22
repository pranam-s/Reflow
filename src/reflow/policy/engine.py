"""The stateful orchestrator: diagnosis, ladder, guardrail chain, audit record.

:class:`PolicyEngine` is the one place this project decides a recovery
action end to end. Given one event and its already-resolved diagnosis
(:mod:`reflow.diagnose`'s ``EventDiagnosis``, regardless of which tier
produced it), it:

1. Maps the diagnosis's remediation class to a base action
   (:func:`reflow.policy.actions.base_action_for`).
2. Advances that base action along the escalation ladder by the event's
   attempt number (:func:`reflow.policy.ladder.ladder_action`).
3. Runs the ladder's output through every guardrail in
   :func:`reflow.policy.guardrails.default_guardrail_chain`, in order,
   recording every guardrail's verdict whether or not it changed anything.
4. Records a chase contact in this engine's own per-customer history if
   (and only if) the final action actually contacts the customer, so the
   next event for the same customer sees an accurate contact count and
   elapsed time.
5. Emits a fully populated :class:`~reflow.policy.decision.Decision`.

:func:`detect_active_incident_indices` reuses Phase 3's own recommended
detector (``poisson_surprise``, ADR-0003) and aggregation primitives
directly -- it is not a reimplementation, and it makes no LLM call and no
live API call, matching this phase's $0-spend requirement.

**Ordering precondition.** :meth:`PolicyEngine.evaluate` must be called in
non-decreasing ``created_at`` order (:meth:`PolicyEngine.evaluate_batch`
guarantees this for a chronologically sorted input, which is what
:func:`reflow.corpus.generator.generate_corpus` always yields). This is
required for the per-customer contact history to mean what its name says:
"contacts already made before this event," not contacts from events that
have not been evaluated yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from reflow.corpus.events import PaymentEvent
from reflow.diagnose.router import EventDiagnosis
from reflow.incident.aggregate import build_entity_series, entity_key
from reflow.incident.detectors import PoissonSurpriseDetector
from reflow.incident.windows import run_detector
from reflow.policy.actions import CHASE_ACTIONS, Action, base_action_for
from reflow.policy.config import PolicyConfig
from reflow.policy.decision import Decision, classify_ladder_terminal_state
from reflow.policy.diagnosis_source import diagnose_reason
from reflow.policy.guardrails import (
    Guardrail,
    GuardrailContext,
    GuardrailEvaluation,
    default_guardrail_chain,
)
from reflow.policy.ladder import ladder_action

_QUIET_HOURS_GUARDRAIL_NAME = "quiet_hours"


def detect_active_incident_indices(events: Sequence[PaymentEvent]) -> frozenset[int]:
    """Find every event index attributed to an active incident.

    Reuses :mod:`reflow.incident`'s ADR-0003-recommended
    :class:`~reflow.incident.detectors.PoissonSurpriseDetector` at the
    standard ``(method, bank)`` entity granularity
    (:func:`reflow.incident.aggregate.entity_key`) -- the same detector
    and granularity :mod:`reflow.eval.diagnose` uses for Tier 2 incident
    diagnosis, so "active incident" means the same thing in this phase as
    it did in Phase 3 and Phase 4.

    Args:
        events: The events to detect incidents in, in any order (the
            detector's own bucketing does not require pre-sorted input,
            though :meth:`PolicyEngine.evaluate_batch`'s caller-facing
            contract does, for the unrelated reason of contact-history
            ordering).

    Returns:
        The set of indices into ``events`` (by position) that belong to
        some detected incident's attributed member events.
    """
    series_by_entity = build_entity_series(events, key_fn=entity_key)
    detector = PoissonSurpriseDetector()
    active_indices: set[int] = set()
    for series in series_by_entity.values():
        for incident in run_detector(series, detector):
            active_indices.update(incident.event_indices)
    return frozenset(active_indices)


def _quiet_hours_delay(created_at: datetime, quiet_hours_end_hour: int) -> timedelta:
    """Compute the delay until the next quiet-hours end boundary.

    Only ever called when ``created_at`` is already known to fall inside
    the configured quiet-hours window (see
    :class:`reflow.policy.guardrails.QuietHoursGuardrail`), so the two
    branches below never need to handle an hour exactly on the boundary
    with no wraparound.

    Args:
        created_at: The event's timestamp.
        quiet_hours_end_hour: The configured quiet-hours end hour.

    Returns:
        The time delta from ``created_at`` to the next occurrence of
        ``quiet_hours_end_hour:00``.
    """
    end_today = created_at.replace(hour=quiet_hours_end_hour, minute=0, second=0, microsecond=0)
    target = end_today if created_at.hour < quiet_hours_end_hour else end_today + timedelta(days=1)
    return target - created_at


def _scheduled_delay_seconds(
    final_action: Action,
    event: PaymentEvent,
    evaluations: tuple[GuardrailEvaluation, ...],
    config: PolicyConfig,
) -> float | None:
    """Compute a backoff's scheduled delay, in seconds.

    Args:
        final_action: The decision's final action.
        event: The diagnosed event.
        evaluations: Every guardrail evaluated for this event.
        config: The active policy configuration.

    Returns:
        ``None`` unless ``final_action`` is
        :attr:`~reflow.policy.actions.Action.RECOVERY_LINK_BACKOFF`.
        When :class:`~reflow.policy.guardrails.QuietHoursGuardrail` is what
        produced the backoff, the delay runs to the next quiet-hours end
        boundary; otherwise it is
        :attr:`~reflow.policy.config.PolicyConfig.backoff_step` scaled by
        the event's attempt number, so a case that has already failed more
        times waits proportionally longer before the next automated
        attempt.
    """
    if final_action is not Action.RECOVERY_LINK_BACKOFF:
        return None
    deferred_by_quiet_hours = any(
        evaluation.name == _QUIET_HOURS_GUARDRAIL_NAME and evaluation.blocked
        for evaluation in evaluations
    )
    if deferred_by_quiet_hours:
        return _quiet_hours_delay(event.created_at, config.quiet_hours_end_hour).total_seconds()
    return (config.backoff_step * max(event.attempt_number, 1)).total_seconds()


def _build_justification(
    diagnosis: EventDiagnosis,
    base_action: Action,
    candidate_action: Action,
    evaluations: tuple[GuardrailEvaluation, ...],
    final_action: Action,
) -> str:
    """Render a human-readable prose summary of one policy evaluation.

    Args:
        diagnosis: The event's resolved diagnosis.
        base_action: The remediation-class-only action.
        candidate_action: The escalation ladder's output.
        evaluations: Every guardrail evaluated, in order.
        final_action: The action remaining after every guardrail has run.

    Returns:
        A prose justification naming the diagnosis, the ladder's
        candidate, every guardrail that actually changed the action (with
        its stated reason), and the final action. Guardrails that merely
        passed are omitted from the prose for readability -- they remain
        fully available, individually, on
        :attr:`~reflow.policy.decision.Decision.guardrail_evaluations`.
    """
    parts = [
        f"error_reason={diagnosis.reason!r} (tier={diagnosis.tier.value}) resolved to "
        f"remediation_class={diagnosis.remediation_class.value} -> base_action="
        f"{base_action.value}.",
        f"Escalation ladder selected candidate_action={candidate_action.value}.",
    ]
    fired = [evaluation for evaluation in evaluations if evaluation.blocked]
    if not fired:
        parts.append("Every guardrail passed; no override was applied.")
    else:
        for evaluation in fired:
            parts.append(
                f"{evaluation.name} blocked ({evaluation.action_before.value} -> "
                f"{evaluation.action_after.value}): {evaluation.reason}"
            )
    parts.append(f"Final action: {final_action.value}.")
    return " ".join(parts)


@dataclass(slots=True)
class PolicyEngine:
    """Evaluates events into :class:`~reflow.policy.decision.Decision` records.

    Attributes:
        config: The active :class:`~reflow.policy.config.PolicyConfig`.
        guardrails: The guardrail chain, in evaluation order. Defaults to
            :func:`reflow.policy.guardrails.default_guardrail_chain`.
    """

    config: PolicyConfig = field(default_factory=PolicyConfig)
    guardrails: tuple[Guardrail, ...] = field(default_factory=default_guardrail_chain)
    _contact_history: dict[str, list[datetime]] = field(default_factory=dict, init=False)
    _last_seen_at: datetime | None = field(default=None, init=False)

    def _contact_stats(
        self, customer_id: str, created_at: datetime
    ) -> tuple[int, timedelta | None]:
        """Compute this customer's contact count and recency as of ``created_at``.

        Args:
            customer_id: The customer to look up.
            created_at: The current event's timestamp.

        Returns:
            A tuple of (number of prior chase contacts within the
            configured contact window, elapsed time since the most recent
            prior contact or ``None`` if there is none).
        """
        history = self._contact_history.get(customer_id)
        if not history:
            return 0, None
        window_start = created_at - self.config.contact_window
        in_window = sum(1 for contacted_at in history if contacted_at >= window_start)
        return in_window, created_at - history[-1]

    def _record_contact(self, customer_id: str, created_at: datetime) -> None:
        """Record a chase contact for future contact-cap/cooldown lookups.

        Args:
            customer_id: The contacted customer.
            created_at: When the contact was decided.
        """
        self._contact_history.setdefault(customer_id, []).append(created_at)

    def evaluate(
        self, event: PaymentEvent, diagnosis: EventDiagnosis, *, in_active_incident: bool
    ) -> Decision:
        """Evaluate one event into a complete :class:`~reflow.policy.decision.Decision`.

        Args:
            event: The event to decide an action for.
            diagnosis: The event's resolved diagnosis (its
                ``error_reason`` must match ``event.error_reason``).
            in_active_incident: Whether this event belongs to an active
                incident on its ``(method, bank)`` entity, e.g. from
                :func:`detect_active_incident_indices`.

        Returns:
            The populated :class:`~reflow.policy.decision.Decision`.

        Raises:
            ValueError: If ``event.created_at`` precedes the most recent
                previously evaluated event's timestamp -- see module
                docstring's ordering precondition.
        """
        if self._last_seen_at is not None and event.created_at < self._last_seen_at:
            raise ValueError(
                f"Events must be evaluated in chronological order: {event.created_at} precedes "
                f"the previously evaluated event's {self._last_seen_at}."
            )
        self._last_seen_at = event.created_at

        base_action = base_action_for(diagnosis.remediation_class)
        candidate_action = ladder_action(base_action, event.attempt_number)

        contacts_in_window, time_since_last_contact = self._contact_stats(
            event.customer_id, event.created_at
        )
        context = GuardrailContext(
            event=event,
            remediation_class=diagnosis.remediation_class,
            in_active_incident=in_active_incident,
            contacts_in_window=contacts_in_window,
            time_since_last_contact=time_since_last_contact,
            config=self.config,
        )

        evaluations: list[GuardrailEvaluation] = []
        current_action = candidate_action
        for guardrail in self.guardrails:
            result = guardrail.evaluate(context, current_action)
            evaluations.append(result)
            current_action = result.action_after
        final_action = current_action
        evaluations_tuple = tuple(evaluations)

        if final_action in CHASE_ACTIONS:
            self._record_contact(event.customer_id, event.created_at)

        return Decision(
            payment_id=event.payment_id,
            order_id=event.order_id,
            customer_id=event.customer_id,
            method=event.method.value,
            bank=event.bank,
            amount=event.amount,
            created_at=event.created_at.isoformat(),
            attempt_number=event.attempt_number,
            error_reason=event.error_reason,
            remediation_class=diagnosis.remediation_class.value,
            diagnosis_tier=diagnosis.tier.value,
            diagnosis_confidence=diagnosis.confidence.value,
            in_active_incident=in_active_incident,
            base_action=base_action,
            candidate_action=candidate_action,
            guardrail_evaluations=evaluations_tuple,
            final_action=final_action,
            ladder_terminal_state=classify_ladder_terminal_state(final_action, evaluations_tuple),
            scheduled_delay_seconds=_scheduled_delay_seconds(
                final_action, event, evaluations_tuple, self.config
            ),
            disallowed_method=(
                event.method.value if final_action is Action.SWITCH_METHOD else None
            ),
            justification=_build_justification(
                diagnosis, base_action, candidate_action, evaluations_tuple, final_action
            ),
        )

    def evaluate_batch(
        self, events: Sequence[PaymentEvent], diagnoses: dict[str, EventDiagnosis]
    ) -> list[Decision]:
        """Evaluate a chronologically sorted batch of events end to end.

        Args:
            events: The events to evaluate, in non-decreasing
                ``created_at`` order (see module docstring's ordering
                precondition).
            diagnoses: Every reason code's resolved diagnosis, e.g. from
                :func:`reflow.policy.diagnosis_source.build_offline_diagnoses`.

        Returns:
            One :class:`~reflow.policy.decision.Decision` per event, in
            the same order.
        """
        active_indices = detect_active_incident_indices(events)
        decisions: list[Decision] = []
        for index, event in enumerate(events):
            diagnosis = diagnose_reason(event.error_reason, diagnoses)
            decisions.append(
                self.evaluate(event, diagnosis, in_active_incident=index in active_indices)
            )
        return decisions
