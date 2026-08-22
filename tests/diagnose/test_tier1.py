"""Tests for reflow.diagnose.tier1.

Uses the real vendored spreadsheet, matching the convention already
established in ``tests/taxonomy/test_remediation.py``:
:func:`reflow.taxonomy.remediation.classify_reasons` validates its input
against a hand-reviewed table keyed to the vendored file's exact row order,
so :func:`~reflow.diagnose.tier1.build_deterministic_table` cannot be
exercised against arbitrary synthetic records without tripping
``TaxonomyDriftError``.
"""

from pathlib import Path

import pytest

from reflow.diagnose.tier1 import build_deterministic_table, default_deterministic_table
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import parse_reason_records
from reflow.taxonomy.remediation import RemediationClass, TaxonomyDriftError

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED_PATH = resolve_vendored_path(REPO_ROOT)

EXPECTED_ESCALATED_REASONS = {
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
    "payment_method_not_enabled",
    "server_error",
    "transaction_daily_count_exceeded",
    "transaction_daily_limit_exceeded",
    "upi_app_technical_error",
}


def test_build_deterministic_table_reconciles_all_110_distinct_reasons() -> None:
    records = parse_reason_records(VENDORED_PATH)
    table = build_deterministic_table(records)
    assert len(table.deterministic) + len(table.escalated) == 110
    assert len(table.deterministic) == 95
    assert len(table.escalated) == 15


def test_escalated_reasons_match_expected_set() -> None:
    records = parse_reason_records(VENDORED_PATH)
    table = build_deterministic_table(records)
    assert set(table.escalated) == EXPECTED_ESCALATED_REASONS


def test_payment_method_not_enabled_escalates_on_cross_row_conflict() -> None:
    """Neither row is individually ambiguous, but the two rows disagree.

    This is the reason code one more than the taxonomy's own 14
    row-flagged-ambiguous rows (see module docstring of
    reflow.diagnose.tier1): a conflict only visible when reconciling by
    reason code, which is what a real event's error_reason carries.
    """
    records = parse_reason_records(VENDORED_PATH)
    table = build_deterministic_table(records)
    contexts = table.escalated["payment_method_not_enabled"]
    assert len(contexts) == 2
    candidate_classes = {frozenset(context.candidate_classes) for context in contexts}
    assert candidate_classes == {
        frozenset({RemediationClass.MERCHANT_CONTACT_RAZORPAY}),
        frozenset({RemediationClass.MERCHANT_ACTION}),
    }
    assert table.is_escalated("payment_method_not_enabled")
    assert table.lookup("payment_method_not_enabled") is None


def test_duplicate_rows_that_agree_resolve_deterministically() -> None:
    """funds_blocked_by_mandate and psp_not_available are exact duplicates."""
    records = parse_reason_records(VENDORED_PATH)
    table = build_deterministic_table(records)
    assert table.lookup("funds_blocked_by_mandate") == RemediationClass.CUSTOMER_FIX
    assert table.lookup("psp_not_available") == RemediationClass.DIFFERENT_INSTRUMENT
    assert not table.is_escalated("funds_blocked_by_mandate")


def test_lookup_returns_none_for_a_reason_never_seen_at_all() -> None:
    table = default_deterministic_table()
    assert table.lookup("not_a_real_reason_code") is None
    assert table.is_escalated("not_a_real_reason_code") is True


def test_lookup_resolves_a_known_narrow_reason() -> None:
    table = default_deterministic_table()
    assert table.lookup("card_expired") == RemediationClass.DIFFERENT_INSTRUMENT_OR_METHOD
    assert not table.is_escalated("card_expired")


def test_default_deterministic_table_is_cached_and_stable() -> None:
    assert default_deterministic_table() is default_deterministic_table()


def test_build_deterministic_table_raises_on_row_count_mismatch() -> None:
    records = parse_reason_records(VENDORED_PATH)
    with pytest.raises(TaxonomyDriftError):
        build_deterministic_table(records[:-1])
