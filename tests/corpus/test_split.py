"""Tests for reflow.corpus.split."""

import random
from datetime import datetime

from reflow.corpus.downtime import DowntimeWindow
from reflow.corpus.events import PaymentEvent
from reflow.corpus.split import TEST, TRAIN, assign_splits
from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep, PaymentMethod


def _make_event(payment_id: str, downtime_window_id: str | None) -> PaymentEvent:
    return PaymentEvent(
        payment_id=payment_id,
        order_id=f"order_{payment_id}",
        amount=100,
        method=PaymentMethod.UPI,
        created_at=datetime(2026, 1, 1),
        customer_id="cust_1",
        attempt_number=1,
        bank="Test Bank",
        vpa="test@upi",
        card_bin=None,
        error_code=ErrorCode.BAD_REQUEST_ERROR,
        error_source=ErrorSource.CUSTOMER,
        error_step=ErrorStep.PAYMENT_INITIATION,
        error_reason="invalid_vpa",
        description="x",
        latent_subcause_id=None,
        description_variant="canonical",
        is_outlier=False,
        downtime_window_id=downtime_window_id,
        split="unassigned",
    )


def _make_window(window_id: str) -> DowntimeWindow:
    return DowntimeWindow(
        window_id=window_id,
        method=PaymentMethod.UPI,
        bank="Test Bank",
        start=datetime(2026, 1, 1),
        end=datetime(2026, 1, 1, 1),
        reason_mixture=("psp_not_available", "upi_app_technical_error", "payment_timed_out"),
    )


def test_all_events_in_one_window_get_the_same_split() -> None:
    window = _make_window("dtw_1")
    events = [_make_event(f"pay_{i}", "dtw_1") for i in range(20)]
    rng = random.Random(1)
    split_events = list(assign_splits(rng, events, [window]))
    splits = {event.split for event in split_events}
    assert len(splits) == 1
    assert splits <= {TRAIN, TEST}


def test_background_events_are_split_independently() -> None:
    events = [_make_event(f"pay_{i}", None) for i in range(500)]
    rng = random.Random(2)
    split_events = list(assign_splits(rng, events, [], test_fraction=0.2))
    splits = [event.split for event in split_events]
    assert TRAIN in splits
    assert TEST in splits
    test_share = splits.count(TEST) / len(splits)
    assert 0.1 < test_share < 0.3


def test_no_window_id_appears_in_both_splits() -> None:
    windows = [_make_window(f"dtw_{i}") for i in range(20)]
    events: list[PaymentEvent] = []
    for window in windows:
        events.extend(
            _make_event(f"{window.window_id}_pay_{i}", window.window_id) for i in range(10)
        )
    rng = random.Random(3)
    split_events = list(assign_splits(rng, events, windows, test_fraction=0.3))

    split_by_window: dict[str, set[str]] = {}
    for event in split_events:
        assert event.downtime_window_id is not None
        split_by_window.setdefault(event.downtime_window_id, set()).add(event.split)

    for window_id, splits in split_by_window.items():
        assert len(splits) == 1, f"window {window_id} leaked across splits: {splits}"


def test_assign_splits_is_deterministic_for_same_seed() -> None:
    window = _make_window("dtw_1")
    events = [_make_event(f"pay_{i}", "dtw_1" if i % 2 == 0 else None) for i in range(50)]
    first = list(assign_splits(random.Random(9), events, [window]))
    second = list(assign_splits(random.Random(9), events, [window]))
    assert [e.split for e in first] == [e.split for e in second]
