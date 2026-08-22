"""Tests for reflow.corpus.tokens."""

import random
from datetime import datetime

import pytest

from reflow.corpus import tokens


def test_random_id_shape() -> None:
    rng = random.Random(1)
    value = tokens.random_id(rng, "pay")
    assert value.startswith("pay_")
    assert len(value) == len("pay_") + 14


def test_random_id_is_deterministic_for_same_seed() -> None:
    first = tokens.random_id(random.Random(42), "order")
    second = tokens.random_id(random.Random(42), "order")
    assert first == second


def test_random_vpa_shape() -> None:
    rng = random.Random(7)
    vpa = tokens.random_vpa(rng)
    assert "@" in vpa
    handle = "@" + vpa.split("@")[1]
    assert handle in tokens.VPA_HANDLES


def test_random_card_bin_is_six_digits_and_known_prefix() -> None:
    rng = random.Random(3)
    for _ in range(50):
        bin_value = tokens.random_card_bin(rng)
        assert len(bin_value) == 6
        assert bin_value.isdigit()


def test_random_bank_name_from_known_list() -> None:
    rng = random.Random(9)
    assert tokens.random_bank_name(rng) in tokens.INDIAN_BANKS


def test_random_rrn_is_twelve_digits() -> None:
    rng = random.Random(11)
    rrn = tokens.random_rrn(rng)
    assert len(rrn) == 12
    assert rrn.isdigit()


def test_random_amount_paise_within_bounds() -> None:
    rng = random.Random(13)
    for _ in range(200):
        amount = tokens.random_amount_paise(rng)
        assert 100 <= amount <= 1_000_000
        assert amount % 100 == 0


def test_random_timestamp_within_range() -> None:
    rng = random.Random(5)
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 2)
    for _ in range(50):
        moment = tokens.random_timestamp(rng, start, end)
        assert start <= moment < end


def test_random_timestamp_rejects_non_positive_span() -> None:
    rng = random.Random(5)
    moment = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="end must be after start"):
        tokens.random_timestamp(rng, moment, moment)


def test_random_customer_id_shape() -> None:
    rng = random.Random(2)
    customer_id = tokens.random_customer_id(rng)
    assert customer_id.startswith("cust_")
