"""Tier 2, per incident: the one diagnosis ``GROUP BY`` structurally cannot serve.

An incident detected by :mod:`reflow.incident` (the ``poisson_surprise``
detector recommended in ``docs/design.md`` ADR-0003) spans several distinct
reason codes by construction -- every one of the corpus's 50 downtime
windows does (``reflow.corpus.downtime`` module docstring). There is no
reason-code lookup that could substitute for a judgment about the incident
*as a whole*: its probable root cause, how confident that judgment is, and
what an on-call engineer should do about it. This module makes exactly one
LLM call per detected incident to produce that judgment; unlike
:mod:`reflow.diagnose.ambiguous`, results are not cached, since no two
incidents share the same entity, time window, and reason-code mix.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from reflow.corpus.events import PaymentEvent
from reflow.diagnose.models import IncidentDiagnosis, RecommendedPosture
from reflow.incident.windows import DetectedIncident
from reflow.llm.client import JsonCompleter, LlmJsonResult, system_message, user_message

_SYSTEM_PROMPT = (
    "You are an on-call payments engineer reviewing one detected incident: a "
    "correlated burst of failed payments for one payment method and "
    "counterparty bank in a short time window, spanning multiple distinct "
    "Razorpay failure reason codes at once. A per-reason-code view would see "
    "this as several small, unrelated alerts; you are looking at it as the "
    "single incident it actually is. Using only the evidence given, state "
    "the single most probable root cause, your confidence, and a "
    "recommended operational posture. Respond only with the requested JSON."
)


@dataclass(frozen=True, slots=True)
class IncidentContext:
    """The evidence one incident diagnosis is grounded in.

    Attributes:
        method: The affected payment method.
        bank: The affected counterparty bank, or ``None`` for a method not
            scoped by bank (see
            :data:`reflow.incident.aggregate.BANK_SCOPED_METHODS`).
        detector: The detector's name that flagged this incident.
        start: The incident's detected start.
        end: The incident's detected end (exclusive).
        total_count: Total failed events attributed to this incident.
        peak_score: The detector's peak anomaly score across the incident.
        reason_counts: Count of ``error_reason`` values among the
            incident's member events.
    """

    method: str
    bank: str | None
    detector: str
    start: str
    end: str
    total_count: int
    peak_score: float
    reason_counts: Mapping[str, int]


def build_incident_context(
    incident: DetectedIncident, events: Sequence[PaymentEvent]
) -> IncidentContext:
    """Build an :class:`IncidentContext` from a detected incident.

    Args:
        incident: The detected incident to describe.
        events: The full event sequence detection was run over -- the same
            sequence :func:`reflow.incident.aggregate.build_entity_series`
            was called with, so ``incident.event_indices`` index into it.

    Returns:
        The populated :class:`IncidentContext`.
    """
    method, bank, _ = incident.entity
    reason_counts = Counter(events[index].error_reason for index in incident.event_indices)
    return IncidentContext(
        method=method.value,
        bank=bank,
        detector=incident.detector,
        start=incident.start.isoformat(),
        end=incident.end.isoformat(),
        total_count=incident.total_count,
        peak_score=incident.peak_score,
        reason_counts=dict(reason_counts),
    )


def _format_incident(context: IncidentContext) -> str:
    """Render an :class:`IncidentContext` into a user prompt.

    Args:
        context: The incident evidence to describe.

    Returns:
        A plain-text prompt body.
    """
    lines = [
        f"Payment method: {context.method}",
        f"Counterparty bank: {context.bank or '(not bank-scoped for this method)'}",
        f"Detector: {context.detector}",
        f"Window start (UTC): {context.start}",
        f"Window end (UTC): {context.end}",
        f"Total failed events in window: {context.total_count}",
        f"Detector peak anomaly score: {context.peak_score:.3f}",
        "Reason code breakdown (reason: count), highest volume first:",
    ]
    for reason, count in sorted(context.reason_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"  - {reason}: {count}")
    lines.append(
        "Available recommended postures: "
        + ", ".join(sorted(posture.value for posture in RecommendedPosture))
    )
    return "\n".join(lines)


@dataclass(slots=True)
class IncidentDiagnoser:
    """Requests one LLM diagnosis per detected incident, uncached.

    Attributes:
        client: The structured-output completer to call.
        schema_name: Name reported to the model for the response schema.
    """

    client: JsonCompleter
    schema_name: str = "incident_diagnosis"
    _results: list[LlmJsonResult[IncidentDiagnosis]] = field(default_factory=list, init=False)

    def diagnose(self, context: IncidentContext) -> LlmJsonResult[IncidentDiagnosis]:
        """Diagnose one incident.

        Args:
            context: The incident evidence to diagnose.

        Returns:
            The requested :class:`~reflow.llm.client.LlmJsonResult`.
        """
        messages = [system_message(_SYSTEM_PROMPT), user_message(_format_incident(context))]
        result = self.client.complete_json(
            messages=messages,
            response_model=IncidentDiagnosis,
            schema_name=self.schema_name,
        )
        self._results.append(result)
        return result

    @property
    def calls_made(self) -> int:
        """Total live LLM calls this diagnoser has made.

        Returns:
            The number of incidents diagnosed so far.
        """
        return len(self._results)

    def total_cost(self) -> float:
        """Sum the reported cost of every call made so far.

        Returns:
            The total dollar cost across every call whose usage reported a
            cost, treating an unreported cost as ``0.0``.
        """
        return sum(result.usage.cost or 0.0 for result in self._results)
