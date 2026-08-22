"""Shared network-free fakes for reflow.diagnose / reflow.eval.diagnose tests.

Not a test module itself (no ``test_`` prefix, so pytest never collects
it): plain helpers other test modules import, mirroring
``tests/incident/factories.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from reflow.diagnose.models import (
    AmbiguousReasonDiagnosis,
    Confidence,
    IncidentDiagnosis,
    JudgeVerdict,
    JudgeVerdictLabel,
    RecommendedPosture,
)
from reflow.llm.client import LlmJsonResult, LlmUsage, Message
from reflow.taxonomy.remediation import RemediationClass


def default_ambiguous_reason_diagnosis() -> AmbiguousReasonDiagnosis:
    return AmbiguousReasonDiagnosis(
        remediation_class=RemediationClass.MERCHANT_CONTACT_RAZORPAY,
        confidence=Confidence.MEDIUM,
        rationale="stub rationale",
    )


def default_incident_diagnosis() -> IncidentDiagnosis:
    return IncidentDiagnosis(
        probable_root_cause="stub root cause",
        confidence=Confidence.HIGH,
        recommended_posture=RecommendedPosture.ESCALATE_TO_ONCALL,
        rationale="stub rationale",
    )


def default_judge_verdict() -> JudgeVerdict:
    return JudgeVerdict(
        agrees_with_diagnosis=True, verdict=JudgeVerdictLabel.CORRECT, concerns="looks fine"
    )


_DEFAULT_FACTORIES: dict[type[BaseModel], Callable[[], BaseModel]] = {
    AmbiguousReasonDiagnosis: default_ambiguous_reason_diagnosis,
    IncidentDiagnosis: default_incident_diagnosis,
    JudgeVerdict: default_judge_verdict,
}


@dataclass
class FakeJsonCompleter:
    """A network-free stand-in for :class:`reflow.llm.client.JsonCompleter`.

    Attributes:
        factory: Overrides the default fixture value for a given response
            model type.
        model_name: The model slug every returned :class:`LlmJsonResult`
            reports.
        cost_per_call: The dollar cost every returned result reports.
        calls: Every call made, in order, for assertions.
    """

    factory: Callable[[type[BaseModel]], BaseModel] | None = None
    model_name: str = "fake/model"
    cost_per_call: float = 0.00005
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete_json(
        self,
        *,
        messages: Sequence[Message],
        response_model: type[BaseModel],
        schema_name: str,
        description: str | None = None,
    ) -> LlmJsonResult[Any]:
        self.calls.append(
            {
                "messages": list(messages),
                "response_model": response_model,
                "schema_name": schema_name,
            }
        )
        if self.factory is not None:
            value = self.factory(response_model)
        else:
            builder = _DEFAULT_FACTORIES.get(response_model)
            if builder is None:
                raise AssertionError(f"No default fixture registered for {response_model!r}.")
            value = builder()
        usage = LlmUsage(
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            reasoning_tokens=0,
            cost=self.cost_per_call,
        )
        return LlmJsonResult(
            value=value, usage=usage, model=self.model_name, attempts=1, finish_reason="stop"
        )
