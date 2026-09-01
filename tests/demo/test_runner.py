"""Tests for reflow.demo.runner."""

from __future__ import annotations

import io
import time
from unittest.mock import patch

from rich.console import Console

from reflow.demo.pacing import FAST, PACED
from reflow.demo.runner import run_demo
from tests.demo.factories import make_demo_data


def _console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, width=300), buffer


def test_run_demo_at_fast_pace_prints_every_beat_and_sleeps_never() -> None:
    console, buffer = _console()
    data = make_demo_data()

    with patch("time.sleep") as mock_sleep:
        run_demo(console=console, data=data, pace=FAST)

    mock_sleep.assert_not_called()
    output = buffer.getvalue()
    assert "reflow demo" in output
    assert data.guardrail_payment_id in output
    assert "BLOCKED" in output
    assert "reflow demo -- end" in output


def test_run_demo_sublabels_the_embedded_replay_so_numbering_never_collides() -> None:
    console, buffer = _console()
    data = make_demo_data()

    run_demo(console=console, data=data, pace=FAST)

    output = buffer.getvalue()
    assert "5. The guardrail refusing to act" in output
    assert "5a. Payment" in output
    assert "5f. Execution outcome" in output
    assert "5. (continued)" in output
    assert "6. Results: reflow vs. baselines" in output
    assert "1. Payment" not in output


def test_run_demo_at_fast_pace_completes_in_negligible_wall_clock_time() -> None:
    console, _buffer = _console()
    data = make_demo_data()

    start = time.monotonic()
    run_demo(console=console, data=data, pace=FAST)

    assert time.monotonic() - start < 2.0


def test_run_demo_output_is_pure_ascii() -> None:
    console, buffer = _console()
    data = make_demo_data()

    run_demo(console=console, data=data, pace=FAST)

    output = buffer.getvalue()
    assert all(ord(character) < 128 for character in output)


def test_run_demo_at_paced_pace_sleeps_for_every_beat() -> None:
    console, _buffer = _console()
    data = make_demo_data()

    with patch("time.sleep") as mock_sleep:
        run_demo(console=console, data=data, pace=PACED)

    slept_seconds = [call.args[0] for call in mock_sleep.call_args_list]
    assert sum(slept_seconds) == PACED.total_seconds
    assert len(slept_seconds) == 9
