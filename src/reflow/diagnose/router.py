"""Routing events between Tier 1 (deterministic) and Tier 2 (LLM).

This module answers the phase's headline question: what fraction of events
resolve deterministically, and what fraction require an LLM call. It never
calls the LLM once per event -- :meth:`DiagnosisRouter.route` calls the LLM
at most once per *distinct* escalated reason code present in a batch of
events (via :class:`~reflow.diagnose.ambiguous.AmbiguousReasonDiagnoser`'s
own cache), then multiplies each reason's resolution by how many events
share it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from reflow.corpus.events import PaymentEvent
from reflow.diagnose.ambiguous import AmbiguousReasonDiagnoser
from reflow.diagnose.models import Confidence
from reflow.diagnose.tier1 import DeterministicTable
from reflow.taxonomy.remediation import RemediationClass


class DiagnosisTier(StrEnum):
    """Which tier resolved one reason code."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"


@dataclass(frozen=True, slots=True)
class EventDiagnosis:
    """One reason code's resolved remediation, tagged with its tier.

    Attributes:
        reason: The reason code diagnosed.
        tier: Which tier produced this diagnosis.
        remediation_class: The resolved remediation class.
        confidence: :attr:`~reflow.diagnose.models.Confidence.HIGH` for
            every deterministic diagnosis (an exact rule-table match is not
            a probabilistic judgment), or the LLM's own reported confidence
            for an escalated one.
        rationale: ``None`` for a deterministic diagnosis (there is nothing
            to explain beyond the rule-table match); the LLM's own
            rationale for an escalated one.
    """

    reason: str
    tier: DiagnosisTier
    remediation_class: RemediationClass
    confidence: Confidence
    rationale: str | None


@dataclass(frozen=True, slots=True)
class RoutingStats:
    """The phase's headline routing-split measurement.

    Attributes:
        total_events: Total events routed.
        deterministic_events: Events whose reason resolved in Tier 1.
        llm_events: Events whose reason was escalated to Tier 2.
        distinct_reasons_seen: Distinct reason codes present in the routed
            events.
        llm_calls_made: Live LLM calls made to resolve every escalated
            reason code seen (at most one per distinct escalated reason,
            regardless of how many events share it).
        escalated_reasons: Every distinct reason code escalated.
    """

    total_events: int
    deterministic_events: int
    llm_events: int
    distinct_reasons_seen: int
    llm_calls_made: int
    escalated_reasons: frozenset[str]

    @property
    def deterministic_fraction(self) -> float:
        """Fraction of events resolved deterministically.

        Returns:
            ``deterministic_events / total_events``, or ``0.0`` if
            ``total_events`` is ``0``.
        """
        return self.deterministic_events / self.total_events if self.total_events else 0.0

    @property
    def llm_fraction(self) -> float:
        """Fraction of events escalated to the LLM.

        Returns:
            ``llm_events / total_events``, or ``0.0`` if ``total_events`` is
            ``0``.
        """
        return self.llm_events / self.total_events if self.total_events else 0.0


@dataclass(slots=True)
class DiagnosisRouter:
    """Combines the deterministic table and the ambiguous-reason diagnoser.

    Attributes:
        table: The reason-code-level deterministic routing table.
        ambiguous_diagnoser: The cached Tier 2 diagnoser for escalated
            reason codes.
    """

    table: DeterministicTable
    ambiguous_diagnoser: AmbiguousReasonDiagnoser

    def diagnose_reason(self, reason: str) -> EventDiagnosis:
        """Diagnose one reason code, resolving it in whichever tier applies.

        Args:
            reason: The reason code to diagnose.

        Returns:
            The populated :class:`EventDiagnosis`.
        """
        deterministic_class = self.table.lookup(reason)
        if deterministic_class is not None:
            return EventDiagnosis(
                reason=reason,
                tier=DiagnosisTier.DETERMINISTIC,
                remediation_class=deterministic_class,
                confidence=Confidence.HIGH,
                rationale=None,
            )
        contexts = self.table.escalated.get(reason, ())
        result = self.ambiguous_diagnoser.diagnose(reason, contexts)
        diagnosis = result.value
        return EventDiagnosis(
            reason=reason,
            tier=DiagnosisTier.LLM,
            remediation_class=diagnosis.remediation_class,
            confidence=diagnosis.confidence,
            rationale=diagnosis.rationale,
        )

    def route(self, events: Sequence[PaymentEvent]) -> RoutingStats:
        """Route a batch of events, measuring the deterministic/LLM split.

        Args:
            events: The events to route.

        Returns:
            The populated :class:`RoutingStats`.
        """
        counts = Counter(event.error_reason for event in events)
        deterministic_events = 0
        llm_events = 0
        for reason, count in counts.items():
            diagnosis = self.diagnose_reason(reason)
            if diagnosis.tier is DiagnosisTier.DETERMINISTIC:
                deterministic_events += count
            else:
                llm_events += count
        return RoutingStats(
            total_events=len(events),
            deterministic_events=deterministic_events,
            llm_events=llm_events,
            distinct_reasons_seen=len(counts),
            llm_calls_made=self.ambiguous_diagnoser.calls_made,
            escalated_reasons=self.ambiguous_diagnoser.cached_reasons,
        )
