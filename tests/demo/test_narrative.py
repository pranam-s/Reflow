"""Tests for reflow.demo.narrative."""

from __future__ import annotations

import io

from rich.console import Console

from reflow.demo import narrative
from tests.demo.factories import make_demo_data


def _render(renderable: object) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=300)
    console.print(renderable)
    return buffer.getvalue()


def test_title_screen_states_no_credentials_network_or_llm() -> None:
    text = _render(narrative.build_title_screen())

    assert "No network call" in text
    assert "no credential" in text
    assert "LLM" in text


def test_corpus_beat_states_the_taxonomy_and_event_count() -> None:
    data = make_demo_data()

    text = _render(narrative.build_corpus_beat(data.corpus))

    assert "50,000" in text
    assert "114-row" in text
    assert "110" in text


def test_root_cause_beat_states_drain3_lost_and_others_tied() -> None:
    data = make_demo_data()

    text = _render(narrative.build_root_cause_beat(data.root_cause))

    assert "WORSE than baseline" in text
    assert text.count("TIES baseline (noise, not signal)") == 2
    assert "ADR-0002" in text


def test_incident_beat_states_fragmentation_range() -> None:
    data = make_demo_data()

    text = _render(narrative.build_incident_beat(data.incident))

    assert "3.7" in text
    assert "4.6" in text
    assert "3-4 reason codes" in text


def test_routing_beat_states_split_and_total_llm_calls() -> None:
    data = make_demo_data()

    text = _render(narrative.build_routing_beat(data.routing))

    assert "86.056%" in text
    assert "128 live LLM calls" in text
    assert "43,028" in text


def test_guardrail_intro_names_the_pinned_payment_from_the_record_itself() -> None:
    data = make_demo_data()

    text = _render(narrative.build_guardrail_intro(data))

    assert data.guardrail_payment_id in text
    assert "Test Bank" in text
    assert data.guardrail_records[0].error_reason in text


def test_guardrail_outro_frames_the_refusal_as_the_key_decision() -> None:
    text = _render(narrative.build_guardrail_outro())

    assert "refusal" in text


def test_results_beat_states_the_loss_and_the_fractions() -> None:
    data = make_demo_data()

    text = _render(narrative.build_results_beat(data.results))

    assert "LESS absolute money" in text
    assert "95%" in text
    assert "71%" in text
    assert "71,874,179" in text
    assert "44,674" in text


def test_limitations_beat_states_the_oracle_and_the_opportunity_cost() -> None:
    data = make_demo_data()

    text = _render(narrative.build_limitations_beat(data.limitations))

    assert "1,552" in text
    assert "9,992" in text
    assert "1,487" in text
    assert "reflow.webhook.dedup" in text


def test_outro_screen_points_to_the_html_report_and_replay_command() -> None:
    text = _render(narrative.build_outro_screen())

    assert "docs/reports/phase8_report.html" in text
    assert "reflow replay" in text
