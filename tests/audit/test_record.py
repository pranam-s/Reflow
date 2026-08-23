"""Tests for reflow.audit.record."""

from __future__ import annotations

from dataclasses import replace

from reflow.audit.record import (
    build_audit_record,
    compute_record_hash,
    record_from_dict,
    record_payload_without_hash,
    to_dict,
)
from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisTier, EventDiagnosis
from reflow.execute.executor import BoundedExecutor
from reflow.policy.actions import Action
from reflow.policy.guardrails import GuardrailEvaluation
from reflow.taxonomy.remediation import RemediationClass
from tests.execute.factories import make_decision, make_event

_RECORDED_AT = "2026-01-01T00:00:00+00:00"


def _diagnosis(reason: str = "payment_timed_out", rationale: str | None = None) -> EventDiagnosis:
    return EventDiagnosis(
        reason=reason,
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.RETRY_SAME,
        confidence=Confidence.HIGH,
        rationale=rationale,
    )


def test_build_audit_record_captures_the_error_group() -> None:
    event = make_event(error_reason="payment_timed_out")
    decision = make_decision(event=event, final_action=Action.RECOVERY_LINK_NOW)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at=_RECORDED_AT,
    )
    assert record.error_code == event.error_code.value
    assert record.error_source == event.error_source.value
    assert record.error_step == event.error_step.value
    assert record.error_reason == "payment_timed_out"


def test_build_audit_record_captures_diagnosis_rationale() -> None:
    event = make_event()
    decision = make_decision(event=event, diagnosis_tier="llm", diagnosis_confidence="medium")
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(rationale="because the vendored text says so"),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at=_RECORDED_AT,
    )
    assert record.diagnosis_tier == "llm"
    assert record.diagnosis_confidence == "medium"
    assert record.diagnosis_rationale == "because the vendored text says so"


def test_build_audit_record_captures_every_guardrail_evaluation_pass_and_block() -> None:
    event = make_event()
    guardrail_evaluations = (
        GuardrailEvaluation(
            name="terminal_reason_blocklist",
            blocked=False,
            action_before=Action.RECOVERY_LINK_NOW,
            action_after=Action.RECOVERY_LINK_NOW,
            reason="not a duplicate reason.",
        ),
        GuardrailEvaluation(
            name="active_incident_suppression",
            blocked=True,
            action_before=Action.RECOVERY_LINK_NOW,
            action_after=Action.WAIT_BANK_RECOVERY,
            reason="an incident is active.",
        ),
    )
    decision = replace(
        make_decision(event=event, final_action=Action.WAIT_BANK_RECOVERY, in_active_incident=True),
        guardrail_evaluations=guardrail_evaluations,
    )
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at=_RECORDED_AT,
    )
    assert len(record.guardrail_evaluations) == 2
    passed = record.guardrail_evaluations[0]
    blocked = record.guardrail_evaluations[1]
    assert passed["blocked"] is False
    assert blocked["blocked"] is True
    assert blocked["name"] == "active_incident_suppression"
    assert record.in_active_incident is True


def test_build_audit_record_serialises_an_execution_record() -> None:
    event = make_event()
    decision = make_decision(event=event, final_action=Action.RECOVERY_LINK_NOW)
    execution = BoundedExecutor().execute(decision, event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=execution,
        sequence=0,
        prev_hash=None,
        recorded_at=_RECORDED_AT,
    )
    assert record.execution is not None
    assert record.execution["outcome"] == "dry_run"


def test_build_audit_record_with_no_execution_serialises_to_none() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at=_RECORDED_AT,
    )
    assert record.execution is None


def test_first_record_has_no_prev_hash() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at=_RECORDED_AT,
    )
    assert record.prev_hash is None
    assert record.record_hash


def test_record_hash_changes_when_prev_hash_changes() -> None:
    event = make_event()
    decision = make_decision(event=event)
    first = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=1,
        prev_hash="aaa",
        recorded_at=_RECORDED_AT,
    )
    second = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=1,
        prev_hash="bbb",
        recorded_at=_RECORDED_AT,
    )
    assert first.record_hash != second.record_hash


def test_compute_record_hash_is_deterministic() -> None:
    payload = {"a": 1, "b": [1, 2, 3]}
    assert compute_record_hash("prev", payload) == compute_record_hash("prev", payload)
    assert compute_record_hash("prev", payload) != compute_record_hash(None, payload)


def test_to_dict_and_record_from_dict_round_trip() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=5,
        prev_hash="deadbeef",
        recorded_at=_RECORDED_AT,
    )
    round_tripped = record_from_dict(to_dict(record))
    assert round_tripped == record


def test_record_payload_without_hash_reproduces_the_hashed_payload() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=2,
        prev_hash="cafebabe",
        recorded_at=_RECORDED_AT,
    )
    payload = record_payload_without_hash(record)
    assert compute_record_hash(record.prev_hash, payload) == record.record_hash


def test_build_audit_record_defaults_recorded_at_to_now() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
    )
    assert record.recorded_at
