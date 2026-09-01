"""Deliverables 2 and 3 of Phase 7: closed-loop evaluation and baselines.

**Why this must be a sequential simulation, not a single-pass scoring.**
Phase 5's benchmark (:mod:`reflow.eval.policy`) scores every event once,
independently, against a diagnosis and a guardrail chain -- it never
learns whether any decision actually recovered the payment, because it
never had an outcome model to consult. ADR-0005 (``docs/design.md``)
recorded the resulting limitation plainly: the escalation ladder
(:mod:`reflow.policy.ladder`) advances by
:attr:`~reflow.corpus.events.PaymentEvent.attempt_number`, an
*observed retry-chain fact* from the corpus, not by anything the policy
itself had done, "because the offline evaluation had never taken an
action."

This module closes that gap. For every order (grouped by
:attr:`~reflow.corpus.events.PaymentEvent.order_id`, since a retry chain
shares one order id but each attempt gets its own fresh ``payment_id`` --
see :mod:`reflow.corpus.generator` module docstring), it walks that
order's raw failure events in chronological order and, for each one still
outstanding: decides an action, scores that action against the seeded
:class:`~reflow.outcome.oracle.RecoveryOracle` (never the policy's own
input), updates the order's state, and only then proceeds to the next
raw event for that order -- **action, outcome, state update, next
decision**, exactly the loop the phase brief requires. Once an order
recovers (or, for :attr:`PolicyName.REFLOW`, once its escalation ladder
gives up or it is reconciled), no further raw event for that order is
evaluated: a customer who already paid does not keep failing.

**No change to `reflow.policy.engine`, `.guardrails`, `.ladder`, or
`.decision` was needed to close ADR-0005's gap.** Every one of those
already takes ``attempt_number`` as a plain input on
:class:`~reflow.corpus.events.PaymentEvent`
(:func:`reflow.policy.ladder.ladder_action`,
:class:`reflow.policy.guardrails.AttemptCapGuardrail`) -- they were
already correctly parameterised, and simply had no genuine decision
history to be handed at the only call site that existed
(:meth:`reflow.policy.engine.PolicyEngine.evaluate_batch`). This module
is the caller ADR-0005 anticipated: for :attr:`PolicyName.REFLOW`, each
raw event is rebuilt via :func:`dataclasses.replace` with
``attempt_number`` overridden to *this order's own count of chase/escalate
actions actually taken by this simulation so far*, before being handed to
the unmodified :meth:`~reflow.policy.engine.PolicyEngine.evaluate`. The
escalation ladder and the attempt-cap guardrail therefore both now climb
and cap against genuine decision history, not an observed fact about
customer behaviour the policy had no part in -- with zero production-code
changes, because the gap was in the caller, not in the callee.
:attr:`PolicyEngine`'s own per-customer contact-history bookkeeping
(:meth:`~reflow.policy.engine.PolicyEngine._record_contact`) was, in
fact, already closed-loop before this phase: it only ever records a
contact when a decision's ``final_action`` actually lands on one, which
is exactly "accumulates from actions actually taken." This module's
contribution is closing the one part of ADR-0005 that was not already
true, and stating that plainly rather than re-describing what already
worked as if it were new.

**The four policies compared.**

- :attr:`PolicyName.DO_NOTHING` -- always
  :attr:`~reflow.policy.actions.Action.NO_ACTION`. The floor: whatever
  recovers, recovers on its own.
- :attr:`PolicyName.NOTIFY_ALL` -- always
  :attr:`~reflow.policy.actions.Action.RECOVERY_LINK_NOW`, on every
  outstanding raw event, forever, with no guardrail of any kind. The
  naive agent the phase brief names explicitly.
- :attr:`PolicyName.NOTIFY_ALL_ONCE` -- the same fixed action, but only
  on an order's first outstanding raw event; every later event for that
  order (if it has not yet recovered) gets
  :attr:`~reflow.policy.actions.Action.NO_ACTION` instead, with no further
  contact ever attempted.
- :attr:`PolicyName.REFLOW` -- the real, unmodified
  :class:`~reflow.policy.engine.PolicyEngine`: diagnosis-informed base
  action, escalation ladder, and the full seven-guardrail chain, run in
  closed loop as described above.

Every policy processes the *same* underlying corpus and the *same*
per-payment-id oracle draws (see
:mod:`reflow.outcome.oracle` module docstring for why the draw is shared
across actions and levels), so a difference in outcome between two
policies is attributable to the policy's own choices, never to
independently re-rolled randomness.

**What "attempts made" and "contacts sent" count, and why they differ.**
:data:`~reflow.policy.actions.CHASE_ACTIONS` is customer-facing contact
only; :attr:`~reflow.policy.actions.Action.ESCALATE_HUMAN` is a merchant
-side human taking over, not another message to the customer -- this
project's own vocabulary already draws that line
(:mod:`reflow.policy.actions` module docstring). This module reuses it
rather than inventing a new one: **contacts sent** counts only
:data:`~reflow.policy.actions.CHASE_ACTIONS`; **attempts made** counts
every escalatable action, i.e. :data:`reflow.policy.ladder.LADDER_ORDER`'s
membership (chase actions plus escalation to a human).

**Honesty statement.** Every "money recovered" figure this module reports
is a simulated outcome scored by a seeded, hand-built oracle
(:mod:`reflow.outcome.oracle`), never an observed real-world rupee. What
is being measured is policy quality against a known, stated,
adversarially-inspectable world -- not real recovery. See
``docs/reports/phase7_evaluation.md`` for the full statement and its
reasoning, restated at the top of that report in plain language per the
phase brief.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from reflow.corpus.events import PaymentEvent
from reflow.corpus.generator import generate_corpus
from reflow.diagnose.router import EventDiagnosis
from reflow.diagnose.tier1 import default_deterministic_table
from reflow.outcome.oracle import RecoveryOracle, SensitivityLevel
from reflow.policy.actions import CHASE_ACTIONS, Action
from reflow.policy.decision import LadderTerminalState, classify_ladder_terminal_state
from reflow.policy.diagnosis_source import (
    DEFAULT_PHASE4_REPORT_PATH,
    build_offline_diagnoses,
    diagnose_reason,
    load_ambiguous_diagnosis_records,
)
from reflow.policy.engine import PolicyEngine, detect_active_incident_indices
from reflow.policy.ladder import LADDER_ORDER
from reflow.taxonomy.remediation import RemediationClass

DEFAULT_SEED: Final[int] = 20260822
DEFAULT_N_EVENTS: Final[int] = 50_000

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

_ATTEMPT_ACTIONS: Final[frozenset[Action]] = frozenset(LADDER_ORDER)
"""Every action that represents a genuine, escalatable attempt: the three
chase actions plus escalation to a human. See module docstring."""

PROVENANCE_NOTES: Final[tuple[str, ...]] = (
    "Every recovery outcome in this report is scored by the seeded, deterministic "
    "reflow.outcome.oracle.RecoveryOracle, never observed from a real customer or a live "
    "Razorpay call -- see that module's docstring and docs/reports/phase7_evaluation.md for "
    "the full honesty statement this project makes about what these numbers do and do not mean.",
    "Diagnoses are loaded from Phase 4's already-committed report at zero marginal LLM cost, "
    "exactly as reflow.eval.policy and reflow.eval.execute do -- this module's own spend is $0.",
    "Active-incident detection reruns the ADR-0003-recommended poisson_surprise detector once "
    "per corpus, over the full, unmodified event sequence, shared identically across every "
    "policy and every sensitivity level compared here.",
    "reflow's escalation-ladder attempt number and attempt-cap guardrail are driven by this "
    "order's own count of chase/escalate actions actually decided during this simulation, not "
    "by the corpus's ground-truth PaymentEvent.attempt_number -- see module docstring for how "
    "this closes the limitation ADR-0005 recorded without modifying reflow.policy itself.",
    "Every policy is run against the same corpus and the same per-payment-id oracle draws, so "
    "a difference in a policy's outcome is attributable only to that policy's own decisions.",
)


class PolicyName(StrEnum):
    """The four policies this module's closed-loop simulation compares."""

    DO_NOTHING = "do_nothing"
    NOTIFY_ALL = "notify_all"
    NOTIFY_ALL_ONCE = "notify_all_once"
    REFLOW = "reflow"


@dataclass(slots=True)
class _OrderState:
    """One order's mutable simulation state, updated after every decision.

    Attributes:
        settled: Whether this order should no longer receive any further
            simulated decision (recovered, given up, or reconciled).
        recovered: Whether this order ever recovered during the
            simulation.
        recovered_amount_paise: The amount, in paise, of the specific raw
            event at which recovery was scored (``0`` if never recovered).
        contacts_sent: Count of decisions whose action was a member of
            :data:`~reflow.policy.actions.CHASE_ACTIONS`.
        attempts_made: Count of decisions whose action was a member of
            :data:`~reflow.policy.ladder.LADDER_ORDER`.
        guardrail_prevented_contacts: Count of :attr:`PolicyName.REFLOW`
            decisions where the escalation ladder's candidate action was
            escalatable but the guardrail chain's final action was not.
        raw_events_seen: Count of raw corpus events actually evaluated for
            this order (excludes events skipped after settlement).
        notified_once: Whether :attr:`PolicyName.NOTIFY_ALL_ONCE` has
            already sent this order's single allowed contact.
    """

    settled: bool = False
    recovered: bool = False
    recovered_amount_paise: int = 0
    contacts_sent: int = 0
    attempts_made: int = 0
    guardrail_prevented_contacts: int = 0
    raw_events_seen: int = 0
    notified_once: bool = False


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """One policy's aggregate result at one sensitivity level.

    Attributes:
        policy: The policy's name.
        sensitivity_level: The oracle sensitivity level this outcome was
            measured under.
        orders_total: Distinct orders (by ``order_id``) with at least one
            raw failure event in the corpus.
        orders_recovered: Orders that ever recovered under this policy.
        recovery_rate: ``orders_recovered / orders_total``.
        money_recovered_paise: Total recovered amount, in paise.
        money_recovered_rupees: Total recovered amount, in rupees.
        contacts_sent: Total customer-facing contacts sent, across every
            order.
        attempts_made: Total escalatable actions taken, across every
            order (contacts plus human escalations).
        guardrail_prevented_contacts: Total times a guardrail changed an
            escalatable candidate action into a non-escalatable one.
            Structurally ``0`` for every baseline, since none of them run
            any guardrail -- reported as a measured, not omitted, zero.
        contacts_per_rupee_recovered: ``contacts_sent / money_recovered_rupees``,
            or ``None`` if nothing was recovered (division is undefined,
            not infinite-by-convention).
        raw_events_processed: Total raw corpus events actually evaluated
            (i.e. not skipped because their order had already settled).
        raw_events_total: Total raw corpus events available to evaluate.
    """

    policy: str
    sensitivity_level: str
    orders_total: int
    orders_recovered: int
    recovery_rate: float
    money_recovered_paise: int
    money_recovered_rupees: float
    contacts_sent: int
    attempts_made: int
    guardrail_prevented_contacts: int
    contacts_per_rupee_recovered: float | None
    raw_events_processed: int
    raw_events_total: int


def _decide_baseline_action(policy: PolicyName, state: _OrderState) -> Action:
    """Decide a non-``reflow`` baseline's action for one raw event.

    Args:
        policy: The baseline being simulated (never
            :attr:`PolicyName.REFLOW`).
        state: The order's current state.

    Returns:
        :attr:`~reflow.policy.actions.Action.NO_ACTION` for
        :attr:`PolicyName.DO_NOTHING`;
        :attr:`~reflow.policy.actions.Action.RECOVERY_LINK_NOW` for every
        raw event under :attr:`PolicyName.NOTIFY_ALL`; the same action
        only for the first raw event, then
        :attr:`~reflow.policy.actions.Action.NO_ACTION` forever after,
        under :attr:`PolicyName.NOTIFY_ALL_ONCE`.
    """
    if policy is PolicyName.DO_NOTHING:
        return Action.NO_ACTION
    if policy is PolicyName.NOTIFY_ALL:
        return Action.RECOVERY_LINK_NOW
    if state.notified_once:
        return Action.NO_ACTION
    state.notified_once = True
    return Action.RECOVERY_LINK_NOW


@runtime_checkable
class RecoveryScorer(Protocol):
    """Structural interface :func:`run_one_policy` scores decisions against.

    :class:`~reflow.outcome.oracle.RecoveryOracle` satisfies this
    structurally with no extra declaration needed; tests use a lightweight
    fake implementing only this interface, so the closed-loop state
    machine's mechanics (settlement, per-policy action choice, guardrail
    -prevented counting) can be verified against hand-picked, fully
    controlled recovery outcomes rather than the real oracle's
    probability-driven ones.
    """

    @property
    def level(self) -> SensitivityLevel:
        """Which sensitivity level this scorer represents, for reporting."""
        ...

    def sample_recovery(
        self, payment_id: str, remediation_class: RemediationClass, action: Action
    ) -> bool:
        """Decide whether one payment attempt recovers under one action.

        Args:
            payment_id: The specific payment attempt's id.
            remediation_class: The diagnosed root cause's remediation
                class.
            action: The action actually taken for this payment attempt.

        Returns:
            ``True`` if this attempt recovers.
        """
        ...


def run_one_policy(
    events: Sequence[PaymentEvent],
    diagnoses: dict[str, EventDiagnosis],
    active_indices: frozenset[int],
    oracle: RecoveryScorer,
    policy: PolicyName,
) -> PolicyOutcome:
    """Run one policy's closed-loop simulation over one event sequence.

    Args:
        events: The events to simulate, in non-decreasing ``created_at``
            order (the same precondition
            :meth:`reflow.policy.engine.PolicyEngine.evaluate_batch`
            documents, since :attr:`PolicyName.REFLOW` drives the same
            underlying engine).
        diagnoses: Every reason code's offline-built diagnosis (see
            :func:`reflow.policy.diagnosis_source.build_offline_diagnoses`).
        active_indices: Indices into ``events`` attributed to an active
            incident, from :func:`reflow.policy.engine.detect_active_incident_indices`.
        oracle: The recovery scorer to score every decision against --
            the real :class:`~reflow.outcome.oracle.RecoveryOracle` in
            production use, or a test fake satisfying
            :class:`RecoveryScorer`.
        policy: Which policy to simulate.

    Returns:
        The populated :class:`PolicyOutcome`.
    """
    engine = PolicyEngine()
    states: dict[str, _OrderState] = defaultdict(_OrderState)
    processed = 0

    for index, event in enumerate(events):
        state = states[event.order_id]
        if state.settled:
            continue
        diagnosis = diagnose_reason(event.error_reason, diagnoses)
        state.raw_events_seen += 1
        processed += 1

        if policy is PolicyName.REFLOW:
            attempt_number = state.attempts_made + 1
            sim_event = replace(event, attempt_number=attempt_number)
            decision = engine.evaluate(
                sim_event, diagnosis, in_active_incident=index in active_indices
            )
            final_action = decision.final_action
            if (
                decision.candidate_action in _ATTEMPT_ACTIONS
                and final_action not in _ATTEMPT_ACTIONS
            ):
                state.guardrail_prevented_contacts += 1
        else:
            final_action = _decide_baseline_action(policy, state)

        if final_action in CHASE_ACTIONS:
            state.contacts_sent += 1
        if final_action in _ATTEMPT_ACTIONS:
            state.attempts_made += 1

        recovered = oracle.sample_recovery(
            event.payment_id, diagnosis.remediation_class, final_action
        )
        if recovered:
            state.settled = True
            state.recovered = True
            state.recovered_amount_paise = event.amount
        elif policy is PolicyName.REFLOW:
            terminal_state = classify_ladder_terminal_state(
                final_action, decision.guardrail_evaluations
            )
            if terminal_state is LadderTerminalState.GAVE_UP or final_action is Action.RECONCILE:
                state.settled = True

    orders_total = len(states)
    orders_recovered = sum(1 for state in states.values() if state.recovered)
    money_paise = sum(state.recovered_amount_paise for state in states.values())
    contacts = sum(state.contacts_sent for state in states.values())
    attempts = sum(state.attempts_made for state in states.values())
    prevented = sum(state.guardrail_prevented_contacts for state in states.values())
    money_rupees = money_paise / 100
    contacts_per_rupee = (contacts / money_rupees) if money_rupees > 0 else None

    return PolicyOutcome(
        policy=policy.value,
        sensitivity_level=oracle.level.value,
        orders_total=orders_total,
        orders_recovered=orders_recovered,
        recovery_rate=(orders_recovered / orders_total if orders_total else 0.0),
        money_recovered_paise=money_paise,
        money_recovered_rupees=money_rupees,
        contacts_sent=contacts,
        attempts_made=attempts,
        guardrail_prevented_contacts=prevented,
        contacts_per_rupee_recovered=contacts_per_rupee,
        raw_events_processed=processed,
        raw_events_total=len(events),
    )


@dataclass(frozen=True, slots=True)
class SensitivityBandFinding:
    """Whether reflow's headline claims hold at one sensitivity level.

    Attributes:
        sensitivity_level: The level this finding was computed at.
        reflow_money_rupees: reflow's recovered rupees at this level.
        do_nothing_money_rupees: ``do_nothing``'s recovered rupees.
        notify_all_money_rupees: ``notify_all``'s recovered rupees.
        notify_all_once_money_rupees: ``notify_all_once``'s recovered
            rupees.
        reflow_beats_do_nothing: Whether reflow recovers strictly more
            money than doing nothing.
        reflow_recovers_more_money_than_notify_all: Whether reflow
            recovers at least as much money as the naive, unbounded
            ``notify_all`` baseline. Reported honestly either way -- see
            module and package docstrings.
        reflow_is_cheaper_per_rupee_than_notify_all: Whether reflow's
            contacts-per-rupee-recovered is at or below ``notify_all``'s
            (lower is better: fewer contacts per rupee recovered).
        reflow_is_cheaper_per_rupee_than_notify_all_once: Same comparison
            against ``notify_all_once``.
    """

    sensitivity_level: str
    reflow_money_rupees: float
    do_nothing_money_rupees: float
    notify_all_money_rupees: float
    notify_all_once_money_rupees: float
    reflow_beats_do_nothing: bool
    reflow_recovers_more_money_than_notify_all: bool
    reflow_is_cheaper_per_rupee_than_notify_all: bool
    reflow_is_cheaper_per_rupee_than_notify_all_once: bool


def _band_finding(
    outcomes_at_level: dict[str, PolicyOutcome], level: str
) -> SensitivityBandFinding:
    """Compute one sensitivity level's headline comparison.

    Args:
        outcomes_at_level: Mapping from :class:`PolicyName` value to that
            policy's :class:`PolicyOutcome` at this level.
        level: The sensitivity level these outcomes were measured at.

    Returns:
        The populated :class:`SensitivityBandFinding`.
    """
    reflow = outcomes_at_level[PolicyName.REFLOW.value]
    do_nothing = outcomes_at_level[PolicyName.DO_NOTHING.value]
    notify_all = outcomes_at_level[PolicyName.NOTIFY_ALL.value]
    notify_all_once = outcomes_at_level[PolicyName.NOTIFY_ALL_ONCE.value]

    def _cheaper_or_equal(a: PolicyOutcome, b: PolicyOutcome) -> bool:
        if a.contacts_per_rupee_recovered is None:
            return b.contacts_per_rupee_recovered is None
        if b.contacts_per_rupee_recovered is None:
            return True
        return a.contacts_per_rupee_recovered <= b.contacts_per_rupee_recovered

    return SensitivityBandFinding(
        sensitivity_level=level,
        reflow_money_rupees=reflow.money_recovered_rupees,
        do_nothing_money_rupees=do_nothing.money_recovered_rupees,
        notify_all_money_rupees=notify_all.money_recovered_rupees,
        notify_all_once_money_rupees=notify_all_once.money_recovered_rupees,
        reflow_beats_do_nothing=reflow.money_recovered_rupees > do_nothing.money_recovered_rupees,
        reflow_recovers_more_money_than_notify_all=(
            reflow.money_recovered_rupees >= notify_all.money_recovered_rupees
        ),
        reflow_is_cheaper_per_rupee_than_notify_all=_cheaper_or_equal(reflow, notify_all),
        reflow_is_cheaper_per_rupee_than_notify_all_once=_cheaper_or_equal(reflow, notify_all_once),
    )


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to attribute and reproduce a simulation run.

    Attributes:
        generated_at: UTC ISO-8601 timestamp of report generation.
        seed: The corpus seed used.
        n_events: The corpus size used.
        phase4_report_path: Path to the Phase 4 report diagnoses were
            loaded from.
        sensitivity_levels: Every sensitivity level simulated.
        command: The command that produced this report.
        library_versions: Installed version of every result-relevant
            library.
        notes: Free-text disclosures (see :data:`PROVENANCE_NOTES`).
    """

    generated_at: str
    seed: int
    n_events: int
    phase4_report_path: str
    sensitivity_levels: tuple[str, ...]
    command: str
    library_versions: dict[str, str]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SimulationReport:
    """The complete Phase 7 closed-loop simulation result.

    Attributes:
        provenance: See :class:`Provenance`.
        outcomes: Every :class:`PolicyOutcome`, one per
            ``(sensitivity_level, policy)`` pair.
        band_findings: One :class:`SensitivityBandFinding` per sensitivity
            level.
    """

    provenance: Provenance
    outcomes: tuple[PolicyOutcome, ...]
    band_findings: tuple[SensitivityBandFinding, ...]


def _library_versions() -> dict[str, str]:
    """Look up the installed version of every result-relevant library.

    Returns:
        A mapping from distribution name to installed version string.
    """
    return {
        "pydantic": importlib.metadata.version("pydantic"),
        "python": platform.python_version(),
        "reflow": importlib.metadata.version("reflow"),
    }


def run_closed_loop(
    seed: int = DEFAULT_SEED,
    n_events: int = DEFAULT_N_EVENTS,
    phase4_report_path: Path = DEFAULT_PHASE4_REPORT_PATH,
) -> SimulationReport:
    """Run the full Phase 7 closed-loop simulation across the sensitivity band.

    Args:
        seed: Corpus seed.
        n_events: Corpus size.
        phase4_report_path: Path to the Phase 4 report the 15 ambiguous
            reasons' diagnoses are loaded from.

    Returns:
        The complete :class:`SimulationReport`.
    """
    events = list(generate_corpus(seed=seed, n_events=n_events))

    table = default_deterministic_table()
    ambiguous_records = load_ambiguous_diagnosis_records(phase4_report_path)
    diagnoses = build_offline_diagnoses(table, ambiguous_records)
    active_indices = detect_active_incident_indices(events)

    outcomes: list[PolicyOutcome] = []
    outcomes_by_level: dict[str, dict[str, PolicyOutcome]] = defaultdict(dict)
    for level in SensitivityLevel:
        oracle = RecoveryOracle(level=level)
        for policy in PolicyName:
            outcome = run_one_policy(events, diagnoses, active_indices, oracle, policy)
            outcomes.append(outcome)
            outcomes_by_level[level.value][policy.value] = outcome

    band_findings = tuple(
        _band_finding(outcomes_by_level[level.value], level.value) for level in SensitivityLevel
    )

    provenance = Provenance(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seed=seed,
        n_events=n_events,
        phase4_report_path=str(phase4_report_path),
        sensitivity_levels=tuple(level.value for level in SensitivityLevel),
        command="uv run python -m reflow.eval.simulate",
        library_versions=_library_versions(),
        notes=PROVENANCE_NOTES,
    )
    return SimulationReport(
        provenance=provenance, outcomes=tuple(outcomes), band_findings=band_findings
    )


def to_json_dict(report: SimulationReport) -> dict[str, object]:
    """Serialise a :class:`SimulationReport` to a JSON-safe nested dict.

    Args:
        report: The report to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``.
    """
    return asdict(report)


def to_markdown(report: SimulationReport) -> str:
    """Render a human-readable markdown summary of a :class:`SimulationReport`.

    Args:
        report: The report to render.

    Returns:
        A markdown document.
    """
    provenance = report.provenance
    lines: list[str] = []
    lines.append("# Phase 7 closed-loop simulation results")
    lines.append("")
    lines.append(
        "**Every number below is a simulated outcome scored by a seeded oracle, not an "
        "observed real-world recovery.** See `docs/reports/phase7_evaluation.md` for the full "
        "honesty statement."
    )
    lines.append("")
    lines.append(f"- Generated at: {provenance.generated_at}")
    lines.append(f"- Command: `{provenance.command}`")
    lines.append(f"- Seed: {provenance.seed}")
    lines.append(f"- Corpus size: {provenance.n_events}")
    lines.append(f"- Phase 4 report: `{provenance.phase4_report_path}`")
    version_items = sorted(provenance.library_versions.items())
    versions_text = ", ".join(f"{name}={version}" for name, version in version_items)
    lines.append(f"- Library versions: {versions_text}")
    for note in provenance.notes:
        lines.append(f"- Note: {note}")
    lines.append("")

    by_level: dict[str, list[PolicyOutcome]] = defaultdict(list)
    for outcome in report.outcomes:
        by_level[outcome.sensitivity_level].append(outcome)

    for level in sorted(by_level):
        lines.append(f"## Sensitivity level: {level}")
        lines.append("")
        lines.append(
            "| policy | money recovered (INR) | contacts sent | attempts made | "
            "guardrail-prevented contacts | contacts / rupee recovered | orders recovered |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for outcome in by_level[level]:
            per_rupee = (
                "n/a"
                if outcome.contacts_per_rupee_recovered is None
                else f"{outcome.contacts_per_rupee_recovered:.6f}"
            )
            lines.append(
                f"| {outcome.policy} | {outcome.money_recovered_rupees:.2f} | "
                f"{outcome.contacts_sent} | {outcome.attempts_made} | "
                f"{outcome.guardrail_prevented_contacts} | {per_rupee} | "
                f"{outcome.orders_recovered}/{outcome.orders_total} |"
            )
        lines.append("")

    lines.append("## Sensitivity-band findings")
    lines.append("")
    lines.append(
        "| level | reflow beats do_nothing | reflow >= notify_all money | "
        "reflow cheaper/rupee than notify_all | reflow cheaper/rupee than notify_all_once |"
    )
    lines.append("| --- | --- | --- | --- | --- |")
    for finding in report.band_findings:
        lines.append(
            f"| {finding.sensitivity_level} | {finding.reflow_beats_do_nothing} | "
            f"{finding.reflow_recovers_more_money_than_notify_all} | "
            f"{finding.reflow_is_cheaper_per_rupee_than_notify_all} | "
            f"{finding.reflow_is_cheaper_per_rupee_than_notify_all_once} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:  # pragma: no cover
    """Run the full closed-loop simulation and write JSON + markdown reports.

    CLI entry point: argument parsing and file writing are glue code, not
    core logic, so this function is excluded from the coverage floor per
    ``CLAUDE.md``'s CLI-glue carve-out. Writes
    ``docs/reports/phase7_simulation.json`` and
    ``docs/reports/phase7_simulation.md``. Makes no LLM call and no live
    Razorpay API call -- every outcome comes from the seeded
    :class:`~reflow.outcome.oracle.RecoveryOracle`.
    """
    parser = argparse.ArgumentParser(description="Run the Phase 7 closed-loop simulation.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-events", type=int, default=DEFAULT_N_EVENTS)
    parser.add_argument("--phase4-report", type=Path, default=DEFAULT_PHASE4_REPORT_PATH)
    parser.add_argument("--output-dir", type=Path, default=_REPO_ROOT / "docs" / "reports")
    args = parser.parse_args()

    report = run_closed_loop(
        seed=args.seed, n_events=args.n_events, phase4_report_path=args.phase4_report
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase7_simulation.json").write_text(
        json.dumps(to_json_dict(report), indent=2), encoding="utf-8"
    )
    (args.output_dir / "phase7_simulation.md").write_text(to_markdown(report), encoding="utf-8")
    print(f"Simulated {len(report.outcomes)} policy/level combinations.")


if __name__ == "__main__":  # pragma: no cover
    main()
