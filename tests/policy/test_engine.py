from datetime import datetime, timedelta

import pytest

from reflow.corpus.events import PaymentEvent
from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisTier, EventDiagnosis
from reflow.incident.aggregate import BUCKET_WIDTH
from reflow.policy.actions import Action
from reflow.policy.config import PolicyConfig
from reflow.policy.decision import LadderTerminalState
from reflow.policy.engine import PolicyEngine, detect_active_incident_indices
from reflow.taxonomy.methods import PaymentMethod
from reflow.taxonomy.remediation import RemediationClass
from tests.policy.factories import make_event

_ORIGIN = datetime(2026, 1, 1, 10, 0, 0)


def _retry_same_diagnosis(reason: str = "payment_timed_out") -> EventDiagnosis:
    return EventDiagnosis(
        reason=reason,
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.RETRY_SAME,
        confidence=Confidence.HIGH,
        rationale=None,
    )


def _customer_fix_diagnosis(reason: str = "incorrect_cvv") -> EventDiagnosis:
    return EventDiagnosis(
        reason=reason,
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.CUSTOMER_FIX,
        confidence=Confidence.HIGH,
        rationale=None,
    )


def test_evaluate_basic_case_reaches_recovery_link_now() -> None:
    engine = PolicyEngine()
    event = make_event(
        error_reason="payment_timed_out",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        amount=100_000,
        attempt_number=1,
    )
    decision = engine.evaluate(event, _retry_same_diagnosis(), in_active_incident=False)
    assert decision.final_action == Action.RECOVERY_LINK_NOW
    assert decision.base_action == Action.RECOVERY_LINK_NOW
    assert decision.candidate_action == Action.RECOVERY_LINK_NOW
    assert decision.ladder_terminal_state == LadderTerminalState.IN_PROGRESS_LINK_NOW
    assert decision.scheduled_delay_seconds is None
    assert decision.disallowed_method is None
    assert all(not evaluation.blocked for evaluation in decision.guardrail_evaluations)
    assert len(decision.guardrail_evaluations) == 7


def test_evaluate_active_incident_overrides_to_wait_bank_recovery() -> None:
    engine = PolicyEngine()
    event = make_event(created_at=datetime(2026, 1, 1, 12, 0, 0))
    decision = engine.evaluate(event, _retry_same_diagnosis(), in_active_incident=True)
    assert decision.final_action == Action.WAIT_BANK_RECOVERY
    assert decision.ladder_terminal_state == LadderTerminalState.WAITING_ON_BANK
    fired = [e for e in decision.guardrail_evaluations if e.blocked]
    assert len(fired) == 1
    assert fired[0].name == "active_incident_suppression"


def test_evaluate_switch_method_records_disallowed_method() -> None:
    engine = PolicyEngine()
    event = make_event(
        method=PaymentMethod.UPI,
        error_reason="collect_on_mcc_blocked",
        attempt_number=1,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    diagnosis = EventDiagnosis(
        reason="collect_on_mcc_blocked",
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.DIFFERENT_METHOD,
        confidence=Confidence.HIGH,
        rationale=None,
    )
    decision = engine.evaluate(event, diagnosis, in_active_incident=False)
    assert decision.final_action == Action.SWITCH_METHOD
    assert decision.disallowed_method == "upi"


def test_evaluate_raises_on_out_of_order_events() -> None:
    engine = PolicyEngine()
    first = make_event(created_at=datetime(2026, 1, 2, 0, 0, 0))
    second = make_event(created_at=datetime(2026, 1, 1, 0, 0, 0))
    engine.evaluate(first, _retry_same_diagnosis(), in_active_incident=False)
    with pytest.raises(ValueError, match="chronological order"):
        engine.evaluate(second, _retry_same_diagnosis(), in_active_incident=False)


def test_cooldown_persists_across_blocked_attempts_for_same_customer() -> None:
    engine = PolicyEngine()
    diagnosis = _customer_fix_diagnosis()
    final_actions = []
    for hour_offset in range(4):
        event = make_event(
            error_reason="incorrect_cvv",
            created_at=_ORIGIN + timedelta(hours=hour_offset),
            order_id=f"order_{hour_offset}",
            customer_id="cust_repeat",
        )
        decision = engine.evaluate(event, diagnosis, in_active_incident=False)
        final_actions.append(decision.final_action)

    assert final_actions[0] == Action.RECOVERY_LINK_NOW
    assert final_actions[1] == Action.NO_ACTION
    assert final_actions[2] == Action.NO_ACTION
    assert final_actions[3] == Action.NO_ACTION


def test_contact_cap_blocks_after_configured_number_of_contacts() -> None:
    config = PolicyConfig(cooldown=timedelta(seconds=0), contact_cap=2)
    engine = PolicyEngine(config=config)
    diagnosis = _customer_fix_diagnosis()
    final_actions = []
    for minute_offset in range(4):
        event = make_event(
            error_reason="incorrect_cvv",
            created_at=_ORIGIN + timedelta(minutes=minute_offset),
            order_id=f"order_{minute_offset}",
            customer_id="cust_repeat",
        )
        decision = engine.evaluate(event, diagnosis, in_active_incident=False)
        final_actions.append(decision.final_action)

    assert final_actions[0] == Action.RECOVERY_LINK_NOW
    assert final_actions[1] == Action.RECOVERY_LINK_NOW
    assert final_actions[2] == Action.NO_ACTION
    assert final_actions[3] == Action.NO_ACTION
    blocked_names = [
        e.name
        for e in engine.evaluate(
            make_event(
                error_reason="incorrect_cvv",
                created_at=_ORIGIN + timedelta(minutes=10),
                order_id="order_x",
                customer_id="cust_repeat",
            ),
            diagnosis,
            in_active_incident=False,
        ).guardrail_evaluations
        if e.blocked
    ]
    assert blocked_names == ["per_customer_contact_cap"]


def test_attempt_cap_gives_up_explicitly() -> None:
    engine = PolicyEngine()
    diagnosis = _retry_same_diagnosis()
    event = make_event(
        error_reason="payment_timed_out",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        attempt_number=5,
    )
    decision = engine.evaluate(event, diagnosis, in_active_incident=False)
    assert decision.final_action == Action.NO_ACTION
    assert decision.ladder_terminal_state == LadderTerminalState.GAVE_UP


def test_reconcile_reason_routes_directly() -> None:
    engine = PolicyEngine()
    diagnosis = EventDiagnosis(
        reason="order_already_paid",
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.MERCHANT_ACTION,
        confidence=Confidence.HIGH,
        rationale=None,
    )
    event = make_event(error_reason="order_already_paid", created_at=datetime(2026, 1, 1, 12, 0, 0))
    decision = engine.evaluate(event, diagnosis, in_active_incident=False)
    assert decision.final_action == Action.RECONCILE
    assert decision.ladder_terminal_state == LadderTerminalState.RECONCILED


def test_quiet_hours_backoff_delay_computed_to_end_of_window() -> None:
    engine = PolicyEngine()
    event = make_event(
        error_reason="payment_timed_out",
        created_at=datetime(2026, 1, 1, 23, 0, 0),
        attempt_number=1,
    )
    decision = engine.evaluate(event, _retry_same_diagnosis(), in_active_incident=False)
    assert decision.final_action == Action.RECOVERY_LINK_BACKOFF
    assert decision.scheduled_delay_seconds == pytest.approx(10 * 3600)


def test_ladder_backoff_delay_scales_with_attempt_number() -> None:
    config = PolicyConfig()
    engine = PolicyEngine(config=config)
    diagnosis = _retry_same_diagnosis("payment_timed_out")
    event = make_event(
        error_reason="payment_timed_out",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        attempt_number=2,
    )
    decision = engine.evaluate(event, diagnosis, in_active_incident=False)
    assert decision.candidate_action == Action.RECOVERY_LINK_BACKOFF
    assert decision.final_action == Action.RECOVERY_LINK_BACKOFF
    assert decision.scheduled_delay_seconds == pytest.approx(
        config.backoff_step.total_seconds() * 2
    )


def _bucket_start(index: int) -> datetime:
    return _ORIGIN + index * BUCKET_WIDTH


def _build_incident_events() -> list[PaymentEvent]:
    events: list[PaymentEvent] = []
    for i in range(10):
        events.append(
            make_event(
                method=PaymentMethod.CARD,
                bank="HDFC Bank",
                created_at=_bucket_start(i) + timedelta(minutes=1),
                error_reason="payment_timed_out",
                customer_id=f"cust_baseline_{i}",
                order_id=f"order_baseline_{i}",
            )
        )
    burst_bucket = 10
    for j in range(20):
        events.append(
            make_event(
                method=PaymentMethod.CARD,
                bank="HDFC Bank",
                created_at=_bucket_start(burst_bucket) + timedelta(seconds=j),
                error_reason="payment_timed_out",
                customer_id=f"cust_burst_{j}",
                order_id=f"order_burst_{j}",
            )
        )
    return events


def test_detect_active_incident_indices_flags_burst_not_baseline() -> None:
    events = _build_incident_events()
    active_indices = detect_active_incident_indices(events)
    assert set(range(10, 30)).issubset(active_indices)
    assert not (set(range(0, 10)) & active_indices)


def test_evaluate_batch_wires_incident_detection_into_final_action() -> None:
    engine = PolicyEngine()
    events = _build_incident_events()
    diagnoses = {"payment_timed_out": _retry_same_diagnosis()}
    decisions = engine.evaluate_batch(events, diagnoses)
    assert len(decisions) == len(events)
    for decision in decisions[:10]:
        assert decision.final_action != Action.WAIT_BANK_RECOVERY
    for decision in decisions[10:]:
        assert decision.final_action == Action.WAIT_BANK_RECOVERY
        assert decision.in_active_incident is True
