"""The Phase 4 diagnosis-tier benchmark harness.

Runs the full two-tier diagnosis pipeline (:mod:`reflow.diagnose`) over one
generated corpus and reports the phase's headline measurement: what
fraction of events resolve deterministically in Tier 1 versus escalate to
an LLM call in Tier 2, the resulting cost per 100,000 events, and an
independent judge's assessment of Tier 2 diagnosis quality
(:mod:`reflow.eval.judge`).

Every LLM-calling function here takes its completer(s) as a parameter
(:class:`~reflow.llm.client.JsonCompleter`) rather than constructing an
:class:`~reflow.llm.client.LlmClient` itself, so :func:`run_benchmark` and
every helper below it are fully exercised by the test suite with a fake,
network-free completer -- only :func:`main` (CLI glue, excluded from the
coverage floor per ``CLAUDE.md``) wires up real credentials and makes real
calls.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from reflow.corpus.events import PaymentEvent
from reflow.corpus.generator import generate_corpus
from reflow.diagnose.ambiguous import AmbiguousReasonDiagnoser
from reflow.diagnose.incident import IncidentContext, IncidentDiagnoser, build_incident_context
from reflow.diagnose.models import (
    AmbiguousReasonDiagnosis,
    Confidence,
    IncidentDiagnosis,
    RecommendedPosture,
)
from reflow.diagnose.router import DiagnosisRouter, RoutingStats
from reflow.diagnose.tier1 import DeterministicTable, default_deterministic_table
from reflow.eval.judge import (
    JudgeSampleResult,
    judge_ambiguous_reason_diagnosis,
    judge_incident_diagnosis,
    sample_for_judging,
)
from reflow.incident.aggregate import build_entity_series, entity_key
from reflow.incident.detectors import PoissonSurpriseDetector
from reflow.incident.windows import DetectedIncident, run_detector
from reflow.llm.client import JsonCompleter
from reflow.taxonomy.remediation import RemediationClass

DEFAULT_SEED: Final[int] = 20260822
DEFAULT_N_EVENTS: Final[int] = 50_000
DEFAULT_JUDGE_SAMPLE_SIZE: Final[int] = 6

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

PROVENANCE_NOTES: Final[tuple[str, ...]] = (
    "Tier 1 covers 95 of 110 distinct reason codes; 15 escalate to Tier 2's "
    "cached per-reason LLM call -- one more than the taxonomy's own 14 "
    "row-flagged-ambiguous rows, because payment_method_not_enabled's two "
    "vendored rows are each individually unambiguous but disagree with each "
    "other, an ambiguity only visible when reconciling by reason code (see "
    "reflow.diagnose.tier1 module docstring).",
    "Incident diagnoses run the ADR-0003-recommended poisson_surprise "
    "detector at (method, bank) granularity over the full generated corpus, "
    "then call the LLM once per detected incident, uncached, since no two "
    "incidents share an entity/window/reason-code mix.",
    "The ambiguous-reason LLM cost is a one-time cost: the 15 escalated "
    "reason codes are fixed by the vendored taxonomy, not by corpus size, "
    "so it is paid at most once ever and then served from cache. The "
    "incident-diagnosis cost scales with detected-incident volume, which "
    "scales with corpus size/time span. Both are reported separately, and "
    "combined two ways: a cold-cache projection (includes the one-time "
    "ambiguous-reason cost) and a warm-cache projection (steady state, "
    "excludes it) -- see CostSummary.",
    "The judge model is a different family from the Tier 2 model under "
    "test, to avoid self-preference bias, and scores a fixed-size seeded "
    "sample of diagnoses rather than every diagnosis produced.",
)


@dataclass(frozen=True, slots=True)
class AmbiguousReasonResult:
    """One ambiguous reason code's resolved diagnosis, ready for reporting.

    Attributes:
        reason: The reason code diagnosed.
        remediation_class: The resolved remediation class.
        confidence: The model's self-reported confidence.
        rationale: The model's rationale.
        model: The model slug that actually served the request.
        cost: The call's reported dollar cost, or ``None``.
        reasoning_tokens: Tokens spent on hidden reasoning, or ``None``.
    """

    reason: str
    remediation_class: str
    confidence: str
    rationale: str
    model: str
    cost: float | None
    reasoning_tokens: int | None


@dataclass(frozen=True, slots=True)
class IncidentDiagnosisResult:
    """One detected incident's diagnosis, ready for reporting.

    Attributes:
        incident_id: A stable identifier for this incident within the run.
        method: The affected payment method.
        bank: The affected counterparty bank, or ``None``.
        start: The incident's detected start, ISO-8601.
        end: The incident's detected end, ISO-8601.
        total_count: Total failed events attributed to this incident.
        reason_counts: Count of reason codes among the incident's events.
        probable_root_cause: The model's stated probable root cause.
        confidence: The model's self-reported confidence.
        recommended_posture: The model's recommended operational posture.
        rationale: The model's rationale.
        model: The model slug that actually served the request.
        cost: The call's reported dollar cost, or ``None``.
        reasoning_tokens: Tokens spent on hidden reasoning, or ``None``.
    """

    incident_id: str
    method: str
    bank: str | None
    start: str
    end: str
    total_count: int
    reason_counts: dict[str, int]
    probable_root_cause: str
    confidence: str
    recommended_posture: str
    rationale: str
    model: str
    cost: float | None
    reasoning_tokens: int | None


@dataclass(frozen=True, slots=True)
class JudgeSummary:
    """Aggregate results of the LLM-as-a-judge quality check.

    Attributes:
        model: The judge model slug.
        samples: Every judged sample.
        n_sampled: Total samples judged.
        n_disagree: Samples the judge did not endorse.
        disagreement_rate: ``n_disagree / n_sampled``, or ``0.0`` if
            ``n_sampled`` is ``0``.
        wrong_cases: Every sample the judge labelled ``"wrong"``.
        total_cost: Total reported dollar cost of every judge call.
    """

    model: str
    samples: tuple[JudgeSampleResult, ...]
    n_sampled: int
    n_disagree: int
    disagreement_rate: float
    wrong_cases: tuple[JudgeSampleResult, ...]
    total_cost: float


@dataclass(frozen=True, slots=True)
class CostSummary:
    """Actual and projected LLM spend for this benchmark run.

    Attributes:
        ambiguous_reason_calls: Live calls made to resolve ambiguous
            reasons.
        ambiguous_reason_cost: Total reported cost of those calls.
        incident_diagnosis_calls: Live calls made to diagnose incidents.
        incident_diagnosis_cost: Total reported cost of those calls.
        judge_calls: Live calls made by the judge.
        judge_cost: Total reported cost of those calls.
        actual_total_spend: Sum of every reported cost above -- the
            phase's actual dollar spend for this run.
        n_events: Corpus size this run used.
        n_incidents_detected: Total incidents the detector found in this
            run, before any ``max_incident_diagnoses`` cap.
        n_incidents_diagnosed: Incidents actually diagnosed (``<=
            n_incidents_detected``; equal unless capped).
        projected_cost_per_100k_events_cold_cache: Projected production
            cost per 100,000 events, including the one-time ambiguous
            -reason cost (worst case: an empty cache). Extrapolated from
            the *average* observed cost per diagnosed incident applied to
            every *detected* incident, not only the ones actually
            diagnosed, so a capped run still projects the full production
            cost rather than silently understating it.
        projected_cost_per_100k_events_warm_cache: Projected production
            cost per 100,000 events, excluding the ambiguous-reason cost
            (steady state: the cache is already populated).
    """

    ambiguous_reason_calls: int
    ambiguous_reason_cost: float
    incident_diagnosis_calls: int
    incident_diagnosis_cost: float
    judge_calls: int
    judge_cost: float
    actual_total_spend: float
    n_events: int
    n_incidents_detected: int
    n_incidents_diagnosed: int
    projected_cost_per_100k_events_cold_cache: float
    projected_cost_per_100k_events_warm_cache: float


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to attribute and reproduce a benchmark run.

    Attributes:
        generated_at: UTC ISO-8601 timestamp of report generation.
        seed: The corpus seed used.
        n_events: The corpus size used.
        tier2_model: The model slug used for both Tier 2 call sites.
        judge_model: The model slug used for judging.
        judge_sample_size: How many samples the judge scored per category.
        judge_seed: Seed used to draw the judge's samples.
        command: The command that produced this report.
        library_versions: Installed version of every result-relevant
            library.
        notes: Free-text disclosures (see :data:`PROVENANCE_NOTES`).
    """

    generated_at: str
    seed: int
    n_events: int
    tier2_model: str
    judge_model: str
    judge_sample_size: int
    judge_seed: int
    command: str
    library_versions: dict[str, str]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiagnosisReport:
    """The complete Phase 4 diagnosis-tier benchmark result.

    Attributes:
        provenance: See :class:`Provenance`.
        routing: The phase's headline deterministic/LLM routing split.
        ambiguous_reason_results: Every ambiguous reason code's resolved
            diagnosis.
        incident_diagnoses: Every diagnosed incident.
        judge_summary: The independent judge's assessment.
        cost: Actual and projected spend.
    """

    provenance: Provenance
    routing: RoutingStats
    ambiguous_reason_results: tuple[AmbiguousReasonResult, ...]
    incident_diagnoses: tuple[IncidentDiagnosisResult, ...]
    judge_summary: JudgeSummary
    cost: CostSummary


def _detect_incidents(events: Sequence[PaymentEvent]) -> list[DetectedIncident]:
    """Run the ADR-0003-recommended detector over a full event sequence.

    Args:
        events: The events to detect incidents in.

    Returns:
        Every detected incident, pooled across every ``(method, bank)``
        entity, in no particular cross-entity order.
    """
    series_by_entity = build_entity_series(events, key_fn=entity_key)
    detector = PoissonSurpriseDetector()
    detected: list[DetectedIncident] = []
    for series in series_by_entity.values():
        detected.extend(run_detector(series, detector))
    return detected


def _incident_id(context: IncidentContext, index: int) -> str:
    """Build a stable, human-readable identifier for one incident.

    Args:
        context: The incident's evidence.
        index: The incident's position in detection order.

    Returns:
        A string combining the method, bank, and start time.
    """
    bank_part = context.bank or "nobank"
    return f"{index:03d}_{context.method}_{bank_part}_{context.start}"


def run_benchmark(
    *,
    tier2_client: JsonCompleter,
    judge_client: JsonCompleter,
    tier2_model_name: str,
    judge_model_name: str,
    seed: int = DEFAULT_SEED,
    n_events: int = DEFAULT_N_EVENTS,
    judge_sample_size: int = DEFAULT_JUDGE_SAMPLE_SIZE,
    judge_seed: int = DEFAULT_SEED,
    max_incident_diagnoses: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> DiagnosisReport:
    """Run the full Phase 4 diagnosis-tier benchmark.

    Args:
        tier2_client: Completer for both Tier 2 call sites (ambiguous
            reasons and incident diagnosis).
        judge_client: Completer for the independent judge.
        tier2_model_name: The Tier 2 model's slug, for provenance.
        judge_model_name: The judge model's slug, for provenance.
        seed: Corpus seed.
        n_events: Corpus size.
        judge_sample_size: Samples drawn per category for judging.
        judge_seed: Seed for judge sampling.
        max_incident_diagnoses: Caps how many detected incidents are
            actually diagnosed (still detected and counted in full);
            ``None`` diagnoses every detected incident. Exists to bound
            wall-clock time and live spend without changing detection
            itself.
        progress: Optional callback invoked with a short human-readable
            status string as each phase starts, e.g. for a CLI to print
            progress during a long live run. Never called during a
            normal, network-free test run unless a test explicitly
            passes one.

    Returns:
        The complete :class:`DiagnosisReport`.
    """
    report_progress = progress or (lambda _message: None)
    report_progress(f"Generating corpus (seed={seed}, n_events={n_events})...")
    events = list(generate_corpus(seed=seed, n_events=n_events))

    table = default_deterministic_table()
    ambiguous_diagnoser = AmbiguousReasonDiagnoser(client=tier2_client)
    router = DiagnosisRouter(table=table, ambiguous_diagnoser=ambiguous_diagnoser)
    routing = router.route(events)
    report_progress(
        f"Routed {routing.total_events} events: {routing.deterministic_events} "
        f"deterministic, {routing.llm_events} escalated across "
        f"{routing.llm_calls_made} live ambiguous-reason calls."
    )

    ambiguous_results = tuple(
        AmbiguousReasonResult(
            reason=reason,
            remediation_class=result.value.remediation_class.value,
            confidence=result.value.confidence.value,
            rationale=result.value.rationale,
            model=result.model,
            cost=result.usage.cost,
            reasoning_tokens=result.usage.reasoning_tokens,
        )
        for reason, result in (
            (reason, ambiguous_diagnoser.diagnose(reason, table.escalated.get(reason, ())))
            for reason in sorted(routing.escalated_reasons)
        )
    )

    detected_incidents = _detect_incidents(events)
    n_incidents_detected = len(detected_incidents)
    if max_incident_diagnoses is not None:
        detected_incidents = detected_incidents[:max_incident_diagnoses]
    report_progress(
        f"Detected {n_incidents_detected} incidents; diagnosing {len(detected_incidents)}."
    )
    incident_diagnoser = IncidentDiagnoser(client=tier2_client)
    incident_contexts: list[IncidentContext] = []
    incident_results: list[IncidentDiagnosisResult] = []
    for index, incident in enumerate(detected_incidents):
        context = build_incident_context(incident, events)
        incident_contexts.append(context)
        result = incident_diagnoser.diagnose(context)
        diagnosis = result.value
        incident_results.append(
            IncidentDiagnosisResult(
                incident_id=_incident_id(context, index),
                method=context.method,
                bank=context.bank,
                start=context.start,
                end=context.end,
                total_count=context.total_count,
                reason_counts=dict(context.reason_counts),
                probable_root_cause=diagnosis.probable_root_cause,
                confidence=diagnosis.confidence.value,
                recommended_posture=diagnosis.recommended_posture.value,
                rationale=diagnosis.rationale,
                model=result.model,
                cost=result.usage.cost,
                reasoning_tokens=result.usage.reasoning_tokens,
            )
        )
        report_progress(f"  incident {index + 1}/{len(detected_incidents)} diagnosed.")

    report_progress("Running LLM-as-a-judge over sampled diagnoses...")
    judge_summary = _run_judge(
        judge_client=judge_client,
        judge_model_name=judge_model_name,
        table=table,
        ambiguous_results=ambiguous_results,
        incident_contexts=incident_contexts,
        incident_results=incident_results,
        sample_size=judge_sample_size,
        judge_seed=judge_seed,
    )

    cost = _summarize_cost(
        ambiguous_diagnoser=ambiguous_diagnoser,
        incident_diagnoser=incident_diagnoser,
        judge_summary=judge_summary,
        n_events=n_events,
        n_incidents_detected=n_incidents_detected,
    )

    provenance = Provenance(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seed=seed,
        n_events=n_events,
        tier2_model=tier2_model_name,
        judge_model=judge_model_name,
        judge_sample_size=judge_sample_size,
        judge_seed=judge_seed,
        command="uv run --env-file .env python -m reflow.eval.diagnose",
        library_versions=_library_versions(),
        notes=PROVENANCE_NOTES,
    )
    return DiagnosisReport(
        provenance=provenance,
        routing=routing,
        ambiguous_reason_results=ambiguous_results,
        incident_diagnoses=tuple(incident_results),
        judge_summary=judge_summary,
        cost=cost,
    )


def _run_judge(
    *,
    judge_client: JsonCompleter,
    judge_model_name: str,
    table: DeterministicTable,
    ambiguous_results: Sequence[AmbiguousReasonResult],
    incident_contexts: Sequence[IncidentContext],
    incident_results: Sequence[IncidentDiagnosisResult],
    sample_size: int,
    judge_seed: int,
) -> JudgeSummary:
    """Sample and judge both Tier 2 call sites' diagnoses.

    Args:
        judge_client: Completer for the independent judge.
        judge_model_name: The judge model's slug, for reporting.
        table: The deterministic table, used to recover each sampled
            ambiguous reason's original vendored-row evidence.
        ambiguous_results: Every ambiguous reason code's resolved
            diagnosis.
        incident_contexts: Every detected incident's evidence, in the same
            order as ``incident_results``.
        incident_results: Every diagnosed incident, in the same order as
            ``incident_contexts``.
        sample_size: Samples drawn per category.
        judge_seed: Seed for judge sampling.

    Returns:
        The populated :class:`JudgeSummary`.
    """
    samples: list[JudgeSampleResult] = []

    sampled_reasons = sample_for_judging(list(ambiguous_results), sample_size, judge_seed)
    for reason_result in sampled_reasons:
        diagnosis = AmbiguousReasonDiagnosis(
            remediation_class=RemediationClass(reason_result.remediation_class),
            confidence=Confidence(reason_result.confidence),
            rationale=reason_result.rationale,
        )
        contexts = table.escalated.get(reason_result.reason, ())
        verdict_result = judge_ambiguous_reason_diagnosis(
            judge_client, reason=reason_result.reason, contexts=contexts, diagnosis=diagnosis
        )
        verdict = verdict_result.value
        samples.append(
            JudgeSampleResult(
                kind="ambiguous_reason",
                subject_id=reason_result.reason,
                diagnosis_confidence=reason_result.confidence,
                verdict=verdict.verdict.value,
                agrees_with_diagnosis=verdict.agrees_with_diagnosis,
                concerns=verdict.concerns,
                judge_cost=verdict_result.usage.cost,
            )
        )

    incident_pairs = list(zip(incident_contexts, incident_results, strict=True))
    sampled_incidents = sample_for_judging(incident_pairs, sample_size, judge_seed)
    for context, incident_result in sampled_incidents:
        incident_diagnosis = IncidentDiagnosis(
            probable_root_cause=incident_result.probable_root_cause,
            confidence=Confidence(incident_result.confidence),
            recommended_posture=RecommendedPosture(incident_result.recommended_posture),
            rationale=incident_result.rationale,
        )
        verdict_result = judge_incident_diagnosis(
            judge_client, context=context, diagnosis=incident_diagnosis
        )
        verdict = verdict_result.value
        samples.append(
            JudgeSampleResult(
                kind="incident",
                subject_id=incident_result.incident_id,
                diagnosis_confidence=incident_result.confidence,
                verdict=verdict.verdict.value,
                agrees_with_diagnosis=verdict.agrees_with_diagnosis,
                concerns=verdict.concerns,
                judge_cost=verdict_result.usage.cost,
            )
        )

    n_sampled = len(samples)
    n_disagree = sum(1 for sample in samples if not sample.agrees_with_diagnosis)
    wrong_cases = tuple(sample for sample in samples if sample.verdict == "wrong")
    total_cost = sum(sample.judge_cost or 0.0 for sample in samples)
    return JudgeSummary(
        model=judge_model_name,
        samples=tuple(samples),
        n_sampled=n_sampled,
        n_disagree=n_disagree,
        disagreement_rate=(n_disagree / n_sampled if n_sampled else 0.0),
        wrong_cases=wrong_cases,
        total_cost=total_cost,
    )


def _summarize_cost(
    *,
    ambiguous_diagnoser: AmbiguousReasonDiagnoser,
    incident_diagnoser: IncidentDiagnoser,
    judge_summary: JudgeSummary,
    n_events: int,
    n_incidents_detected: int,
) -> CostSummary:
    """Summarise actual spend and project it to a per-100k-events cost.

    Args:
        ambiguous_diagnoser: The Tier 2 ambiguous-reason diagnoser used in
            this run.
        incident_diagnoser: The Tier 2 incident diagnoser used in this run.
        judge_summary: The judge's results for this run.
        n_events: The corpus size this run used.
        n_incidents_detected: Total incidents the detector found, before
            any ``max_incident_diagnoses`` cap -- used, not the possibly
            smaller number actually diagnosed, so a capped benchmark run
            still projects the true production cost.

    Returns:
        The populated :class:`CostSummary`.
    """
    ambiguous_cost = ambiguous_diagnoser.total_cost()
    incident_cost = incident_diagnoser.total_cost()
    n_incidents_diagnosed = incident_diagnoser.calls_made
    average_incident_cost = incident_cost / n_incidents_diagnosed if n_incidents_diagnosed else 0.0
    scale = 100_000 / n_events if n_events else 0.0
    incident_cost_per_100k = average_incident_cost * n_incidents_detected * scale
    return CostSummary(
        ambiguous_reason_calls=ambiguous_diagnoser.calls_made,
        ambiguous_reason_cost=ambiguous_cost,
        incident_diagnosis_calls=n_incidents_diagnosed,
        incident_diagnosis_cost=incident_cost,
        judge_calls=judge_summary.n_sampled,
        judge_cost=judge_summary.total_cost,
        actual_total_spend=ambiguous_cost + incident_cost + judge_summary.total_cost,
        n_events=n_events,
        n_incidents_detected=n_incidents_detected,
        n_incidents_diagnosed=n_incidents_diagnosed,
        projected_cost_per_100k_events_cold_cache=ambiguous_cost + incident_cost_per_100k,
        projected_cost_per_100k_events_warm_cache=incident_cost_per_100k,
    )


def _library_versions() -> dict[str, str]:
    """Look up the installed version of every result-relevant library.

    Returns:
        A mapping from distribution name to installed version string.
    """
    return {
        "openrouter": importlib.metadata.version("openrouter"),
        "pydantic": importlib.metadata.version("pydantic"),
        "python": platform.python_version(),
        "reflow": importlib.metadata.version("reflow"),
    }


def to_json_dict(report: DiagnosisReport) -> dict[str, object]:
    """Serialise a :class:`DiagnosisReport` to a JSON-safe nested dict.

    Args:
        report: The report to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``.
    """
    routing = report.routing
    return {
        "provenance": asdict(report.provenance),
        "routing": {
            "total_events": routing.total_events,
            "deterministic_events": routing.deterministic_events,
            "llm_events": routing.llm_events,
            "deterministic_fraction": routing.deterministic_fraction,
            "llm_fraction": routing.llm_fraction,
            "distinct_reasons_seen": routing.distinct_reasons_seen,
            "llm_calls_made": routing.llm_calls_made,
            "escalated_reasons": sorted(routing.escalated_reasons),
        },
        "ambiguous_reason_results": [asdict(r) for r in report.ambiguous_reason_results],
        "incident_diagnoses": [asdict(r) for r in report.incident_diagnoses],
        "judge_summary": {
            "model": report.judge_summary.model,
            "n_sampled": report.judge_summary.n_sampled,
            "n_disagree": report.judge_summary.n_disagree,
            "disagreement_rate": report.judge_summary.disagreement_rate,
            "total_cost": report.judge_summary.total_cost,
            "samples": [asdict(s) for s in report.judge_summary.samples],
            "wrong_cases": [asdict(s) for s in report.judge_summary.wrong_cases],
        },
        "cost": asdict(report.cost),
    }


def _format_optional(value: float | None, digits: int = 6) -> str:
    """Format an optional float for a markdown report.

    Args:
        value: The value to format, or ``None``.
        digits: Number of decimal places.

    Returns:
        ``"n/a"`` if ``value`` is ``None``, otherwise ``value`` formatted to
        ``digits`` decimal places.
    """
    return "n/a" if value is None else f"{value:.{digits}f}"


def to_markdown(report: DiagnosisReport) -> str:
    """Render a human-readable markdown summary of a :class:`DiagnosisReport`.

    Args:
        report: The report to render.

    Returns:
        A markdown document.
    """
    provenance = report.provenance
    routing = report.routing
    cost = report.cost
    lines: list[str] = []
    lines.append("# Phase 4 diagnosis-tier benchmark results")
    lines.append("")
    lines.append(f"- Generated at: {provenance.generated_at}")
    lines.append(f"- Command: `{provenance.command}`")
    lines.append(f"- Seed: {provenance.seed}")
    lines.append(f"- Corpus size: {provenance.n_events}")
    lines.append(f"- Tier 2 model: **{provenance.tier2_model}**")
    lines.append(f"- Judge model: **{provenance.judge_model}**")
    lines.append(f"- Judge sample size (per category): {provenance.judge_sample_size}")
    version_items = sorted(provenance.library_versions.items())
    versions_text = ", ".join(f"{name}={version}" for name, version in version_items)
    lines.append(f"- Library versions: {versions_text}")
    for note in provenance.notes:
        lines.append(f"- Note: {note}")
    lines.append("")

    lines.append("## Routing split (the headline metric)")
    lines.append("")
    lines.append(f"- Total events routed: {routing.total_events}")
    lines.append(
        f"- Deterministic (Tier 1): {routing.deterministic_events} "
        f"({routing.deterministic_fraction:.4%})"
    )
    lines.append(f"- Escalated to LLM (Tier 2): {routing.llm_events} ({routing.llm_fraction:.4%})")
    lines.append(f"- Distinct reason codes seen: {routing.distinct_reasons_seen}")
    lines.append(f"- Live LLM calls made to resolve ambiguous reasons: {routing.llm_calls_made}")
    lines.append(f"- Escalated reason codes: {', '.join(sorted(routing.escalated_reasons))}")
    lines.append("")

    lines.append("## Cost")
    lines.append("")
    lines.append(f"- Ambiguous-reason calls (one-time): {cost.ambiguous_reason_calls}")
    lines.append(f"- Ambiguous-reason cost (one-time): ${cost.ambiguous_reason_cost:.6f}")
    lines.append(
        f"- Incidents detected in this run ({cost.n_events} events): {cost.n_incidents_detected}"
    )
    lines.append(f"- Incidents actually diagnosed (live calls): {cost.n_incidents_diagnosed}")
    lines.append(f"- Incident-diagnosis cost (this run): ${cost.incident_diagnosis_cost:.6f}")
    lines.append(f"- Judge calls: {cost.judge_calls}")
    lines.append(f"- Judge cost: ${cost.judge_cost:.6f}")
    lines.append(f"- **Actual total spend this run: ${cost.actual_total_spend:.6f}**")
    lines.append(
        "- Projected production cost per 100,000 events, cold cache "
        f"(first-ever run): ${cost.projected_cost_per_100k_events_cold_cache:.6f}"
    )
    lines.append(
        "- Projected production cost per 100,000 events, warm cache "
        f"(steady state): ${cost.projected_cost_per_100k_events_warm_cache:.6f}"
    )
    lines.append("")

    lines.append("## Ambiguous-reason diagnoses (Tier 2, cached)")
    lines.append("")
    lines.append("| reason | remediation_class | confidence | cost | reasoning_tokens |")
    lines.append("| --- | --- | --- | --- | --- |")
    for result in report.ambiguous_reason_results:
        reasoning_tokens = (
            "n/a" if result.reasoning_tokens is None else str(result.reasoning_tokens)
        )
        lines.append(
            f"| {result.reason} | {result.remediation_class} | {result.confidence} | "
            f"{_format_optional(result.cost)} | {reasoning_tokens} |"
        )
    lines.append("")

    lines.append("## Incident diagnoses (Tier 2, uncached)")
    lines.append("")
    lines.append("| incident | method | bank | total_count | posture | confidence | cost |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for incident_result in report.incident_diagnoses:
        lines.append(
            f"| {incident_result.incident_id} | {incident_result.method} | "
            f"{incident_result.bank or 'n/a'} | {incident_result.total_count} | "
            f"{incident_result.recommended_posture} | {incident_result.confidence} | "
            f"{_format_optional(incident_result.cost)} |"
        )
    lines.append("")

    judge = report.judge_summary
    lines.append("## LLM-as-a-judge")
    lines.append("")
    lines.append(f"- Judge model: **{judge.model}**")
    lines.append(f"- Samples judged: {judge.n_sampled}")
    lines.append(f"- Disagreements (judge did not endorse the diagnosis): {judge.n_disagree}")
    lines.append(f"- Disagreement rate: {judge.disagreement_rate:.4%}")
    lines.append(f'- Cases the judge labelled "wrong": {len(judge.wrong_cases)}')
    lines.append("")
    lines.append("| kind | subject | diagnosis_confidence | verdict | agrees | concerns |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for sample in judge.samples:
        lines.append(
            f"| {sample.kind} | {sample.subject_id} | {sample.diagnosis_confidence} | "
            f"{sample.verdict} | {sample.agrees_with_diagnosis} | {sample.concerns} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:  # pragma: no cover
    """Run the full benchmark against real OpenRouter models and write reports.

    CLI entry point: argument parsing, live-credential loading, and file
    writing are glue code excluded from the coverage floor per
    ``CLAUDE.md``'s CLI-glue carve-out -- the pipeline logic it calls
    (:func:`run_benchmark` and everything it calls) is fully covered by
    tests using a fake, network-free completer. Requires
    ``OPENROUTER_API_KEY`` in the process environment (e.g. ``uv run
    --env-file .env python -m reflow.eval.diagnose``); this module never
    reads ``.env`` itself.

    ``reasoning_effort="none"`` is requested only for the Tier 2 model,
    which ``tests/llm/test_client_vcr.py`` verified live actually honours
    it. It is deliberately *not* requested for the judge model: a live run
    against ``openai/gpt-oss-20b`` showed it also mandates reasoning and
    rejects ``reasoning_effort="none"`` with the same refusal
    ``google/gemini-3.7-flash`` gives (see ``BUILD_LOG.md``, 2026-08-23),
    so the judge is left at its provider default reasoning behaviour and
    relies on :attr:`~reflow.llm.config.LlmConfig.max_completion_tokens`
    being generous enough to survive it.
    """
    from reflow.llm.client import LlmClient
    from reflow.llm.config import LlmConfig, load_api_key

    parser = argparse.ArgumentParser(description="Run the Phase 4 diagnosis-tier benchmark.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-events", type=int, default=DEFAULT_N_EVENTS)
    parser.add_argument("--tier2-model", type=str, required=True)
    parser.add_argument("--judge-model", type=str, required=True)
    parser.add_argument("--judge-sample-size", type=int, default=DEFAULT_JUDGE_SAMPLE_SIZE)
    parser.add_argument("--max-incidents", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=_REPO_ROOT / "docs" / "reports")
    args = parser.parse_args()

    api_key = load_api_key()
    tier2_client = LlmClient(
        LlmConfig(model=args.tier2_model, api_key=api_key, reasoning_effort="none")
    )
    judge_client = LlmClient(
        LlmConfig(model=args.judge_model, api_key=api_key, max_completion_tokens=1500)
    )
    try:
        report = run_benchmark(
            tier2_client=tier2_client,
            judge_client=judge_client,
            tier2_model_name=args.tier2_model,
            judge_model_name=args.judge_model,
            seed=args.seed,
            n_events=args.n_events,
            judge_sample_size=args.judge_sample_size,
            judge_seed=args.seed,
            max_incident_diagnoses=args.max_incidents,
            progress=print,
        )
    finally:
        tier2_client.close()
        judge_client.close()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase4_diagnosis.json").write_text(
        json.dumps(to_json_dict(report), indent=2), encoding="utf-8"
    )
    (args.output_dir / "phase4_diagnosis.md").write_text(to_markdown(report), encoding="utf-8")
    print(f"Actual total spend: ${report.cost.actual_total_spend:.6f}")


if __name__ == "__main__":  # pragma: no cover
    main()
