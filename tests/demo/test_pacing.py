"""Tests for reflow.demo.pacing."""

from __future__ import annotations

import time
from unittest.mock import patch

from reflow.demo.pacing import FAST, PACED, Pace, pause


def test_fast_pace_has_zero_total_seconds() -> None:
    assert FAST.total_seconds == 0.0


def test_paced_pace_is_within_the_2_5_to_3_minute_target() -> None:
    assert 150.0 <= PACED.total_seconds <= 180.0


def test_paced_pace_gives_the_guardrail_beat_the_most_time() -> None:
    fields = (
        PACED.intro_seconds,
        PACED.corpus_seconds,
        PACED.root_cause_seconds,
        PACED.incident_seconds,
        PACED.routing_seconds,
        PACED.results_seconds,
        PACED.limitations_seconds,
        PACED.outro_seconds,
    )
    assert PACED.guardrail_seconds >= max(fields)


def test_pause_does_not_sleep_for_zero_seconds() -> None:
    with patch("time.sleep") as mock_sleep:
        pause(0.0)

    mock_sleep.assert_not_called()


def test_pause_sleeps_for_a_positive_duration() -> None:
    with patch("time.sleep") as mock_sleep:
        pause(2.5)

    mock_sleep.assert_called_once_with(2.5)


def test_running_a_full_fast_pace_takes_negligible_wall_clock_time() -> None:
    custom = Pace(
        intro_seconds=0.0,
        corpus_seconds=0.0,
        root_cause_seconds=0.0,
        incident_seconds=0.0,
        routing_seconds=0.0,
        guardrail_seconds=0.0,
        results_seconds=0.0,
        limitations_seconds=0.0,
        outro_seconds=0.0,
    )
    start = time.monotonic()
    for value in (
        custom.intro_seconds,
        custom.corpus_seconds,
        custom.root_cause_seconds,
        custom.incident_seconds,
        custom.routing_seconds,
        custom.guardrail_seconds,
        custom.results_seconds,
        custom.limitations_seconds,
        custom.outro_seconds,
    ):
        pause(value)
    assert time.monotonic() - start < 1.0
