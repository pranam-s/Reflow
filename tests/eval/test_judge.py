"""Tests for reflow.eval.judge."""

from reflow.diagnose.incident import IncidentContext
from reflow.diagnose.models import (
    AmbiguousReasonDiagnosis,
    Confidence,
    IncidentDiagnosis,
    JudgeVerdict,
    RecommendedPosture,
)
from reflow.diagnose.tier1 import ReasonRowContext
from reflow.eval.judge import (
    judge_ambiguous_reason_diagnosis,
    judge_incident_diagnosis,
    sample_for_judging,
)
from reflow.taxonomy.remediation import RemediationClass
from tests.diagnose.factories import FakeJsonCompleter


def test_sample_for_judging_returns_everything_when_k_exceeds_population() -> None:
    assert sample_for_judging([1, 2, 3], k=10, seed=1) == [1, 2, 3]


def test_sample_for_judging_returns_exactly_k_items() -> None:
    sample = sample_for_judging(list(range(100)), k=7, seed=42)
    assert len(sample) == 7
    assert len(set(sample)) == 7


def test_sample_for_judging_is_deterministic_for_a_fixed_seed() -> None:
    population = list(range(50))
    assert sample_for_judging(population, k=5, seed=99) == sample_for_judging(
        population, k=5, seed=99
    )


def test_sample_for_judging_differs_across_seeds_in_general() -> None:
    population = list(range(50))
    first = sample_for_judging(population, k=5, seed=1)
    second = sample_for_judging(population, k=5, seed=2)
    assert first != second


def test_judge_ambiguous_reason_diagnosis_calls_completer_with_evidence() -> None:
    judge = FakeJsonCompleter(model_name="fake/judge")
    diagnosis = AmbiguousReasonDiagnosis(
        remediation_class=RemediationClass.MERCHANT_ACTION,
        confidence=Confidence.MEDIUM,
        rationale="a rationale",
    )
    contexts = (
        ReasonRowContext(
            explanation="explanation text",
            next_steps="next steps text",
            candidate_classes=frozenset({RemediationClass.MERCHANT_ACTION}),
            ambiguity_note=None,
        ),
    )
    result = judge_ambiguous_reason_diagnosis(
        judge, reason="upi_intent_not_enabled", contexts=contexts, diagnosis=diagnosis
    )
    assert isinstance(result.value, JudgeVerdict)
    prompt = judge.calls[0]["messages"][1]["content"]
    assert "upi_intent_not_enabled" in prompt
    assert "a rationale" in prompt
    assert "explanation text" in prompt


def test_judge_incident_diagnosis_calls_completer_with_evidence() -> None:
    judge = FakeJsonCompleter(model_name="fake/judge")
    context = IncidentContext(
        method="upi",
        bank="HDFC Bank",
        detector="poisson_surprise",
        start="2026-01-01T00:00:00",
        end="2026-01-01T00:15:00",
        total_count=42,
        peak_score=9.9,
        reason_counts={"payment_timed_out": 30, "bank_not_available": 12},
    )
    diagnosis = IncidentDiagnosis(
        probable_root_cause="likely bank-side outage",
        confidence=Confidence.HIGH,
        recommended_posture=RecommendedPosture.ESCALATE_TO_ONCALL,
        rationale="two correlated reason codes on one bank",
    )
    result = judge_incident_diagnosis(judge, context=context, diagnosis=diagnosis)
    assert isinstance(result.value, JudgeVerdict)
    prompt = judge.calls[0]["messages"][1]["content"]
    assert "HDFC Bank" in prompt
    assert "likely bank-side outage" in prompt
    assert prompt.index("payment_timed_out") < prompt.index("bank_not_available")
