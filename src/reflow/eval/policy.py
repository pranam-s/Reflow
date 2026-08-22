"""The Phase 5 policy-engine benchmark harness.

Runs :class:`~reflow.policy.engine.PolicyEngine` over the full generated
corpus, using Phase 4's already-committed diagnoses
(:mod:`reflow.policy.diagnosis_source`) and a fresh run of Phase 3's
recommended incident detector
(:func:`reflow.policy.engine.detect_active_incident_indices`), and reports
this phase's headline measurements: the action distribution across the
closed seven-action set, how often each guardrail fired and what it
prevented, how many events reached ``wait_bank_recovery`` because an
incident was active, the concrete over-contact reduction guardrails
produce, and the escalation ladder's terminal-state distribution.

**No LLM call, no live Razorpay API call, $0 spend.** Every number in this
module's output is either a pure function of the generated corpus, the
deterministic taxonomy table, or Phase 4's already-paid-for, committed
report -- see :mod:`reflow.policy.diagnosis_source` module docstring for
why loading that report, rather than calling an LLM again, is the correct
way to honour "the policy layer must not care which tier produced the
input."
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from reflow.corpus.generator import generate_corpus
from reflow.diagnose.tier1 import default_deterministic_table
from reflow.policy.actions import CHASE_ACTIONS, Action
from reflow.policy.decision import Decision
from reflow.policy.decision import to_dict as decision_to_dict
from reflow.policy.diagnosis_source import (
    DEFAULT_PHASE4_REPORT_PATH,
    build_offline_diagnoses,
    load_ambiguous_diagnosis_records,
)
from reflow.policy.engine import PolicyEngine

DEFAULT_SEED: Final[int] = 20260822
DEFAULT_N_EVENTS: Final[int] = 50_000

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

PROVENANCE_NOTES: Final[tuple[str, ...]] = (
    "No LLM call and no live Razorpay API call is made anywhere in this benchmark. The 15 "
    "ambiguous reason codes' remediation classes are loaded from the already-committed Phase 4 "
    "report at zero marginal spend -- see reflow.policy.diagnosis_source module docstring.",
    "Active-incident detection reruns the ADR-0003-recommended poisson_surprise detector at "
    "(method, bank) granularity over the full corpus: a pure statistical computation, not an "
    "LLM call, and the same detector/granularity Phase 3 and Phase 4 used.",
    "Guardrail fire counts and the over-contact reduction compare each decision's escalation "
    "-ladder candidate_action (what would have been sent with zero guardrails) against its "
    "final_action (what the full guardrail chain actually decided).",
    "The terminal_reason_blocklist guardrail's TERMINAL-class branch cannot fire on this corpus: "
    "reflow.taxonomy.remediation currently classifies zero of 110 reason codes as TERMINAL. Its "
    "duplicate/already-paid branch (order_already_paid, duplicate_request, duplicate_refund_id) "
    "can and does fire; both branches are exercised directly in tests/policy/test_guardrails.py "
    "independent of what this corpus happens to contain.",
    "example_decisions is a small, illustrative sample (the first decision each guardrail "
    "blocked, plus one fully-passed decision), not the full per-event audit trail -- Phase 6 "
    "persists every Decision this engine produces; this report is a benchmark summary.",
)


@dataclass(frozen=True, slots=True)
class ActionDistribution:
    """The closed action set's distribution, before and after guardrails.

    Attributes:
        candidate_counts: Count of each action the escalation ladder
            proposed, before any guardrail ran -- "what would have
            happened with zero guardrails."
        final_counts: Count of each action actually decided, after the
            full guardrail chain ran.
    """

    candidate_counts: dict[str, int]
    final_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class GuardrailFireSummary:
    """One guardrail's fire/pass counts and what its blocks changed.

    Attributes:
        name: The guardrail's stable identifier.
        fired: How many times this guardrail blocked (overrode) an action.
        passed: How many times this guardrail evaluated and left the
            action unchanged.
        overrides: Count of each distinct ``"before->after"`` action
            transition this guardrail produced while blocking -- the
            concrete answer to "what did this guardrail prevent."
    """

    name: str
    fired: int
    passed: int
    overrides: dict[str, int]


@dataclass(frozen=True, slots=True)
class OverContactSummary:
    """The concrete over-contact reduction guardrails produce.

    Attributes:
        contacts_without_guardrails: Number of events whose escalation
            -ladder candidate action was a chase action
            (:data:`reflow.policy.actions.CHASE_ACTIONS`), before any
            guardrail ran.
        contacts_with_guardrails: Number of events whose final action was
            a chase action, after the full guardrail chain ran.
        reduction: ``contacts_without_guardrails - contacts_with_guardrails``.
        reduction_rate: ``reduction / contacts_without_guardrails``, or
            ``0.0`` if ``contacts_without_guardrails`` is ``0``.
    """

    contacts_without_guardrails: int
    contacts_with_guardrails: int
    reduction: int
    reduction_rate: float


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to attribute and reproduce a benchmark run.

    Attributes:
        generated_at: UTC ISO-8601 timestamp of report generation.
        seed: The corpus seed used.
        n_events: The corpus size used.
        phase4_report_path: Path to the Phase 4 report the 15 ambiguous
            reasons' diagnoses were loaded from.
        command: The command that produced this report.
        library_versions: Installed version of every result-relevant
            library.
        notes: Free-text disclosures (see :data:`PROVENANCE_NOTES`).
    """

    generated_at: str
    seed: int
    n_events: int
    phase4_report_path: str
    command: str
    library_versions: dict[str, str]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyReport:
    """The complete Phase 5 policy-engine benchmark result.

    Attributes:
        provenance: See :class:`Provenance`.
        n_events: Total events evaluated.
        action_distribution: See :class:`ActionDistribution`.
        guardrail_fires: One :class:`GuardrailFireSummary` per guardrail,
            in evaluation order.
        wait_bank_recovery_count: How many events reached
            :attr:`~reflow.policy.actions.Action.WAIT_BANK_RECOVERY`
            because an incident was active on their entity.
        over_contact: See :class:`OverContactSummary`.
        ladder_terminal_distribution: Count of each
            :class:`~reflow.policy.decision.LadderTerminalState` value
            across every decision.
        example_decisions: A small, illustrative sample of full
            :class:`~reflow.policy.decision.Decision` records, already
            JSON-serialised -- see :data:`PROVENANCE_NOTES`.
    """

    provenance: Provenance
    n_events: int
    action_distribution: ActionDistribution
    guardrail_fires: tuple[GuardrailFireSummary, ...]
    wait_bank_recovery_count: int
    over_contact: OverContactSummary
    ladder_terminal_distribution: dict[str, int]
    example_decisions: tuple[dict[str, object], ...]


def _summarize_action_distribution(decisions: Sequence[Decision]) -> ActionDistribution:
    """Tally candidate and final action counts across every action in the closed set.

    Args:
        decisions: Every decision to summarise.

    Returns:
        The populated :class:`ActionDistribution`, with an explicit ``0``
        entry for any action in :class:`~reflow.policy.actions.Action`
        that never occurred, so the report is honest about gaps rather
        than omitting them.
    """
    candidate_counts: Counter[str] = Counter(
        decision.candidate_action.value for decision in decisions
    )
    final_counts: Counter[str] = Counter(decision.final_action.value for decision in decisions)
    for action in Action:
        candidate_counts.setdefault(action.value, 0)
        final_counts.setdefault(action.value, 0)
    return ActionDistribution(
        candidate_counts=dict(sorted(candidate_counts.items())),
        final_counts=dict(sorted(final_counts.items())),
    )


def _summarize_guardrail_fires(decisions: Sequence[Decision]) -> tuple[GuardrailFireSummary, ...]:
    """Tally each guardrail's fire/pass counts and override transitions.

    Args:
        decisions: Every decision to summarise.

    Returns:
        One :class:`GuardrailFireSummary` per guardrail name observed, in
        the order each name was first seen (which, since every decision
        runs the same fixed guardrail chain, is the chain's own
        evaluation order).
    """
    names_in_order: list[str] = []
    seen_names: set[str] = set()
    fired_counts: Counter[str] = Counter()
    passed_counts: Counter[str] = Counter()
    overrides_by_name: dict[str, Counter[str]] = defaultdict(Counter)
    for decision in decisions:
        for evaluation in decision.guardrail_evaluations:
            if evaluation.name not in seen_names:
                seen_names.add(evaluation.name)
                names_in_order.append(evaluation.name)
            if evaluation.blocked:
                fired_counts[evaluation.name] += 1
                transition = f"{evaluation.action_before.value}->{evaluation.action_after.value}"
                overrides_by_name[evaluation.name][transition] += 1
            else:
                passed_counts[evaluation.name] += 1
    return tuple(
        GuardrailFireSummary(
            name=name,
            fired=fired_counts.get(name, 0),
            passed=passed_counts.get(name, 0),
            overrides=dict(sorted(overrides_by_name.get(name, Counter()).items())),
        )
        for name in names_in_order
    )


def _summarize_over_contact(decisions: Sequence[Decision]) -> OverContactSummary:
    """Compute the concrete over-contact reduction guardrails produce.

    Args:
        decisions: Every decision to summarise.

    Returns:
        The populated :class:`OverContactSummary`.
    """
    without_guardrails = sum(
        1 for decision in decisions if decision.candidate_action in CHASE_ACTIONS
    )
    with_guardrails = sum(1 for decision in decisions if decision.final_action in CHASE_ACTIONS)
    reduction = without_guardrails - with_guardrails
    reduction_rate = reduction / without_guardrails if without_guardrails else 0.0
    return OverContactSummary(
        contacts_without_guardrails=without_guardrails,
        contacts_with_guardrails=with_guardrails,
        reduction=reduction,
        reduction_rate=reduction_rate,
    )


def _pick_example_decisions(decisions: Sequence[Decision]) -> tuple[dict[str, object], ...]:
    """Pick a small, illustrative sample of decisions for the report.

    Args:
        decisions: Every decision to sample from.

    Returns:
        The first decision each guardrail was ever seen to block (keyed by
        guardrail name, so at most one example per guardrail), plus one
        fully-passed decision if any exists, each already serialised via
        :func:`reflow.policy.decision.to_dict`, in a stable order.
    """
    examples: dict[str, Decision] = {}
    for decision in decisions:
        for evaluation in decision.guardrail_evaluations:
            if evaluation.blocked and evaluation.name not in examples:
                examples[evaluation.name] = decision
    clean_pass = next(
        (
            decision
            for decision in decisions
            if not any(evaluation.blocked for evaluation in decision.guardrail_evaluations)
        ),
        None,
    )
    if clean_pass is not None:
        examples["all_guardrails_passed"] = clean_pass
    return tuple(decision_to_dict(examples[key]) for key in examples)


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


def run_benchmark(
    seed: int = DEFAULT_SEED,
    n_events: int = DEFAULT_N_EVENTS,
    phase4_report_path: Path = DEFAULT_PHASE4_REPORT_PATH,
) -> PolicyReport:
    """Run the full Phase 5 policy-engine benchmark.

    Args:
        seed: Corpus seed.
        n_events: Corpus size.
        phase4_report_path: Path to the Phase 4 report the 15 ambiguous
            reasons' diagnoses are loaded from -- must have been generated
            from the same ``seed``/vendored taxonomy, since
            :func:`~reflow.policy.diagnosis_source.build_offline_diagnoses`
            raises if any escalated reason is missing.

    Returns:
        The complete :class:`PolicyReport`.
    """
    events = list(generate_corpus(seed=seed, n_events=n_events))

    table = default_deterministic_table()
    ambiguous_records = load_ambiguous_diagnosis_records(phase4_report_path)
    diagnoses = build_offline_diagnoses(table, ambiguous_records)

    engine = PolicyEngine()
    decisions = engine.evaluate_batch(events, diagnoses)

    action_distribution = _summarize_action_distribution(decisions)
    guardrail_fires = _summarize_guardrail_fires(decisions)
    over_contact = _summarize_over_contact(decisions)
    ladder_terminal_distribution = dict(
        sorted(Counter(decision.ladder_terminal_state.value for decision in decisions).items())
    )
    wait_bank_recovery_count = action_distribution.final_counts.get(
        Action.WAIT_BANK_RECOVERY.value, 0
    )

    provenance = Provenance(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seed=seed,
        n_events=n_events,
        phase4_report_path=str(phase4_report_path),
        command="uv run python -m reflow.eval.policy",
        library_versions=_library_versions(),
        notes=PROVENANCE_NOTES,
    )
    return PolicyReport(
        provenance=provenance,
        n_events=len(events),
        action_distribution=action_distribution,
        guardrail_fires=guardrail_fires,
        wait_bank_recovery_count=wait_bank_recovery_count,
        over_contact=over_contact,
        ladder_terminal_distribution=ladder_terminal_distribution,
        example_decisions=_pick_example_decisions(decisions),
    )


def to_json_dict(report: PolicyReport) -> dict[str, object]:
    """Serialise a :class:`PolicyReport` to a JSON-safe nested dict.

    Args:
        report: The report to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``.
    """
    return asdict(report)


def to_markdown(report: PolicyReport) -> str:
    """Render a human-readable markdown summary of a :class:`PolicyReport`.

    Args:
        report: The report to render.

    Returns:
        A markdown document.
    """
    provenance = report.provenance
    lines: list[str] = []
    lines.append("# Phase 5 policy-engine benchmark results")
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

    lines.append("## Action distribution across the closed set")
    lines.append("")
    lines.append("| action | candidate (no guardrails) | final (with guardrails) |")
    lines.append("| --- | --- | --- |")
    for action in sorted(report.action_distribution.final_counts):
        candidate = report.action_distribution.candidate_counts.get(action, 0)
        final = report.action_distribution.final_counts.get(action, 0)
        lines.append(f"| {action} | {candidate} | {final} |")
    lines.append("")
    lines.append(
        f"- Events reaching `wait_bank_recovery` because an incident was active: "
        f"**{report.wait_bank_recovery_count}**"
    )
    lines.append("")

    lines.append("## Guardrail fire counts")
    lines.append("")
    lines.append("| guardrail | fired (blocked) | passed | overrides (before->after: count) |")
    lines.append("| --- | --- | --- | --- |")
    for summary in report.guardrail_fires:
        overrides_text = "; ".join(f"{k}: {v}" for k, v in summary.overrides.items()) or "n/a"
        lines.append(f"| {summary.name} | {summary.fired} | {summary.passed} | {overrides_text} |")
    lines.append("")

    over_contact = report.over_contact
    lines.append("## Over-contact reduction")
    lines.append("")
    lines.append(
        f"- Contacts that would have been sent with zero guardrails: "
        f"**{over_contact.contacts_without_guardrails}**"
    )
    lines.append(
        f"- Contacts actually sent with guardrails: **{over_contact.contacts_with_guardrails}**"
    )
    lines.append(f"- Reduction: **{over_contact.reduction}** ({over_contact.reduction_rate:.4%})")
    lines.append("")

    lines.append("## Escalation ladder terminal-state distribution")
    lines.append("")
    lines.append("| terminal state | count |")
    lines.append("| --- | --- |")
    for state, count in sorted(report.ladder_terminal_distribution.items()):
        lines.append(f"| {state} | {count} |")
    lines.append("")

    lines.append("## Example decisions (illustrative sample, not the full audit trail)")
    lines.append("")
    lines.append("| final_action | error_reason | justification |")
    lines.append("| --- | --- | --- |")
    for example in report.example_decisions:
        justification = str(example["justification"]).replace("|", "\\|")
        lines.append(f"| {example['final_action']} | {example['error_reason']} | {justification} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:  # pragma: no cover
    """Run the full benchmark and write JSON + markdown reports.

    CLI entry point: argument parsing and file writing are glue code, not
    core logic, so this function is excluded from the coverage floor per
    ``CLAUDE.md``'s CLI-glue carve-out. Writes
    ``docs/reports/phase5_policy.json`` and ``docs/reports/phase5_policy.md``.
    Makes no LLM call and no live Razorpay API call.
    """
    parser = argparse.ArgumentParser(description="Run the Phase 5 policy-engine benchmark.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-events", type=int, default=DEFAULT_N_EVENTS)
    parser.add_argument("--phase4-report", type=Path, default=DEFAULT_PHASE4_REPORT_PATH)
    parser.add_argument("--output-dir", type=Path, default=_REPO_ROOT / "docs" / "reports")
    args = parser.parse_args()

    report = run_benchmark(
        seed=args.seed, n_events=args.n_events, phase4_report_path=args.phase4_report
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase5_policy.json").write_text(
        json.dumps(to_json_dict(report), indent=2), encoding="utf-8"
    )
    (args.output_dir / "phase5_policy.md").write_text(to_markdown(report), encoding="utf-8")
    reduction = report.over_contact.reduction
    print(f"Evaluated {report.n_events} events; over-contact reduction: {reduction}")


if __name__ == "__main__":  # pragma: no cover
    main()
