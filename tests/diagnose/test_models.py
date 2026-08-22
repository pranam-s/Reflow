"""Tests for reflow.diagnose.models."""

import pytest
from pydantic import ValidationError

from reflow.diagnose.models import (
    AmbiguousReasonDiagnosis,
    Confidence,
    IncidentDiagnosis,
    JudgeVerdict,
    JudgeVerdictLabel,
    RecommendedPosture,
)
from reflow.llm.schema import json_schema_response_format
from reflow.taxonomy.remediation import RemediationClass


@pytest.mark.parametrize(
    "model",
    [AmbiguousReasonDiagnosis, IncidentDiagnosis, JudgeVerdict],
)
def test_every_diagnosis_model_is_strict_schema_compatible(model: type) -> None:
    schema = json_schema_response_format(model, name=model.__name__)["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_ambiguous_reason_diagnosis_rejects_unknown_remediation_class() -> None:
    with pytest.raises(ValidationError):
        AmbiguousReasonDiagnosis.model_validate(
            {
                "remediation_class": "not_a_real_class",
                "confidence": Confidence.LOW.value,
                "rationale": "r",
            }
        )


def test_ambiguous_reason_diagnosis_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AmbiguousReasonDiagnosis.model_validate(
            {
                "remediation_class": RemediationClass.WAIT.value,
                "confidence": Confidence.LOW.value,
                "rationale": "r",
                "unexpected_field": True,
            }
        )


def test_incident_diagnosis_round_trips_through_json() -> None:
    diagnosis = IncidentDiagnosis(
        probable_root_cause="bank outage",
        confidence=Confidence.HIGH,
        recommended_posture=RecommendedPosture.FAILOVER_METHOD,
        rationale="multiple reason codes spiking together",
    )
    restored = IncidentDiagnosis.model_validate_json(diagnosis.model_dump_json())
    assert restored == diagnosis


def test_judge_verdict_label_values_are_the_three_documented_tiers() -> None:
    assert {label.value for label in JudgeVerdictLabel} == {"correct", "questionable", "wrong"}
