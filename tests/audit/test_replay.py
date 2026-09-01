"""Tests for reflow.audit.replay."""

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest
from rich.console import Console

from reflow.audit.record import AuditRecord, build_audit_record
from reflow.audit.replay import PaymentNotFoundError, find_records_for_payment, render_replay
from reflow.audit.store import AuditTrailWriter
from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisTier, EventDiagnosis
from reflow.execute.executor import BoundedExecutor
from reflow.execute.models import ExecutionOutcome, ExecutionRecord
from reflow.policy.actions import Action
from reflow.policy.guardrails import GuardrailEvaluation
from reflow.taxonomy.remediation import RemediationClass
from tests.execute.factories import make_decision, make_event


def _diagnosis(reason: str = "payment_timed_out") -> EventDiagnosis:
    return EventDiagnosis(
        reason=reason,
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.RETRY_SAME,
        confidence=Confidence.HIGH,
        rationale=None,
    )


def _render_to_text(records: list[AuditRecord]) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=120)
    render_replay(console, records)
    return buffer.getvalue()


def test_find_records_for_payment_returns_matches(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    event = make_event(payment_id="pay_target")
    other = make_event(payment_id="pay_other")
    with AuditTrailWriter.open(path) as writer:
        writer.append(
            decision=make_decision(event=other), event=other, diagnosis=_diagnosis(), execution=None
        )
        writer.append(
            decision=make_decision(event=event), event=event, diagnosis=_diagnosis(), execution=None
        )

    records = find_records_for_payment(path, "pay_target")
    assert len(records) == 1
    assert records[0].payment_id == "pay_target"


def test_find_records_for_payment_raises_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    event = make_event(payment_id="pay_other")
    with AuditTrailWriter.open(path) as writer:
        writer.append(
            decision=make_decision(event=event), event=event, diagnosis=_diagnosis(), execution=None
        )

    with pytest.raises(PaymentNotFoundError):
        find_records_for_payment(path, "pay_missing")


def test_find_records_for_payment_propagates_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_records_for_payment(tmp_path / "missing.jsonl", "pay_x")


def test_render_replay_pure_ascii_output_and_guardrail_block_shown() -> None:
    event = make_event(payment_id="pay_incident_case", bank="HDFC Bank")
    guardrail_evaluations = (
        GuardrailEvaluation(
            name="terminal_reason_blocklist",
            blocked=False,
            action_before=Action.RECOVERY_LINK_NOW,
            action_after=Action.RECOVERY_LINK_NOW,
            reason="error_reason is not on the terminal/reconcile blocklist.",
        ),
        GuardrailEvaluation(
            name="active_incident_suppression",
            blocked=True,
            action_before=Action.RECOVERY_LINK_NOW,
            action_after=Action.WAIT_BANK_RECOVERY,
            reason="poisson_surprise detected an active incident on this (method, bank).",
        ),
    )
    decision = replace(
        make_decision(
            event=event,
            final_action=Action.WAIT_BANK_RECOVERY,
            candidate_action=Action.RECOVERY_LINK_NOW,
            in_active_incident=True,
        ),
        guardrail_evaluations=guardrail_evaluations,
    )
    execution = BoundedExecutor().execute(decision, event)

    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=execution,
        sequence=0,
        prev_hash=None,
        recorded_at="2026-01-01T00:00:00+00:00",
    )

    text = _render_to_text([record])

    text.encode("ascii")
    assert "pay_incident_case" in text
    assert "BLOCKED" in text
    assert "active_incident_suppression" in text
    assert "wait_bank_recovery" in text
    assert "PASSED" in text
    assert "NO_OP" in text


def test_render_replay_multiple_records_labels_each(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    event = make_event(payment_id="pay_multi")
    with AuditTrailWriter.open(path) as writer:
        writer.append(
            decision=make_decision(event=event), event=event, diagnosis=_diagnosis(), execution=None
        )
        writer.append(
            decision=make_decision(event=event), event=event, diagnosis=_diagnosis(), execution=None
        )

    records = find_records_for_payment(path, "pay_multi")
    text = _render_to_text(records)
    assert "record 1 of 2" in text
    assert "record 2 of 2" in text


def test_render_replay_reports_no_execution_record() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    text = _render_to_text([record])
    assert "no execution record" in text


def test_render_replay_shows_a_fully_populated_executed_outcome() -> None:
    event = make_event()
    decision = make_decision(event=event, final_action=Action.RECOVERY_LINK_NOW)
    execution = ExecutionRecord(
        outcome=ExecutionOutcome.EXECUTED,
        action=Action.RECOVERY_LINK_NOW,
        dry_run=False,
        reference_id="reflow_abc123",
        request={"amount": 100},
        request_headers={"Authorization": "[REDACTED]"},
        response={"id": "plink_abc", "short_url": "https://rzp.io/i/abc"},
        short_url="https://rzp.io/i/abc",
        payment_link_id="plink_abc",
        http_status=200,
        latency_ms=42.5,
        retry_count=1,
        idempotent_replay=False,
        error_message=None,
        error_detail=None,
        note="a free-text note",
    )
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=execution,
        sequence=0,
        prev_hash=None,
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    text = _render_to_text([record])
    assert "https://rzp.io/i/abc" in text
    assert "plink_abc" in text
    assert "200" in text
    assert "42.5 ms" in text
    assert "a free-text note" in text


def test_render_replay_defaults_to_plain_numbering_one_through_six() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    text = _render_to_text([record])
    assert "1. Payment" in text
    assert "6. Execution outcome" in text


def test_render_replay_accepts_sublettered_section_numbers() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    buffer = io.StringIO()
    console = Console(file=buffer, width=120)
    render_replay(console, [record], section_numbers=("5a", "5b", "5c", "5d", "5e", "5f"))
    text = buffer.getvalue()
    assert "5a. Payment" in text
    assert "5f. Execution outcome" in text
    assert "1. Payment" not in text


def test_render_replay_rejects_wrong_length_section_numbers() -> None:
    event = make_event()
    decision = make_decision(event=event)
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    buffer = io.StringIO()
    console = Console(file=buffer, width=120)
    with pytest.raises(ValueError, match="exactly 6"):
        render_replay(console, [record], section_numbers=("1", "2"))


def test_render_replay_shows_a_failed_outcome_error_message() -> None:
    event = make_event()
    decision = make_decision(event=event, final_action=Action.RECOVERY_LINK_NOW)
    execution = ExecutionRecord(
        outcome=ExecutionOutcome.FAILED,
        action=Action.RECOVERY_LINK_NOW,
        dry_run=False,
        reference_id="reflow_abc123",
        request={"amount": 100},
        request_headers={},
        response=None,
        short_url=None,
        payment_link_id=None,
        http_status=400,
        latency_ms=None,
        retry_count=0,
        idempotent_replay=False,
        error_message="amount is required",
        error_detail={"error": {"description": "amount is required"}},
        note=None,
    )
    record = build_audit_record(
        decision=decision,
        event=event,
        diagnosis=_diagnosis(),
        execution=execution,
        sequence=0,
        prev_hash=None,
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    text = _render_to_text([record])
    assert "amount is required" in text
