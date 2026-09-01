"""Tests for reflow.report.validate."""

from __future__ import annotations

import pytest

from reflow.report import colors
from reflow.report.validate import ValidationResult, validate_report_html

_MINIMAL_VALID_DOCUMENT = """<!DOCTYPE html>
<html lang="en">
<head><title>Test report</title></head>
<body>
<h1>Title</h1>
<h2>Section</h2>
<h3>Subsection</h3>
<figure class="bar-chart" aria-hidden="true"></figure>
<table id="t1"><caption>Caption</caption>
<thead><tr><th scope="col">A</th></tr></thead>
<tbody><tr><th scope="row">B</th><td>1</td></tr></tbody>
</table>
</body>
</html>
"""


def _check_by_name(result: ValidationResult, name: str) -> bool:
    return next(check for check in result.checks if check.name == name).passed


def test_minimal_valid_document_passes_every_structural_check() -> None:
    result = validate_report_html(_MINIMAL_VALID_DOCUMENT)

    assert _check_by_name(result, "lang_and_title")
    assert _check_by_name(result, "heading_order")
    assert _check_by_name(result, "tables_have_captions")
    assert _check_by_name(result, "th_scopes_valid")
    assert _check_by_name(result, "images_have_alt")
    assert _check_by_name(result, "charts_aria_hidden")
    assert _check_by_name(result, "charts_paired_with_tables")
    assert _check_by_name(result, "self_contained")
    assert _check_by_name(result, "unique_ids")


def test_missing_html_lang_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace('lang="en"', "")

    result = validate_report_html(document)

    assert not _check_by_name(result, "lang_and_title")


def test_missing_title_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace("<title>Test report</title>", "")

    result = validate_report_html(document)

    assert not _check_by_name(result, "lang_and_title")


def test_missing_h1_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace("<h1>Title</h1>", "")

    result = validate_report_html(document)

    assert not _check_by_name(result, "heading_order")


def test_two_h1_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace("<h1>Title</h1>", "<h1>Title</h1><h1>Again</h1>")

    result = validate_report_html(document)

    assert not _check_by_name(result, "heading_order")


def test_heading_level_skip_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace("<h2>Section</h2>", "")

    result = validate_report_html(document)

    assert not _check_by_name(result, "heading_order")


def test_table_without_caption_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace("<caption>Caption</caption>", "")

    result = validate_report_html(document)

    assert not _check_by_name(result, "tables_have_captions")


def test_th_without_scope_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace('<th scope="col">A</th>', "<th>A</th>")

    result = validate_report_html(document)

    assert not _check_by_name(result, "th_scopes_valid")


def test_th_with_invalid_scope_value_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace(
        '<th scope="row">B</th>', '<th scope="banana">B</th>'
    )

    result = validate_report_html(document)

    assert not _check_by_name(result, "th_scopes_valid")


def test_img_without_alt_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace("<body>", "<body><img src='local.png'>")

    result = validate_report_html(document)

    assert not _check_by_name(result, "images_have_alt")


def test_img_with_alt_passes() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace(
        "<body>", "<body><img src='local.png' alt='a picture'>"
    )

    result = validate_report_html(document)

    assert _check_by_name(result, "images_have_alt")


def test_chart_without_aria_hidden_fails() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace(
        '<figure class="bar-chart" aria-hidden="true"></figure>',
        '<figure class="bar-chart"></figure>',
    )

    result = validate_report_html(document)

    assert not _check_by_name(result, "charts_aria_hidden")


def test_chart_not_followed_by_a_table_fails() -> None:
    document = """<!DOCTYPE html>
<html lang="en"><head><title>T</title></head><body>
<h1>Title</h1>
<figure class="bar-chart" aria-hidden="true"></figure>
<h2>Next section, no table in between</h2>
<table><caption>c</caption><tr><th scope="col">a</th></tr></table>
</body></html>"""

    result = validate_report_html(document)

    assert not _check_by_name(result, "charts_paired_with_tables")


def test_script_tag_fails_self_contained() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace("<body>", "<body><script>alert(1)</script>")

    result = validate_report_html(document)

    assert not _check_by_name(result, "self_contained")


def test_link_tag_fails_self_contained() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace(
        "<head>", "<head><link rel='stylesheet' href='style.css'>"
    )

    result = validate_report_html(document)

    assert not _check_by_name(result, "self_contained")


def test_external_href_fails_self_contained() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace(
        "<body>", "<body><a href='https://example.com'>link</a>"
    )

    result = validate_report_html(document)

    assert not _check_by_name(result, "self_contained")


def test_duplicate_ids_fail() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace('<table id="t1">', '<table id="t1">').replace(
        "<body>", "<body><div id='t1'></div>"
    )

    result = validate_report_html(document)

    assert not _check_by_name(result, "unique_ids")


def test_wcag_contrast_fails_when_a_declared_pair_is_too_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        colors,
        "TEXT_CONTRAST_PAIRS",
        (("low contrast pair", "#777777", "#888888"),),
    )

    result = validate_report_html(_MINIMAL_VALID_DOCUMENT)

    assert not _check_by_name(result, "wcag_contrast")


def test_wcag_contrast_fails_when_a_declared_colour_is_missing_from_the_stylesheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        colors,
        "TEXT_CONTRAST_PAIRS",
        (("not present", "#123456", "#ffffff"),),
    )

    result = validate_report_html(_MINIMAL_VALID_DOCUMENT)

    assert not _check_by_name(result, "wcag_contrast")


def test_wcag_contrast_fails_when_a_graphical_pair_is_too_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(colors, "TEXT_CONTRAST_PAIRS", ())
    monkeypatch.setattr(
        colors,
        "GRAPHICAL_CONTRAST_PAIRS",
        (("low contrast graphical pair", "#777777", "#888888"),),
    )

    result = validate_report_html(_MINIMAL_VALID_DOCUMENT)

    assert not _check_by_name(result, "wcag_contrast")


def test_validation_result_failures_property_lists_only_failed_checks() -> None:
    document = _MINIMAL_VALID_DOCUMENT.replace('lang="en"', "")

    result = validate_report_html(document)

    assert len(result.failures) >= 1
    assert all(not failure.passed for failure in result.failures)
    assert result.all_passed is False
