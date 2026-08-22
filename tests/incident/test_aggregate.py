"""Tests for reflow.incident.aggregate."""

from datetime import datetime, timedelta

import pytest

from reflow.incident.aggregate import (
    BANK_SCOPED_METHODS,
    BUCKET_WIDTH,
    BucketGrid,
    build_entity_series,
    entity_key,
    floor_to_bucket,
    reason_scoped_entity_key,
)
from reflow.taxonomy.methods import PaymentMethod
from tests.incident.factories import make_event


def test_bank_scoped_methods_matches_expected_set() -> None:
    assert (
        frozenset(
            {
                PaymentMethod.CARD,
                PaymentMethod.UPI,
                PaymentMethod.NETBANKING,
                PaymentMethod.EMANDATE,
            }
        )
        == BANK_SCOPED_METHODS
    )


def test_entity_key_uses_bank_for_bank_scoped_method() -> None:
    event = make_event(method=PaymentMethod.UPI, bank="HDFC Bank")
    assert entity_key(event) == (PaymentMethod.UPI, "HDFC Bank", None)


def test_entity_key_ignores_bank_for_wallet() -> None:
    event = make_event(method=PaymentMethod.WALLET, bank="Some Random Bank")
    assert entity_key(event) == (PaymentMethod.WALLET, None, None)


def test_entity_key_ignores_bank_for_cardless_emi() -> None:
    event = make_event(method=PaymentMethod.CARDLESS_EMI, bank="Some Random Bank")
    assert entity_key(event) == (PaymentMethod.CARDLESS_EMI, None, None)


def test_reason_scoped_entity_key_adds_reason() -> None:
    event = make_event(method=PaymentMethod.CARD, bank="Axis Bank", error_reason="card_declined")
    assert reason_scoped_entity_key(event) == (PaymentMethod.CARD, "Axis Bank", "card_declined")


def test_floor_to_bucket_floors_to_15_minutes() -> None:
    moment = datetime(2026, 8, 22, 10, 7, 33)
    assert floor_to_bucket(moment) == datetime(2026, 8, 22, 10, 0, 0)


def test_floor_to_bucket_exact_boundary_is_stable() -> None:
    moment = datetime(2026, 8, 22, 10, 15, 0)
    assert floor_to_bucket(moment) == moment


def test_floor_to_bucket_respects_custom_width() -> None:
    moment = datetime(2026, 8, 22, 10, 40, 0)
    assert floor_to_bucket(moment, timedelta(hours=1)) == datetime(2026, 8, 22, 10, 0, 0)


def test_bucket_grid_index_and_start_round_trip() -> None:
    grid = BucketGrid(origin=datetime(2026, 1, 1), bucket_width=BUCKET_WIDTH, n_buckets=10)
    moment = datetime(2026, 1, 1, 1, 7)
    index = grid.index_of(moment)
    assert grid.start_of(index) <= moment < grid.start_of(index) + BUCKET_WIDTH


def test_bucket_grid_index_of_rejects_moment_before_origin() -> None:
    grid = BucketGrid(origin=datetime(2026, 1, 1), bucket_width=BUCKET_WIDTH, n_buckets=10)
    with pytest.raises(ValueError, match="precedes"):
        grid.index_of(datetime(2025, 12, 31))


def test_build_entity_series_empty_input() -> None:
    assert build_entity_series([]) == {}


def test_build_entity_series_dense_zero_fill_across_shared_global_range() -> None:
    early_event = make_event(
        method=PaymentMethod.UPI,
        bank="HDFC Bank",
        created_at=datetime(2026, 1, 1, 0, 0),
        payment_id="pay_early",
    )
    late_event = make_event(
        method=PaymentMethod.UPI,
        bank="ICICI Bank",
        created_at=datetime(2026, 1, 1, 5, 0),
        payment_id="pay_late",
    )
    series = build_entity_series([early_event, late_event])
    hdfc = series[(PaymentMethod.UPI, "HDFC Bank", None)]
    icici = series[(PaymentMethod.UPI, "ICICI Bank", None)]

    assert hdfc.grid is icici.grid
    assert len(hdfc.counts) == len(icici.counts)
    assert sum(hdfc.counts) == 1
    assert sum(icici.counts) == 1
    assert hdfc.counts[0] == 1
    assert icici.counts[-1] == 1
    assert icici.counts[0] == 0


def test_build_entity_series_tracks_event_indices_and_reason_counts() -> None:
    events = [
        make_event(
            method=PaymentMethod.CARD,
            bank="Axis Bank",
            created_at=datetime(2026, 1, 1, 0, 3),
            error_reason="card_declined",
            payment_id="pay_a",
        ),
        make_event(
            method=PaymentMethod.CARD,
            bank="Axis Bank",
            created_at=datetime(2026, 1, 1, 0, 5),
            error_reason="issuer_technical_error",
            payment_id="pay_b",
        ),
    ]
    series = build_entity_series(events)
    axis = series[(PaymentMethod.CARD, "Axis Bank", None)]
    assert axis.counts[0] == 2
    assert axis.event_indices_by_bucket[0] == (0, 1)
    assert axis.reason_counts_by_bucket[0] == {"card_declined": 1, "issuer_technical_error": 1}


def test_build_entity_series_with_reason_scoped_key_splits_by_reason() -> None:
    events = [
        make_event(
            method=PaymentMethod.CARD,
            bank="Axis Bank",
            created_at=datetime(2026, 1, 1, 0, 3),
            error_reason="card_declined",
            payment_id="pay_a",
        ),
        make_event(
            method=PaymentMethod.CARD,
            bank="Axis Bank",
            created_at=datetime(2026, 1, 1, 0, 5),
            error_reason="issuer_technical_error",
            payment_id="pay_b",
        ),
    ]
    series = build_entity_series(events, key_fn=reason_scoped_entity_key)
    assert set(series.keys()) == {
        (PaymentMethod.CARD, "Axis Bank", "card_declined"),
        (PaymentMethod.CARD, "Axis Bank", "issuer_technical_error"),
    }
    for entity_series in series.values():
        assert sum(entity_series.counts) == 1


def test_build_entity_series_default_bucket_width_matches_module_constant() -> None:
    event = make_event()
    series = build_entity_series([event])
    (only_series,) = series.values()
    assert only_series.grid.bucket_width == BUCKET_WIDTH
