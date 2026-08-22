import json
from pathlib import Path

import pytest

from reflow.eval.policy import run_benchmark, to_json_dict, to_markdown
from reflow.policy.actions import CHASE_ACTIONS, Action
from reflow.policy.diagnosis_source import MissingAmbiguousDiagnosisError

_SEED = 20260822
_SMALL_N_EVENTS = 4000


def test_run_benchmark_action_distribution_covers_the_closed_set() -> None:
    report = run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS)
    expected_keys = {action.value for action in Action}
    assert set(report.action_distribution.final_counts) == expected_keys
    assert set(report.action_distribution.candidate_counts) == expected_keys
    assert sum(report.action_distribution.final_counts.values()) == _SMALL_N_EVENTS
    assert sum(report.action_distribution.candidate_counts.values()) == _SMALL_N_EVENTS
    assert report.n_events == _SMALL_N_EVENTS


def test_run_benchmark_guardrail_fired_plus_passed_equals_total_events() -> None:
    report = run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS)
    assert len(report.guardrail_fires) == 7
    for summary in report.guardrail_fires:
        assert summary.fired + summary.passed == _SMALL_N_EVENTS


def test_run_benchmark_over_contact_reduction_matches_action_distribution() -> None:
    report = run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS)
    chase_values = {action.value for action in CHASE_ACTIONS}
    expected_without = sum(
        count
        for action, count in report.action_distribution.candidate_counts.items()
        if action in chase_values
    )
    expected_with = sum(
        count
        for action, count in report.action_distribution.final_counts.items()
        if action in chase_values
    )
    assert report.over_contact.contacts_without_guardrails == expected_without
    assert report.over_contact.contacts_with_guardrails == expected_with
    assert report.over_contact.reduction == expected_without - expected_with
    assert (
        report.over_contact.contacts_without_guardrails
        >= report.over_contact.contacts_with_guardrails
    )


def test_run_benchmark_wait_bank_recovery_count_matches_final_distribution() -> None:
    report = run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS)
    assert (
        report.wait_bank_recovery_count
        == report.action_distribution.final_counts[Action.WAIT_BANK_RECOVERY.value]
    )


def test_run_benchmark_ladder_terminal_distribution_sums_to_total() -> None:
    report = run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS)
    assert sum(report.ladder_terminal_distribution.values()) == _SMALL_N_EVENTS


def test_run_benchmark_example_decisions_are_non_empty_and_serialisable() -> None:
    report = run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS)
    assert len(report.example_decisions) > 0
    for example in report.example_decisions:
        assert "final_action" in example
        assert "justification" in example


def test_to_json_dict_round_trips_through_json() -> None:
    report = run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS)
    payload = to_json_dict(report)
    serialized = json.dumps(payload)
    reloaded = json.loads(serialized)
    assert reloaded["n_events"] == _SMALL_N_EVENTS
    assert reloaded["provenance"]["seed"] == _SEED


def test_to_markdown_contains_expected_sections() -> None:
    report = run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS)
    markdown = to_markdown(report)
    assert "# Phase 5 policy-engine benchmark results" in markdown
    assert "## Action distribution across the closed set" in markdown
    assert "## Guardrail fire counts" in markdown
    assert "## Over-contact reduction" in markdown
    assert "## Escalation ladder terminal-state distribution" in markdown
    assert "## Example decisions" in markdown


def test_run_benchmark_raises_when_phase4_report_is_missing_an_escalated_reason(
    tmp_path: Path,
) -> None:
    incomplete_report = tmp_path / "incomplete_phase4.json"
    incomplete_report.write_text(json.dumps({"ambiguous_reason_results": []}), encoding="utf-8")
    with pytest.raises(MissingAmbiguousDiagnosisError):
        run_benchmark(seed=_SEED, n_events=_SMALL_N_EVENTS, phase4_report_path=incomplete_report)
