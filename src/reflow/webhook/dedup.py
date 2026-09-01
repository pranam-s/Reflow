"""A bounded, expiring seen-event-id store for webhook delivery deduplication.

**The gap this closes, stated precisely.** Razorpay's webhook documentation
(fetched live, 2026-09-01,
<https://razorpay.com/docs/webhooks/best-practices/>) states that "every
event that receives a non-2xx response is considered an event delivery
failure," and that Razorpay "retr[ies] the delivery in exponential backoff
policy for 24 hours after event creation timestamp," disabling the webhook
only if every retry fails for that entire 24-hour window. The same page
states plainly that "there could be scenarios where your endpoint might
receive the same webhook event multiple times. This is an expected
behaviour based on the webhook design," driven by at-least-once delivery
semantics and a five-second delivery timeout, and names the mechanism a
consumer is expected to use to tell deliveries apart: "check the value of
the `x-razorpay-event-id` in the webhook request header. The value for this
header is unique per event and can help you determine the duplicity of a
webhook event."

This project already has :meth:`reflow.taxonomy.signal.FailureSignal.from_webhook_payment_entity`
(typed parsing of a ``payment.failed`` webhook body) and typed models for
downtime webhooks (:mod:`reflow.incident.downtime_api`), but **no live HTTP
endpoint anywhere in this codebase that receives a Razorpay webhook** --
every event this project ever diagnoses comes from the generated corpus
(:mod:`reflow.corpus`) or a committed report, never a real inbound request.
Consequently, nothing here has ever double-fired a recovery action on a
replayed delivery, because nothing here has ever received one. This is
reported plainly as a **production-readiness gap, not a live bug**: the
day a real webhook consumer is built, it will receive genuinely duplicate
deliveries by Razorpay's own documented design, and it will need to reject
a replay before it reaches :mod:`reflow.policy` a second time for the same
event, or a single bank-side failure could trigger two recovery actions
(e.g. two Payment Links) for one payment.

**What this module provides, and what it deliberately does not.**
:class:`WebhookEventDeduplicator` is the one primitive a future consumer
would need: given an ``x-razorpay-event-id`` value, tell the caller whether
it has been seen before, bounded in both size (a fixed maximum number of
tracked ids, oldest evicted first) and time (an entry ages out after a
configurable TTL, defaulting to the 24 hours Razorpay itself documents as
its own retry window, so this store never needs to remember an id longer
than Razorpay could plausibly still be retrying it). It does not parse a
webhook body, verify a webhook signature, expose an HTTP endpoint, or
persist its state anywhere -- none of those exist in this project, and
none are built here. A real consumer would call
:meth:`WebhookEventDeduplicator.seen_before` with the request's
``x-razorpay-event-id`` header value before doing anything else, and
short-circuit (return a ``2xx`` immediately, taking no further action) on
``True``.

**Why a fixed 24-hour window, not a sliding one.** A duplicate sighting
does not extend that event id's own retention past its original
first-seen timestamp plus the TTL. Razorpay's own documentation retries
"for 24 hours after event creation timestamp," not for 24 hours after the
most recent delivery attempt, so a sliding, per-delivery-refreshed window
would track an id for longer than Razorpay could ever plausibly still be
retrying it, unboundedly, for an endpoint under sustained retry pressure.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

DEFAULT_TTL: timedelta = timedelta(hours=24)
"""Matches Razorpay's own documented webhook retry window (see module
docstring): an event id is never worth remembering longer than Razorpay
could plausibly still be redelivering it."""

DEFAULT_MAX_TRACKED_EVENTS: int = 100_000
"""A generous default bound on memory, independent of the TTL, so a store
that somehow never gets pruned by time (e.g. a consumer that never calls
:meth:`WebhookEventDeduplicator.seen_before` again after a burst) still
cannot grow without limit."""


@dataclass(slots=True)
class WebhookEventDeduplicator:
    """A bounded, TTL-expiring set of already-seen webhook event ids.

    Not thread-safe: a real HTTP consumer serving concurrent requests would
    need to guard calls to :meth:`seen_before` with its own lock, exactly as
    it would for any other in-process mutable state -- this module does not
    assume or provide one, since none of this project's own code is
    multi-threaded.

    Attributes:
        ttl: How long an event id is remembered after it is first seen.
            Defaults to :data:`DEFAULT_TTL`.
        max_tracked_events: The maximum number of event ids retained at
            once; the oldest (by first-seen order) is evicted once this is
            exceeded. Defaults to :data:`DEFAULT_MAX_TRACKED_EVENTS`.
    """

    ttl: timedelta = DEFAULT_TTL
    max_tracked_events: int = DEFAULT_MAX_TRACKED_EVENTS
    _first_seen_at: OrderedDict[str, datetime] = field(default_factory=OrderedDict, repr=False)

    def seen_before(self, event_id: str, *, now: datetime | None = None) -> bool:
        """Check whether ``event_id`` was already seen, recording it if not.

        Every call first prunes any tracked id whose TTL has elapsed as of
        ``now``, so an id that aged out is correctly treated as new again --
        matching Razorpay's own behaviour of eventually giving up on a
        delivery and, in principle, being free to reuse identifiers far
        enough apart in time that this project has no way to observe reuse
        happening in practice.

        Args:
            event_id: The webhook request's ``x-razorpay-event-id`` header
                value.
            now: The current time, for reproducible tests. Defaults to
                ``datetime.now(UTC)``.

        Returns:
            ``True`` if ``event_id`` was already tracked and not yet
            expired (the caller should treat this delivery as a replay and
            take no further action); ``False`` if this is the first time
            ``event_id`` has been seen within its TTL (the caller should
            proceed, and this id is now recorded).
        """
        current = now if now is not None else datetime.now(UTC)
        self._evict_expired(current)
        if event_id in self._first_seen_at:
            return True
        self._first_seen_at[event_id] = current
        self._evict_over_capacity()
        return False

    def _evict_expired(self, now: datetime) -> None:
        """Drop every tracked id whose TTL has elapsed as of ``now``.

        Args:
            now: The current time to measure expiry against.
        """
        cutoff = now - self.ttl
        while self._first_seen_at:
            oldest_id, oldest_at = next(iter(self._first_seen_at.items()))
            if oldest_at > cutoff:
                break
            del self._first_seen_at[oldest_id]

    def _evict_over_capacity(self) -> None:
        """Drop the oldest tracked ids until at or under the capacity bound."""
        while len(self._first_seen_at) > self.max_tracked_events:
            self._first_seen_at.popitem(last=False)

    def __len__(self) -> int:
        """Return the number of event ids currently tracked (not yet expired or evicted).

        Returns:
            The current tracked-id count.
        """
        return len(self._first_seen_at)
