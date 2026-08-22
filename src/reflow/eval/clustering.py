"""The Phase 2 clustering bake-off harness.

Runs every candidate in :mod:`reflow.cluster` against every other, across
three sweep axes, and reports whether clustering earns its place over the
trivial ``GROUP BY (code, source, step, reason)`` baseline -- and if so,
where exactly. See the module docstrings of :mod:`reflow.signature.mask`,
:mod:`reflow.eval.opacity`, and ``docs/design.md``'s Phase 2 ADR for the
design decisions this harness implements.

**Scope.** Per the phase brief, the three genuine clusterers
(:class:`~reflow.cluster.drain3_clusterer.Drain3Clusterer`,
:class:`~reflow.cluster.template_hash.TemplateHashClusterer`,
:class:`~reflow.cluster.tfidf_hdbscan.TfidfHdbscanClusterer`) are run only
on the catch-all stratum (events whose ``latent_subcause_id`` is not
``None``): the structured taxonomy already resolves narrow reasons
outright, and clustering them would be theatre.
:class:`~reflow.cluster.groupby_reason.GroupByReasonClusterer` is run over
the whole corpus once per (richness, arm) -- it is arm-invariant by
construction (it never reads text) but is run for both arms anyway so the
results table's shape stays uniform and self-documenting -- and its
metrics are then reported separately for both strata, which is what
:func:`run_bakeoff`'s Axis C crossover analysis needs.

**Three sweep axes.**

- Axis A (variant richness): :data:`~reflow.corpus.reasons.SUPPORTED_VARIANT_RICHNESS_LEVELS`.
- Axis B (opacity): :data:`ARMS` -- ``"transparent"`` (the corpus as
  generated) and ``"opaque"`` (catch-all descriptions collapsed via
  :func:`reflow.eval.opacity.opaque_description`, the null-hypothesis
  control).
- Axis C (catch-all share): not resampled. :func:`reflow.eval.metrics.blended_metric`
  and :func:`reflow.eval.metrics.find_crossover_share` compute, from the
  stratified metrics this harness already produces, the catch-all share at
  which each real clusterer's blended performance would overtake GROUP
  BY's -- see :func:`_compute_crossovers` for the modelling assumption
  this reduces to, stated plainly rather than hidden in the arithmetic.

**Noise-handling caveat.** :attr:`reflow.corpus.events.PaymentEvent.is_outlier`
is never ``True`` for a catch-all reason (see that attribute's docstring:
catch-all sub-causes are deliberately substantial, multi-cause clusters by
construction, not one-offs). Since the primary bake-off clusters only the
catch-all stratum, it structurally cannot exercise true-outlier recall --
:func:`run_noise_diagnostic` is a separate, explicitly out-of-primary-scope
measurement that runs the same three clusterers on the (subsampled) narrow
stratum instead, where true outliers actually exist.
"""

from __future__ import annotations

import importlib.metadata
import platform
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from reflow.cluster.base import Clusterer, ClusterInput
from reflow.cluster.drain3_clusterer import Drain3Clusterer
from reflow.cluster.groupby_reason import GroupByReasonClusterer
from reflow.cluster.template_hash import TemplateHashClusterer
from reflow.cluster.tfidf_hdbscan import TfidfHdbscanClusterer
from reflow.corpus.events import PaymentEvent
from reflow.corpus.generator import generate_corpus
from reflow.corpus.reasons import SUPPORTED_VARIANT_RICHNESS_LEVELS
from reflow.eval.metrics import (
    ClusteringMetrics,
    NoiseHandling,
    compute_metrics,
    compute_noise_handling,
    find_crossover_share,
)
from reflow.eval.opacity import opaque_description
from reflow.signature.mask import mask_description
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import ReasonRecord, parse_reason_records

DEFAULT_SEED: Final[int] = 20260822
DEFAULT_N_EVENTS: Final[int] = 50_000

TRANSPARENT_ARM: Final[str] = "transparent"
OPAQUE_ARM: Final[str] = "opaque"
ARMS: Final[tuple[str, str]] = (TRANSPARENT_ARM, OPAQUE_ARM)

CATCHALL_STRATUM: Final[str] = "catchall"
NARROW_STRATUM: Final[str] = "narrow"

NOISE_DIAGNOSTIC_SAMPLE_SIZE: Final[int] = 4_000
"""Target size of the outlier-enriched narrow-stratum sample
:func:`run_noise_diagnostic` clusters. Chosen so TF-IDF + HDBSCAN's
``O(n^2)`` brute-force cosine distance computation (cosine is not
supported by a KD-tree/ball-tree, see
:mod:`reflow.cluster.tfidf_hdbscan`) stays tractable -- the full narrow
stratum at 50,000 events is itself on the order of 40,000+ events, whose
dense pairwise-distance matrix would run to tens of gigabytes."""

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

PROVENANCE_NOTES: Final[tuple[str, ...]] = (
    "The three genuine clusterers are run only on the catch-all stratum "
    "(observed as ~8,000 of 50,000 events at this seed), never the full corpus; "
    "GROUP BY is run on the full corpus. See the 'Scope' section of this module's "
    "docstring for why.",
    "The noise/outlier-handling diagnostic table is a supplementary, "
    "out-of-primary-scope measurement on a subsample of the narrow stratum "
    "(target size 4,000, every true outlier deliberately kept -- see "
    "_sample_narrow_stratum_for_noise_diagnostic), not the primary catch-all "
    "bake-off, because PaymentEvent.is_outlier is never True for a catch-all "
    "reason by corpus design. Its precision figures are inflated relative to true "
    "deployment outlier prevalence by the deliberate enrichment; recall is not.",
    "TfidfHdbscanClusterer's cosine-metric HDBSCAN computes pairwise distances by "
    "brute force (O(n^2); cosine has no KD-tree/ball-tree support), which is "
    "tractable at the catch-all stratum's actual observed size (~8,000) but would "
    "not scale to a literal 50,000-event catch-all stratum without further "
    "subsampling, a different metric, or a dimensionality-reduction step.",
)
"""Disclosures surfaced in every generated report's provenance header, per
this phase's requirement to state subsampling and scope decisions clearly
rather than silently."""


def _real_clusterers() -> tuple[Clusterer, ...]:
    """Build one fresh instance of each genuine (non-baseline) clusterer.

    Returns:
        ``(Drain3Clusterer(), TemplateHashClusterer(), TfidfHdbscanClusterer())``.
    """
    return (Drain3Clusterer(), TemplateHashClusterer(), TfidfHdbscanClusterer())


def _build_reason_record_lookup(records: Sequence[ReasonRecord]) -> dict[str, ReasonRecord]:
    """Build a reason-code-keyed lookup, first occurrence wins.

    Args:
        records: All parsed reason records, in file order.

    Returns:
        A mapping from reason code to its first-seen :class:`ReasonRecord`.
    """
    lookup: dict[str, ReasonRecord] = {}
    for record in records:
        lookup.setdefault(record.reason, record)
    return lookup


def _true_label(event: PaymentEvent) -> str:
    """Compute an event's ground-truth cluster label.

    Args:
        event: The event to label.

    Returns:
        ``event.latent_subcause_id`` for a catch-all event, otherwise
        ``event.error_reason``.
    """
    return event.latent_subcause_id if event.latent_subcause_id is not None else event.error_reason


def _cluster_input(event: PaymentEvent, masked_description: str) -> ClusterInput:
    """Build one event's :class:`~reflow.cluster.base.ClusterInput`.

    Args:
        event: The source event.
        masked_description: The already-masked description to carry.

    Returns:
        The populated :class:`~reflow.cluster.base.ClusterInput`.
    """
    return ClusterInput(
        masked_description=masked_description,
        code=event.error_code,
        source=event.error_source,
        step=event.error_step,
        reason=event.error_reason,
    )


@dataclass(frozen=True, slots=True)
class StratumResult:
    """One candidate's metrics on one stratum of one run.

    Attributes:
        stratum: :data:`CATCHALL_STRATUM` or :data:`NARROW_STRATUM`.
        metrics: The core separability metrics on this stratum.
        noise_handling: Noise/outlier agreement on this stratum.
    """

    stratum: str
    metrics: ClusteringMetrics
    noise_handling: NoiseHandling


@dataclass(frozen=True, slots=True)
class CandidateRun:
    """One (candidate, richness, arm) execution of the bake-off.

    Attributes:
        candidate: The candidate's :attr:`~reflow.cluster.base.Clusterer.name`.
        richness: The Axis A variant-richness level this run used.
        arm: :data:`TRANSPARENT_ARM` or :data:`OPAQUE_ARM`.
        n_input_events: Number of events actually passed to ``fit_predict``
            (the whole corpus for
            :class:`~reflow.cluster.groupby_reason.GroupByReasonClusterer`,
            the catch-all stratum only for every genuine clusterer).
        runtime_seconds: Wall-clock time of the single ``fit_predict`` call.
        strata: Per-stratum results. A genuine clusterer contributes
            exactly one (:data:`CATCHALL_STRATUM`); the baseline
            contributes two.
    """

    candidate: str
    richness: int
    arm: str
    n_input_events: int
    runtime_seconds: float
    strata: tuple[StratumResult, ...]

    def stratum(self, name: str) -> StratumResult | None:
        """Look up this run's result for one stratum.

        Args:
            name: :data:`CATCHALL_STRATUM` or :data:`NARROW_STRATUM`.

        Returns:
            The matching :class:`StratumResult`, or ``None`` if this run
            has no result for that stratum.
        """
        for result in self.strata:
            if result.stratum == name:
                return result
        return None


@dataclass(frozen=True, slots=True)
class CrossoverResult:
    """Axis C: whether/where one candidate's blend overtakes GROUP BY's.

    See :func:`_compute_crossovers` for the modelling assumption behind
    ``crossover_share``.

    Attributes:
        candidate: The genuine clusterer's name.
        richness: The Axis A richness level this result was computed at.
        arm: The Axis B arm this result was computed at.
        metric_name: ``"purity"``, ``"nmi"``, or ``"ari"``.
        candidate_catchall_metric: The candidate's metric on the catch-all
            stratum.
        baseline_catchall_metric: GROUP BY's metric on the catch-all
            stratum.
        baseline_narrow_metric: GROUP BY's metric on the narrow stratum.
        crossover_share: The smallest catch-all share at which the
            candidate's blended system overtakes GROUP BY's, or ``None`` if
            it never does -- see :func:`reflow.eval.metrics.find_crossover_share`.
    """

    candidate: str
    richness: int
    arm: str
    metric_name: str
    candidate_catchall_metric: float
    baseline_catchall_metric: float
    baseline_narrow_metric: float
    crossover_share: float | None


@dataclass(frozen=True, slots=True)
class NoiseDiagnosticRun:
    """One clusterer's result in the supplementary noise-handling diagnostic.

    Attributes:
        candidate: The clusterer's name.
        n_input_events: Number of (outlier-enriched, subsampled) narrow-stratum
            events clustered.
        noise_handling: Noise/outlier agreement on this sample.
        runtime_seconds: Wall-clock time of the ``fit_predict`` call.
    """

    candidate: str
    n_input_events: int
    noise_handling: NoiseHandling
    runtime_seconds: float


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to attribute and reproduce a bake-off run.

    Attributes:
        generated_at: UTC ISO-8601 timestamp of report generation.
        seed: The corpus seed used for every richness level.
        n_events: The corpus size used for every richness level.
        richness_levels: The Axis A levels swept.
        arms: The Axis B arms swept.
        command: The command that produced this report.
        library_versions: Installed version of every library whose
            behaviour materially affects the result.
        notes: Free-text disclosures -- in particular, the noise
            diagnostic's subsampling (see :data:`NOISE_DIAGNOSTIC_SAMPLE_SIZE`)
            is recorded here rather than left implicit.
    """

    generated_at: str
    seed: int
    n_events: int
    richness_levels: tuple[int, ...]
    arms: tuple[str, ...]
    command: str
    library_versions: dict[str, str]
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class BakeoffReport:
    """The complete Phase 2 clustering bake-off result.

    Attributes:
        provenance: See :class:`Provenance`.
        runs: One :class:`CandidateRun` per (candidate, richness, arm).
        crossovers: One :class:`CrossoverResult` per (genuine candidate,
            richness, arm, metric).
        noise_diagnostic: The supplementary noise-handling diagnostic
            results (see module docstring).
    """

    provenance: Provenance
    runs: tuple[CandidateRun, ...]
    crossovers: tuple[CrossoverResult, ...]
    noise_diagnostic: tuple[NoiseDiagnosticRun, ...]


_METRIC_EXTRACTORS: Final[dict[str, Callable[[ClusteringMetrics], float]]] = {
    "purity": lambda metrics: metrics.purity,
    "nmi": lambda metrics: metrics.nmi,
    "ari": lambda metrics: metrics.ari,
}


def _compute_crossovers(runs: Sequence[CandidateRun]) -> tuple[CrossoverResult, ...]:
    """Compute Axis C crossover shares for every genuine candidate.

    Models the deployed system as: catch-all traffic routed to the
    candidate being scored, narrow traffic always routed to GROUP BY --
    because the phase's scope decision keeps clustering off narrow reasons
    regardless of which candidate wins the catch-all stratum. Under that
    model, the "blend clustering in" system's narrow-stratum term and the
    "pure GROUP BY" system's narrow-stratum term are identical (both are
    GROUP BY's narrow-stratum metric), so the crossover reduces to
    whether the candidate beats GROUP BY on the catch-all stratum alone:
    if it does, the blended system is ahead at every catch-all share above
    zero; if it does not, it is never ahead. This reduction is a
    consequence of the scope decision, not hard-coded here --
    :func:`reflow.eval.metrics.find_crossover_share` is a generic scan
    over both curves, so a caller who supplies a different candidate
    narrow-stratum assumption gets a genuinely different answer.

    Args:
        runs: Every :class:`CandidateRun` from one :func:`run_bakeoff` call.

    Returns:
        One :class:`CrossoverResult` per (genuine candidate, richness, arm,
        metric in :data:`_METRIC_EXTRACTORS`).
    """
    groupby_by_key = {
        (run.richness, run.arm): run for run in runs if run.candidate == GroupByReasonClusterer.name
    }
    results: list[CrossoverResult] = []
    for run in runs:
        if run.candidate == GroupByReasonClusterer.name:
            continue
        baseline = groupby_by_key.get((run.richness, run.arm))
        candidate_catchall = run.stratum(CATCHALL_STRATUM)
        if baseline is None or candidate_catchall is None:
            continue
        baseline_catchall = baseline.stratum(CATCHALL_STRATUM)
        baseline_narrow = baseline.stratum(NARROW_STRATUM)
        if baseline_catchall is None or baseline_narrow is None:
            continue
        for metric_name, extract in _METRIC_EXTRACTORS.items():
            candidate_catchall_metric = extract(candidate_catchall.metrics)
            baseline_catchall_metric = extract(baseline_catchall.metrics)
            baseline_narrow_metric = extract(baseline_narrow.metrics)
            crossover_share = find_crossover_share(
                candidate_catchall_metric=candidate_catchall_metric,
                candidate_narrow_metric=baseline_narrow_metric,
                baseline_catchall_metric=baseline_catchall_metric,
                baseline_narrow_metric=baseline_narrow_metric,
            )
            results.append(
                CrossoverResult(
                    candidate=run.candidate,
                    richness=run.richness,
                    arm=run.arm,
                    metric_name=metric_name,
                    candidate_catchall_metric=candidate_catchall_metric,
                    baseline_catchall_metric=baseline_catchall_metric,
                    baseline_narrow_metric=baseline_narrow_metric,
                    crossover_share=crossover_share,
                )
            )
    return tuple(results)


def _run_richness_level(
    richness: int,
    seed: int,
    n_events: int,
    records: list[ReasonRecord],
    record_by_reason: dict[str, ReasonRecord],
) -> list[CandidateRun]:
    """Run every candidate, on both arms, at one Axis A richness level.

    Args:
        richness: The variant-richness level to generate the corpus at.
        seed: The corpus seed.
        n_events: The corpus size.
        records: All parsed reason records.
        record_by_reason: Reason-code-keyed lookup built from ``records``.

    Returns:
        One :class:`CandidateRun` per (candidate, arm) at this richness
        level.
    """
    events = list(
        generate_corpus(
            seed=seed, n_events=n_events, reason_records=records, variant_richness=richness
        )
    )
    catchall_idx = [i for i, event in enumerate(events) if event.latent_subcause_id is not None]
    narrow_idx = [i for i, event in enumerate(events) if event.latent_subcause_id is None]
    true_labels = [_true_label(event) for event in events]
    is_outlier = [event.is_outlier for event in events]

    arm_texts: dict[str, list[str]] = {
        TRANSPARENT_ARM: [mask_description(event.description) for event in events],
        OPAQUE_ARM: [
            mask_description(opaque_description(event, record_by_reason[event.error_reason]))
            for event in events
        ],
    }

    runs: list[CandidateRun] = []
    for arm in ARMS:
        inputs = [
            _cluster_input(event, text) for event, text in zip(events, arm_texts[arm], strict=True)
        ]

        start = time.perf_counter()
        groupby_labels = GroupByReasonClusterer().fit_predict(inputs)
        groupby_runtime = time.perf_counter() - start
        groupby_strata = tuple(
            StratumResult(
                stratum=stratum_name,
                metrics=compute_metrics(
                    [true_labels[i] for i in idx], [groupby_labels[i] for i in idx]
                ),
                noise_handling=compute_noise_handling(
                    [is_outlier[i] for i in idx], [groupby_labels[i] for i in idx]
                ),
            )
            for stratum_name, idx in (
                (CATCHALL_STRATUM, catchall_idx),
                (NARROW_STRATUM, narrow_idx),
            )
        )
        runs.append(
            CandidateRun(
                candidate=GroupByReasonClusterer.name,
                richness=richness,
                arm=arm,
                n_input_events=len(events),
                runtime_seconds=groupby_runtime,
                strata=groupby_strata,
            )
        )

        catchall_inputs = [inputs[i] for i in catchall_idx]
        catchall_true = [true_labels[i] for i in catchall_idx]
        catchall_outlier = [is_outlier[i] for i in catchall_idx]
        for clusterer in _real_clusterers():
            start = time.perf_counter()
            predicted = clusterer.fit_predict(catchall_inputs)
            runtime = time.perf_counter() - start
            runs.append(
                CandidateRun(
                    candidate=clusterer.name,
                    richness=richness,
                    arm=arm,
                    n_input_events=len(catchall_inputs),
                    runtime_seconds=runtime,
                    strata=(
                        StratumResult(
                            stratum=CATCHALL_STRATUM,
                            metrics=compute_metrics(catchall_true, predicted),
                            noise_handling=compute_noise_handling(catchall_outlier, predicted),
                        ),
                    ),
                )
            )
    return runs


def run_bakeoff(
    seed: int = DEFAULT_SEED,
    n_events: int = DEFAULT_N_EVENTS,
    richness_levels: Sequence[int] = SUPPORTED_VARIANT_RICHNESS_LEVELS,
    reason_records: list[ReasonRecord] | None = None,
) -> BakeoffReport:
    """Run the full Phase 2 clustering bake-off.

    Args:
        seed: Corpus seed, reused identically at every richness level.
        n_events: Corpus size, reused identically at every richness level.
        richness_levels: The Axis A levels to sweep.
        reason_records: Pre-parsed reason records, mainly for tests that
            want to avoid re-parsing the vendored spreadsheet on every
            call. Defaults to parsing ``data/razorpay_error_reasons.xlsx``.

    Returns:
        The complete :class:`BakeoffReport`, including the Axis C crossover
        analysis but excluding the noise-handling diagnostic (see
        :func:`run_noise_diagnostic`, run separately since it uses a
        different, subsampled stratum).
    """
    records = reason_records or parse_reason_records(resolve_vendored_path(_REPO_ROOT))
    record_by_reason = _build_reason_record_lookup(records)

    runs: list[CandidateRun] = []
    for richness in richness_levels:
        runs.extend(_run_richness_level(richness, seed, n_events, records, record_by_reason))

    provenance = Provenance(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seed=seed,
        n_events=n_events,
        richness_levels=tuple(richness_levels),
        arms=ARMS,
        command="uv run python -m reflow.eval.clustering",
        library_versions=_library_versions(),
    )
    return BakeoffReport(
        provenance=provenance,
        runs=tuple(runs),
        crossovers=_compute_crossovers(runs),
        noise_diagnostic=(),
    )


def _sample_narrow_stratum_for_noise_diagnostic(
    events: Sequence[PaymentEvent], sample_size: int, seed: int
) -> list[PaymentEvent]:
    """Build a true-outlier-enriched sample of the narrow stratum.

    Every genuine outlier is kept; the remainder of ``sample_size`` is
    filled with a uniform random sample of non-outlier narrow events. This
    deliberately over-represents true outliers relative to their real
    prevalence (36 in 42,445 narrow events at this corpus's default size)
    so that :func:`run_noise_diagnostic`'s recall/precision figures are
    computed over enough true positives to be informative -- precision is
    consequently not representative of true deployment prevalence and must
    be read as such (see the report's provenance notes).

    Args:
        events: The full narrow-stratum event list.
        sample_size: Target sample size, including the kept outliers.
        seed: Seed for the random non-outlier sub-sample.

    Returns:
        A shuffled list of at most ``sample_size`` events, containing
        every outlier in ``events``.

    Note:
        Uses :class:`random.Random`, which ruff's ``S311`` rule flags as
        unsuitable for cryptographic use; suppressed below (``# noqa:
        S311``) because this is a deterministic evaluation sub-sample, not
        a security-sensitive context.
    """
    outliers = [event for event in events if event.is_outlier]
    non_outliers = [event for event in events if not event.is_outlier]
    rng = random.Random(seed)  # noqa: S311
    n_non_outliers = max(0, sample_size - len(outliers))
    sampled_non_outliers = rng.sample(non_outliers, k=min(n_non_outliers, len(non_outliers)))
    sample = [*outliers, *sampled_non_outliers]
    rng.shuffle(sample)
    return sample


def run_noise_diagnostic(
    seed: int = DEFAULT_SEED,
    n_events: int = DEFAULT_N_EVENTS,
    sample_size: int = NOISE_DIAGNOSTIC_SAMPLE_SIZE,
    reason_records: list[ReasonRecord] | None = None,
) -> tuple[NoiseDiagnosticRun, ...]:
    """Run the supplementary, out-of-primary-scope noise-handling diagnostic.

    See module docstring for why the primary bake-off cannot exercise this
    metric and why this diagnostic exists and is reported separately.

    Args:
        seed: Corpus seed.
        n_events: Corpus size.
        sample_size: Target size of the outlier-enriched narrow-stratum
            sample (see :func:`_sample_narrow_stratum_for_noise_diagnostic`).
        reason_records: Pre-parsed reason records, to avoid re-parsing the
            vendored spreadsheet.

    Returns:
        One :class:`NoiseDiagnosticRun` per genuine clusterer (never
        GROUP BY, which cannot express noise at all).
    """
    records = reason_records or parse_reason_records(resolve_vendored_path(_REPO_ROOT))
    events = list(
        generate_corpus(seed=seed, n_events=n_events, reason_records=records, variant_richness=3)
    )
    narrow_events = [event for event in events if event.latent_subcause_id is None]
    sample = _sample_narrow_stratum_for_noise_diagnostic(narrow_events, sample_size, seed)

    inputs = [_cluster_input(event, mask_description(event.description)) for event in sample]
    is_outlier = [event.is_outlier for event in sample]

    results: list[NoiseDiagnosticRun] = []
    for clusterer in _real_clusterers():
        start = time.perf_counter()
        predicted = clusterer.fit_predict(inputs)
        runtime = time.perf_counter() - start
        results.append(
            NoiseDiagnosticRun(
                candidate=clusterer.name,
                n_input_events=len(inputs),
                noise_handling=compute_noise_handling(is_outlier, predicted),
                runtime_seconds=runtime,
            )
        )
    return tuple(results)


def _library_versions() -> dict[str, str]:
    """Look up the installed version of every result-relevant library.

    Returns:
        A mapping from distribution name to installed version string,
        covering the Python interpreter and every library whose behaviour
        materially affects bake-off results.
    """
    distributions = ("scikit-learn", "scipy", "numpy", "drain3")
    versions = {name: importlib.metadata.version(name) for name in distributions}
    versions["python"] = platform.python_version()
    versions["reflow"] = importlib.metadata.version("reflow")
    return versions


def _noise_handling_to_dict(noise_handling: NoiseHandling) -> dict[str, object]:
    """Serialise one :class:`~reflow.eval.metrics.NoiseHandling` to a dict.

    Args:
        noise_handling: The value to serialise.

    Returns:
        Its dataclass fields plus its two computed properties
        (``recall``, ``precision``), which :func:`dataclasses.asdict`
        alone would not include.
    """
    return {
        **asdict(noise_handling),
        "recall": noise_handling.recall,
        "precision": noise_handling.precision,
    }


def _stratum_result_to_dict(result: StratumResult) -> dict[str, object]:
    """Serialise one :class:`StratumResult` to a JSON-safe dict.

    Args:
        result: The result to serialise.

    Returns:
        A nested plain-value dict.
    """
    return {
        "stratum": result.stratum,
        "metrics": asdict(result.metrics),
        "noise_handling": _noise_handling_to_dict(result.noise_handling),
    }


def to_json_dict(report: BakeoffReport) -> dict[str, object]:
    """Serialise a :class:`BakeoffReport` to a JSON-safe nested dict.

    Args:
        report: The report to serialise.

    Returns:
        A plain-value (``str``/``int``/``float``/``bool``/``None``/``list``/``dict``)
        structure suitable for ``json.dumps``.
    """
    return {
        "provenance": asdict(report.provenance),
        "runs": [
            {
                "candidate": run.candidate,
                "richness": run.richness,
                "arm": run.arm,
                "n_input_events": run.n_input_events,
                "runtime_seconds": run.runtime_seconds,
                "strata": [_stratum_result_to_dict(stratum) for stratum in run.strata],
            }
            for run in report.runs
        ],
        "crossovers": [asdict(crossover) for crossover in report.crossovers],
        "noise_diagnostic": [
            {
                "candidate": diagnostic.candidate,
                "n_input_events": diagnostic.n_input_events,
                "runtime_seconds": diagnostic.runtime_seconds,
                "noise_handling": _noise_handling_to_dict(diagnostic.noise_handling),
            }
            for diagnostic in report.noise_diagnostic
        ],
    }


def _format_optional(value: float | None, digits: int = 3) -> str:
    """Format an optional float for a markdown table cell.

    Args:
        value: The value to format, or ``None``.
        digits: Number of decimal places.

    Returns:
        ``"n/a"`` if ``value`` is ``None``, otherwise ``value`` formatted
        to ``digits`` decimal places.
    """
    return "n/a" if value is None else f"{value:.{digits}f}"


def to_markdown(report: BakeoffReport) -> str:
    """Render a human-readable markdown summary of a :class:`BakeoffReport`.

    Args:
        report: The report to render.

    Returns:
        A markdown document: a provenance header, the full per-run results
        table, the Axis C crossover table, and the noise-handling
        diagnostic table.
    """
    lines: list[str] = []
    provenance = report.provenance
    lines.append("# Phase 2 clustering bake-off results")
    lines.append("")
    lines.append(f"- Generated at: {provenance.generated_at}")
    lines.append(f"- Command: `{provenance.command}`")
    lines.append(f"- Seed: {provenance.seed}")
    lines.append(f"- Corpus size: {provenance.n_events}")
    lines.append(f"- Richness levels swept: {list(provenance.richness_levels)}")
    lines.append(f"- Arms swept: {list(provenance.arms)}")
    version_items = sorted(provenance.library_versions.items())
    versions_text = ", ".join(f"{name}={version}" for name, version in version_items)
    lines.append(f"- Library versions: {versions_text}")
    for note in provenance.notes:
        lines.append(f"- Note: {note}")
    lines.append("")

    lines.append("## Results by candidate x richness x arm x stratum")
    lines.append("")
    header = (
        "| candidate | richness | arm | stratum | n | purity | nmi | ari | "
        "pred_clusters | true_clusters | noise_recall | noise_precision | runtime_s |"
    )
    lines.append(header)
    lines.append("|" + " --- |" * 13)
    for run in report.runs:
        for stratum in run.strata:
            metrics = stratum.metrics
            noise = stratum.noise_handling
            lines.append(
                f"| {run.candidate} | {run.richness} | {run.arm} | {stratum.stratum} | "
                f"{metrics.n_events} | {metrics.purity:.3f} | {metrics.nmi:.3f} | "
                f"{metrics.ari:.3f} | {metrics.n_predicted_clusters} | "
                f"{metrics.n_true_clusters} | {_format_optional(noise.recall)} | "
                f"{_format_optional(noise.precision)} | {run.runtime_seconds:.4f} |"
            )
    lines.append("")

    lines.append("## Axis C: catch-all-share crossover vs GROUP BY")
    lines.append("")
    lines.append(
        "| candidate | richness | arm | metric | candidate_catchall | "
        "groupby_catchall | groupby_narrow | crossover_share |"
    )
    lines.append("|" + " --- |" * 8)
    for crossover in report.crossovers:
        crossover_text = (
            "never" if crossover.crossover_share is None else f"{crossover.crossover_share:.3f}"
        )
        lines.append(
            f"| {crossover.candidate} | {crossover.richness} | {crossover.arm} | "
            f"{crossover.metric_name} | {crossover.candidate_catchall_metric:.3f} | "
            f"{crossover.baseline_catchall_metric:.3f} | {crossover.baseline_narrow_metric:.3f} | "
            f"{crossover_text} |"
        )
    lines.append("")

    lines.append("## Supplementary: noise/outlier-handling diagnostic (narrow stratum sample)")
    lines.append("")
    lines.append(
        "| candidate | n | true_outliers | predicted_noise | recall | precision | runtime_s |"
    )
    lines.append("|" + " --- |" * 7)
    for diagnostic in report.noise_diagnostic:
        noise = diagnostic.noise_handling
        lines.append(
            f"| {diagnostic.candidate} | {diagnostic.n_input_events} | "
            f"{noise.n_true_outliers} | {noise.n_predicted_noise} | "
            f"{_format_optional(noise.recall)} | {_format_optional(noise.precision)} | "
            f"{diagnostic.runtime_seconds:.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:  # pragma: no cover
    """Run the full bake-off and write JSON + markdown reports.

    CLI entry point: argument parsing and file writing are glue code, not
    core logic, so this function is excluded from the coverage floor per
    :mod:`CLAUDE.md`'s CLI-glue carve-out. Writes
    ``docs/reports/phase2_clustering_bakeoff.json`` and
    ``docs/reports/phase2_clustering_bakeoff.md``.
    """
    import argparse
    import dataclasses
    import json

    parser = argparse.ArgumentParser(description="Run the Phase 2 clustering bake-off.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-events", type=int, default=DEFAULT_N_EVENTS)
    parser.add_argument("--output-dir", type=Path, default=_REPO_ROOT / "docs" / "reports")
    args = parser.parse_args()

    report = run_bakeoff(seed=args.seed, n_events=args.n_events)
    diagnostic = run_noise_diagnostic(seed=args.seed, n_events=args.n_events)
    report = BakeoffReport(
        provenance=dataclasses.replace(report.provenance, notes=PROVENANCE_NOTES),
        runs=report.runs,
        crossovers=report.crossovers,
        noise_diagnostic=diagnostic,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase2_clustering_bakeoff.json").write_text(
        json.dumps(to_json_dict(report), indent=2), encoding="utf-8"
    )
    (args.output_dir / "phase2_clustering_bakeoff.md").write_text(
        to_markdown(report), encoding="utf-8"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
