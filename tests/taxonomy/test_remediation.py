"""Tests for reflow.taxonomy.remediation.

The exact per-class counts asserted here are the test-asserted coverage
artefact required by the Phase 1 brief: they pin down, for regression
purposes, how the 114 vendored reasons distribute across remediation
classes and which reasons are honestly ambiguous.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import ReasonRecord, parse_reason_records
from reflow.taxonomy.remediation import (
    RemediationClass,
    TaxonomyDriftError,
    build_coverage_report,
    classify_reasons,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED_PATH = resolve_vendored_path(REPO_ROOT)

EXPECTED_CLASS_COUNTS = {
    RemediationClass.RETRY_SAME: 18,
    RemediationClass.WAIT: 2,
    RemediationClass.CUSTOMER_FIX: 24,
    RemediationClass.DIFFERENT_INSTRUMENT: 7,
    RemediationClass.DIFFERENT_METHOD: 7,
    RemediationClass.DIFFERENT_INSTRUMENT_OR_METHOD: 13,
    RemediationClass.CUSTOMER_CONTACT_ISSUER_BANK: 4,
    RemediationClass.MERCHANT_ACTION: 15,
    RemediationClass.MERCHANT_CONTACT_RAZORPAY: 10,
    RemediationClass.TERMINAL: 0,
}

EXPECTED_AMBIGUOUS_REASONS = {
    "authorisation_declined_by_psp",
    "card_not_enrolled",
    "compliance_violation",
    "credit_limit_inactive",
    "gateway_technical_error",
    "input_validation_failed",
    "invalid_response_from_gateway",
    "issuer_technical_error",
    "mismatch_in_transaction_details",
    "mobile_number_invalid",
    "server_error",
    "transaction_daily_count_exceeded",
    "transaction_daily_limit_exceeded",
    "upi_app_technical_error",
}


def test_classify_reasons_covers_every_record() -> None:
    records = parse_reason_records(VENDORED_PATH)
    classifications = classify_reasons(records)
    assert len(classifications) == 114
    assert [c.row_index for c in classifications] == list(range(114))


def test_coverage_report_class_counts_are_exact() -> None:
    records = parse_reason_records(VENDORED_PATH)
    report = build_coverage_report(classify_reasons(records))
    assert report.class_counts == EXPECTED_CLASS_COUNTS


def test_coverage_report_totals_are_consistent() -> None:
    records = parse_reason_records(VENDORED_PATH)
    report = build_coverage_report(classify_reasons(records))
    assert report.total_reasons == 114
    assert report.unambiguous_count() + len(report.ambiguous) == 114
    assert report.unambiguous_count() == 100
    assert len(report.ambiguous) == 14


def test_coverage_report_ambiguous_list_matches_expected_reasons() -> None:
    records = parse_reason_records(VENDORED_PATH)
    report = build_coverage_report(classify_reasons(records))
    ambiguous_reasons = {item.reason for item in report.ambiguous}
    assert ambiguous_reasons == EXPECTED_AMBIGUOUS_REASONS


def test_coverage_report_ambiguous_entries_all_have_at_least_one_candidate() -> None:
    records = parse_reason_records(VENDORED_PATH)
    report = build_coverage_report(classify_reasons(records))
    for item in report.ambiguous:
        assert len(item.candidate_classes) >= 1


def test_data_defect_rows_are_flagged_with_a_note() -> None:
    records = parse_reason_records(VENDORED_PATH)
    report = build_coverage_report(classify_reasons(records))
    by_reason = {item.reason: item for item in report.ambiguous}
    assert by_reason["invalid_response_from_gateway"].note is not None
    assert "copy" in by_reason["invalid_response_from_gateway"].note.lower()
    assert by_reason["mismatch_in_transaction_details"].note is not None


def test_classify_reasons_raises_on_length_mismatch() -> None:
    records = parse_reason_records(VENDORED_PATH)
    with pytest.raises(TaxonomyDriftError, match="reason records"):
        classify_reasons(records[:-1])


def test_classify_reasons_raises_on_reason_mismatch() -> None:
    records = parse_reason_records(VENDORED_PATH)
    tampered = list(records)
    tampered[0] = replace(tampered[0], reason="not_the_real_reason")
    with pytest.raises(TaxonomyDriftError, match="does not match reviewed table"):
        classify_reasons(tampered)


def test_reason_classification_remediation_class_is_none_when_ambiguous() -> None:
    records = parse_reason_records(VENDORED_PATH)
    classifications = classify_reasons(records)
    ambiguous = [c for c in classifications if c.is_ambiguous]
    assert ambiguous
    for classification in ambiguous:
        assert classification.remediation_class is None


def test_reason_classification_remediation_class_set_when_unambiguous() -> None:
    records = parse_reason_records(VENDORED_PATH)
    classifications = classify_reasons(records)
    unambiguous = [c for c in classifications if not c.is_ambiguous]
    for classification in unambiguous:
        assert classification.remediation_class is not None
        assert classification.remediation_class in classification.candidate_classes


def test_reason_record_row_index_field_exists() -> None:
    record = ReasonRecord(row_index=0, reason="x", explanation="y", next_steps="z")
    assert record.row_index == 0
