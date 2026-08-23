"""Tests for reflow.cli."""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from reflow.audit.store import AuditTrailWriter
from reflow.cli import _build_parser, execute_command, replay_command
from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisTier, EventDiagnosis
from reflow.taxonomy.remediation import RemediationClass
from tests.execute.factories import make_decision, make_event

_SEED = 20260822
_SMALL_N_EVENTS = 500


def _console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, width=120), buffer


def test_execute_subcommand_writes_reports_and_summary(tmp_path: Path) -> None:
    parser = _build_parser()
    audit_path = tmp_path / "trail.jsonl"
    output_dir = tmp_path / "reports"
    args = parser.parse_args(
        [
            "execute",
            "--seed",
            str(_SEED),
            "--n-events",
            str(_SMALL_N_EVENTS),
            "--audit-path",
            str(audit_path),
            "--audit-sample-size",
            "20",
            "--output-dir",
            str(output_dir),
        ]
    )
    console, buffer = _console()

    exit_code = execute_command(args, console=console)

    assert exit_code == 0
    assert audit_path.exists()
    assert (output_dir / "phase6_execution.json").exists()
    assert (output_dir / "phase6_execution.md").exists()
    assert "Evaluated" in buffer.getvalue()


def test_execute_subcommand_without_output_dir_skips_report_files(tmp_path: Path) -> None:
    parser = _build_parser()
    audit_path = tmp_path / "trail.jsonl"
    args = parser.parse_args(
        [
            "execute",
            "--n-events",
            str(_SMALL_N_EVENTS),
            "--audit-path",
            str(audit_path),
        ]
    )
    console, _buffer = _console()

    exit_code = execute_command(args, console=console)

    assert exit_code == 0
    assert audit_path.exists()


def test_replay_subcommand_renders_a_known_payment(tmp_path: Path) -> None:
    audit_path = tmp_path / "trail.jsonl"
    event = make_event(payment_id="pay_cli_target")
    decision = make_decision(event=event)
    diagnosis = EventDiagnosis(
        reason=event.error_reason,
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.RETRY_SAME,
        confidence=Confidence.HIGH,
        rationale=None,
    )
    with AuditTrailWriter.open(audit_path) as writer:
        writer.append(decision=decision, event=event, diagnosis=diagnosis, execution=None)

    parser = _build_parser()
    args = parser.parse_args(["replay", "pay_cli_target", "--audit-path", str(audit_path)])
    console, buffer = _console()

    exit_code = replay_command(args, console=console)

    assert exit_code == 0
    assert "pay_cli_target" in buffer.getvalue()


def test_replay_subcommand_reports_missing_payment(tmp_path: Path) -> None:
    audit_path = tmp_path / "trail.jsonl"
    event = make_event(payment_id="pay_present")
    with AuditTrailWriter.open(audit_path) as writer:
        writer.append(
            decision=make_decision(event=event),
            event=event,
            diagnosis=EventDiagnosis(
                reason=event.error_reason,
                tier=DiagnosisTier.DETERMINISTIC,
                remediation_class=RemediationClass.RETRY_SAME,
                confidence=Confidence.HIGH,
                rationale=None,
            ),
            execution=None,
        )

    parser = _build_parser()
    args = parser.parse_args(["replay", "pay_absent", "--audit-path", str(audit_path)])
    console, buffer = _console()

    exit_code = replay_command(args, console=console)

    assert exit_code == 1
    assert "Error" in buffer.getvalue()


def test_replay_subcommand_reports_missing_audit_trail(tmp_path: Path) -> None:
    parser = _build_parser()
    args = parser.parse_args(["replay", "pay_x", "--audit-path", str(tmp_path / "missing.jsonl")])
    console, buffer = _console()

    exit_code = replay_command(args, console=console)

    assert exit_code == 1
    output = buffer.getvalue()
    assert "no audit trail found" in output
    assert "execute" in output
