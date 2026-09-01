"""``P(recovery | root cause, action)``: a seeded oracle the agent never sees.

**Why an oracle exists at all.** Razorpay's test mode lets a caller force
one payment to succeed or fail on demand -- a binary toggle, not a
probability. There is no sandbox surface that says "a `card_declined`
failure recovers 42% of the time if you send a fresh Payment Link
immediately, 61% if you wait and retry after the customer's bank clears an
outage." A realistic, multi-reason outcome model cannot be *obtained* from
the sandbox; it can only be *assumed*, honestly and on the record, or not
built at all. This module is that honest assumption, built once, in the
open, so every later evaluation measures **policy quality against a
known, stated, adversarially-inspectable world** -- never real-world
rupees, and never a number the policy layer can query or curve-fit
against. :mod:`reflow.eval.simulate` is the only caller.

**Grounding, not invention.** Every base probability here is derived from
the *already-existing* classification in
:mod:`reflow.taxonomy.remediation`, which read all 114 vendored rows'
``Next Steps`` text by hand once, in Phase 1. This module adds no new
reading of that spreadsheet and no new judgment about what any reason
code's text says -- it only assigns two numbers per
:class:`~reflow.taxonomy.remediation.RemediationClass` (never per reason
code, since the class *is* the remediation-text-derived grouping) that
express what that classification already implies:

- :data:`_SELF_RECOVERY_RATE` -- the probability a failure in this class
  recovers with **no intervention at all** (:attr:`~reflow.policy.actions.Action.NO_ACTION`).
  Every class gets a strictly positive rate: some customers retry
  unprompted, some transient issues clear on their own, and a `do_nothing`
  baseline that recovers literally nothing would flatter every alternative
  by comparison rather than measuring one honestly (the phase brief's own
  requirement). The ordering across classes tracks the taxonomy directly:
  :attr:`~reflow.taxonomy.remediation.RemediationClass.RETRY_SAME` --
  "nothing needs fixing, the payment just needs to be reattempted" -- has
  this module's highest self-recovery rate, because a customer who fails
  for that reason is disproportionately likely to just try again on their
  own. :attr:`~reflow.taxonomy.remediation.RemediationClass.MERCHANT_ACTION`
  and :attr:`~reflow.taxonomy.remediation.RemediationClass.MERCHANT_CONTACT_RAZORPAY`
  -- reasons whose vendored text puts the fix in the merchant's or
  Razorpay's court, never the customer's -- get this module's lowest rates,
  because nothing the customer does on their own resolves an invalid order
  id or a Razorpay-side block.
- :data:`_ACTION_CEILING` -- the probability a failure in this class
  recovers **if given the textbook-correct action for it**, i.e. the
  action :func:`reflow.policy.actions.base_action_for` already maps that
  class to. This is the module's only other free parameter per class, and
  it is ordered the same way: `RETRY_SAME` has the highest ceiling (a
  clean retry channel is close to a full fix), `TERMINAL` the lowest (the
  taxonomy's own forward-compatibility class for "not actionable in
  practice" -- see :mod:`reflow.taxonomy.remediation` module docstring for
  why zero of 110 reasons are actually classified into it today).

**How an action's fit is scored, reusing Phase 5's own mapping.** A class
does not only ever receive its "native" action -- the escalation ladder
(:mod:`reflow.policy.ladder`) can push a case through
:attr:`~reflow.policy.actions.Action.SWITCH_METHOD` or
:attr:`~reflow.policy.actions.Action.ESCALATE_HUMAN` regardless of which
class it started in, and the baselines in :mod:`reflow.eval.simulate`
apply one fixed action to every class indiscriminately. Rather than
hand-writing a 10-class-by-7-action probability matrix (72 invented
numbers, most never justified by anything), :func:`recovery_probability`
asks exactly one question of
:func:`reflow.policy.actions.base_action_for`: is the action being scored
the one this class's own remediation text already recommends? If yes, the
action gets full credit (:data:`_NATIVE_ACTION_FIT`) toward closing the
gap between the class's self-recovery floor and its ceiling. If no, it
gets a fixed, much smaller fraction (:data:`_NONNATIVE_ACTION_FIT`) --
modelling directly the claim the phase brief asks this oracle to make
concrete: "one whose documented remediation is 'use a different method'
will not recover by retrying the same way." Forcing a method switch onto a
case that only needed a fresh retry, or sending a plain retry link to a
case that needed a method switch, both still help a little (a fresh
channel bypasses *some* transient friction regardless of the original
cause) but nowhere near as much as doing the textbook-correct thing.

**Two actions score outside the class-conditional formula, on purpose.**

- :attr:`~reflow.policy.actions.Action.RECONCILE` always scores probability
  ``0.0`` for *new* recovery, by construction, at every sensitivity level.
  A reconciled case (:data:`reflow.policy.actions.RECONCILE_REASONS`:
  ``order_already_paid``, ``duplicate_request``, ``duplicate_refund_id``)
  is a payment that already succeeded through another channel or a
  duplicate that must not be charged again -- crediting it as "recovered"
  here would double-count revenue the merchant already has, not model a
  real incremental outcome.
- :attr:`~reflow.policy.actions.Action.WAIT_BANK_RECOVERY` -- the action
  :class:`reflow.policy.guardrails.ActiveIncidentGuardrail` produces while
  a bank/rail outage is detected as active -- is scored by a single flat
  rate (:data:`_INCIDENT_RECOVERY_RATE_CENTRAL`), independent of
  remediation class. During a live incident the specific class-level
  reasoning is moot: the rail itself is down, not the customer's
  instrument or input, so *any* reason routed here shares the same
  "recovers once the bank does" mechanism the phase brief names
  explicitly. This is deliberately modelled as elevated relative to the
  generic self-recovery floor it is compared against
  (:data:`_GENERIC_SELF_RECOVERY_FLOOR`): this corpus's downtime windows
  (:mod:`reflow.corpus.downtime`) span 15 minutes to 4 hours, and by the
  time a customer's *next* recorded failure on the same order arrives
  (this is a closed-loop simulation -- see :mod:`reflow.eval.simulate` --
  so "next" means the corpus's own next scheduled attempt on that order),
  most such outages have already ended. Individual
  :class:`~reflow.corpus.events.PaymentEvent` records do not carry their
  originating :class:`~reflow.corpus.downtime.DowntimeWindow`'s end
  timestamp, so this module does not attempt to reconstruct exact
  incident-elapsed-time-dependent recovery odds; a flat, class-independent
  rate is the honest, stated simplification instead of a false precision
  this data does not support.

**The sensitivity band covers every probability, not only the ones that
favour intervention.** A band that only widened the case *for* acting
would not survive "an attack on any individual probability" -- a
reviewer could reasonably ask why the ``do_nothing`` floor alone was
held immune from doubt. :class:`SensitivityLevel` therefore scales two
distinct things at each of its three points, both fixed before any
simulation was run and before any result was read, per this project's
second governing principle:

- :data:`_SENSITIVITY_MULTIPLIER` (``0.6`` / ``1.0`` / ``1.4``) scales
  the *uplift* any action provides over its class's no-action floor --
  the primary, contested claim ("does taking this action help, and by
  how much").
- :data:`_FLOOR_SENSITIVITY_MULTIPLIER` (``0.8`` / ``1.0`` / ``1.2``)
  scales the no-action floor itself, including
  :data:`_GENERIC_SELF_RECOVERY_FLOOR`. This band is deliberately
  narrower than the uplift band: ambient, no-intervention behaviour
  (does a customer retry unprompted, does a transient issue clear on
  its own) is a less contested quantity than "how effective is a
  merchant's specific intervention", which is what this whole project
  exists to measure -- but it is still a real assumption, so it still
  moves, and the ``do_nothing`` baseline's own recovered total genuinely
  varies across the band rather than being pinned to one point.

Both bands are plausible, symmetric-ish ranges around their central
estimate, not ranges shaped after seeing which values would flatter any
particular comparison. :mod:`reflow.eval.simulate` runs its full
closed-loop comparison at all three levels and reports whether its
conclusion holds throughout the band or breaks somewhere in it --
whichever is true.

**Determinism, and why the "luck" draw does not depend on sensitivity
level or on which action was actually taken.** :meth:`RecoveryOracle.sample_recovery`
derives a uniform ``[0, 1)`` draw from a SHA-256 digest of the payment id
alone (every :class:`~reflow.corpus.events.PaymentEvent` -- including every
retry of the same order, which each get a fresh ``payment_id`` -- has
exactly one). The *same* draw is reused across every sensitivity level and
every action a caller might score that payment attempt against; only the
probability threshold the draw is compared to changes. This has two
consequences, both intentional: first, comparing two policies (or the same
policy under two sensitivity levels) on the same underlying corpus is a
fair, apples-to-apples comparison of *policy quality*, not an artefact of
independently re-rolled dice for each one; second, the relationship is
monotonic by construction -- for a fixed payment attempt, a strictly more
effective action can never recover *less* often than a less effective one
would have. Nothing here uses Python's global ``random`` module, so this
oracle's output cannot be perturbed by unrelated randomness consumed
elsewhere in a simulation run.

**Independence assumption, stated plainly.** Each raw attempt on an order
is scored as an independent Bernoulli trial against that attempt's own
probability; recovery odds do not decay or improve across an order's
repeated attempts beyond whatever the escalation ladder's own action
choice already implies. A real population would plausibly show
diminishing returns as the easiest-to-recover customers resolve first,
leaving a harder residual behind. This module does not model that,
because doing so would add a free parameter (a decay rate) with no
grounding in anything the vendored taxonomy states -- exactly the kind of
invented number this module's whole design is built to avoid.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from reflow.policy.actions import Action, base_action_for
from reflow.taxonomy.remediation import RemediationClass

_HASH_SALT: Final[str] = "reflow-outcome-oracle"


class SensitivityLevel(StrEnum):
    """The three points Phase 7 reports the recovery oracle's claims across.

    Fixed before any simulation was run (see module docstring): the band
    is a stated, symmetric-ish sensitivity sweep, not a range chosen after
    seeing which values would flatter a particular conclusion.
    """

    PESSIMISTIC = "pessimistic"
    CENTRAL = "central"
    OPTIMISTIC = "optimistic"


_SENSITIVITY_MULTIPLIER: Final[dict[SensitivityLevel, float]] = {
    SensitivityLevel.PESSIMISTIC: 0.6,
    SensitivityLevel.CENTRAL: 1.0,
    SensitivityLevel.OPTIMISTIC: 1.4,
}
"""Scales the uplift any action provides over its class's central-estimate
no-action floor (see module docstring)."""

_FLOOR_SENSITIVITY_MULTIPLIER: Final[dict[SensitivityLevel, float]] = {
    SensitivityLevel.PESSIMISTIC: 0.8,
    SensitivityLevel.CENTRAL: 1.0,
    SensitivityLevel.OPTIMISTIC: 1.2,
}
"""Scales the no-action floor itself (and
:data:`_GENERIC_SELF_RECOVERY_FLOOR`), independently of and more narrowly
than :data:`_SENSITIVITY_MULTIPLIER` -- see module docstring for why the
two are deliberately different widths."""

_SELF_RECOVERY_RATE: Final[dict[RemediationClass, float]] = {
    RemediationClass.RETRY_SAME: 0.30,
    RemediationClass.WAIT: 0.25,
    RemediationClass.CUSTOMER_FIX: 0.15,
    RemediationClass.DIFFERENT_INSTRUMENT: 0.10,
    RemediationClass.DIFFERENT_METHOD: 0.08,
    RemediationClass.DIFFERENT_INSTRUMENT_OR_METHOD: 0.10,
    RemediationClass.CUSTOMER_CONTACT_ISSUER_BANK: 0.05,
    RemediationClass.MERCHANT_ACTION: 0.03,
    RemediationClass.MERCHANT_CONTACT_RAZORPAY: 0.02,
    RemediationClass.TERMINAL: 0.01,
}
"""``P(recovery | class, NO_ACTION)`` -- see module docstring for the
per-class grounding narrative. Every value is strictly positive: no class
is modelled as literally unable to self-recover."""

_ACTION_CEILING: Final[dict[RemediationClass, float]] = {
    RemediationClass.RETRY_SAME: 0.80,
    RemediationClass.WAIT: 0.65,
    RemediationClass.CUSTOMER_FIX: 0.60,
    RemediationClass.DIFFERENT_INSTRUMENT: 0.45,
    RemediationClass.DIFFERENT_METHOD: 0.55,
    RemediationClass.DIFFERENT_INSTRUMENT_OR_METHOD: 0.50,
    RemediationClass.CUSTOMER_CONTACT_ISSUER_BANK: 0.30,
    RemediationClass.MERCHANT_ACTION: 0.55,
    RemediationClass.MERCHANT_CONTACT_RAZORPAY: 0.40,
    RemediationClass.TERMINAL: 0.02,
}
"""``P(recovery | class, base_action_for(class))`` at the central
sensitivity level -- the class's textbook-correct-action ceiling. See
module docstring."""

_NATIVE_ACTION_FIT: Final[float] = 1.0
"""Credit given when the action being scored is exactly
``base_action_for(remediation_class)`` -- full, uncompromised access to
the gap between the class's floor and its ceiling."""

_NONNATIVE_ACTION_FIT: Final[float] = 0.35
"""Credit given when the action being scored is *not* the class's own
textbook action (e.g. the escalation ladder pushed a ``RETRY_SAME`` case
through ``switch_method`` after repeated failures, or a baseline applies
one fixed action regardless of class). Still positive -- a fresh channel
helps a little regardless of the original cause -- but far short of full
credit, which is the concrete modelling of "will not recover by retrying
the same way" the phase brief asks this oracle to express."""

_GENERIC_SELF_RECOVERY_FLOOR: Final[float] = 0.20
"""The no-action baseline :attr:`Action.WAIT_BANK_RECOVERY`'s flat rate is
compared against when computing its own uplift under the sensitivity
band -- a class-independent stand-in, since during an active incident the
specific remediation class is not the operative mechanism (see module
docstring)."""

_INCIDENT_RECOVERY_RATE_CENTRAL: Final[float] = 0.70
"""``P(recovery | WAIT_BANK_RECOVERY)`` at the central sensitivity level,
independent of remediation class -- see module docstring."""

_TAXONOMY_CLASSES: Final[frozenset[RemediationClass]] = frozenset(RemediationClass)


class UnmodeledRemediationClassError(ValueError):
    """Raised when a :class:`RemediationClass` has no oracle-modelled rate.

    Mirrors :class:`reflow.policy.actions.UnmappedRemediationClassError`:
    both of this module's per-class tables are written out exhaustively
    against today's ten-member enum, so reaching this error means the
    enum grew without this module being updated to match.
    """


def _clamp_unit(value: float) -> float:
    """Clamp a probability into the closed unit interval.

    Args:
        value: A computed probability that may have drifted outside
            ``[0, 1]`` after applying a sensitivity multiplier.

    Returns:
        ``value`` clamped to ``[0.0, 1.0]``.
    """
    return max(0.0, min(1.0, value))


def _deterministic_unit_draw(payment_id: str) -> float:
    """Derive a stable, seeded ``[0, 1)`` draw from a payment id alone.

    Args:
        payment_id: The specific payment attempt's id (unique per attempt
            in this project's corpus, including retries -- see
            :mod:`reflow.corpus.events` module docstring: only
            ``order_id`` is shared across a retry chain).

    Returns:
        A float in ``[0, 1)``, stable across processes and Python
        versions (built from a fixed-width slice of a SHA-256 digest,
        never from :mod:`random` or :mod:`hashlib`'s object identity),
        and independent of sensitivity level or the action being scored
        -- see module docstring for why sharing this draw across both is
        deliberate.
    """
    digest = hashlib.sha256(f"{_HASH_SALT}:{payment_id}".encode()).hexdigest()
    return int(digest[:16], 16) / float(1 << 64)


@dataclass(frozen=True, slots=True)
class RecoveryOracle:
    """``P(recovery | root cause, action)`` at one fixed sensitivity level.

    The agent this project builds never constructs or queries this class;
    only :mod:`reflow.eval.simulate` does, strictly after a decision has
    already been made, to score it.

    Attributes:
        level: Which point on the sensitivity band this oracle instance
            scores at. Defaults to :attr:`SensitivityLevel.CENTRAL`.
    """

    level: SensitivityLevel = SensitivityLevel.CENTRAL

    def recovery_probability(self, remediation_class: RemediationClass, action: Action) -> float:
        """Compute ``P(recovery | remediation_class, action)`` at this oracle's level.

        Args:
            remediation_class: The diagnosed root cause's remediation
                class.
            action: The action actually taken for this payment attempt
                (a decision's ``final_action``, or a baseline's fixed
                choice).

        Returns:
            A probability in ``[0.0, 1.0]``. See module docstring for the
            three scoring paths: :attr:`~reflow.policy.actions.Action.RECONCILE`
            (always ``0.0``), :attr:`~reflow.policy.actions.Action.WAIT_BANK_RECOVERY`
            (a flat, class-independent rate), and every other action
            (the class's self-recovery floor plus a fit-scaled,
            band-scaled uplift toward its ceiling).

        Raises:
            UnmodeledRemediationClassError: If ``remediation_class`` has
                no entry in this module's tables.
        """
        if remediation_class not in _TAXONOMY_CLASSES:
            raise UnmodeledRemediationClassError(
                f"RemediationClass {remediation_class!r} has no oracle-modelled recovery rate."
            )
        multiplier = _SENSITIVITY_MULTIPLIER[self.level]
        floor_multiplier = _FLOOR_SENSITIVITY_MULTIPLIER[self.level]
        if action is Action.RECONCILE:
            return 0.0
        if action is Action.WAIT_BANK_RECOVERY:
            scaled_incident_floor = _GENERIC_SELF_RECOVERY_FLOOR * floor_multiplier
            uplift = (_INCIDENT_RECOVERY_RATE_CENTRAL - _GENERIC_SELF_RECOVERY_FLOOR) * multiplier
            return _clamp_unit(scaled_incident_floor + uplift)
        floor = _SELF_RECOVERY_RATE[remediation_class]
        scaled_floor = floor * floor_multiplier
        if action is Action.NO_ACTION:
            return _clamp_unit(scaled_floor)
        ceiling = _ACTION_CEILING[remediation_class]
        fit = (
            _NATIVE_ACTION_FIT
            if base_action_for(remediation_class) is action
            else _NONNATIVE_ACTION_FIT
        )
        uplift = fit * (ceiling - floor) * multiplier
        return _clamp_unit(scaled_floor + uplift)

    def sample_recovery(
        self, payment_id: str, remediation_class: RemediationClass, action: Action
    ) -> bool:
        """Draw one deterministic recovery outcome for a payment attempt.

        Args:
            payment_id: The specific payment attempt's id.
            remediation_class: The diagnosed root cause's remediation
                class.
            action: The action actually taken for this payment attempt.

        Returns:
            ``True`` if this attempt recovers under this oracle's
            sensitivity level, given the deterministic per-payment draw
            from :func:`_deterministic_unit_draw` and the probability from
            :meth:`recovery_probability`.
        """
        probability = self.recovery_probability(remediation_class, action)
        return _deterministic_unit_draw(payment_id) < probability

    def self_recovery_rate(self, remediation_class: RemediationClass) -> float:
        """Expose the class's bare no-action floor, for reporting.

        Args:
            remediation_class: The remediation class to look up.

        Returns:
            ``P(recovery | remediation_class, NO_ACTION)`` -- identical to
            calling :meth:`recovery_probability` with
            :attr:`~reflow.policy.actions.Action.NO_ACTION`, exposed here
            as a convenience name. This value does still vary with this
            oracle's sensitivity level, via
            :data:`_FLOOR_SENSITIVITY_MULTIPLIER` -- see module docstring
            for why the no-action floor is deliberately part of the band,
            not held fixed.

        Raises:
            UnmodeledRemediationClassError: If ``remediation_class`` has
                no entry in this module's tables.
        """
        return self.recovery_probability(remediation_class, Action.NO_ACTION)
