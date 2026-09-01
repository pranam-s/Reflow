"""Tests for reflow.webhook.dedup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from reflow.webhook.dedup import (
    DEFAULT_MAX_TRACKED_EVENTS,
    DEFAULT_TTL,
    WebhookEventDeduplicator,
)

_T0 = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


def test_first_sighting_of_an_event_id_is_not_a_duplicate() -> None:
    deduplicator = WebhookEventDeduplicator()

    assert deduplicator.seen_before("evt_1", now=_T0) is False
    assert len(deduplicator) == 1


def test_replayed_event_id_within_ttl_is_a_duplicate() -> None:
    deduplicator = WebhookEventDeduplicator()

    assert deduplicator.seen_before("evt_1", now=_T0) is False
    assert deduplicator.seen_before("evt_1", now=_T0 + timedelta(minutes=5)) is True
    assert len(deduplicator) == 1


def test_distinct_event_ids_are_tracked_independently() -> None:
    deduplicator = WebhookEventDeduplicator()

    assert deduplicator.seen_before("evt_1", now=_T0) is False
    assert deduplicator.seen_before("evt_2", now=_T0) is False
    assert deduplicator.seen_before("evt_1", now=_T0) is True
    assert deduplicator.seen_before("evt_2", now=_T0) is True


def test_an_event_id_ages_out_after_its_ttl_elapses() -> None:
    deduplicator = WebhookEventDeduplicator(ttl=timedelta(hours=24))

    assert deduplicator.seen_before("evt_1", now=_T0) is False
    just_before_expiry = _T0 + timedelta(hours=24) - timedelta(seconds=1)
    assert deduplicator.seen_before("evt_1", now=just_before_expiry) is True
    just_after_expiry = _T0 + timedelta(hours=24, seconds=1)
    assert deduplicator.seen_before("evt_1", now=just_after_expiry) is False
    assert len(deduplicator) == 1


def test_a_duplicate_sighting_does_not_extend_its_own_ttl() -> None:
    deduplicator = WebhookEventDeduplicator(ttl=timedelta(hours=24))

    assert deduplicator.seen_before("evt_1", now=_T0) is False
    assert deduplicator.seen_before("evt_1", now=_T0 + timedelta(hours=23)) is True
    after_original_ttl = _T0 + timedelta(hours=24, seconds=1)
    assert deduplicator.seen_before("evt_1", now=after_original_ttl) is False


def test_capacity_eviction_drops_the_oldest_tracked_id_first() -> None:
    deduplicator = WebhookEventDeduplicator(max_tracked_events=2)

    assert deduplicator.seen_before("evt_1", now=_T0) is False
    assert deduplicator.seen_before("evt_2", now=_T0) is False
    assert deduplicator.seen_before("evt_3", now=_T0) is False

    assert len(deduplicator) == 2
    assert deduplicator.seen_before("evt_1", now=_T0) is False
    assert deduplicator.seen_before("evt_3", now=_T0) is True


def test_expired_entries_are_pruned_before_a_capacity_check_would_evict_a_live_one() -> None:
    deduplicator = WebhookEventDeduplicator(max_tracked_events=2, ttl=timedelta(minutes=10))

    assert deduplicator.seen_before("evt_1", now=_T0) is False
    assert deduplicator.seen_before("evt_2", now=_T0 + timedelta(minutes=20)) is False

    assert len(deduplicator) == 1
    assert deduplicator.seen_before("evt_2", now=_T0 + timedelta(minutes=20)) is True


def test_defaults_match_documented_razorpay_retry_window() -> None:
    assert timedelta(hours=24) == DEFAULT_TTL
    assert DEFAULT_MAX_TRACKED_EVENTS == 100_000


def test_now_defaults_to_the_real_current_time() -> None:
    deduplicator = WebhookEventDeduplicator()

    assert deduplicator.seen_before("evt_live") is False
    assert deduplicator.seen_before("evt_live") is True
