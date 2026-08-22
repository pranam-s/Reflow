"""Tests for :mod:`reflow.eval.clustering`."""

import dataclasses
import json
from pathlib import Path

import pytest

from reflow.corpus.reasons import CATCH_ALL_REASONS
from reflow.eval.clustering import (
    CATCHALL_STRATUM,
    NARROW_STRATUM,
    BakeoffReport,
    CandidateRun,
    _compute_crossovers,
    run_bakeoff,
    run_noise_diagnostic,
    to_json_dict,
    to_markdown,
)
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import parse_reason_records

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDS = parse_reason_records(resolve_vendored_path(REPO_ROOT))

_SMALL_N_EVENTS = 6_000
_SMALL_SEED = 4242


@pytest.fixture(scope="module")
def small_report():
    return run_bakeoff(
        seed=_SMALL_SEED,
        n_events=_SMALL_N_EVENTS,
        richness_levels=(1, 3),
        reason_records=RECORDS,
    )


def test_run_bakeoff_covers_every_candidate_richness_and_arm(small_report) -> None:
    seen = {(run.candidate, run.richness, run.arm) for run in small_report.runs}
    candidates = {"groupby_reason", "drain3", "template_hash", "tfidf_hdbscan"}
    for candidate in candidates:
        for richness in (1, 3):
            for arm in ("transparent", "opaque"):
                assert (candidate, richness, arm) in seen


def test_groupby_reason_reports_both_strata(small_report) -> None:
    for run in small_report.runs:
        if run.candidate == "groupby_reason":
            assert run.stratum(CATCHALL_STRATUM) is not None
            assert run.stratum(NARROW_STRATUM) is not None


def test_real_clusterers_report_only_catchall_stratum(small_report) -> None:
    for run in small_report.runs:
        if run.candidate != "groupby_reason":
            assert len(run.strata) == 1
            assert run.strata[0].stratum == CATCHALL_STRATUM


def test_groupby_reason_narrow_purity_is_high(small_report) -> None:
    for run in small_report.runs:
        if run.candidate == "groupby_reason":
            narrow = run.stratum(NARROW_STRATUM)
            assert narrow is not None
            assert narrow.metrics.purity == pytest.approx(1.0)


def test_groupby_reason_is_arm_invariant_on_catchall(small_report) -> None:
    by_key = {
        (run.richness, run.arm): run
        for run in small_report.runs
        if run.candidate == "groupby_reason"
    }
    for richness in (1, 3):
        transparent = by_key[(richness, "transparent")].stratum(CATCHALL_STRATUM)
        opaque = by_key[(richness, "opaque")].stratum(CATCHALL_STRATUM)
        assert transparent is not None
        assert opaque is not None
        assert transparent.metrics.purity == pytest.approx(opaque.metrics.purity)
        assert transparent.metrics.nmi == pytest.approx(opaque.metrics.nmi)


def test_opaque_arm_purity_never_exceeds_transparent_arm_for_real_clusterers(small_report) -> None:
    by_key = {(run.candidate, run.richness, run.arm): run for run in small_report.runs}
    for candidate in ("drain3", "template_hash", "tfidf_hdbscan"):
        for richness in (1, 3):
            transparent = by_key[(candidate, richness, "transparent")].stratum(CATCHALL_STRATUM)
            opaque = by_key[(candidate, richness, "opaque")].stratum(CATCHALL_STRATUM)
            assert transparent is not None
            assert opaque is not None
            assert opaque.metrics.ari <= transparent.metrics.ari + 1e-9


def test_opaque_arm_is_richness_invariant_for_real_clusterers(small_report) -> None:
    by_key = {(run.candidate, run.richness, run.arm): run for run in small_report.runs}
    for candidate in ("template_hash",):
        richness_one = by_key[(candidate, 1, "opaque")].stratum(CATCHALL_STRATUM)
        richness_three = by_key[(candidate, 3, "opaque")].stratum(CATCHALL_STRATUM)
        assert richness_one is not None
        assert richness_three is not None
        assert (
            richness_one.metrics.n_predicted_clusters == richness_three.metrics.n_predicted_clusters
        )


def test_catchall_true_cluster_count_matches_subcause_count(small_report) -> None:
    for run in small_report.runs:
        catchall = run.stratum(CATCHALL_STRATUM)
        if catchall is not None:
            assert catchall.metrics.n_true_clusters <= 4 * len(CATCH_ALL_REASONS)
            assert catchall.metrics.n_true_clusters > 0


def test_crossovers_cover_every_real_candidate_richness_arm_and_metric(small_report) -> None:
    seen = {
        (crossover.candidate, crossover.richness, crossover.arm, crossover.metric_name)
        for crossover in small_report.crossovers
    }
    for candidate in ("drain3", "template_hash", "tfidf_hdbscan"):
        for richness in (1, 3):
            for arm in ("transparent", "opaque"):
                for metric_name in ("purity", "nmi", "ari"):
                    assert (candidate, richness, arm, metric_name) in seen


def test_run_bakeoff_is_deterministic() -> None:
    first = run_bakeoff(seed=99, n_events=2_000, richness_levels=(1,), reason_records=RECORDS)
    second = run_bakeoff(seed=99, n_events=2_000, richness_levels=(1,), reason_records=RECORDS)
    first_metrics = [(run.candidate, run.strata[0].metrics.purity) for run in first.runs]
    second_metrics = [(run.candidate, run.strata[0].metrics.purity) for run in second.runs]
    assert first_metrics == second_metrics


def test_to_json_dict_round_trips_through_json(small_report) -> None:
    payload = to_json_dict(small_report)
    text = json.dumps(payload)
    reloaded = json.loads(text)
    assert reloaded["provenance"]["seed"] == _SMALL_SEED
    assert len(reloaded["runs"]) == len(small_report.runs)
    assert len(reloaded["crossovers"]) == len(small_report.crossovers)


def test_to_markdown_contains_every_section(small_report) -> None:
    markdown = to_markdown(small_report)
    assert "# Phase 2 clustering bake-off results" in markdown
    assert "## Results by candidate x richness x arm x stratum" in markdown
    assert "## Axis C: catch-all-share crossover vs GROUP BY" in markdown
    assert "## Supplementary" in markdown
    assert "groupby_reason" in markdown


def test_run_noise_diagnostic_covers_every_real_candidate() -> None:
    diagnostic = run_noise_diagnostic(
        seed=7, n_events=5_000, sample_size=500, reason_records=RECORDS
    )
    candidates = {result.candidate for result in diagnostic}
    assert candidates == {"drain3", "template_hash", "tfidf_hdbscan"}


def test_run_noise_diagnostic_keeps_every_true_outlier(small_report) -> None:
    diagnostic = run_noise_diagnostic(
        seed=11, n_events=8_000, sample_size=200, reason_records=RECORDS
    )
    for result in diagnostic:
        assert result.noise_handling.n_true_outliers >= 1


def test_run_noise_diagnostic_only_hdbscan_can_recall_a_true_outlier() -> None:
    diagnostic = run_noise_diagnostic(
        seed=11, n_events=8_000, sample_size=300, reason_records=RECORDS
    )
    by_candidate = {result.candidate: result for result in diagnostic}
    assert by_candidate["drain3"].noise_handling.n_predicted_noise == 0
    assert by_candidate["template_hash"].noise_handling.n_predicted_noise == 0


def test_candidate_run_stratum_returns_none_for_a_missing_stratum(small_report) -> None:
    for run in small_report.runs:
        if run.candidate != "groupby_reason":
            assert run.stratum(NARROW_STRATUM) is None


def test_compute_crossovers_skips_a_candidate_run_with_no_matching_baseline(small_report) -> None:
    real_run = next(run for run in small_report.runs if run.candidate == "drain3")
    orphaned_run = CandidateRun(
        candidate=real_run.candidate,
        richness=999,
        arm=real_run.arm,
        n_input_events=real_run.n_input_events,
        runtime_seconds=real_run.runtime_seconds,
        strata=real_run.strata,
    )
    crossovers = _compute_crossovers([orphaned_run])
    assert crossovers == ()


def test_compute_crossovers_skips_a_candidate_run_with_no_catchall_stratum(small_report) -> None:
    groupby_run = next(run for run in small_report.runs if run.candidate == "groupby_reason")
    real_run = next(run for run in small_report.runs if run.candidate == "drain3")
    strataless_run = CandidateRun(
        candidate=real_run.candidate,
        richness=groupby_run.richness,
        arm=groupby_run.arm,
        n_input_events=real_run.n_input_events,
        runtime_seconds=real_run.runtime_seconds,
        strata=(),
    )
    crossovers = _compute_crossovers([groupby_run, strataless_run])
    assert crossovers == ()


def test_compute_crossovers_skips_a_baseline_missing_a_stratum(small_report) -> None:
    real_run = next(run for run in small_report.runs if run.candidate == "drain3")
    incomplete_baseline = CandidateRun(
        candidate="groupby_reason",
        richness=real_run.richness,
        arm=real_run.arm,
        n_input_events=real_run.n_input_events,
        runtime_seconds=real_run.runtime_seconds,
        strata=(real_run.strata[0],),
    )
    crossovers = _compute_crossovers([incomplete_baseline, real_run])
    assert crossovers == ()


def test_to_markdown_renders_provenance_notes_and_noise_diagnostic_rows(small_report) -> None:
    diagnostic = run_noise_diagnostic(
        seed=13, n_events=4_000, sample_size=200, reason_records=RECORDS
    )
    provenance = dataclasses.replace(
        small_report.provenance, notes=("a disclosed subsampling note",)
    )
    annotated_report = BakeoffReport(
        provenance=provenance,
        runs=small_report.runs,
        crossovers=small_report.crossovers,
        noise_diagnostic=diagnostic,
    )
    markdown = to_markdown(annotated_report)
    assert "- Note: a disclosed subsampling note" in markdown
    assert "drain3" in markdown.split("## Supplementary")[1]
