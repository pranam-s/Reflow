"""Pydantic response models for the LLM-backed diagnosis tier.

Every model here is defined with ``model_config = ConfigDict(extra="forbid")``
and no optional or defaulted field, so
:meth:`pydantic.BaseModel.model_json_schema` emits a schema already
compatible with OpenRouter's ``strict`` ``json_schema`` structured-output
mode (every property required, ``additionalProperties: false``) without
:mod:`reflow.llm.schema` needing to post-process it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from reflow.taxonomy.remediation import RemediationClass


class Confidence(StrEnum):
    """How confident a diagnosis is in its own conclusion."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendedPosture(StrEnum):
    """An operational response to a detected multi-reason incident.

    Distinct from :class:`~reflow.taxonomy.remediation.RemediationClass`,
    which is a per-event customer/merchant remediation action. A posture is
    an on-call-facing recommendation for the *incident as a whole* -- the
    thing ``GROUP BY reason`` cannot see because it never observes the
    incident as one object (``docs/design.md`` ADR-0003).
    """

    MONITOR = "monitor"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    FAILOVER_METHOD = "failover_method"
    ESCALATE_TO_ONCALL = "escalate_to_oncall"
    CONTACT_PROVIDER = "contact_provider"
    NO_ACTION = "no_action"


class JudgeVerdictLabel(StrEnum):
    """A coarse three-way quality label a judge model assigns a diagnosis."""

    CORRECT = "correct"
    QUESTIONABLE = "questionable"
    WRONG = "wrong"


class AmbiguousReasonDiagnosis(BaseModel):
    """One LLM-resolved classification for a reason the taxonomy left ambiguous.

    Attributes:
        remediation_class: The single best-fit remediation class for this
            reason, chosen from the same closed vocabulary
            :mod:`reflow.taxonomy.remediation` uses for the 95 reasons it
            resolves deterministically.
        confidence: How confident the model is in ``remediation_class``.
        rationale: A one-to-two sentence justification grounded in the
            reason's vendored ``Explanation``/``Next Steps`` text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    remediation_class: RemediationClass
    confidence: Confidence
    rationale: str


class IncidentDiagnosis(BaseModel):
    """An LLM-produced diagnosis for one detected, multi-reason incident.

    This is the one case ``GROUP BY`` structurally cannot serve (see
    ``docs/design.md`` ADR-0003): a detected incident spans several reason
    codes by construction, so there is no single reason-code lookup that
    could stand in for this judgment.

    Attributes:
        probable_root_cause: A one-to-two sentence plain-language hypothesis
            for what is causing this incident, grounded in its entity,
            reason-code mix, and severity.
        confidence: How confident the model is in ``probable_root_cause``.
        recommended_posture: The recommended operational response.
        rationale: A one-to-two sentence justification connecting the
            evidence (reason codes, volume, duration) to the conclusion.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    probable_root_cause: str
    confidence: Confidence
    recommended_posture: RecommendedPosture
    rationale: str


class JudgeVerdict(BaseModel):
    """An independent judge model's assessment of one Tier-2 diagnosis.

    Attributes:
        agrees_with_diagnosis: Whether the judge, reasoning independently
            from the same evidence, would reach materially the same
            conclusion as the diagnosis under review.
        verdict: A coarse three-way quality label.
        concerns: A one-to-two sentence explanation, especially for
            ``"questionable"`` or ``"wrong"`` verdicts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agrees_with_diagnosis: bool
    verdict: JudgeVerdictLabel
    concerns: str
