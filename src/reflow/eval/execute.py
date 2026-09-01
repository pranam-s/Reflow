"""The Phase 6 bounded-execution benchmark and audit-trail generator.

Runs the full pipeline -- corpus generation, diagnosis
(:mod:`reflow.policy.diagnosis_source`, zero marginal LLM cost, reusing
Phase 4's already-committed diagnoses exactly as :mod:`reflow.eval.policy`
does), policy evaluation (:mod:`reflow.policy.engine`), and bounded
execution (:mod:`reflow.execute`) -- over one generated corpus, always in
**dry-run mode**: this benchmark's own spend is $0, matching
:mod:`reflow.eval.policy`'s precedent, and it never imports Razorpay
credentials. The small number of genuine, credential-backed live calls
this phase makes to prove real integration live entirely in
``tests/execute/test_gateway_live.py``, recorded as VCR cassettes -- this
module only *reports* on those cassettes (:func:`_live_verification`), it
never re-makes the calls itself.

**The committed audit trail is a bounded, representative sample, not the
full corpus.** ``docs/design.md`` ADR-0005 anticipated Phase 6 persisting
"every ``Decision`` this engine produces" -- and :func:`run_benchmark`
supports exactly that (``audit_sample_size=None`` persists all
``n_events`` records). The report this module actually generates for the
repository uses a bounded sample instead
(:data:`DEFAULT_AUDIT_TRAIL_HEAD` chronological events, plus a guaranteed
first example of every guardrail block and every final action), because a
literal 50,000-record JSONL trail is tens of megabytes with no added
demonstration value over a smaller, still-genuine sample drawn from the
same real run -- stated here plainly rather than silently shipping a
partial trail under the full-trail label ADR-0005 used.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from reflow.audit.record import AuditRecord
from reflow.audit.store import AuditTrailWriter, ChainVerificationResult, verify_chain
from reflow.corpus.events import PaymentEvent
from reflow.corpus.generator import generate_corpus
from reflow.diagnose.router import EventDiagnosis
from reflow.diagnose.tier1 import default_deterministic_table
from reflow.execute.executor import BoundedExecutor
from reflow.execute.models import ExecutionRecord
from reflow.execute.reference import derive_reference_id
from reflow.policy.decision import Decision
from reflow.policy.diagnosis_source import (
    DEFAULT_PHASE4_REPORT_PATH,
    build_offline_diagnoses,
    diagnose_reason,
    load_ambiguous_diagnosis_records,
)
from reflow.policy.engine import PolicyEngine

DEFAULT_SEED: Final[int] = 20260822
DEFAULT_N_EVENTS: Final[int] = 50_000
DEFAULT_AUDIT_TRAIL_HEAD: Final[int] = 500

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_TRAIL_PATH: Final[Path] = _REPO_ROOT / "docs" / "reports" / "phase6_audit_trail.jsonl"
DEFAULT_LIVE_CASSETTE_DIR: Final[Path] = (
    _REPO_ROOT / "tests" / "execute" / "cassettes" / "test_gateway_live"
)


def _relative_path(path: Path) -> str:
    """Render a path relative to the repository root, for report output.

    Args:
        path: The path to render.

    Returns:
        ``path`` relative to :data:`_REPO_ROOT`, with forward slashes
        regardless of host OS, so a committed report never discloses the
        generating machine's absolute filesystem layout. Falls back to
        ``str(path)`` unchanged if ``path`` does not resolve to somewhere
        under :data:`_REPO_ROOT`.
    """
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


PROVENANCE_NOTES: Final[tuple[str, ...]] = (
    "This benchmark always runs the bounded executor in dry-run mode: no Razorpay credentials "
    "are imported and no network call is ever made here. Every EXECUTED outcome anywhere in "
    "this project's test suite comes from a committed VCR cassette recorded once against the "
    "real API, never from this benchmark.",
    "Diagnoses are loaded from Phase 4's already-committed report at zero marginal LLM cost, "
    "exactly as reflow.eval.policy does -- see reflow.policy.diagnosis_source module docstring.",
    "reference_id collision-freedom is checked directly against every payment_id in the "
    "generated corpus, not merely asserted from the birthday-bound arithmetic.",
    "The persisted audit trail is a bounded, representative sample (see this module's own "
    "docstring), not the full n_events run -- docs/design.md ADR-0005 anticipated persisting "
    "every decision, and run_benchmark's audit_sample_size=None option does exactly that for a "
    "caller who wants the complete trail; the committed report uses a bounded sample instead, "
    "stated here rather than silently shipping a partial trail under the full-trail label.",
    "live_verification reports on cassettes already committed under "
    "tests/execute/cassettes/test_gateway_live/ -- it parses those files, it does not make any "
    "network call itself.",
)


@dataclass(frozen=True, slots=True)
class ReferenceIdCheck:
    """The empirical collision-freedom check for the idempotency key derivation.

    Attributes:
        n_events: Total events checked.
        n_unique_reference_ids: Distinct derived ``reference_id`` values.
        collision_free: ``n_events == n_unique_reference_ids``.
        max_length: The longest derived ``reference_id``'s length, always
            equal to :data:`reflow.execute.reference.REFERENCE_ID_MAX_LENGTH`.
    """

    n_events: int
    n_unique_reference_ids: int
    collision_free: bool
    max_length: int


@dataclass(frozen=True, slots=True)
class LiveVerificationSummary:
    """What the committed, credential-free-to-replay live cassettes prove.

    Attributes:
        cassette_dir: Where the live-recorded cassettes live.
        n_cassette_files: How many cassette files are committed.
        n_interactions: Total HTTP interactions recorded across every
            cassette file.
        short_urls: Every distinct ``short_url`` found in a recorded
            response body -- concrete evidence a real Payment Link was
            created against Razorpay's live test-mode API.
    """

    cassette_dir: str
    n_cassette_files: int
    n_interactions: int
    short_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to attribute and reproduce a benchmark run.

    Attributes:
        generated_at: UTC ISO-8601 timestamp of report generation.
        seed: The corpus seed used.
        n_events: The corpus size used.
        phase4_report_path: Path to the Phase 4 report diagnoses were
            loaded from.
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
class ExecutionReport:
    """The complete Phase 6 bounded-execution benchmark result.

    Attributes:
        provenance: See :class:`Provenance`.
        n_events_evaluated: Total events run through diagnosis, policy,
            and (dry-run) execution.
        dry_run_outcome_counts: Count of each
            :class:`~reflow.execute.models.ExecutionOutcome` across every
            evaluated event, in this always-dry-run benchmark.
        reference_id_check: See :class:`ReferenceIdCheck`.
        audit_trail_path: Where the sampled audit trail was written.
        n_audit_records_persisted: How many records were actually
            appended to ``audit_trail_path``.
        audit_chain_valid: Whether :func:`reflow.audit.store.verify_chain`
            confirmed the persisted trail's hash chain.
        example_payment_ids: A small, named lookup of interesting payment
            ids in the persisted trail, e.g. ``"active_incident_block"``
            -- concrete, ready-to-run ``reflow replay <payment_id>``
            arguments.
        live_verification: See :class:`LiveVerificationSummary`.
    """

    provenance: Provenance
    n_events_evaluated: int
    dry_run_outcome_counts: dict[str, int]
    reference_id_check: ReferenceIdCheck
    audit_trail_path: str
    n_audit_records_persisted: int
    audit_chain_valid: bool
    example_payment_ids: dict[str, str]
    live_verification: LiveVerificationSummary


def _reference_id_check(events: Sequence[PaymentEvent]) -> ReferenceIdCheck:
    """Empirically check idempotency-key collision-freedom over a corpus.

    Args:
        events: Every event to check.

    Returns:
        The populated :class:`ReferenceIdCheck`.
    """
    reference_ids = [derive_reference_id(event.payment_id) for event in events]
    unique_count = len(set(reference_ids))
    max_length = max((len(value) for value in reference_ids), default=0)
    return ReferenceIdCheck(
        n_events=len(events),
        n_unique_reference_ids=unique_count,
        collision_free=unique_count == len(events),
        max_length=max_length,
    )


def _select_sample_indices(decisions: Sequence[Decision], head: int) -> list[int]:
    """Choose a bounded, representative sample of decisions to persist.

    Args:
        decisions: Every decision produced for the full run, in order.
        head: How many leading (chronological) decisions to always
            include.

    Returns:
        Sorted, de-duplicated indices covering: the first ``head``
        decisions; the first decision on which each guardrail ever
        blocked (guaranteeing, in particular, the first
        ``active_incident_suppression`` block -- Deliverable 3's named
        demo case -- appears whenever the underlying corpus produces one
        at all); and the first decision reaching each distinct final
        action in the closed seven-member set.
    """
    selected: set[int] = set(range(min(head, len(decisions))))
    seen_guardrail_blocks: set[str] = set()
    seen_actions: set[str] = set()
    for index, decision in enumerate(decisions):
        for evaluation in decision.guardrail_evaluations:
            if evaluation.blocked and evaluation.name not in seen_guardrail_blocks:
                seen_guardrail_blocks.add(evaluation.name)
                selected.add(index)
        if decision.final_action.value not in seen_actions:
            seen_actions.add(decision.final_action.value)
            selected.add(index)
    return sorted(selected)


def _example_payment_ids(
    events: Sequence[PaymentEvent], decisions: Sequence[Decision], sample_indices: Sequence[int]
) -> dict[str, str]:
    """Name a handful of interesting payment ids within the sampled trail.

    Args:
        events: Every event for the full run, in order.
        decisions: Every decision for the full run, in the same order.
        sample_indices: The indices actually persisted (see
            :func:`_select_sample_indices`).

    Returns:
        A mapping from a stable, descriptive key to a ``payment_id``
        present in the persisted trail, restricted to keys whose
        condition is actually satisfied by this run (e.g.
        ``"active_incident_block"`` is present only if some sampled
        decision actually had that guardrail block).
    """
    examples: dict[str, str] = {}
    for index in sample_indices:
        decision = decisions[index]
        for evaluation in decision.guardrail_evaluations:
            key = f"{evaluation.name}_block"
            if evaluation.blocked and key not in examples:
                examples[key] = events[index].payment_id
        action_key = f"final_action_{decision.final_action.value}"
        if action_key not in examples:
            examples[action_key] = events[index].payment_id
    return dict(sorted(examples.items()))


def _extract_cassette_interactions(cassette_dir: Path) -> list[dict[str, Any]]:
    """Parse every recorded HTTP interaction from a directory of cassettes.

    Args:
        cassette_dir: Directory containing ``vcrpy`` cassette YAML files.

    Returns:
        Every ``interactions`` list entry across every ``*.yaml`` file
        found, or an empty list if the directory does not exist. Import
        of ``yaml`` is local to this function so a missing cassette
        directory (e.g. before any live recording has happened) never
        requires the dependency to be resolved eagerly at module import
        time.
    """
    if not cassette_dir.is_dir():
        return []
    import yaml

    interactions: list[dict[str, Any]] = []
    for cassette_file in sorted(cassette_dir.glob("*.yaml")):
        payload = yaml.safe_load(cassette_file.read_text(encoding="utf-8"))
        interactions.extend(payload.get("interactions", []) if payload else [])
    return interactions


def _live_verification(cassette_dir: Path = DEFAULT_LIVE_CASSETTE_DIR) -> LiveVerificationSummary:
    """Summarise what the committed live cassettes prove.

    Args:
        cassette_dir: Directory containing the live-recorded cassettes.

    Returns:
        The populated :class:`LiveVerificationSummary`.
    """
    interactions = _extract_cassette_interactions(cassette_dir)
    short_urls: set[str] = set()
    for interaction in interactions:
        body = interaction.get("response", {}).get("body", {}).get("string")
        if not body:
            continue
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("short_url"), str):
            short_urls.add(parsed["short_url"])
    n_files = len(list(cassette_dir.glob("*.yaml"))) if cassette_dir.is_dir() else 0
    return LiveVerificationSummary(
        cassette_dir=_relative_path(cassette_dir),
        n_cassette_files=n_files,
        n_interactions=len(interactions),
        short_urls=tuple(sorted(short_urls)),
    )


def _library_versions() -> dict[str, str]:
    """Look up the installed version of every result-relevant library.

    Returns:
        A mapping from distribution name to installed version string.
    """
    return {
        "pydantic": importlib.metadata.version("pydantic"),
        "razorpay": importlib.metadata.version("razorpay"),
        "rich": importlib.metadata.version("rich"),
        "python": platform.python_version(),
        "reflow": importlib.metadata.version("reflow"),
    }


def run_benchmark(
    seed: int = DEFAULT_SEED,
    n_events: int = DEFAULT_N_EVENTS,
    phase4_report_path: Path = DEFAULT_PHASE4_REPORT_PATH,
    audit_trail_path: Path = DEFAULT_AUDIT_TRAIL_PATH,
    audit_sample_size: int | None = DEFAULT_AUDIT_TRAIL_HEAD,
    live_cassette_dir: Path = DEFAULT_LIVE_CASSETTE_DIR,
) -> ExecutionReport:
    """Run the full Phase 6 bounded-execution benchmark.

    Args:
        seed: Corpus seed.
        n_events: Corpus size.
        phase4_report_path: Path to the Phase 4 report the 15 ambiguous
            reasons' diagnoses are loaded from.
        audit_trail_path: Where to write the (freshly started, per module
            docstring) sampled audit trail.
        audit_sample_size: How many leading events to guarantee in the
            persisted sample (see :func:`_select_sample_indices`); ``None``
            persists every one of ``n_events`` decisions, matching
            ``docs/design.md`` ADR-0005's "every decision" framing exactly.
        live_cassette_dir: Directory of committed live-call cassettes to
            report on (never called over the network by this function).

    Returns:
        The complete :class:`ExecutionReport`.
    """
    events = list(generate_corpus(seed=seed, n_events=n_events))

    table = default_deterministic_table()
    ambiguous_records = load_ambiguous_diagnosis_records(phase4_report_path)
    diagnoses = build_offline_diagnoses(table, ambiguous_records)

    engine = PolicyEngine()
    decisions = engine.evaluate_batch(events, diagnoses)

    executor = BoundedExecutor(dry_run=True)
    executions: list[ExecutionRecord] = [
        executor.execute(decision, event) for decision, event in zip(decisions, events, strict=True)
    ]
    outcome_counts = dict(
        sorted(Counter(execution.outcome.value for execution in executions).items())
    )

    reference_id_check = _reference_id_check(events)

    sample_indices = (
        list(range(len(decisions)))
        if audit_sample_size is None
        else _select_sample_indices(decisions, audit_sample_size)
    )

    if audit_trail_path.exists():
        audit_trail_path.unlink()
    resolved_diagnoses: list[EventDiagnosis] = [
        diagnose_reason(event.error_reason, diagnoses) for event in events
    ]
    persisted_records: list[AuditRecord] = []
    with AuditTrailWriter.open(audit_trail_path) as writer:
        for index in sample_indices:
            persisted_records.append(
                writer.append(
                    decision=decisions[index],
                    event=events[index],
                    diagnosis=resolved_diagnoses[index],
                    execution=executions[index],
                )
            )

    chain_result: ChainVerificationResult = verify_chain(audit_trail_path)
    example_payment_ids = _example_payment_ids(events, decisions, sample_indices)

    provenance = Provenance(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seed=seed,
        n_events=n_events,
        phase4_report_path=_relative_path(phase4_report_path),
        command="uv run python -m reflow.eval.execute",
        library_versions=_library_versions(),
        notes=PROVENANCE_NOTES,
    )
    return ExecutionReport(
        provenance=provenance,
        n_events_evaluated=len(events),
        dry_run_outcome_counts=outcome_counts,
        reference_id_check=reference_id_check,
        audit_trail_path=_relative_path(audit_trail_path),
        n_audit_records_persisted=len(persisted_records),
        audit_chain_valid=chain_result.valid,
        example_payment_ids=example_payment_ids,
        live_verification=_live_verification(live_cassette_dir),
    )


def to_json_dict(report: ExecutionReport) -> dict[str, object]:
    """Serialise an :class:`ExecutionReport` to a JSON-safe nested dict.

    Args:
        report: The report to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``.
    """
    return asdict(report)


def to_markdown(report: ExecutionReport) -> str:
    """Render a human-readable markdown summary of an :class:`ExecutionReport`.

    Args:
        report: The report to render.

    Returns:
        A markdown document.
    """
    provenance = report.provenance
    lines: list[str] = []
    lines.append("# Phase 6 bounded-execution benchmark results")
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

    lines.append("## Dry-run execution outcomes (this benchmark, $0 spend)")
    lines.append("")
    lines.append("| outcome | count |")
    lines.append("| --- | --- |")
    for outcome, count in report.dry_run_outcome_counts.items():
        lines.append(f"| {outcome} | {count} |")
    lines.append("")

    check = report.reference_id_check
    lines.append("## Idempotency key (reference_id) collision check")
    lines.append("")
    lines.append(f"- Events checked: **{check.n_events}**")
    lines.append(f"- Distinct reference_id values: **{check.n_unique_reference_ids}**")
    lines.append(f"- Collision-free: **{check.collision_free}**")
    lines.append(f"- Maximum reference_id length: **{check.max_length}** (cap: 40)")
    lines.append("")

    lines.append("## Persisted audit trail (bounded, representative sample)")
    lines.append("")
    lines.append(f"- Path: `{report.audit_trail_path}`")
    lines.append(f"- Records persisted: **{report.n_audit_records_persisted}**")
    lines.append(f"- Hash chain valid: **{report.audit_chain_valid}**")
    lines.append("")
    lines.append("Example `reflow replay <payment_id>` arguments:")
    lines.append("")
    lines.append("| example | payment_id |")
    lines.append("| --- | --- |")
    for key, payment_id in report.example_payment_ids.items():
        lines.append(f"| {key} | `{payment_id}` |")
    lines.append("")

    live = report.live_verification
    lines.append("## Live test-mode verification (evidence, not re-executed here)")
    lines.append("")
    lines.append(f"- Cassette directory: `{live.cassette_dir}`")
    lines.append(f"- Cassette files: **{live.n_cassette_files}**")
    lines.append(f"- Recorded HTTP interactions: **{live.n_interactions}**")
    lines.append("- Real `short_url` values observed:")
    for short_url in live.short_urls:
        lines.append(f"  - {short_url}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:  # pragma: no cover
    """Run the full benchmark and write JSON + markdown reports.

    CLI entry point: argument parsing and file writing are glue code, not
    core logic, so this function is excluded from the coverage floor per
    ``CLAUDE.md``'s CLI-glue carve-out. Writes
    ``docs/reports/phase6_execution.json`` and
    ``docs/reports/phase6_execution.md``. Always dry-run: makes no
    Razorpay API call and imports no credentials.
    """
    parser = argparse.ArgumentParser(description="Run the Phase 6 bounded-execution benchmark.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-events", type=int, default=DEFAULT_N_EVENTS)
    parser.add_argument("--phase4-report", type=Path, default=DEFAULT_PHASE4_REPORT_PATH)
    parser.add_argument("--audit-path", type=Path, default=DEFAULT_AUDIT_TRAIL_PATH)
    parser.add_argument("--audit-sample-size", type=int, default=DEFAULT_AUDIT_TRAIL_HEAD)
    parser.add_argument(
        "--full-audit-trail",
        action="store_true",
        help="Persist every decision instead of the bounded sample.",
    )
    parser.add_argument("--output-dir", type=Path, default=_REPO_ROOT / "docs" / "reports")
    args = parser.parse_args()

    sample_size = None if args.full_audit_trail else args.audit_sample_size
    report = run_benchmark(
        seed=args.seed,
        n_events=args.n_events,
        phase4_report_path=args.phase4_report,
        audit_trail_path=args.audit_path,
        audit_sample_size=sample_size,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase6_execution.json").write_text(
        json.dumps(to_json_dict(report), indent=2), encoding="utf-8"
    )
    (args.output_dir / "phase6_execution.md").write_text(to_markdown(report), encoding="utf-8")
    print(
        f"Evaluated {report.n_events_evaluated} events; persisted "
        f"{report.n_audit_records_persisted} audit records; chain valid: "
        f"{report.audit_chain_valid}."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
