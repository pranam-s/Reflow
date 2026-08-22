"""Tier 2, ambiguous reasons: one cached LLM call per reason code.

Results are deterministic per reason code (the same vendored text always
produces the same prompt), so :class:`AmbiguousReasonDiagnoser` caches every
result in memory the first time a reason code is diagnosed. A 50,000-event
run therefore makes at most as many live calls as there are distinct
escalated reason codes -- 15 at this repository's vendored spreadsheet (see
:mod:`reflow.diagnose.tier1` module docstring for why that is one more than
the taxonomy's own "14 ambiguous rows" count), never one call per event.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reflow.diagnose.models import AmbiguousReasonDiagnosis
from reflow.diagnose.tier1 import ReasonRowContext
from reflow.llm.client import JsonCompleter, LlmJsonResult, system_message, user_message
from reflow.taxonomy.remediation import RemediationClass

_SYSTEM_PROMPT = (
    "You are diagnosing a Razorpay payment failure reason code whose vendored "
    "remediation guidance could not be resolved by rule-based parsing alone -- "
    "either one row's text offers more than one remediation path, or two rows "
    "for the same reason code disagree with each other. Using only the "
    "evidence given, choose the single best-fit remediation class for a "
    "merchant handling this failure in the general case. Respond only with "
    "the requested JSON."
)


def _format_context(reason: str, contexts: tuple[ReasonRowContext, ...]) -> str:
    """Render one reason code's vendored rows into a user prompt.

    Args:
        reason: The reason code being diagnosed.
        contexts: Every vendored row recorded for this reason code.

    Returns:
        A plain-text prompt body listing each row's explanation, next
        steps, rule-parsed candidate classes, and any ambiguity note.
    """
    lines = [f"Reason code: {reason}", ""]
    for index, context in enumerate(contexts, start=1):
        candidates = ", ".join(sorted(c.value for c in context.candidate_classes)) or "(none)"
        lines.extend(
            [
                f"Row {index} explanation: {context.explanation}",
                f"Row {index} next steps: {context.next_steps}",
                f"Row {index} rule-parsed candidate remediation class(es): {candidates}",
            ]
        )
        if context.ambiguity_note:
            lines.append(f"Row {index} ambiguity note: {context.ambiguity_note}")
        lines.append("")
    lines.append(
        "Available remediation classes: " + ", ".join(sorted(c.value for c in RemediationClass))
    )
    return "\n".join(lines)


@dataclass(slots=True)
class AmbiguousReasonDiagnoser:
    """Caches one LLM diagnosis per ambiguous reason code.

    Attributes:
        client: The structured-output completer to call.
        schema_name: Name reported to the model for the response schema.
    """

    client: JsonCompleter
    schema_name: str = "ambiguous_reason_diagnosis"
    _cache: dict[str, LlmJsonResult[AmbiguousReasonDiagnosis]] = field(
        default_factory=dict, init=False
    )

    def diagnose(
        self, reason: str, contexts: tuple[ReasonRowContext, ...]
    ) -> LlmJsonResult[AmbiguousReasonDiagnosis]:
        """Diagnose one ambiguous reason code, using the cache if available.

        Args:
            reason: The reason code to diagnose.
            contexts: Every vendored row recorded for this reason code.
                Ignored on a cache hit.

        Returns:
            The cached or freshly requested :class:`~reflow.llm.client.LlmJsonResult`.
        """
        cached = self._cache.get(reason)
        if cached is not None:
            return cached
        messages = [
            system_message(_SYSTEM_PROMPT),
            user_message(_format_context(reason, contexts)),
        ]
        result = self.client.complete_json(
            messages=messages,
            response_model=AmbiguousReasonDiagnosis,
            schema_name=self.schema_name,
        )
        self._cache[reason] = result
        return result

    @property
    def cached_reasons(self) -> frozenset[str]:
        """Every reason code this diagnoser has resolved so far.

        Returns:
            A frozenset of reason codes with a cached result.
        """
        return frozenset(self._cache)

    @property
    def calls_made(self) -> int:
        """Total live LLM calls this diagnoser has made.

        Returns:
            The number of distinct reason codes cached, since each is
            called at most once.
        """
        return len(self._cache)

    def total_cost(self) -> float:
        """Sum the reported cost of every cached call.

        Returns:
            The total dollar cost across every cached call whose usage
            reported a cost, treating an unreported cost as ``0.0``.
        """
        return sum(result.usage.cost or 0.0 for result in self._cache.values())
