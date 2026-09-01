"""Tests for reflow.report.html."""

from __future__ import annotations

from reflow.report.data import DEFAULT_OUTPUT_PATH, load_report_data
from reflow.report.html import _bar_chart_figure, _esc, _table, build_report_html
from reflow.report.validate import validate_report_html


def test_esc_escapes_html_special_characters() -> None:
    assert _esc("<script>alert('x')</script>") == (
        "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
    )


def test_esc_converts_non_string_values() -> None:
    assert _esc(42) == "42"
    assert _esc(0.86056) == "0.86056"


def test_bar_chart_figure_handles_all_zero_values_without_dividing_by_zero() -> None:
    figure = _bar_chart_figure(rows=[("a", 0.0), ("b", 0.0)], value_format=".0f", aria_label="test")

    assert "width:0.00%" in figure
    assert "aria-hidden='true'" in figure


def test_bar_chart_figure_scales_the_largest_bar_to_full_width() -> None:
    figure = _bar_chart_figure(
        rows=[("a", 10.0), ("b", 5.0)], value_format=".0f", aria_label="test"
    )

    assert "width:100.00%" in figure
    assert "width:50.00%" in figure


def test_table_escapes_column_headers_and_caption() -> None:
    table = _table(
        table_id="t1",
        caption="<caption> & things",
        column_headers=["<col>"],
        rows=[["row1"]],
    )

    assert "&lt;caption&gt;" in table
    assert "&lt;col&gt;" in table
    assert "scope='row'" in table
    assert "scope='col'" in table


def test_build_report_html_against_real_committed_data_passes_every_validator_check() -> None:
    data = load_report_data()

    html_text = build_report_html(data)
    result = validate_report_html(html_text)

    assert result.all_passed, result.failures


def test_build_report_html_states_the_key_headline_numbers() -> None:
    data = load_report_data()

    html_text = build_report_html(data)

    assert "50,000" in html_text
    assert "114-row" in html_text
    assert "86.056%" in html_text
    assert "128" in html_text
    assert data.demo.guardrail_payment_id in html_text
    assert "BELOW baseline (no signal to find)" in html_text
    assert "reflow.webhook.dedup" in html_text
    assert "1,552" in html_text


def test_build_report_html_never_mentions_a_network_call_or_credential() -> None:
    data = load_report_data()

    html_text = build_report_html(data)

    assert "No network call, credential, or LLM call was" in html_text


def test_committed_report_matches_the_generator_output() -> None:
    data = load_report_data()

    regenerated = build_report_html(data)
    committed = DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8")

    assert committed == regenerated
