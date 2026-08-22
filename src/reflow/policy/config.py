"""Configurable thresholds every guardrail reads from, in one place.

Every number here is a **policy default**, not a value derived from a
verified external requirement, except where a docstring says otherwise and
names its source. Centralising them in one frozen dataclass makes every
guardrail independently configurable (per the phase brief) without
touching guardrail logic, and makes the defaults themselves auditable in
one place rather than scattered as magic numbers across seven classes.

**On quiet hours and Indian telecom compliance, stated plainly.** TRAI's
TCCCPR framework, DND/DLT registration, and time-of-day restrictions on
commercial communication are real, but this project has not verified a
specific numeric time-of-day threshold against a primary TRAI source, and
the applicable rule for a given message depends on facts this corpus does
not model (whether a recovery notification is classified transactional or
promotional under the sender's DLT template registration, which differs by
message content and registration, not by this project's say-so). Rather
than fabricate a cited legal threshold this project cannot verify, quiet
hours here are an honestly-labelled **policy default**:
:attr:`PolicyConfig.quiet_hours_start_hour` /
:attr:`PolicyConfig.quiet_hours_end_hour` default to 21:00-09:00, a
conservative window chosen because it is uncontroversial across common
consumer-communication norms (most "do not disturb" defaults land inside
it) and is short enough not to meaningfully delay a same-day recovery
attempt sent during business hours. A merchant operating under a specific
DLT-registered template and a verified TRAI time window should override
these two fields with that verified value; this project does not claim to
supply it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    """Every guardrail's configurable threshold, in one immutable bundle.

    Attributes:
        attempt_cap: Maximum attempt number
            (:attr:`reflow.corpus.events.PaymentEvent.attempt_number`) at
            which :class:`~reflow.policy.guardrails.AttemptCapGuardrail`
            still allows a chase or escalate action through. Defaults to
            ``4``, matching :data:`reflow.policy.ladder.LADDER_ORDER`'s own
            four rungs: attempts 1-4 climb the ladder from a fresh recovery
            link through human escalation, and attempt 5 onward is where
            continuing to try is no longer allowed and the case gives up
            (an independently configurable safety net, not hard-coded to
            the ladder's length, since a merchant may want a stricter or
              looser cap than "exactly as many attempts as ladder rungs").
        contact_cap: Maximum number of chase contacts
            (:data:`reflow.policy.actions.CHASE_ACTIONS`) one customer may
            receive within :attr:`contact_window` before
            :class:`~reflow.policy.guardrails.ContactCapGuardrail` blocks a
            further one. Defaults to ``3``: a policy default balancing
            "the merchant should keep trying to recover revenue" against
            "one customer with several failed orders on the same day
            should not receive a message for every single one."
        contact_window: The rolling window :attr:`contact_cap` is measured
            over. Defaults to 24 hours.
        cooldown: Minimum elapsed time
            :class:`~reflow.policy.guardrails.CooldownGuardrail` requires
            between two successive chase contacts to the same customer,
            independent of :attr:`contact_cap` (a customer could be under
            the daily cap and still have been contacted five minutes ago).
            Defaults to 4 hours.
        amount_floor_paise: Minimum payment amount, in paise, below which
            :class:`~reflow.policy.guardrails.AmountFloorGuardrail` blocks
            any further chase or escalate action. Defaults to ``5_000``
            (INR 50): a policy default set as an order of magnitude above
            the marginal cost of one automated contact (an SMS/email is a
            few paise to a few rupees), so it binds only on payments where
            a human-escalation-priced ladder rung (materially more
            expensive than an automated message) would plausibly cost more
            than the payment itself, not on ordinary small transactions.
        quiet_hours_start_hour: Local hour (0-23, inclusive) at which quiet
            hours begin. See module docstring for why this is a policy
            default, not a cited legal threshold. Defaults to ``21`` (9pm).
        quiet_hours_end_hour: Local hour (0-23, inclusive) at which quiet
            hours end. Defaults to ``9`` (9am). Interpreted as wrapping
            past midnight when ``quiet_hours_start_hour >
            quiet_hours_end_hour``, which is true for every value this
            project ships as a default.
        backoff_step: Base delay
            :class:`~reflow.policy.guardrails` schedules a
            :attr:`~reflow.policy.actions.Action.RECOVERY_LINK_BACKOFF`
            for, multiplied by the current attempt number so later,
            already-failed-more-often attempts wait longer. Defaults to 3
            hours.
    """

    attempt_cap: int = 4
    contact_cap: int = 3
    contact_window: timedelta = timedelta(hours=24)
    cooldown: timedelta = timedelta(hours=4)
    amount_floor_paise: int = 5_000
    quiet_hours_start_hour: int = 21
    quiet_hours_end_hour: int = 9
    backoff_step: timedelta = timedelta(hours=3)
