"""Tests for reflow.audit.store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reflow.audit.record import to_dict
from reflow.audit.store import AuditTrailWriter, iter_audit_records, verify_chain
from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisTier, EventDiagnosis
from reflow.execute.executor import BoundedExecutor
from reflow.policy.actions import Action
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


def test_append_writes_one_json_line(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    event = make_event()
    decision = make_decision(event=event)
    with AuditTrailWriter.open(path) as writer:
        writer.append(decision=decision, event=event, diagnosis=_diagnosis(), execution=None)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["payment_id"] == event.payment_id
    assert parsed["sequence"] == 0
    assert parsed["prev_hash"] is None


def test_append_chains_sequence_and_prev_hash(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    with AuditTrailWriter.open(path) as writer:
        first_event = make_event(payment_id="pay_a")
        second_event = make_event(payment_id="pay_b")
        first = writer.append(
            decision=make_decision(event=first_event),
            event=first_event,
            diagnosis=_diagnosis(),
            execution=None,
        )
        second = writer.append(
            decision=make_decision(event=second_event),
            event=second_event,
            diagnosis=_diagnosis(),
            execution=None,
        )

    assert first.sequence == 0
    assert second.sequence == 1
    assert second.prev_hash == first.record_hash


def test_open_resumes_an_existing_trail(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    event_a = make_event(payment_id="pay_a")
    with AuditTrailWriter.open(path) as writer:
        first = writer.append(
            decision=make_decision(event=event_a),
            event=event_a,
            diagnosis=_diagnosis(),
            execution=None,
        )

    event_b = make_event(payment_id="pay_b")
    with AuditTrailWriter.open(path) as writer:
        second = writer.append(
            decision=make_decision(event=event_b),
            event=event_b,
            diagnosis=_diagnosis(),
            execution=None,
        )

    assert second.sequence == 1
    assert second.prev_hash == first.record_hash
    records = list(iter_audit_records(path))
    assert [record.payment_id for record in records] == ["pay_a", "pay_b"]


def test_append_never_truncates_existing_content(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    event = make_event()
    with AuditTrailWriter.open(path) as writer:
        writer.append(
            decision=make_decision(event=event), event=event, diagnosis=_diagnosis(), execution=None
        )
    size_after_first = path.stat().st_size

    event_b = make_event(payment_id="pay_second")
    with AuditTrailWriter.open(path) as writer:
        writer.append(
            decision=make_decision(event=event_b),
            event=event_b,
            diagnosis=_diagnosis(),
            execution=None,
        )

    assert path.stat().st_size > size_after_first
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_iter_audit_records_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    event = make_event()
    with AuditTrailWriter.open(path) as writer:
        writer.append(
            decision=make_decision(event=event), event=event, diagnosis=_diagnosis(), execution=None
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")

    records = list(iter_audit_records(path))
    assert len(records) == 1


def test_iter_audit_records_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(iter_audit_records(tmp_path / "missing.jsonl"))


def test_verify_chain_on_a_valid_trail(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    with AuditTrailWriter.open(path) as writer:
        for index in range(5):
            event = make_event(payment_id=f"pay_{index:03d}")
            writer.append(
                decision=make_decision(event=event),
                event=event,
                diagnosis=_diagnosis(),
                execution=None,
            )

    result = verify_chain(path)
    assert result.valid is True
    assert result.n_records == 5
    assert result.first_broken_sequence is None


def test_verify_chain_detects_tampered_content(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    with AuditTrailWriter.open(path) as writer:
        for index in range(3):
            event = make_event(payment_id=f"pay_{index:03d}")
            writer.append(
                decision=make_decision(event=event),
                event=event,
                diagnosis=_diagnosis(),
                execution=None,
            )

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["amount"] = 999_999_999
    lines[1] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(path)
    assert result.valid is False
    assert result.first_broken_sequence == 1
    assert result.detail is not None


def test_verify_chain_detects_a_missing_record(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    with AuditTrailWriter.open(path) as writer:
        for index in range(3):
            event = make_event(payment_id=f"pay_{index:03d}")
            writer.append(
                decision=make_decision(event=event),
                event=event,
                diagnosis=_diagnosis(),
                execution=None,
            )

    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(path)
    assert result.valid is False
    assert result.detail is not None


def test_verify_chain_on_an_empty_trail(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    path.touch()
    result = verify_chain(path)
    assert result.valid is True
    assert result.n_records == 0


def test_append_with_a_populated_execution_record(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    event = make_event()
    decision = make_decision(event=event, final_action=Action.RECOVERY_LINK_NOW)
    execution = BoundedExecutor().execute(decision, event)
    with AuditTrailWriter.open(path) as writer:
        record = writer.append(
            decision=decision, event=event, diagnosis=_diagnosis(), execution=execution
        )
    assert record.execution is not None
    assert record.execution == to_dict(record)["execution"]
