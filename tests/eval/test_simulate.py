"""Tests for reflow.eval.simulate."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from reflow.corpus.events import PaymentEvent
from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisTier, EventDiagnosis
from reflow.eval.simulate import (
    PolicyName,
    PolicyOutcome,
    SimulationReport,
    _band_finding,
    run_closed_loop,
    run_one_policy,
    to_json_dict,
    to_markdown,
)
from reflow.outcome.oracle import SensitivityLevel
from reflow.policy.actions import Action
from reflow.policy.diagnosis_source import MissingAmbiguousDiagnosisError
from reflow.taxonomy.remediation import RemediationClass
from tests.policy.factories import make_event

_SEED = 20260822
_SMALL_N_EVENTS = 4000
_BASE_TIME = datetime(2026, 1, 1, 10, 0, 0)


class _NeverRecovers:
    level = SensitivityLevel.CENTRAL

    def sample_recovery(
        self, payment_id: str, remediation_class: RemediationClass, action: Action
    ) -> bool:
        return False


class _AlwaysRecovers:
    level = SensitivityLevel.CENTRAL

    def sample_recovery(
        self, payment_id: str, remediation_class: RemediationClass, action: Action
    ) -> bool:
        return True


def _diagnosis(reason: str = "payment_timed_out") -> EventDiagnosis:
    return EventDiagnosis(
        reason=reason,
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.RETRY_SAME,
        confidence=Confidence.HIGH,
        rationale=None,
    )


def _chain(order_id: str, n: int, *, spacing: timedelta = timedelta(hours=4)) -> list[PaymentEvent]:
    return [
        make_event(
            order_id=order_id,
            payment_id=f"pay_{order_id}_{i}",
            created_at=_BASE_TIME + spacing * i,
            attempt_number=999,
        )
        for i in range(n)
    ]


def test_reflow_ladder_gives_up_after_attempt_cap_using_self_tracked_history() -> None:
    events = _chain("order_ladder", 6)
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(events, diagnoses, frozenset(), _NeverRecovers(), PolicyName.REFLOW)

    assert outcome.raw_events_processed == 5
    assert outcome.attempts_made == 4
    assert outcome.contacts_sent == 3
    assert outcome.guardrail_prevented_contacts == 1
    assert outcome.orders_recovered == 0
    assert outcome.money_recovered_rupees == 0.0


def test_do_nothing_never_contacts_or_attempts() -> None:
    events = _chain("order_dn", 4)
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(
        events, diagnoses, frozenset(), _NeverRecovers(), PolicyName.DO_NOTHING
    )

    assert outcome.contacts_sent == 0
    assert outcome.attempts_made == 0
    assert outcome.guardrail_prevented_contacts == 0
    assert outcome.raw_events_processed == 4
    assert outcome.orders_recovered == 0


def test_notify_all_contacts_every_outstanding_raw_event() -> None:
    events = _chain("order_na", 4)
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(
        events, diagnoses, frozenset(), _NeverRecovers(), PolicyName.NOTIFY_ALL
    )

    assert outcome.contacts_sent == 4
    assert outcome.attempts_made == 4
    assert outcome.guardrail_prevented_contacts == 0
    assert outcome.raw_events_processed == 4


def test_notify_all_once_contacts_exactly_once_per_order() -> None:
    events = _chain("order_nao", 4)
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(
        events, diagnoses, frozenset(), _NeverRecovers(), PolicyName.NOTIFY_ALL_ONCE
    )

    assert outcome.contacts_sent == 1
    assert outcome.attempts_made == 1
    assert outcome.raw_events_processed == 4


def test_recovery_stops_further_processing_of_the_same_order() -> None:
    events = _chain("order_rec", 5)
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(
        events, diagnoses, frozenset(), _AlwaysRecovers(), PolicyName.NOTIFY_ALL
    )

    assert outcome.raw_events_processed == 1
    assert outcome.orders_recovered == 1
    assert outcome.orders_total == 1
    assert outcome.contacts_sent == 1
    assert outcome.money_recovered_paise == events[0].amount


def test_contacts_per_rupee_is_none_when_nothing_recovered() -> None:
    events = _chain("order_zero", 1)
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(
        events, diagnoses, frozenset(), _NeverRecovers(), PolicyName.NOTIFY_ALL
    )

    assert outcome.money_recovered_rupees == 0.0
    assert outcome.contacts_per_rupee_recovered is None


def test_contacts_per_rupee_recovered_matches_the_stated_formula() -> None:
    events = [
        make_event(
            order_id="order_rupee",
            payment_id="pay_rupee_0",
            created_at=_BASE_TIME,
            amount=20_000,
        )
    ]
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(
        events, diagnoses, frozenset(), _AlwaysRecovers(), PolicyName.NOTIFY_ALL
    )

    assert outcome.money_recovered_rupees == pytest.approx(200.0)
    assert outcome.contacts_per_rupee_recovered == pytest.approx(1 / 200.0)


def test_distinct_orders_are_tracked_independently() -> None:
    events = _chain("order_a", 2) + _chain("order_b", 2)
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(
        events, diagnoses, frozenset(), _NeverRecovers(), PolicyName.NOTIFY_ALL
    )

    assert outcome.orders_total == 2
    assert outcome.raw_events_processed == 4


def test_active_incident_suppresses_reflow_contact_and_counts_as_prevented() -> None:
    events = _chain("order_incident", 1)
    diagnoses = {"payment_timed_out": _diagnosis()}

    outcome = run_one_policy(events, diagnoses, frozenset({0}), _NeverRecovers(), PolicyName.REFLOW)

    assert outcome.contacts_sent == 0
    assert outcome.guardrail_prevented_contacts == 1


def _outcome(policy: PolicyName, *, contacts_per_rupee: float | None) -> PolicyOutcome:
    return PolicyOutcome(
        policy=policy.value,
        sensitivity_level=SensitivityLevel.CENTRAL.value,
        orders_total=10,
        orders_recovered=0 if contacts_per_rupee is None else 5,
        recovery_rate=0.0 if contacts_per_rupee is None else 0.5,
        money_recovered_paise=0 if contacts_per_rupee is None else 1000,
        money_recovered_rupees=0.0 if contacts_per_rupee is None else 10.0,
        contacts_sent=0,
        attempts_made=0,
        guardrail_prevented_contacts=0,
        contacts_per_rupee_recovered=contacts_per_rupee,
        raw_events_processed=10,
        raw_events_total=10,
    )


def test_band_finding_treats_two_never_recovering_policies_as_equally_cheap() -> None:
    outcomes = {
        PolicyName.REFLOW.value: _outcome(PolicyName.REFLOW, contacts_per_rupee=None),
        PolicyName.DO_NOTHING.value: _outcome(PolicyName.DO_NOTHING, contacts_per_rupee=None),
        PolicyName.NOTIFY_ALL.value: _outcome(PolicyName.NOTIFY_ALL, contacts_per_rupee=None),
        PolicyName.NOTIFY_ALL_ONCE.value: _outcome(
            PolicyName.NOTIFY_ALL_ONCE, contacts_per_rupee=None
        ),
    }
    finding = _band_finding(outcomes, SensitivityLevel.CENTRAL.value)
    assert finding.reflow_is_cheaper_per_rupee_than_notify_all is True
    assert finding.reflow_is_cheaper_per_rupee_than_notify_all_once is True


def test_band_finding_prefers_reflow_when_only_the_baseline_recovers_nothing() -> None:
    outcomes = {
        PolicyName.REFLOW.value: _outcome(PolicyName.REFLOW, contacts_per_rupee=0.5),
        PolicyName.DO_NOTHING.value: _outcome(PolicyName.DO_NOTHING, contacts_per_rupee=None),
        PolicyName.NOTIFY_ALL.value: _outcome(PolicyName.NOTIFY_ALL, contacts_per_rupee=None),
        PolicyName.NOTIFY_ALL_ONCE.value: _outcome(
            PolicyName.NOTIFY_ALL_ONCE, contacts_per_rupee=None
        ),
    }
    finding = _band_finding(outcomes, SensitivityLevel.CENTRAL.value)
    assert finding.reflow_is_cheaper_per_rupee_than_notify_all is True
    assert finding.reflow_is_cheaper_per_rupee_than_notify_all_once is True


def test_run_closed_loop_produces_one_outcome_per_level_and_policy() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    assert len(report.outcomes) == len(SensitivityLevel) * len(PolicyName)
    seen = {(o.sensitivity_level, o.policy) for o in report.outcomes}
    assert len(seen) == len(report.outcomes)


def test_run_closed_loop_do_nothing_never_contacts_at_any_level() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    for outcome in report.outcomes:
        if outcome.policy == PolicyName.DO_NOTHING.value:
            assert outcome.contacts_sent == 0
            assert outcome.attempts_made == 0
            assert outcome.guardrail_prevented_contacts == 0


def test_run_closed_loop_notify_all_once_contacts_every_order_exactly_once() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    for outcome in report.outcomes:
        if outcome.policy == PolicyName.NOTIFY_ALL_ONCE.value:
            assert outcome.contacts_sent == outcome.orders_total


def test_run_closed_loop_baselines_never_report_guardrail_prevented_contacts() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    for outcome in report.outcomes:
        if outcome.policy != PolicyName.REFLOW.value:
            assert outcome.guardrail_prevented_contacts == 0


def test_run_closed_loop_reflow_recovers_more_than_do_nothing_at_every_level() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    for finding in report.band_findings:
        assert finding.reflow_beats_do_nothing is True


def test_run_closed_loop_reflow_is_cheaper_per_rupee_than_both_notify_baselines() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    for finding in report.band_findings:
        assert finding.reflow_is_cheaper_per_rupee_than_notify_all is True
        assert finding.reflow_is_cheaper_per_rupee_than_notify_all_once is True


def test_run_closed_loop_orders_total_is_identical_across_every_policy_and_level() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    totals = {outcome.orders_total for outcome in report.outcomes}
    assert len(totals) == 1


def test_run_closed_loop_raises_when_phase4_report_is_missing_an_escalated_reason(
    tmp_path: Path,
) -> None:
    incomplete_report = tmp_path / "incomplete_phase4.json"
    incomplete_report.write_text(json.dumps({"ambiguous_reason_results": []}), encoding="utf-8")
    with pytest.raises(MissingAmbiguousDiagnosisError):
        run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS, phase4_report_path=incomplete_report)


def test_to_json_dict_round_trips_through_json() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    payload = json.dumps(to_json_dict(report))
    reloaded = json.loads(payload)
    assert reloaded["provenance"]["seed"] == _SEED
    assert len(reloaded["outcomes"]) == len(report.outcomes)


def test_to_markdown_contains_expected_sections() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    markdown = to_markdown(report)
    assert "# Phase 7 closed-loop simulation results" in markdown
    assert "## Sensitivity level: central" in markdown
    assert "## Sensitivity-band findings" in markdown
    assert "seeded oracle" in markdown


def test_simulation_report_is_a_dataclass_instance() -> None:
    report = run_closed_loop(seed=_SEED, n_events=_SMALL_N_EVENTS)
    assert isinstance(report, SimulationReport)
