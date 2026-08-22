"""Tests for reflow.corpus.methods."""

import random
from collections import Counter

from reflow.corpus.methods import METHOD_MIX, UPI_FLOW_MIX, sample_method, sample_upi_flow
from reflow.taxonomy.methods import PaymentMethod, UpiFlow


def test_method_mix_sums_to_one() -> None:
    assert abs(sum(METHOD_MIX.values()) - 1.0) < 1e-9


def test_method_mix_covers_every_method() -> None:
    assert set(METHOD_MIX) == set(PaymentMethod)


def test_upi_flow_mix_sums_to_one() -> None:
    assert abs(sum(UPI_FLOW_MIX.values()) - 1.0) < 1e-9


def test_upi_is_dominant_over_ten_thousand_draws() -> None:
    rng = random.Random(123)
    counts = Counter(sample_method(rng) for _ in range(10_000))
    upi_share = counts[PaymentMethod.UPI] / 10_000
    assert 0.55 < upi_share < 0.73


def test_sample_upi_flow_favours_intent() -> None:
    rng = random.Random(456)
    counts = Counter(sample_upi_flow(rng) for _ in range(5_000))
    intent_share = counts[UpiFlow.INTENT] / 5_000
    assert intent_share > 0.85


def test_sample_method_is_deterministic_for_same_seed() -> None:
    rng_a = random.Random(99)
    rng_b = random.Random(99)
    first = [sample_method(rng_a) for _ in range(20)]
    second = [sample_method(rng_b) for _ in range(20)]
    assert first == second
