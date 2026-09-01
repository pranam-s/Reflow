"""Tests for reflow.demo.data."""

from __future__ import annotations

from pathlib import Path

import pytest

from reflow.audit.replay import PaymentNotFoundError
from reflow.demo.data import (
    DEFAULT_AUDIT_TRAIL_PATH,
    DEFAULT_PHASE2_REPORT_PATH,
    DEFAULT_PHASE3_REPORT_PATH,
    DEFAULT_PHASE4_REPORT_PATH,
    DEFAULT_PHASE7_EVALUATION_REPORT_PATH,
    PINNED_GUARDRAIL_PAYMENT_ID,
    _find_detector_row,
    _find_run,
    _find_stratum,
    _load_json,
    load_demo_data,
)


def test_default_report_paths_all_exist() -> None:
    assert DEFAULT_PHASE2_REPORT_PATH.exists()
    assert DEFAULT_PHASE3_REPORT_PATH.exists()
    assert DEFAULT_PHASE4_REPORT_PATH.exists()
    assert DEFAULT_PHASE7_EVALUATION_REPORT_PATH.exists()
    assert DEFAULT_AUDIT_TRAIL_PATH.exists()


def test_load_demo_data_against_real_committed_reports() -> None:
    data = load_demo_data()

    assert data.seed == 20260822
    assert data.corpus.n_events == 50000
    assert data.corpus.taxonomy_row_count == 114
    assert data.corpus.distinct_reasons_seen == 110

    assert data.root_cause.narrow_n_true_clusters == 102
    assert data.root_cause.narrow_purity == pytest.approx(1.0)
    assert data.root_cause.catchall_drain3.ari < data.root_cause.catchall_groupby.ari
    assert data.root_cause.catchall_template_hash.ari == pytest.approx(
        data.root_cause.catchall_groupby.ari, abs=0.01
    )

    assert data.incident.poisson_train_f1 == pytest.approx(0.6621621621621622)
    assert data.incident.poisson_test_f1 == pytest.approx(0.64)
    assert 3.7 <= data.incident.groupby_reason_fragments_train_mean < 3.8
    assert 4.6 <= data.incident.groupby_reason_fragments_test_mean < 4.7

    assert data.routing.total_events == 50000
    assert data.routing.deterministic_events == 43028
    assert data.routing.deterministic_fraction == pytest.approx(0.86056)
    assert data.routing.n_escalated_reasons == 15
    assert data.routing.ambiguous_reason_calls == 15
    assert data.routing.incident_diagnosis_calls == 113
    assert data.routing.total_llm_calls == 128

    assert data.results.reflow_money_rupees == pytest.approx(71874179.0)
    assert data.results.reflow_as_fraction_of_notify_all_money == pytest.approx(0.9497)
    assert 0.70 <= data.results.reflow_contacts_as_fraction_of_notify_all < 0.72
    assert data.results.notify_all_once_contacts == 44674

    assert data.limitations.guardrail_blocked_events == 9992
    assert data.limitations.would_have_recovered_events == 1552
    assert data.limitations.orders_never_recovered == 1487

    assert data.guardrail_payment_id == PINNED_GUARDRAIL_PAYMENT_ID
    assert len(data.guardrail_records) == 1
    record = data.guardrail_records[0]
    assert record.payment_id == PINNED_GUARDRAIL_PAYMENT_ID
    assert record.in_active_incident is True
    assert record.final_action == "wait_bank_recovery"
    blocked_names = {
        evaluation["name"] for evaluation in record.guardrail_evaluations if evaluation["blocked"]
    }
    assert "active_incident_suppression" in blocked_names


def test_load_demo_data_raises_for_unknown_pinned_payment_id() -> None:
    with pytest.raises(PaymentNotFoundError):
        load_demo_data(guardrail_payment_id="pay_does_not_exist")


def test_load_demo_data_raises_for_missing_report(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_demo_data(phase2_report_path=tmp_path / "missing.json")


def test_load_json_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _load_json(tmp_path / "missing.json")


def test_find_run_raises_lookuperror_when_no_run_matches() -> None:
    runs = [{"candidate": "groupby_reason", "richness": 1, "arm": "opaque", "strata": []}]

    with pytest.raises(LookupError, match="drain3"):
        _find_run(runs, candidate="drain3", richness=1, arm="opaque")


def test_find_stratum_raises_lookuperror_when_no_stratum_matches() -> None:
    run = {"candidate": "groupby_reason", "strata": [{"stratum": "narrow", "metrics": {}}]}

    with pytest.raises(LookupError, match="catchall"):
        _find_stratum(run, "catchall")


def test_find_detector_row_raises_lookuperror_when_no_row_matches() -> None:
    rows = [{"detector": "fixed_threshold", "split": "train"}]

    with pytest.raises(LookupError, match="poisson_surprise"):
        _find_detector_row(rows, detector="poisson_surprise", split="train")
