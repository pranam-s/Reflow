"""Tests for reflow.corpus.reasons."""

import itertools
from pathlib import Path

import pytest

from reflow.corpus.reasons import (
    BANK_METHODS,
    CARD_ONLY,
    CARDLESS_EMI_ONLY,
    CATCH_ALL_REASONS,
    CATCH_ALL_SUBCAUSES,
    UPI_ONLY,
    WALLET_ONLY,
    generic_reasons,
    reason_pool_for_method,
    unique_reason_records,
    zipf_weights,
)
from reflow.taxonomy.methods import PaymentMethod
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import parse_reason_records

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDS = parse_reason_records(resolve_vendored_path(REPO_ROOT))

_EXPLICIT_BUCKETS = (CARD_ONLY, UPI_ONLY, WALLET_ONLY, CARDLESS_EMI_ONLY, BANK_METHODS)


def test_unique_reason_records_has_110_entries() -> None:
    assert len(unique_reason_records(RECORDS)) == 110


def test_explicit_buckets_reference_real_reason_codes() -> None:
    known_reasons = {record.reason for record in RECORDS}
    for bucket in _EXPLICIT_BUCKETS:
        for reason in bucket:
            assert reason in known_reasons


def test_explicit_buckets_are_pairwise_disjoint() -> None:
    seen: set[str] = set()
    for bucket in _EXPLICIT_BUCKETS:
        bucket_set = set(bucket)
        assert not (seen & bucket_set)
        seen |= bucket_set


def test_generic_reasons_excludes_explicit_buckets() -> None:
    explicit = {reason for bucket in _EXPLICIT_BUCKETS for reason in bucket}
    generic = generic_reasons(RECORDS)
    assert not (set(generic) & explicit)


def test_generic_plus_explicit_covers_every_unique_reason() -> None:
    explicit = {reason for bucket in _EXPLICIT_BUCKETS for reason in bucket}
    generic = set(generic_reasons(RECORDS))
    unique_reasons = {record.reason for record in unique_reason_records(RECORDS)}
    assert explicit | generic == unique_reasons


def test_catch_all_reasons_are_known_and_narrow_reasons_are_not_catch_all() -> None:
    known_reasons = {record.reason for record in RECORDS}
    assert known_reasons >= CATCH_ALL_REASONS
    assert "card_expired" not in CATCH_ALL_REASONS
    assert "incorrect_otp" not in CATCH_ALL_REASONS


def test_catch_all_subcauses_defined_for_every_catch_all_reason() -> None:
    assert set(CATCH_ALL_SUBCAUSES) == CATCH_ALL_REASONS


@pytest.mark.parametrize("reason", sorted(CATCH_ALL_REASONS))
def test_catch_all_reason_has_multiple_distinct_subcauses(reason: str) -> None:
    subcauses = CATCH_ALL_SUBCAUSES[reason]
    assert len(subcauses) >= 3
    ids = {s.subcause_id for s in subcauses}
    assert len(ids) == len(subcauses)
    templates = {s.template for s in subcauses}
    assert len(templates) == len(subcauses)


@pytest.mark.parametrize("reason", sorted(CATCH_ALL_REASONS))
def test_catch_all_subcause_weights_sum_close_to_one(reason: str) -> None:
    total = sum(s.weight for s in CATCH_ALL_SUBCAUSES[reason])
    assert abs(total - 1.0) < 1e-6


def test_reason_pool_for_method_starts_with_method_specific_reasons() -> None:
    pool = reason_pool_for_method(PaymentMethod.CARD, RECORDS)
    assert pool[: len(CARD_ONLY)] == list(CARD_ONLY)
    assert len(pool) == len(CARD_ONLY) + len(generic_reasons(RECORDS))


def test_reason_pool_covers_every_method_without_error() -> None:
    for method in PaymentMethod:
        pool = reason_pool_for_method(method, RECORDS)
        assert len(pool) > 0
        assert len(pool) == len(set(pool))


def test_zipf_weights_sum_to_one_and_decrease() -> None:
    weights = zipf_weights(10)
    assert abs(sum(weights) - 1.0) < 1e-9
    assert all(earlier > later for earlier, later in itertools.pairwise(weights))


def test_zipf_weights_single_item_is_certain() -> None:
    assert zipf_weights(1) == [1.0]
