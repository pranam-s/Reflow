"""Tests for reflow.report.data."""

from __future__ import annotations

from pathlib import Path

import pytest

from reflow.report.data import (
    DEFAULT_OUTPUT_PATH,
    DEFAULT_PHASE5_REPORT_PATH,
    DEFAULT_PHASE7_SIMULATION_REPORT_PATH,
    REGENERATE_COMMAND,
    REPORT_GENERATED_ON,
    load_report_data,
)


def test_default_report_paths_exist() -> None:
    assert DEFAULT_PHASE5_REPORT_PATH.exists()
    assert DEFAULT_PHASE7_SIMULATION_REPORT_PATH.exists()


def test_default_output_path_is_under_docs_reports() -> None:
    assert DEFAULT_OUTPUT_PATH.name == "phase8_report.html"
    assert DEFAULT_OUTPUT_PATH.parent.name == "reports"


def test_load_report_data_against_real_committed_reports() -> None:
    data = load_report_data()

    assert data.demo.corpus.n_events == 50000
    assert len(data.policy_outcomes) == 12
    policies = {row.policy for row in data.policy_outcomes}
    assert policies == {"do_nothing", "notify_all", "notify_all_once", "reflow"}
    levels = {row.sensitivity_level for row in data.policy_outcomes}
    assert levels == {"pessimistic", "central", "optimistic"}

    assert len(data.guardrail_fires) == 7
    fire_names = {row.name for row in data.guardrail_fires}
    assert "active_incident_suppression" in fire_names
    assert "per_customer_contact_cap" in fire_names

    assert data.action_distribution.candidate_counts["recovery_link_now"] == 32254
    assert data.action_distribution.final_counts["wait_bank_recovery"] == 7372

    assert data.over_contact_reduction == 9580
    assert data.over_contact_reduction_rate == pytest.approx(0.21370571963951102)

    assert data.generated_on == REPORT_GENERATED_ON
    assert data.regenerate_command == REGENERATE_COMMAND
    assert data.reflow_version == "0.1.0"
    assert data.python_requires == ">=3.11"
    assert "." in data.pydantic_version
    assert "." in data.rich_version


def test_load_report_data_raises_for_missing_phase5_report(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_report_data(phase5_report_path=tmp_path / "missing.json")


def test_load_report_data_raises_for_missing_phase7_simulation_report(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_report_data(phase7_simulation_report_path=tmp_path / "missing.json")


def test_load_report_data_accepts_a_custom_generated_on_date() -> None:
    data = load_report_data(generated_on="2099-01-01")

    assert data.generated_on == "2099-01-01"
