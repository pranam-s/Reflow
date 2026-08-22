"""Tests for reflow.eval.diagnose.

Every test uses :class:`tests.diagnose.factories.FakeJsonCompleter` in
place of a real :class:`reflow.llm.client.LlmClient`, so this module makes
no network calls and needs no credentials -- consistent with
:func:`reflow.eval.diagnose.run_benchmark`'s own design (every LLM-calling
function takes its completer as a parameter for exactly this reason).
"""

import json

import pytest

from reflow.diagnose.models import IncidentDiagnosis
from reflow.eval.diagnose import DiagnosisReport, run_benchmark, to_json_dict, to_markdown
from tests.diagnose.factories import FakeJsonCompleter

_SEED = 20260822
_SMALL_N_EVENTS = 6000


def test_run_benchmark_routes_events_and_bounds_llm_calls() -> None:
    tier2 = FakeJsonCompleter(model_name="fake/tier2", cost_per_call=0.00005)
    judge = FakeJsonCompleter(model_name="fake/judge", cost_per_call=0.00001)

    report = run_benchmark(
        tier2_client=tier2,
        judge_client=judge,
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=3,
        judge_seed=_SEED,
    )

    routing = report.routing
    assert routing.total_events == _SMALL_N_EVENTS
    assert routing.deterministic_events + routing.llm_events == _SMALL_N_EVENTS
    assert routing.deterministic_fraction > 0.5
    assert routing.llm_calls_made == len(routing.escalated_reasons)
    assert routing.llm_calls_made <= 15

    assert len(report.ambiguous_reason_results) == routing.llm_calls_made
    assert {r.reason for r in report.ambiguous_reason_results} == routing.escalated_reasons


def test_run_benchmark_diagnoses_every_detected_incident_exactly_once() -> None:
    tier2 = FakeJsonCompleter()
    judge = FakeJsonCompleter()

    report = run_benchmark(
        tier2_client=tier2,
        judge_client=judge,
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=2,
        judge_seed=_SEED,
    )

    incident_calls = sum(1 for call in tier2.calls if call["response_model"] is IncidentDiagnosis)
    assert incident_calls == len(report.incident_diagnoses)
    assert report.cost.incident_diagnosis_calls == len(report.incident_diagnoses)
    assert report.cost.n_incidents_detected == len(report.incident_diagnoses)
    assert report.cost.n_incidents_diagnosed == len(report.incident_diagnoses)


def test_run_benchmark_max_incident_diagnoses_caps_calls_but_not_the_cost_projection() -> None:
    tier2 = FakeJsonCompleter(cost_per_call=0.0001)
    judge = FakeJsonCompleter()

    uncapped = run_benchmark(
        tier2_client=FakeJsonCompleter(cost_per_call=0.0001),
        judge_client=FakeJsonCompleter(),
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=2,
        judge_seed=_SEED,
    )
    n_detected = uncapped.cost.n_incidents_detected
    assert n_detected > 1

    capped = run_benchmark(
        tier2_client=tier2,
        judge_client=judge,
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=2,
        judge_seed=_SEED,
        max_incident_diagnoses=1,
    )

    assert capped.cost.n_incidents_detected == n_detected
    assert capped.cost.n_incidents_diagnosed == 1
    assert len(capped.incident_diagnoses) == 1
    assert capped.cost.incident_diagnosis_calls == 1
    assert capped.cost.projected_cost_per_100k_events_warm_cache == pytest.approx(
        uncapped.cost.projected_cost_per_100k_events_warm_cache
    )


def test_run_benchmark_reports_progress_when_a_callback_is_given() -> None:
    messages: list[str] = []
    run_benchmark(
        tier2_client=FakeJsonCompleter(),
        judge_client=FakeJsonCompleter(),
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=1,
        judge_seed=_SEED,
        progress=messages.append,
    )
    assert any("Generating corpus" in message for message in messages)
    assert any("Routed" in message for message in messages)
    assert any("incidents; diagnosing" in message for message in messages)
    assert any("judge" in message.lower() for message in messages)


def test_run_benchmark_judges_a_bounded_sample_from_each_category() -> None:
    tier2 = FakeJsonCompleter()
    judge = FakeJsonCompleter(model_name="fake/judge")

    report = run_benchmark(
        tier2_client=tier2,
        judge_client=judge,
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=3,
        judge_seed=_SEED,
    )

    n_reasons = len(report.ambiguous_reason_results)
    n_incidents = len(report.incident_diagnoses)
    expected = min(3, n_reasons) + min(3, n_incidents)
    assert report.judge_summary.n_sampled == expected
    assert len(judge.calls) == expected
    assert report.judge_summary.model == "fake/judge"
    assert 0.0 <= report.judge_summary.disagreement_rate <= 1.0


def test_run_benchmark_flags_a_disagreeing_judge_verdict() -> None:
    from reflow.diagnose.models import JudgeVerdict, JudgeVerdictLabel

    tier2 = FakeJsonCompleter()

    def judge_factory(_response_model: type) -> JudgeVerdict:
        return JudgeVerdict(
            agrees_with_diagnosis=False, verdict=JudgeVerdictLabel.WRONG, concerns="unsupported"
        )

    judge = FakeJsonCompleter(model_name="fake/judge", factory=judge_factory)

    report = run_benchmark(
        tier2_client=tier2,
        judge_client=judge,
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=2,
        judge_seed=_SEED,
    )

    assert report.judge_summary.n_sampled > 0
    assert report.judge_summary.disagreement_rate == 1.0
    assert len(report.judge_summary.wrong_cases) == report.judge_summary.n_sampled


def test_run_benchmark_cost_summary_is_internally_consistent() -> None:
    tier2 = FakeJsonCompleter(cost_per_call=0.00005)
    judge = FakeJsonCompleter(cost_per_call=0.00002)

    report = run_benchmark(
        tier2_client=tier2,
        judge_client=judge,
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=2,
        judge_seed=_SEED,
    )
    cost = report.cost
    assert cost.actual_total_spend == (
        cost.ambiguous_reason_cost + cost.incident_diagnosis_cost + cost.judge_cost
    )
    assert (
        cost.projected_cost_per_100k_events_warm_cache
        <= cost.projected_cost_per_100k_events_cold_cache
    )
    assert cost.ambiguous_reason_calls == len(report.ambiguous_reason_results)


def test_run_benchmark_is_deterministic_for_a_fixed_seed() -> None:
    def make_report() -> DiagnosisReport:
        tier2 = FakeJsonCompleter()
        judge = FakeJsonCompleter()
        return run_benchmark(
            tier2_client=tier2,
            judge_client=judge,
            tier2_model_name="fake/tier2",
            judge_model_name="fake/judge",
            seed=_SEED,
            n_events=_SMALL_N_EVENTS,
            judge_sample_size=2,
            judge_seed=_SEED,
        )

    first = make_report()
    second = make_report()
    assert first.routing.total_events == second.routing.total_events
    assert first.routing.deterministic_events == second.routing.deterministic_events
    assert first.routing.llm_events == second.routing.llm_events
    assert [r.subject_id for r in first.judge_summary.samples] == [
        r.subject_id for r in second.judge_summary.samples
    ]


def test_to_json_dict_serialises_without_error() -> None:
    tier2 = FakeJsonCompleter()
    judge = FakeJsonCompleter()
    report = run_benchmark(
        tier2_client=tier2,
        judge_client=judge,
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=2,
        judge_seed=_SEED,
    )
    payload = json.dumps(to_json_dict(report))
    parsed = json.loads(payload)
    assert parsed["provenance"]["tier2_model"] == "fake/tier2"
    assert parsed["routing"]["total_events"] == _SMALL_N_EVENTS


def test_to_markdown_includes_headline_routing_numbers() -> None:
    tier2 = FakeJsonCompleter()
    judge = FakeJsonCompleter()
    report = run_benchmark(
        tier2_client=tier2,
        judge_client=judge,
        tier2_model_name="fake/tier2",
        judge_model_name="fake/judge",
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        judge_sample_size=2,
        judge_seed=_SEED,
    )
    markdown = to_markdown(report)
    assert "# Phase 4 diagnosis-tier benchmark results" in markdown
    assert "## Routing split (the headline metric)" in markdown
    assert "## LLM-as-a-judge" in markdown
    assert str(report.routing.total_events) in markdown
    assert "fake/tier2" in markdown
    assert "fake/judge" in markdown
