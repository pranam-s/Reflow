"""Deliverable 3 of Phase 7: a small, honest, cross-model comparison.

**Why this reuses Phase 4's diagnoser rather than building a new one.**
:mod:`reflow.eval.diagnose` already established the shipped diagnosis
pipeline's only two live LLM call sites (``docs/design.md`` ADR-0004): one
cached call per ambiguous reason code (:class:`reflow.diagnose.ambiguous.AmbiguousReasonDiagnoser`)
and one uncached call per detected incident. This module calls the exact
same :class:`~reflow.diagnose.ambiguous.AmbiguousReasonDiagnoser` -- not a
reimplementation of its prompt or schema -- against several models in turn,
so a difference in the numbers below is attributable to the model, never to
a divergent harness. Incident diagnosis is not separately re-benchmarked
here: it shares the identical client/schema/retry machinery this module
already exercises, and doubling the live-call surface would spend money
without adding evidence relevant to picking a model.

**What is measured, and why each metric is here.** ``docs/design.md``
ADR-0004 and ``BUILD_LOG.md`` (2026-08-22/23) already found, live, that
models differ in ways a bare "did it answer correctly" comparison would
hide entirely: a model can mandate reasoning and be rejected outright by a
disabled-reasoning request; a model can spend its whole completion-token
budget on hidden reasoning and return truncated JSON; a model's true cost is
understated by an order of magnitude if reasoning tokens are not counted
separately from the visible answer. This module measures, per model: total
cost, per-call latency, reasoning tokens as their own column (not folded
into an opaque total), a first-attempt JSON validity rate (whether
:class:`~reflow.llm.client.LlmClient`'s internal truncated/invalid-JSON
retry had to fire at all), and, where both are defined, agreement with
Tier 1's deterministic table (:mod:`reflow.diagnose.tier1`).

**How the deterministic-agreement check works.** Tier 1's deterministic
table resolves 95 of 110 reason codes without ever calling an LLM, because
their vendored ``Next Steps`` text is unambiguous -- Tier 2 never sees them
in production. To get an honest, ground-truth-backed agreement number
(rather than the judge's endorsement rate, which has no ground truth to
check against, only plausibility), this module deliberately asks each
candidate model to diagnose a small sample of *already-deterministically
-resolved* reason codes too, using the same vendored explanation/next-steps
text Tier 1 itself resolved, and checks whether the model's independent
answer matches Tier 1's. This is an evaluation-only probe: production Tier
2 never makes this call, since Tier 1 already has the answer for free.

**The sample is small and deliberately labelled as such.** Every ambiguous
reason code (15) and a fair fraction of deterministic ones are available,
but running all of them against three models would spend real money for
diminishing evidence about which model to ship. :data:`DEFAULT_N_AMBIGUOUS_SAMPLE`
and :data:`DEFAULT_N_DETERMINISTIC_SAMPLE` fix a small, seeded,
reproducible sample (:func:`_sample_reasons`, the same
``random.Random(seed).sample`` pattern :func:`reflow.eval.judge.sample_for_judging`
already uses for the same honesty reason) -- a sampled subset, reported as
one, not implied to be exhaustive.

**The model-selection rule is pre-committed, exactly as ADR-0003's burst
-detector selection rule was, before any live call in this module was
made:** among models that completed every sampled call with zero errors,
pick the lowest total measured cost, tied-broken by lower mean latency; if
every model has at least one error, pick the model with the fewest errors,
tie-broken by lowest total cost. :func:`_pick_default` implements this
mechanically and cannot be adjusted after seeing which model it prefers,
per this project's first governing principle. Whether that mechanical
pick matches the holistic judgement written in ``docs/design.md`` ADR-0007
is reported there, not silently assumed.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from statistics import mean
from typing import Final

from reflow.diagnose.ambiguous import AmbiguousReasonDiagnoser
from reflow.diagnose.tier1 import DeterministicTable, ReasonRowContext, default_deterministic_table
from reflow.llm.client import JsonCompleter
from reflow.llm.errors import LlmError
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import parse_reason_records
from reflow.taxonomy.remediation import ReasonClassification, RemediationClass, classify_reasons

DEFAULT_SAMPLE_SEED: Final[int] = 20260822
DEFAULT_N_AMBIGUOUS_SAMPLE: Final[int] = 6
DEFAULT_N_DETERMINISTIC_SAMPLE: Final[int] = 6
DEFAULT_MODELS: Final[tuple[str, ...]] = (
    "deepseek/deepseek-v4-flash",
    "google/gemini-3.7-flash",
    "openai/gpt-oss-20b",
)
REASONING_EFFORT_NONE_VERIFIED_MODELS: Final[frozenset[str]] = frozenset(
    {"deepseek/deepseek-v4-flash"}
)
"""Models verified live (``BUILD_LOG.md``, 2026-08-22/23) to honour
``reasoning_effort="none"``. Every other model is left at its provider
-default reasoning behaviour with a generous completion-token budget,
exactly as :func:`reflow.eval.diagnose.main` already treats the judge
model, rather than assuming an unverified model will accept the same
request."""

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

PROVENANCE_NOTES: Final[tuple[str, ...]] = (
    "This is a small, seeded, labelled sample, not an exhaustive comparison -- see module "
    "docstring for the sample-size rationale and the $0.50 Phase 7 spend cap it is bounded by.",
    "Every model is called through the exact same "
    "reflow.diagnose.ambiguous.AmbiguousReasonDiagnoser used in production Tier 2, never a "
    "reimplemented prompt, so a difference in the numbers is attributable to the model, not to "
    "a divergent harness.",
    "The deterministic-tier agreement check is an evaluation-only probe: it asks a model to "
    "diagnose reason codes Tier 1 already resolves for free, purely to get a ground-truth-backed "
    "agreement number, distinct from the judge's plausibility-only endorsement rate elsewhere.",
    "reasoning_effort='none' is requested only for models verified live to honour it "
    "(reflow.eval.model_compare.REASONING_EFFORT_NONE_VERIFIED_MODELS); every other model is "
    "left at its provider default with a generous max_completion_tokens, per BUILD_LOG.md "
    "2026-08-22/23.",
    "The default-model recommendation follows a mechanical, pre-committed selection rule stated "
    "in this module's docstring before any live call was made -- see docs/design.md ADR-0007 for "
    "whether that mechanical pick agrees with this project's fuller, holistic judgement.",
)


class SampleKind(StrEnum):
    """Which of the two probes one :class:`ModelCallResult` came from."""

    AMBIGUOUS = "ambiguous"
    DETERMINISTIC_CHECK = "deterministic_check"


@dataclass(frozen=True, slots=True)
class ModelCallResult:
    """One live model call's outcome, ready for reporting.

    Attributes:
        reason: The reason code this call diagnosed.
        kind: Which probe this call belongs to.
        model_remediation_class: The model's chosen remediation class, or
            ``None`` if the call errored.
        expected_remediation_class: Tier 1's known-correct remediation
            class, present only for :attr:`SampleKind.DETERMINISTIC_CHECK`
            calls.
        agrees_with_deterministic_tier: Whether ``model_remediation_class``
            matches ``expected_remediation_class``, or ``None`` when there
            is no ground truth to compare against (every
            :attr:`SampleKind.AMBIGUOUS` call, and any errored call).
        confidence: The model's self-reported confidence, or ``None`` if the
            call errored.
        cost: The call's reported dollar cost, or ``None`` if unreported or
            errored.
        latency_seconds: Wall-clock time for this call, including any
            internal retries :class:`~reflow.llm.client.LlmClient` made.
        reasoning_tokens: Tokens spent on hidden reasoning, or ``None`` if
            unreported or errored.
        attempts: Total attempts the client made before returning, or
            ``None`` if the call errored (every attempt failed).
        finish_reason: The provider's reported completion finish reason, or
            ``None`` if unreported or errored.
        error: A short description of the failure, or ``None`` on success.
    """

    reason: str
    kind: str
    model_remediation_class: str | None
    expected_remediation_class: str | None
    agrees_with_deterministic_tier: bool | None
    confidence: str | None
    cost: float | None
    latency_seconds: float
    reasoning_tokens: int | None
    attempts: int | None
    finish_reason: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class ModelAggregate:
    """One model's aggregate results across every sampled call.

    Attributes:
        model: The model slug.
        calls: Every :class:`ModelCallResult` for this model, in call
            order.
        n_calls: Total calls attempted.
        n_errors: Calls that raised an :class:`~reflow.llm.errors.LlmError`.
        n_successes: ``n_calls - n_errors``.
        total_cost: Summed reported cost across every successful call.
        mean_latency_seconds: Mean wall-clock latency across every call,
            successful or not (``0.0`` if there were no calls at all).
        total_reasoning_tokens: Summed reasoning tokens across every
            successful call that reported them.
        mean_reasoning_tokens: Mean reasoning tokens per successful call
            that reported them, or ``None`` if none did.
        first_attempt_json_valid_rate: Fraction of successful calls that
            needed no internal JSON-validity retry (``attempts == 1``), or
            ``None`` if there were no successful calls.
        deterministic_agreement_rate: Fraction of successful
            :attr:`SampleKind.DETERMINISTIC_CHECK` calls whose answer
            matched Tier 1's, or ``None`` if no such call succeeded.
    """

    model: str
    calls: tuple[ModelCallResult, ...]
    n_calls: int
    n_errors: int
    n_successes: int
    total_cost: float
    mean_latency_seconds: float
    total_reasoning_tokens: int
    mean_reasoning_tokens: float | None
    first_attempt_json_valid_rate: float | None
    deterministic_agreement_rate: float | None


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to attribute and reproduce a comparison run.

    Attributes:
        generated_at: UTC ISO-8601 timestamp of report generation.
        models: Every model compared, in comparison order.
        n_ambiguous_sample: Requested ambiguous-reason sample size.
        n_deterministic_sample: Requested deterministic-reason sample size.
        sample_seed: Seed used to draw both samples.
        command: The command that produced this report.
        library_versions: Installed version of every result-relevant
            library.
        notes: Free-text disclosures (see :data:`PROVENANCE_NOTES`).
    """

    generated_at: str
    models: tuple[str, ...]
    n_ambiguous_sample: int
    n_deterministic_sample: int
    sample_seed: int
    command: str
    library_versions: dict[str, str]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelComparisonReport:
    """The complete Phase 7 model-comparison result.

    Attributes:
        provenance: See :class:`Provenance`.
        ambiguous_reasons_sampled: The ambiguous reason codes actually
            sampled, shared identically across every model.
        deterministic_reasons_sampled: The deterministic reason codes
            actually sampled, shared identically across every model.
        models: Every :class:`ModelAggregate`, in comparison order.
        recommended_default_model: The model :func:`_pick_default` selected.
        recommendation_rationale: A human-readable explanation of that
            pick, generated from the measured numbers above.
    """

    provenance: Provenance
    ambiguous_reasons_sampled: tuple[str, ...]
    deterministic_reasons_sampled: tuple[str, ...]
    models: tuple[ModelAggregate, ...]
    recommended_default_model: str
    recommendation_rationale: str


def _sample_reasons(reasons: Sequence[str], k: int, seed: int) -> list[str]:
    """Draw a fixed-size, seeded, reproducible sample of reason codes.

    Args:
        reasons: The population to sample from.
        k: Desired sample size.
        seed: Seed for reproducible sampling.

    Returns:
        ``min(k, len(reasons))`` reason codes, sorted for a stable, legible
        report order. Returns every reason, sorted, if ``k >= len(reasons)``.
    """
    if k >= len(reasons):
        return sorted(reasons)
    rng = random.Random(seed)  # noqa: S311
    return sorted(rng.sample(list(reasons), k))


def _build_deterministic_row_contexts(table: DeterministicTable) -> dict[str, ReasonRowContext]:
    """Recover one representative vendored row per deterministic reason code.

    :class:`~reflow.diagnose.tier1.DeterministicTable` deliberately discards
    row text for reasons it already resolves deterministically -- Tier 1
    never needs it in production. This evaluation module does need it, to
    actually ask a model to diagnose a reason Tier 1 already has an answer
    for (see module docstring). Re-parses the vendored spreadsheet once,
    independently of :func:`~reflow.diagnose.tier1.default_deterministic_table`'s
    own parse, since neither :mod:`reflow.taxonomy` nor
    :mod:`reflow.diagnose.tier1` exposes this mapping directly.

    Args:
        table: The deterministic table whose
            :attr:`~reflow.diagnose.tier1.DeterministicTable.deterministic`
            keys define which reasons need a context here.

    Returns:
        A mapping from deterministic reason code to one
        :class:`~reflow.diagnose.tier1.ReasonRowContext` built from that
        reason's first vendored row (every row for a deterministic reason
        already agrees on the same remediation class, by
        :func:`~reflow.diagnose.tier1.build_deterministic_table`'s own
        definition of "deterministic", so any one row's text is
        representative).
    """
    records = parse_reason_records(resolve_vendored_path(_REPO_ROOT))
    classifications = classify_reasons(records)
    record_by_row_index = {record.row_index: record for record in records}
    first_row_by_reason: dict[str, ReasonClassification] = {}
    for classification in classifications:
        first_row_by_reason.setdefault(classification.reason, classification)

    contexts: dict[str, ReasonRowContext] = {}
    for reason in table.deterministic:
        row = first_row_by_reason[reason]
        record = record_by_row_index[row.row_index]
        contexts[reason] = ReasonRowContext(
            explanation=record.explanation,
            next_steps=record.next_steps,
            candidate_classes=row.candidate_classes,
            ambiguity_note=row.ambiguity_note,
        )
    return contexts


def _call_and_record(
    diagnoser: AmbiguousReasonDiagnoser,
    reason: str,
    contexts: tuple[ReasonRowContext, ...],
    *,
    kind: SampleKind,
    expected: RemediationClass | None,
) -> ModelCallResult:
    """Make one live call and turn its outcome into a :class:`ModelCallResult`.

    Args:
        diagnoser: The (per-model) diagnoser to call.
        reason: The reason code to diagnose.
        contexts: The vendored row(s) backing this reason code.
        kind: Which probe this call belongs to.
        expected: Tier 1's known-correct remediation class, for
            :attr:`SampleKind.DETERMINISTIC_CHECK` calls; ``None`` for
            :attr:`SampleKind.AMBIGUOUS` calls.

    Returns:
        The populated :class:`ModelCallResult`, whether the call succeeded
        or raised an :class:`~reflow.llm.errors.LlmError`.
    """
    expected_value = expected.value if expected is not None else None
    start = time.perf_counter()
    try:
        result = diagnoser.diagnose(reason, contexts)
    except LlmError as exc:
        elapsed = time.perf_counter() - start
        return ModelCallResult(
            reason=reason,
            kind=kind.value,
            model_remediation_class=None,
            expected_remediation_class=expected_value,
            agrees_with_deterministic_tier=None,
            confidence=None,
            cost=None,
            latency_seconds=elapsed,
            reasoning_tokens=None,
            attempts=None,
            finish_reason=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    elapsed = time.perf_counter() - start
    diagnosis = result.value
    agrees = None if expected is None else diagnosis.remediation_class == expected
    return ModelCallResult(
        reason=reason,
        kind=kind.value,
        model_remediation_class=diagnosis.remediation_class.value,
        expected_remediation_class=expected_value,
        agrees_with_deterministic_tier=agrees,
        confidence=diagnosis.confidence.value,
        cost=result.usage.cost,
        latency_seconds=elapsed,
        reasoning_tokens=result.usage.reasoning_tokens,
        attempts=result.attempts,
        finish_reason=result.finish_reason,
        error=None,
    )


def _aggregate(model: str, calls: Sequence[ModelCallResult]) -> ModelAggregate:
    """Summarise one model's calls into a :class:`ModelAggregate`.

    Args:
        model: The model slug.
        calls: Every call made for this model, in call order.

    Returns:
        The populated :class:`ModelAggregate`.
    """
    successes = [call for call in calls if call.error is None]
    n_errors = len(calls) - len(successes)
    total_cost = sum(call.cost or 0.0 for call in successes)
    mean_latency = mean(call.latency_seconds for call in calls) if calls else 0.0
    reasoning_values = [
        call.reasoning_tokens for call in successes if call.reasoning_tokens is not None
    ]
    total_reasoning = sum(reasoning_values)
    mean_reasoning = (total_reasoning / len(reasoning_values)) if reasoning_values else None
    first_attempt_successes = sum(1 for call in successes if call.attempts == 1)
    first_attempt_rate = (first_attempt_successes / len(successes)) if successes else None
    deterministic_calls = [
        call for call in successes if call.agrees_with_deterministic_tier is not None
    ]
    agreement_rate = (
        sum(1 for call in deterministic_calls if call.agrees_with_deterministic_tier)
        / len(deterministic_calls)
        if deterministic_calls
        else None
    )
    return ModelAggregate(
        model=model,
        calls=tuple(calls),
        n_calls=len(calls),
        n_errors=n_errors,
        n_successes=len(successes),
        total_cost=total_cost,
        mean_latency_seconds=mean_latency,
        total_reasoning_tokens=total_reasoning,
        mean_reasoning_tokens=mean_reasoning,
        first_attempt_json_valid_rate=first_attempt_rate,
        deterministic_agreement_rate=agreement_rate,
    )


def _pick_default(aggregates: Sequence[ModelAggregate]) -> tuple[str, str]:
    """Apply the pre-committed model-selection rule (see module docstring).

    Args:
        aggregates: Every model's :class:`ModelAggregate`.

    Returns:
        A ``(model_slug, rationale)`` pair.
    """
    zero_error = [aggregate for aggregate in aggregates if aggregate.n_errors == 0]
    pool = zero_error if zero_error else list(aggregates)
    ranked = sorted(pool, key=lambda a: (a.n_errors, a.total_cost, a.mean_latency_seconds))
    winner = ranked[0]
    if zero_error:
        rationale = (
            "Pre-committed rule: among models with zero call errors, pick the lowest total "
            f"measured cost, tie-broken by lower mean latency. {winner.model} wins at "
            f"${winner.total_cost:.6f} total across {winner.n_calls} calls, "
            f"{winner.mean_latency_seconds:.3f}s mean latency."
        )
    else:
        rationale = (
            "No model completed every sampled call with zero errors. Falling back to the "
            f"pre-committed tie-break: fewest errors, then lowest total cost. {winner.model} "
            f"wins with {winner.n_errors} error(s) and ${winner.total_cost:.6f} total cost."
        )
    return winner.model, rationale


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


def run_model_comparison(
    *,
    model_clients: Mapping[str, JsonCompleter],
    n_ambiguous_sample: int = DEFAULT_N_AMBIGUOUS_SAMPLE,
    n_deterministic_sample: int = DEFAULT_N_DETERMINISTIC_SAMPLE,
    sample_seed: int = DEFAULT_SAMPLE_SEED,
    table: DeterministicTable | None = None,
) -> ModelComparisonReport:
    """Run the full Phase 7 cross-model diagnosis comparison.

    Args:
        model_clients: Mapping from model slug to its completer, in the
            order models should be compared and reported.
        n_ambiguous_sample: How many ambiguous reason codes to sample.
        n_deterministic_sample: How many deterministic reason codes to
            sample for the ground-truth agreement check.
        sample_seed: Seed for both samples.
        table: The deterministic table to sample from. Defaults to
            :func:`reflow.diagnose.tier1.default_deterministic_table`.

    Returns:
        The complete :class:`ModelComparisonReport`.
    """
    resolved_table = table if table is not None else default_deterministic_table()
    deterministic_contexts = _build_deterministic_row_contexts(resolved_table)

    ambiguous_reasons = _sample_reasons(
        sorted(resolved_table.escalated), n_ambiguous_sample, sample_seed
    )
    deterministic_reasons = _sample_reasons(
        sorted(resolved_table.deterministic), n_deterministic_sample, sample_seed
    )

    aggregates: list[ModelAggregate] = []
    for model, client in model_clients.items():
        diagnoser = AmbiguousReasonDiagnoser(client=client)
        calls: list[ModelCallResult] = []
        for reason in ambiguous_reasons:
            calls.append(
                _call_and_record(
                    diagnoser,
                    reason,
                    resolved_table.escalated[reason],
                    kind=SampleKind.AMBIGUOUS,
                    expected=None,
                )
            )
        for reason in deterministic_reasons:
            calls.append(
                _call_and_record(
                    diagnoser,
                    reason,
                    (deterministic_contexts[reason],),
                    kind=SampleKind.DETERMINISTIC_CHECK,
                    expected=resolved_table.deterministic[reason],
                )
            )
        aggregates.append(_aggregate(model, calls))

    recommended_model, rationale = _pick_default(aggregates)

    provenance = Provenance(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        models=tuple(model_clients),
        n_ambiguous_sample=n_ambiguous_sample,
        n_deterministic_sample=n_deterministic_sample,
        sample_seed=sample_seed,
        command="uv run --env-file .env python -m reflow.eval.model_compare",
        library_versions=_library_versions(),
        notes=PROVENANCE_NOTES,
    )
    return ModelComparisonReport(
        provenance=provenance,
        ambiguous_reasons_sampled=tuple(ambiguous_reasons),
        deterministic_reasons_sampled=tuple(deterministic_reasons),
        models=tuple(aggregates),
        recommended_default_model=recommended_model,
        recommendation_rationale=rationale,
    )


def to_json_dict(report: ModelComparisonReport) -> dict[str, object]:
    """Serialise a :class:`ModelComparisonReport` to a JSON-safe nested dict.

    Args:
        report: The report to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``.
    """
    return asdict(report)


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


def to_markdown(report: ModelComparisonReport) -> str:
    """Render a human-readable markdown summary of a :class:`ModelComparisonReport`.

    Args:
        report: The report to render.

    Returns:
        A markdown document.
    """
    provenance = report.provenance
    lines: list[str] = []
    lines.append("# Phase 7 model-comparison results")
    lines.append("")
    lines.append(f"- Generated at: {provenance.generated_at}")
    lines.append(f"- Command: `{provenance.command}`")
    lines.append(f"- Models compared: {', '.join(provenance.models)}")
    lines.append(f"- Ambiguous-reason sample size: {provenance.n_ambiguous_sample}")
    lines.append(f"- Deterministic-reason sample size: {provenance.n_deterministic_sample}")
    lines.append(f"- Sample seed: {provenance.sample_seed}")
    version_items = sorted(provenance.library_versions.items())
    versions_text = ", ".join(f"{name}={version}" for name, version in version_items)
    lines.append(f"- Library versions: {versions_text}")
    for note in provenance.notes:
        lines.append(f"- Note: {note}")
    lines.append("")
    lines.append(f"- Ambiguous reasons sampled: {', '.join(report.ambiguous_reasons_sampled)}")
    lines.append(
        f"- Deterministic reasons sampled: {', '.join(report.deterministic_reasons_sampled)}"
    )
    lines.append("")

    lines.append("## Aggregate comparison")
    lines.append("")
    lines.append(
        "| model | calls | errors | total cost | mean latency (s) | total reasoning tokens | "
        "mean reasoning tokens | first-attempt JSON valid | deterministic agreement |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for aggregate in report.models:
        lines.append(
            f"| {aggregate.model} | {aggregate.n_calls} | {aggregate.n_errors} | "
            f"${aggregate.total_cost:.6f} | {aggregate.mean_latency_seconds:.3f} | "
            f"{aggregate.total_reasoning_tokens} | "
            f"{_format_optional(aggregate.mean_reasoning_tokens, 1)} | "
            f"{_format_optional(aggregate.first_attempt_json_valid_rate, 4)} | "
            f"{_format_optional(aggregate.deterministic_agreement_rate, 4)} |"
        )
    lines.append("")

    lines.append(f"**Recommended default model: `{report.recommended_default_model}`**")
    lines.append("")
    lines.append(report.recommendation_rationale)
    lines.append("")

    for aggregate in report.models:
        lines.append(f"## {aggregate.model}: per-call detail")
        lines.append("")
        lines.append(
            "| reason | kind | model class | expected class | agrees | confidence | cost | "
            "latency (s) | reasoning tokens | attempts | finish_reason | error |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for call in aggregate.calls:
            lines.append(
                f"| {call.reason} | {call.kind} | {call.model_remediation_class or 'n/a'} | "
                f"{call.expected_remediation_class or 'n/a'} | "
                f"{call.agrees_with_deterministic_tier} | {call.confidence or 'n/a'} | "
                f"{_format_optional(call.cost)} | {call.latency_seconds:.3f} | "
                f"{call.reasoning_tokens if call.reasoning_tokens is not None else 'n/a'} | "
                f"{call.attempts if call.attempts is not None else 'n/a'} | "
                f"{call.finish_reason or 'n/a'} | {call.error or ''} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:  # pragma: no cover
    """Run the live model comparison and write JSON + markdown reports.

    CLI entry point: argument parsing, live-credential loading, and file
    writing are glue code excluded from the coverage floor per
    ``CLAUDE.md``'s CLI-glue carve-out -- the comparison logic it calls
    (:func:`run_model_comparison` and everything it calls) is fully covered
    by tests using a fake, network-free completer. Requires
    ``OPENROUTER_API_KEY`` in the process environment (e.g. ``uv run
    --env-file .env python -m reflow.eval.model_compare``); this module
    never reads ``.env`` itself.
    """
    from reflow.llm.client import LlmClient
    from reflow.llm.config import LlmConfig, load_api_key

    parser = argparse.ArgumentParser(description="Run the Phase 7 model comparison.")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--n-ambiguous", type=int, default=DEFAULT_N_AMBIGUOUS_SAMPLE)
    parser.add_argument("--n-deterministic", type=int, default=DEFAULT_N_DETERMINISTIC_SAMPLE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SAMPLE_SEED)
    parser.add_argument("--output-dir", type=Path, default=_REPO_ROOT / "docs" / "reports")
    args = parser.parse_args()

    api_key = load_api_key()
    clients: dict[str, JsonCompleter] = {}
    llm_clients: list[LlmClient] = []
    for model in args.models:
        honours_none = model in REASONING_EFFORT_NONE_VERIFIED_MODELS
        client = LlmClient(
            LlmConfig(
                model=model,
                api_key=api_key,
                reasoning_effort="none" if honours_none else None,
                max_completion_tokens=1024 if honours_none else 1500,
            )
        )
        llm_clients.append(client)
        clients[model] = client

    try:
        report = run_model_comparison(
            model_clients=clients,
            n_ambiguous_sample=args.n_ambiguous,
            n_deterministic_sample=args.n_deterministic,
            sample_seed=args.seed,
        )
    finally:
        for client in llm_clients:
            client.close()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase7_model_comparison.json").write_text(
        json.dumps(to_json_dict(report), indent=2), encoding="utf-8"
    )
    (args.output_dir / "phase7_model_comparison.md").write_text(
        to_markdown(report), encoding="utf-8"
    )
    total_spend = sum(aggregate.total_cost for aggregate in report.models)
    print(f"Recommended default model: {report.recommended_default_model}")
    print(f"Actual total spend: ${total_spend:.6f}")


if __name__ == "__main__":  # pragma: no cover
    main()
