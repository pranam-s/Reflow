"""LLM-as-a-judge scoring for Tier 2 diagnosis quality (Deliverable 3).

The judge is deliberately a **different model family** from the Tier 2
model under test, to avoid self-preference bias (a model rating its own
kind of output favourably) -- see :mod:`reflow.eval.diagnose` for which
concrete models this repository's benchmark run used and why. Judging is
sampled, not exhaustive: :func:`sample_for_judging` draws a fixed-size,
seeded sample from a larger population of diagnoses, the way a real
deployment would spot-check quality rather than re-score every diagnosis
ever produced.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

from reflow.diagnose.incident import IncidentContext
from reflow.diagnose.models import AmbiguousReasonDiagnosis, IncidentDiagnosis, JudgeVerdict
from reflow.diagnose.tier1 import ReasonRowContext
from reflow.llm.client import JsonCompleter, LlmJsonResult, system_message, user_message

T = TypeVar("T")

_JUDGE_SYSTEM_PROMPT = (
    "You are an independent quality reviewer for an automated payments-failure "
    "diagnosis system. You did not produce the diagnosis under review and have "
    "no stake in defending it. Given the original evidence and the diagnosis it "
    "produced, assess whether the diagnosis is well-supported by that evidence. "
    'Use "wrong" only when the diagnosis is clearly unsupported by or '
    'contradicts the evidence, "questionable" when it is plausible but weakly '
    "supported, overconfident, or omits an equally plausible alternative, and "
    '"correct" otherwise. Respond only with the requested JSON.'
)


def sample_for_judging(items: Sequence[T], k: int, seed: int) -> list[T]:
    """Draw a fixed-size, seeded sample for judging.

    Args:
        items: The population to sample from.
        k: Desired sample size.
        seed: Seed for reproducible sampling.

    Returns:
        ``min(k, len(items))`` items drawn without replacement, in the
        order :class:`random.Random.sample` returns them. Returns every
        item, unsampled, if ``k >= len(items)``.
    """
    if k >= len(items):
        return list(items)
    rng = random.Random(seed)  # noqa: S311
    return rng.sample(list(items), k)


def _format_ambiguous_review(
    reason: str,
    contexts: tuple[ReasonRowContext, ...],
    diagnosis: AmbiguousReasonDiagnosis,
) -> str:
    """Render an ambiguous-reason diagnosis and its evidence for review.

    Args:
        reason: The reason code that was diagnosed.
        contexts: Every vendored row recorded for this reason code.
        diagnosis: The diagnosis under review.

    Returns:
        A plain-text prompt body.
    """
    lines = [f"Reason code under review: {reason}", ""]
    for index, context in enumerate(contexts, start=1):
        lines.append(f"Row {index} explanation: {context.explanation}")
        lines.append(f"Row {index} next steps: {context.next_steps}")
    lines.extend(
        [
            "",
            "Diagnosis under review:",
            f"  remediation_class = {diagnosis.remediation_class.value}",
            f"  confidence = {diagnosis.confidence.value}",
            f"  rationale = {diagnosis.rationale}",
        ]
    )
    return "\n".join(lines)


def judge_ambiguous_reason_diagnosis(
    judge: JsonCompleter,
    *,
    reason: str,
    contexts: tuple[ReasonRowContext, ...],
    diagnosis: AmbiguousReasonDiagnosis,
    schema_name: str = "judge_verdict",
) -> LlmJsonResult[JudgeVerdict]:
    """Judge one ambiguous-reason diagnosis.

    Args:
        judge: The judge model's completer.
        reason: The reason code that was diagnosed.
        contexts: Every vendored row recorded for this reason code.
        diagnosis: The diagnosis under review.
        schema_name: Name reported to the model for the response schema.

    Returns:
        The judge's :class:`~reflow.llm.client.LlmJsonResult`.
    """
    messages = [
        system_message(_JUDGE_SYSTEM_PROMPT),
        user_message(_format_ambiguous_review(reason, contexts, diagnosis)),
    ]
    return judge.complete_json(
        messages=messages, response_model=JudgeVerdict, schema_name=schema_name
    )


def _format_incident_review(context: IncidentContext, diagnosis: IncidentDiagnosis) -> str:
    """Render an incident diagnosis and its evidence for review.

    Args:
        context: The incident evidence that was diagnosed.
        diagnosis: The diagnosis under review.

    Returns:
        A plain-text prompt body.
    """
    lines = [
        f"Payment method: {context.method}",
        f"Counterparty bank: {context.bank or '(not bank-scoped for this method)'}",
        f"Window: {context.start} to {context.end}",
        f"Total failed events: {context.total_count}",
        "Reason code breakdown:",
    ]
    for reason, count in sorted(context.reason_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"  - {reason}: {count}")
    lines.extend(
        [
            "",
            "Diagnosis under review:",
            f"  probable_root_cause = {diagnosis.probable_root_cause}",
            f"  confidence = {diagnosis.confidence.value}",
            f"  recommended_posture = {diagnosis.recommended_posture.value}",
            f"  rationale = {diagnosis.rationale}",
        ]
    )
    return "\n".join(lines)


def judge_incident_diagnosis(
    judge: JsonCompleter,
    *,
    context: IncidentContext,
    diagnosis: IncidentDiagnosis,
    schema_name: str = "judge_verdict",
) -> LlmJsonResult[JudgeVerdict]:
    """Judge one incident diagnosis.

    Args:
        judge: The judge model's completer.
        context: The incident evidence that was diagnosed.
        diagnosis: The diagnosis under review.
        schema_name: Name reported to the model for the response schema.

    Returns:
        The judge's :class:`~reflow.llm.client.LlmJsonResult`.
    """
    messages = [
        system_message(_JUDGE_SYSTEM_PROMPT),
        user_message(_format_incident_review(context, diagnosis)),
    ]
    return judge.complete_json(
        messages=messages, response_model=JudgeVerdict, schema_name=schema_name
    )


@dataclass(frozen=True, slots=True)
class JudgeSampleResult:
    """One judged sample's outcome, ready for reporting.

    Attributes:
        kind: ``"ambiguous_reason"`` or ``"incident"``.
        subject_id: The reason code, or a stable incident identifier.
        diagnosis_confidence: The confidence the diagnosis under review
            self-reported.
        verdict: The judge's coarse quality label.
        agrees_with_diagnosis: Whether the judge endorsed the diagnosis.
        concerns: The judge's explanation.
        judge_cost: The judge call's reported dollar cost, or ``None``.
    """

    kind: str
    subject_id: str
    diagnosis_confidence: str
    verdict: str
    agrees_with_diagnosis: bool
    concerns: str
    judge_cost: float | None
