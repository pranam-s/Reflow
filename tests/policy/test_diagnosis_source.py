import json
from pathlib import Path

import pytest

from reflow.diagnose.router import DiagnosisTier
from reflow.diagnose.tier1 import DeterministicTable
from reflow.policy.diagnosis_source import (
    AmbiguousDiagnosisRecord,
    MissingAmbiguousDiagnosisError,
    build_offline_diagnoses,
    diagnose_reason,
    load_ambiguous_diagnosis_records,
)
from reflow.taxonomy.remediation import RemediationClass


def _write_report(path: Path, entries: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"ambiguous_reason_results": entries}), encoding="utf-8")


def test_load_ambiguous_diagnosis_records(tmp_path: Path) -> None:
    report_path = tmp_path / "phase4_diagnosis.json"
    _write_report(
        report_path,
        [
            {
                "reason": "server_error",
                "remediation_class": "wait",
                "confidence": "high",
                "rationale": "vendored text says wait or contact razorpay.",
            }
        ],
    )
    records = load_ambiguous_diagnosis_records(report_path)
    assert records["server_error"] == AmbiguousDiagnosisRecord(
        reason="server_error",
        remediation_class="wait",
        confidence="high",
        rationale="vendored text says wait or contact razorpay.",
    )


def test_build_offline_diagnoses_merges_deterministic_and_ambiguous() -> None:
    table = DeterministicTable(
        deterministic={"payment_timed_out": RemediationClass.RETRY_SAME},
        escalated={"server_error": ()},
    )
    ambiguous_records = {
        "server_error": AmbiguousDiagnosisRecord(
            reason="server_error",
            remediation_class="wait",
            confidence="high",
            rationale="rationale text",
        )
    }
    diagnoses = build_offline_diagnoses(table, ambiguous_records)

    deterministic_diagnosis = diagnoses["payment_timed_out"]
    assert deterministic_diagnosis.tier is DiagnosisTier.DETERMINISTIC
    assert deterministic_diagnosis.remediation_class is RemediationClass.RETRY_SAME
    assert deterministic_diagnosis.rationale is None

    llm_diagnosis = diagnoses["server_error"]
    assert llm_diagnosis.tier is DiagnosisTier.LLM
    assert llm_diagnosis.remediation_class is RemediationClass.WAIT
    assert llm_diagnosis.rationale == "rationale text"

    assert diagnose_reason("server_error", diagnoses) is llm_diagnosis


def test_build_offline_diagnoses_raises_when_escalated_reason_missing() -> None:
    table = DeterministicTable(
        deterministic={},
        escalated={"some_ambiguous_reason": ()},
    )
    with pytest.raises(MissingAmbiguousDiagnosisError):
        build_offline_diagnoses(table, {})


def test_diagnose_reason_raises_key_error_for_unknown_reason() -> None:
    with pytest.raises(KeyError):
        diagnose_reason("totally_unknown_reason", {})
