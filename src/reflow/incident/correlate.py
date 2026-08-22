"""Reconciling detected incidents against Razorpay-declared downtimes.

A declared :class:`~reflow.incident.downtime_api.Downtime` is treated as
**corroborating evidence** for a detected incident that overlaps it, never
as a prerequisite for the incident being real -- the entire point of
Phase 3 is surfacing incidents Razorpay has not (yet, or ever) declared.
:func:`correlate_downtimes` therefore never filters or invalidates a
detected incident for lacking a declared match; it only annotates each
detected incident with whichever declared downtime, if any, corroborates
it, and how much lead or lag there was between the two.

**A structural, not incidental, limitation.** :class:`~reflow.incident.downtime_api.DowntimeMethod`
has only three members (``card``, ``netbanking``, ``upi``), verified
against Razorpay's own live documentation
(:mod:`reflow.incident.downtime_api` module docstring). A detected
incident on Wallet, Cardless EMI, or Emandate can therefore *never* be
corroborated by a declared downtime, regardless of how good detection is
-- Razorpay's API has no way to express one for those methods. This
module does not paper over that gap; :mod:`reflow.eval.incident` reports
the corroboration rate split out by whether the entity's method is even
correlatable in principle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from reflow.incident.downtime_api import Downtime, DowntimeMethod
from reflow.incident.windows import DetectedIncident
from reflow.taxonomy.methods import PaymentMethod

_OPEN_ENDED_HORIZON: timedelta = timedelta(days=3650)
"""Treats a still-ongoing declared downtime (``end is None``) as open-ended
far enough into the future that any detected incident starting at or after
its ``begin`` is considered within its span, without needing a second,
separate "ongoing" comparison branch."""


def _naive_utc(moment: datetime) -> datetime:
    """Strip timezone info from a UTC-aware timestamp.

    Args:
        moment: A timezone-aware timestamp, assumed already UTC (which is
            what Pydantic's Unix-timestamp coercion produces for
            :class:`~reflow.incident.downtime_api.Downtime` fields).

    Returns:
        The same instant, represented as a naive :class:`datetime` -- the
        convention :mod:`reflow.corpus` uses throughout (see
        :data:`reflow.corpus.generator.CORPUS_PERIOD_END`), so it can be
        compared directly against a :class:`~reflow.incident.windows.DetectedIncident`'s
        naive ``start``/``end``.
    """
    return moment.astimezone(UTC).replace(tzinfo=None)


def _method_matches(payment_method: PaymentMethod, downtime_method: DowntimeMethod) -> bool:
    """Whether an entity's method corresponds to a declared downtime's method.

    Args:
        payment_method: The detected incident's entity method.
        downtime_method: The declared downtime's method.

    Returns:
        ``True`` if the two enums' string values match.
    """
    return payment_method.value == downtime_method.value


@dataclass(frozen=True, slots=True)
class DowntimeCorrelation:
    """One detected incident's correlation result against declared downtimes.

    Attributes:
        detected: The detected incident being annotated.
        matched_downtime: The declared downtime that best corroborates
            ``detected`` (the one whose ``begin`` is closest in time among
            every overlapping, method/bank-matching candidate), or
            ``None`` if none does.
        lead_time_minutes: ``(detected.start - matched_downtime.begin)`` in
            minutes, or ``None`` if there is no match. Negative means
            detection fired *before* Razorpay's declared downtime began --
            the operationally valuable case this project exists to find.
    """

    detected: DetectedIncident
    matched_downtime: Downtime | None
    lead_time_minutes: float | None


def correlate_downtimes(
    detected: Sequence[DetectedIncident],
    downtimes: Sequence[Downtime],
) -> list[DowntimeCorrelation]:
    """Reconcile detected incidents against declared downtimes.

    Args:
        detected: Detected incidents to annotate.
        downtimes: Declared downtimes to correlate against. Never fetched
            from a live API by this function -- see module and
            :mod:`reflow.incident.downtime_api` docstrings.

    Returns:
        One :class:`DowntimeCorrelation` per input incident, in the same
        order.
    """
    results: list[DowntimeCorrelation] = []
    for incident in detected:
        method, bank, _ = incident.entity
        candidates: list[Downtime] = []
        for downtime in downtimes:
            if not _method_matches(method, downtime.method):
                continue
            if bank is not None and downtime.bank is not None and bank != downtime.bank:
                continue
            begin = _naive_utc(downtime.begin)
            end = (
                _naive_utc(downtime.end)
                if downtime.end is not None
                else begin + _OPEN_ENDED_HORIZON
            )
            if incident.start < end and begin < incident.end:
                candidates.append(downtime)

        match = min(
            candidates,
            key=lambda downtime: abs((_naive_utc(downtime.begin) - incident.start).total_seconds()),
            default=None,
        )
        lead_time = (
            (incident.start - _naive_utc(match.begin)).total_seconds() / 60.0
            if match is not None
            else None
        )
        results.append(
            DowntimeCorrelation(
                detected=incident, matched_downtime=match, lead_time_minutes=lead_time
            )
        )
    return results
