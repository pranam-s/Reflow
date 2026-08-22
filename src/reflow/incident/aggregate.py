"""Bucketed, per-entity failure-count aggregation for incident detection.

Phase 2's negative result (``docs/design.md`` ADR-0002) leaves temporal and
entity correlation as the remaining place clustering-adjacent techniques
could add value: a single bank outage does not manifest as one repeated
reason code, it manifests as several reason codes climbing together, for
one payment method and (usually) one bank, inside one time window. This
module builds the substrate every detector in :mod:`reflow.incident.detectors`
scores: a dense, per-entity, per-time-bucket failure count series.

**Bucket width: 15 minutes.** Chosen deliberately, not defaulted:

- It equals :data:`reflow.corpus.downtime._MIN_DURATION`, the shortest
  outage window the corpus generates. A shorter incident than that would
  need sub-bucket resolution to see at all; at 15 minutes, even the
  shortest true incident always spans at least one whole bucket, so no
  detector is structurally blind to it before the incident has even
  finished.
- It is short enough that detection delay is operationally meaningful:
  each bucket of delay before a burst crosses a threshold is a bucket's
  worth of payments retried against a bank that is still down. A hierarchy
  of hourly or daily buckets would make Deliverable 4's time-to-detect
  numbers report in hours before the numbers even become interesting.
  15 minutes was chosen over 5 or 10 because the corpus's background
  traffic is heavily fragmented across ~50 ``(method, bank)`` entities
  (see :data:`BANK_SCOPED_METHODS`) with a Zipf-weighted method mix
  (:data:`reflow.corpus.methods.METHOD_MIX`): at 5-minute buckets, several
  entities' background rate would average under 0.1 events per bucket,
  making "was this bucket empty" almost entirely a coin flip unrelated to
  whether an incident is happening. 15 minutes does not eliminate this
  sparsity (see :mod:`reflow.incident.detectors`'s cold-start and
  low-count handling), but it reduces it materially without pushing
  detection delay into hours.

**Entity key: ``(method, bank)`` -- except when it structurally cannot be.**
Razorpay's own error taxonomy (:data:`reflow.taxonomy.methods.SOURCES_BY_METHOD`)
never attributes a Wallet or Cardless EMI failure to a bank-shaped source
(``issuer_bank``, ``beneficiary_bank``, or ``bank``) -- only to a generic
``issuer``. :data:`BANK_SCOPED_METHODS` is derived from that fact, not
copied from :mod:`reflow.corpus.downtime` (which this module never
imports, since ``src/reflow/corpus/`` is frozen and this is an
independent, taxonomy-grounded justification that happens to agree with
it): for Card, UPI, Netbanking, and Emandate, grouping by the counterparty
bank name is a real, taxonomy-supported dimension; for Wallet and Cardless
EMI it is not, and a
:class:`~reflow.corpus.events.PaymentEvent`'s ``bank`` field for those two
methods is populated only as "a generic institution stand-in" (see that
attribute's docstring) -- treating it as a grouping key would fragment one
method-wide incident across the corpus's entire bank-name pool for no
principled reason. :func:`entity_key` therefore keys Wallet and Cardless
EMI events by method alone.

:func:`reason_scoped_entity_key` adds the reason code as a third component,
used only by the ``GROUP BY reason`` comparison baseline
(:mod:`reflow.incident.attribution`) to build the finest-grained series a
naive per-reason-code monitor would ever see.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from reflow.corpus.events import PaymentEvent
from reflow.taxonomy.methods import SOURCES_BY_METHOD, ErrorSource, PaymentMethod

BUCKET_WIDTH: Final[timedelta] = timedelta(minutes=15)
"""The fixed bucket width every detector and the evaluation harness uses.
See module docstring for why 15 minutes."""

_EPOCH: Final[datetime] = datetime(1970, 1, 1)
"""Fixed reference point bucket boundaries are computed relative to (not
the dataset's own minimum timestamp), so bucket boundaries are stable
regardless of which subset of events (train only, test only, a single
entity) is being bucketed -- the same wall-clock instant always floors to
the same bucket start."""

_BANK_NAMED_SOURCES: Final[frozenset[ErrorSource]] = frozenset(
    {ErrorSource.ISSUER_BANK, ErrorSource.BENEFICIARY_BANK, ErrorSource.BANK}
)

BANK_SCOPED_METHODS: Final[frozenset[PaymentMethod]] = frozenset(
    method for method in PaymentMethod if SOURCES_BY_METHOD[method] & _BANK_NAMED_SOURCES
)
"""Payment methods whose error taxonomy names a specific bank-shaped
counterparty. Computed from :data:`reflow.taxonomy.methods.SOURCES_BY_METHOD`
rather than hard-coded, so a future taxonomy change is reflected
automatically. See module docstring."""

EntityKey = tuple[PaymentMethod, str | None, str | None]
"""``(method, bank_or_None, reason_or_None)``. The third element is
``None`` for the standard ``(method, bank)`` aggregation every detector in
:mod:`reflow.incident.detectors` scores, and a specific reason code for
:func:`reason_scoped_entity_key`'s finer-grained ``GROUP BY reason``
baseline. Carrying a fixed-shape 3-tuple in both cases (rather than a
``tuple[PaymentMethod, str | None] | tuple[PaymentMethod, str | None, str]``
union) keeps every downstream consumer's type simple."""


def entity_key(event: PaymentEvent) -> EntityKey:
    """Compute an event's standard ``(method, bank)`` incident entity.

    Args:
        event: The event to key.

    Returns:
        ``(event.method, event.bank, None)`` if ``event.method`` is in
        :data:`BANK_SCOPED_METHODS`, otherwise ``(event.method, None, None)``.
    """
    bank = event.bank if event.method in BANK_SCOPED_METHODS else None
    return (event.method, bank, None)


def reason_scoped_entity_key(event: PaymentEvent) -> EntityKey:
    """Compute an event's ``(method, bank, reason)`` entity.

    Used only by the ``GROUP BY reason`` comparison baseline: it is the
    finest-grained view a naive per-reason-code monitor would have, since
    such a monitor never merges reason codes back together even when they
    share a method and bank.

    Args:
        event: The event to key.

    Returns:
        :func:`entity_key`'s result with ``event.error_reason`` substituted
        for the third element.
    """
    method, bank, _ = entity_key(event)
    return (method, bank, event.error_reason)


def floor_to_bucket(moment: datetime, bucket_width: timedelta = BUCKET_WIDTH) -> datetime:
    """Floor a timestamp to its containing bucket's start.

    Args:
        moment: The timestamp to floor. Must be timezone-naive, matching
            :attr:`reflow.corpus.events.PaymentEvent.created_at`.
        bucket_width: The bucket width to floor to.

    Returns:
        The largest ``_EPOCH + n * bucket_width`` (``n`` a non-negative
        integer) that does not exceed ``moment``.
    """
    elapsed = moment - _EPOCH
    bucket_index = elapsed // bucket_width
    return _EPOCH + bucket_index * bucket_width


@dataclass(frozen=True, slots=True)
class BucketGrid:
    """A shared, dense sequence of bucket boundaries every entity aligns to.

    Materialising bucket boundaries once and sharing them across every
    entity (rather than each :class:`EntitySeries` carrying its own tuple
    of ``datetime`` objects) is what keeps the ``GROUP BY reason`` baseline
    tractable: that baseline builds a series for every ``(method, bank,
    reason)`` triple with at least one event -- over 2,000 of them at the
    corpus's default size -- and duplicating a ~2,880-element tuple of
    ``datetime`` objects per entity would cost hundreds of megabytes for no
    reason, since every entity shares the same global time axis.

    Attributes:
        origin: The first bucket's start.
        bucket_width: The bucket width.
        n_buckets: Total number of buckets in the grid.
    """

    origin: datetime
    bucket_width: timedelta
    n_buckets: int

    def index_of(self, moment: datetime) -> int:
        """Compute the bucket index containing ``moment``.

        Args:
            moment: The timestamp to locate. Must not be earlier than
                :attr:`origin`.

        Returns:
            The zero-based index of the bucket containing ``moment``.

        Raises:
            ValueError: If ``moment`` falls before :attr:`origin`.
        """
        if moment < self.origin:
            raise ValueError(f"moment {moment} precedes grid origin {self.origin}.")
        return (moment - self.origin) // self.bucket_width

    def start_of(self, index: int) -> datetime:
        """Compute the start timestamp of a bucket index.

        Args:
            index: The zero-based bucket index.

        Returns:
            ``origin + index * bucket_width``.
        """
        return self.origin + index * self.bucket_width


@dataclass(frozen=True, slots=True)
class EntitySeries:
    """One entity's dense, chronologically ordered failure-count series.

    Attributes:
        entity: The entity this series describes.
        grid: The shared :class:`BucketGrid` every index in ``counts``
            aligns to.
        counts: Dense failure counts, one per bucket in ``grid``, index 0
            aligned to ``grid.origin``. Buckets with no events are ``0``,
            not omitted -- a trailing-baseline detector must see a true
            lull as zero, not skip past it, or its baseline would be
            biased upward by ignoring quiet periods.
        event_indices_by_bucket: Sparse map from bucket index to the
            indices (into the original event sequence passed to
            :func:`build_entity_series`) of every event in that bucket.
            Only non-empty buckets have an entry.
        reason_counts_by_bucket: Sparse map from bucket index to a count of
            ``error_reason`` values among that bucket's events. Only
            non-empty buckets have an entry.
    """

    entity: EntityKey
    grid: BucketGrid
    counts: tuple[int, ...]
    event_indices_by_bucket: Mapping[int, tuple[int, ...]]
    reason_counts_by_bucket: Mapping[int, Mapping[str, int]]


def build_entity_series(
    events: Sequence[PaymentEvent],
    key_fn: Callable[[PaymentEvent], EntityKey] = entity_key,
    bucket_width: timedelta = BUCKET_WIDTH,
) -> dict[EntityKey, EntitySeries]:
    """Aggregate events into a dense, per-entity failure-count series.

    Every entity's series spans the same global bucket range (the earliest
    to the latest bucket across *all* input events), not just that
    entity's own active span: a bucket where a normally-active entity saw
    zero failures is a real, informative zero for baseline estimation and
    for the false-positive-rate measurement in
    :mod:`reflow.incident.attribution`, and must not be silently absent.

    Args:
        events: The events to aggregate, in any order.
        key_fn: Computes an entity key per event. Defaults to
            :func:`entity_key`; pass :func:`reason_scoped_entity_key` to
            build the ``GROUP BY reason`` baseline's finer-grained series.
        bucket_width: The bucket width to aggregate into.

    Returns:
        A mapping from entity key to that entity's :class:`EntitySeries`.
        Empty if ``events`` is empty.
    """
    if not events:
        return {}

    bucket_of = [floor_to_bucket(event.created_at, bucket_width) for event in events]
    origin = min(bucket_of)
    latest = max(bucket_of)
    n_buckets = (latest - origin) // bucket_width + 1
    grid = BucketGrid(origin=origin, bucket_width=bucket_width, n_buckets=n_buckets)

    indices_by_key_bucket: dict[EntityKey, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    reasons_by_key_bucket: dict[EntityKey, dict[int, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )

    for idx, event in enumerate(events):
        key = key_fn(event)
        bucket_index = grid.index_of(bucket_of[idx])
        indices_by_key_bucket[key][bucket_index].append(idx)
        reasons_by_key_bucket[key][bucket_index][event.error_reason] += 1

    result: dict[EntityKey, EntitySeries] = {}
    for key, bucket_map in indices_by_key_bucket.items():
        counts = tuple(len(bucket_map.get(i, ())) for i in range(n_buckets))
        event_indices_by_bucket = {i: tuple(idxs) for i, idxs in bucket_map.items()}
        reason_counts_by_bucket = {
            i: dict(counter) for i, counter in reasons_by_key_bucket[key].items()
        }
        result[key] = EntitySeries(
            entity=key,
            grid=grid,
            counts=counts,
            event_indices_by_bucket=event_indices_by_bucket,
            reason_counts_by_bucket=reason_counts_by_bucket,
        )
    return result
