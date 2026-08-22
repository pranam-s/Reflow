"""Tests for reflow.corpus.downtime."""

import random
from datetime import datetime, timedelta

from reflow.corpus.downtime import (
    _MAX_DURATION,
    _METHODS_WITH_NAMED_BANK,
    _MIN_DURATION,
    generate_downtime_windows,
)
from reflow.taxonomy.methods import PaymentMethod

PERIOD_START = datetime(2026, 1, 1)
PERIOD_END = PERIOD_START + timedelta(days=30)


def test_generate_downtime_windows_returns_requested_count() -> None:
    rng = random.Random(1)
    windows = generate_downtime_windows(rng, 25, PERIOD_START, PERIOD_END)
    assert len(windows) == 25


def test_windows_are_sorted_by_start() -> None:
    rng = random.Random(2)
    windows = generate_downtime_windows(rng, 30, PERIOD_START, PERIOD_END)
    starts = [window.start for window in windows]
    assert starts == sorted(starts)


def test_windows_fall_within_period_and_respect_duration_bounds() -> None:
    rng = random.Random(3)
    windows = generate_downtime_windows(rng, 40, PERIOD_START, PERIOD_END)
    for window in windows:
        assert PERIOD_START <= window.start < PERIOD_END
        assert window.start < window.end <= PERIOD_END
        duration = window.end - window.start
        assert _MIN_DURATION <= duration <= _MAX_DURATION


def test_windows_carry_a_multi_reason_mixture() -> None:
    rng = random.Random(4)
    windows = generate_downtime_windows(rng, 40, PERIOD_START, PERIOD_END)
    for window in windows:
        assert len(window.reason_mixture) >= 3
        assert len(set(window.reason_mixture)) == len(window.reason_mixture)


def test_bank_is_named_only_for_bank_relevant_methods() -> None:
    rng = random.Random(5)
    windows = generate_downtime_windows(rng, 60, PERIOD_START, PERIOD_END)
    for window in windows:
        if window.method in _METHODS_WITH_NAMED_BANK:
            assert window.bank is not None
        else:
            assert window.bank is None


def test_window_ids_are_unique() -> None:
    rng = random.Random(6)
    windows = generate_downtime_windows(rng, 100, PERIOD_START, PERIOD_END)
    ids = [window.window_id for window in windows]
    assert len(ids) == len(set(ids))


def test_generation_is_deterministic_for_same_seed() -> None:
    first = generate_downtime_windows(random.Random(77), 20, PERIOD_START, PERIOD_END)
    second = generate_downtime_windows(random.Random(77), 20, PERIOD_START, PERIOD_END)
    assert first == second


def test_contains_and_duration_seconds() -> None:
    rng = random.Random(8)
    windows = generate_downtime_windows(rng, 5, PERIOD_START, PERIOD_END)
    window = windows[0]
    assert window.contains(window.start)
    assert not window.contains(window.end)
    assert window.duration_seconds() == (window.end - window.start).total_seconds()


def test_all_configured_methods_are_reachable() -> None:
    rng = random.Random(9)
    windows = generate_downtime_windows(rng, 3_000, PERIOD_START, PERIOD_END)
    seen_methods = {window.method for window in windows}
    assert seen_methods == set(PaymentMethod)
