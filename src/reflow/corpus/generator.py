"""Top-level, deterministic, streaming corpus generation.

:func:`generate_corpus` is the single public entry point for Phase 1's
synthetic corpus. Given a seed, it deterministically produces the same
sequence of :class:`~reflow.corpus.events.PaymentEvent` every time -- this
is asserted directly in ``tests/corpus/test_generator.py`` by comparing two
runs with the same seed byte-for-byte (via each event's field tuple).

**Streaming design and its one deliberate compromise.** The public API is
a generator, and the expensive part of building each event (noise-token
generation, description rendering, dataclass construction) happens lazily,
one event at a time, as the caller iterates. The one thing that *is*
materialised eagerly is a list of ``n_events`` lightweight scheduling
tuples (:class:`_Slot`: a timestamp plus a handful of small values) so
that background traffic and downtime-window traffic can be merged into one
chronologically ordered stream. At 50,000 events this list is on the order
of a few megabytes, not the tens-to-hundreds of megabytes a list of fully
rendered :class:`~reflow.corpus.events.PaymentEvent` objects (each holding
several description-length strings) would cost. This trade-off is stated
here rather than hidden: a fully constant-memory design is possible (e.g.
a k-way merge of independent generators keyed by next-timestamp) but was
judged not worth the added complexity for a one-time, bounded-size corpus
build.

**Retry chains.** ``attempt_number`` and ``customer_id`` are not
independent per event: a bounded pool of synthetic customers is reused
across events, and, walking the schedule in chronological order, each
customer has a chance (:data:`RETRY_CONTINUATION_PROBABILITY`) of
continuing their most recent still-open order (same ``order_id``, same
``method``, incremented ``attempt_number``, capped at
:data:`MAX_ATTEMPT_NUMBER`) rather than starting a fresh one. This is a
simplification -- real customers sometimes switch method or instrument
between retries, which this generator does not model -- but it gives
``attempt_number`` > 1 events a real shared ``order_id`` with their
earlier attempt, rather than being a free-floating, meaningless counter.

**Outlier tagging.** :func:`_compute_outlier_keys` is the one piece of the
second corpus-design addendum that lives here rather than in
:mod:`reflow.corpus.reasons` or :mod:`reflow.corpus.events`: whether a
``(method, reason)`` pair is rare enough to be a genuine singleton is a
property of the *realized* corpus, not something that can be decided from
the reason table alone. It is computed from the already-materialised
``_Slot`` list before the lazy event stream starts, which is why the
eager-scheduling compromise above pays for itself twice over.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from reflow.corpus.downtime import DowntimeWindow, generate_downtime_windows
from reflow.corpus.events import PaymentEvent, build_event
from reflow.corpus.methods import sample_method, sample_upi_flow
from reflow.corpus.reasons import (
    CATCH_ALL_REASONS,
    reason_pool_for_method,
    unique_reason_records,
    zipf_weights,
)
from reflow.corpus.split import assign_splits
from reflow.corpus.tokens import random_id, random_timestamp
from reflow.taxonomy.methods import PaymentMethod, UpiFlow
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import ReasonRecord, parse_reason_records
from reflow.taxonomy.remediation import RemediationClass, classify_reasons

DEFAULT_N_EVENTS: int = 50_000

CORPUS_PERIOD_END: datetime = datetime(2026, 8, 22)
CORPUS_PERIOD_START: datetime = CORPUS_PERIOD_END - timedelta(days=30)
"""The synthetic observation window. Fixed (not "now") so that generation
never depends on the wall clock, which determinism requires."""

DOWNTIME_EVENT_SHARE: float = 0.20
"""Target fraction of all events attributable to some downtime window,
rather than an ordinary idiosyncratic failure. Chosen as a plausible
middle ground: real payment platforms do see meaningful correlated-outage
traffic, but most failed payments, most of the time, are unrelated,
one-off customer/instrument problems."""

RETRY_CONTINUATION_PROBABILITY: float = 0.35
MAX_ATTEMPT_NUMBER: int = 5
_WINDOWS_PER_THOUSAND_EVENTS: int = 1
_MIN_WINDOWS: int = 10

OUTLIER_MAX_COUNT: int = 2
"""A ``(method, reason)`` pair occurring at most this many times among
background (non-downtime) slots in one generated corpus is tagged
``is_outlier=True`` on its event(s): a genuine one-off occurrence, not
a cluster, and exactly the kind of case a density-based method such as
HDBSCAN should be allowed to call noise rather than being penalised for
not placing in a cluster of its own. Catch-all reasons are never eligible
(see :attr:`reflow.corpus.events.PaymentEvent.is_outlier`), and downtime-
window events are never eligible either, since by construction they share
their window's cause with other events in the same window."""


@dataclass(frozen=True, slots=True)
class _Slot:
    """One scheduled event, before the expensive fields are rendered."""

    created_at: datetime
    method: PaymentMethod
    upi_flow: UpiFlow | None
    reason: str
    downtime_window_id: str | None
    forced_bank: str | None


def _build_reason_index(
    records: list[ReasonRecord],
) -> tuple[dict[str, ReasonRecord], dict[str, RemediationClass | None]]:
    """Build reason-code-keyed lookups from the 114 parsed records.

    Args:
        records: All 114 parsed reason records, in file order.

    Returns:
        A tuple of (reason -> representative :class:`ReasonRecord`, reason
        -> remediation class or ``None``), both keyed by unique reason
        code and both resolved to each reason's first occurrence in file
        order when the code repeats.
    """
    record_by_reason = {record.reason: record for record in unique_reason_records(records)}
    remediation_by_reason: dict[str, RemediationClass | None] = {}
    for classification in classify_reasons(records):
        remediation_by_reason.setdefault(classification.reason, classification.remediation_class)
    return record_by_reason, remediation_by_reason


def _build_method_pools(
    records: list[ReasonRecord],
) -> dict[PaymentMethod, tuple[tuple[str, ...], list[float]]]:
    """Build each method's Zipf-weighted reason pool.

    Args:
        records: All 114 parsed reason records, in file order.

    Returns:
        A mapping from method to (ordered reason codes, matching Zipf
        weights), ready for :func:`random.Random.choices`.
    """
    pools: dict[PaymentMethod, tuple[tuple[str, ...], list[float]]] = {}
    for method in PaymentMethod:
        pool = tuple(reason_pool_for_method(method, records))
        pools[method] = (pool, zipf_weights(len(pool)))
    return pools


def _schedule_slots(
    rng: random.Random,
    n_events: int,
    windows: list[DowntimeWindow],
    method_pools: dict[PaymentMethod, tuple[tuple[str, ...], list[float]]],
) -> list[_Slot]:
    """Decide, for every event, its timestamp/method/reason/window.

    Args:
        rng: Deterministic random source.
        n_events: Total number of slots to schedule.
        windows: Available downtime windows to draw correlated slots from.
        method_pools: Each method's Zipf-weighted reason pool.

    Returns:
        ``n_events`` :class:`_Slot`, sorted by ``created_at``.
    """
    n_downtime = round(n_events * DOWNTIME_EVENT_SHARE) if windows else 0
    n_background = n_events - n_downtime

    slots: list[_Slot] = []

    if windows:
        window_weights = [window.duration_seconds() for window in windows]
        for _ in range(n_downtime):
            window = rng.choices(windows, weights=window_weights, k=1)[0]
            reason = rng.choice(window.reason_mixture)
            timestamp = random_timestamp(rng, window.start, window.end)
            upi_flow = sample_upi_flow(rng) if window.method is PaymentMethod.UPI else None
            slots.append(
                _Slot(timestamp, window.method, upi_flow, reason, window.window_id, window.bank)
            )

    for _ in range(n_background):
        method = sample_method(rng)
        upi_flow = sample_upi_flow(rng) if method is PaymentMethod.UPI else None
        pool, weights = method_pools[method]
        reason = rng.choices(pool, weights=weights, k=1)[0]
        timestamp = random_timestamp(rng, CORPUS_PERIOD_START, CORPUS_PERIOD_END)
        slots.append(_Slot(timestamp, method, upi_flow, reason, None, None))

    slots.sort(key=lambda slot: slot.created_at)
    return slots


def _compute_outlier_keys(slots: list[_Slot]) -> frozenset[tuple[PaymentMethod, str]]:
    """Determine which ``(method, reason)`` pairs are genuine singletons.

    Args:
        slots: The full schedule from :func:`_schedule_slots`.

    Returns:
        Every ``(method, reason)`` pair that occurs at most
        :data:`OUTLIER_MAX_COUNT` times among background (non-downtime)
        slots and is not a :data:`~reflow.corpus.reasons.CATCH_ALL_REASONS`
        member.
    """
    counts: Counter[tuple[PaymentMethod, str]] = Counter()
    for slot in slots:
        if slot.downtime_window_id is None and slot.reason not in CATCH_ALL_REASONS:
            counts[(slot.method, slot.reason)] += 1
    return frozenset(key for key, count in counts.items() if count <= OUTLIER_MAX_COUNT)


def _event_stream(
    rng: random.Random,
    slots: list[_Slot],
    record_by_reason: dict[str, ReasonRecord],
    remediation_by_reason: dict[str, RemediationClass | None],
    customer_pool: list[str],
    outlier_keys: frozenset[tuple[PaymentMethod, str]],
) -> Iterator[PaymentEvent]:
    """Lazily build one :class:`PaymentEvent` per scheduled slot.

    Args:
        rng: Deterministic random source.
        slots: The chronologically sorted schedule from
            :func:`_schedule_slots`.
        record_by_reason: Reason-code-keyed representative records.
        remediation_by_reason: Reason-code-keyed remediation classes.
        customer_pool: Fixed pool of synthetic customer ids to draw from.
        outlier_keys: ``(method, reason)`` pairs to tag ``is_outlier=True``,
            from :func:`_compute_outlier_keys`.

    Yields:
        One :class:`PaymentEvent` per slot, in chronological order, with
        ``customer_id``/``order_id``/``attempt_number`` linked into retry
        chains as described in the module docstring.
    """
    open_orders: dict[str, tuple[str, int, PaymentMethod]] = {}
    for slot in slots:
        customer_id = rng.choice(customer_pool)
        open_order = open_orders.get(customer_id)
        if (
            open_order is not None
            and open_order[2] is slot.method
            and open_order[1] < MAX_ATTEMPT_NUMBER
            and rng.random() < RETRY_CONTINUATION_PROBABILITY
        ):
            order_id = open_order[0]
            attempt_number = open_order[1] + 1
        else:
            order_id = random_id(rng, "order")
            attempt_number = 1
        open_orders[customer_id] = (order_id, attempt_number, slot.method)

        yield build_event(
            rng=rng,
            reason_record=record_by_reason[slot.reason],
            remediation_class=remediation_by_reason.get(slot.reason),
            method=slot.method,
            upi_flow=slot.upi_flow,
            created_at=slot.created_at,
            customer_id=customer_id,
            attempt_number=attempt_number,
            downtime_window_id=slot.downtime_window_id,
            forced_bank=slot.forced_bank,
            forced_order_id=order_id,
            is_outlier=(slot.method, slot.reason) in outlier_keys,
        )


def generate_corpus(
    seed: int,
    n_events: int = DEFAULT_N_EVENTS,
    reason_records: list[ReasonRecord] | None = None,
) -> Iterator[PaymentEvent]:
    """Generate a deterministic, streaming synthetic failed-payment corpus.

    Args:
        seed: Seed for the single :class:`random.Random` instance driving
            every random decision in this corpus. Identical ``seed`` and
            ``n_events`` reproduce a byte-identical event sequence.
        n_events: Total number of events to generate.
        reason_records: Pre-parsed reason records, mainly for tests that
            want to avoid re-parsing the vendored spreadsheet on every
            call. Defaults to parsing
            ``data/razorpay_error_reasons.xlsx`` from the repository root.

    Yields:
        ``n_events`` :class:`~reflow.corpus.events.PaymentEvent`, in
        chronological order by ``created_at``, each with ``split`` set to
        ``"train"`` or ``"test"``.

    Note:
        Uses :class:`random.Random`, which ruff's ``S311`` rule flags as
        unsuitable for cryptographic use; suppressed below (``# noqa:
        S311``) because this is deterministic synthetic-data generation,
        not a security-sensitive context -- reproducibility from a seeded
        PRNG is the entire point.
    """
    if n_events <= 0:
        return

    rng = random.Random(seed)  # noqa: S311
    records = reason_records or parse_reason_records(
        resolve_vendored_path(Path(__file__).resolve().parents[3])
    )
    record_by_reason, remediation_by_reason = _build_reason_index(records)
    method_pools = _build_method_pools(records)

    n_windows = max(_MIN_WINDOWS, (n_events * _WINDOWS_PER_THOUSAND_EVENTS) // 1000)
    windows = generate_downtime_windows(rng, n_windows, CORPUS_PERIOD_START, CORPUS_PERIOD_END)

    slots = _schedule_slots(rng, n_events, windows, method_pools)
    outlier_keys = _compute_outlier_keys(slots)

    customer_pool_size = max(1, n_events // 3)
    customer_pool = [random_id(rng, "cust") for _ in range(customer_pool_size)]

    events = _event_stream(
        rng, slots, record_by_reason, remediation_by_reason, customer_pool, outlier_keys
    )
    yield from assign_splits(rng, events, windows)
