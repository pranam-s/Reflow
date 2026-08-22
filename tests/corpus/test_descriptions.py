"""Tests for reflow.corpus.descriptions."""

import itertools
import random
from datetime import datetime

import pytest

from reflow.corpus.descriptions import (
    generate_noise_tokens,
    render_narrow_description,
    render_subcause_description,
)
from reflow.corpus.reasons import CATCH_ALL_SUBCAUSES, NARROW_REASON_ALT_PHRASINGS
from reflow.taxonomy.methods import PaymentMethod

_A_SUBCAUSE = next(subcause for subcauses in CATCH_ALL_SUBCAUSES.values() for subcause in subcauses)


def test_generate_noise_tokens_reuses_created_at_and_amount() -> None:
    rng = random.Random(1)
    moment = datetime(2026, 3, 1, 12, 0, 0)
    noise = generate_noise_tokens(rng, created_at=moment, amount_paise=4999)
    assert noise.created_at == moment
    assert noise.amount_paise == 4999


def test_render_narrow_description_includes_explanation_and_tokens() -> None:
    rng = random.Random(2)
    noise = generate_noise_tokens(rng, created_at=datetime(2026, 1, 1), amount_paise=9900)
    explanation = "The customer has entered an incorrect CVV to complete the payment."
    rendered, variant = render_narrow_description(
        "incorrect_cvv", explanation, PaymentMethod.CARD, noise, random.Random(1)
    )
    assert "incorrect CVV" in rendered
    assert noise.payment_id in rendered
    assert noise.card_bin in rendered
    assert variant == "canonical"


def test_render_narrow_description_varies_with_noise() -> None:
    explanation = "The customer must retry."
    noise_a = generate_noise_tokens(random.Random(10), datetime(2026, 1, 1), 100)
    noise_b = generate_noise_tokens(random.Random(20), datetime(2026, 1, 2), 200)
    rendered_a, _ = render_narrow_description(
        "request_timed_out", explanation, PaymentMethod.UPI, noise_a, random.Random(1)
    )
    rendered_b, _ = render_narrow_description(
        "request_timed_out", explanation, PaymentMethod.UPI, noise_b, random.Random(1)
    )
    assert rendered_a != rendered_b


def test_render_narrow_description_upi_includes_vpa_and_rrn() -> None:
    rng = random.Random(3)
    noise = generate_noise_tokens(rng, datetime(2026, 1, 1), 100)
    rendered, _ = render_narrow_description(
        "invalid_vpa", "The customer must use a valid VPA.", PaymentMethod.UPI, noise, rng
    )
    assert noise.vpa in rendered
    assert noise.rrn in rendered


def test_render_narrow_description_can_select_alt_phrasing() -> None:
    noise = generate_noise_tokens(random.Random(1), datetime(2026, 1, 1), 100)
    explanation = "The customer is making the payment with an expired card."
    seen_variants = set()
    for seed in range(200):
        _, variant = render_narrow_description(
            "card_expired", explanation, PaymentMethod.CARD, noise, random.Random(seed)
        )
        seen_variants.add(variant)
    assert seen_variants == {"canonical", "paraphrase_wording"}


def test_narrow_reason_alt_phrasings_cover_every_documented_style() -> None:
    labels = {variant.label for variant in NARROW_REASON_ALT_PHRASINGS.values()}
    assert labels == {"paraphrase_wording", "paraphrase_reordered"}


def test_render_subcause_description_for_every_catch_all_template() -> None:
    rng = random.Random(4)
    noise = generate_noise_tokens(rng, datetime(2026, 1, 1), 500)
    for subcauses in CATCH_ALL_SUBCAUSES.values():
        for subcause in subcauses:
            rendered, variant = render_subcause_description(subcause, noise, rng)
            assert noise.payment_id in rendered
            assert "{" not in rendered
            assert variant in {"canonical", "paraphrase_wording", "paraphrase_reordered"}


def test_render_subcause_description_can_select_paraphrase() -> None:
    noise = generate_noise_tokens(random.Random(1), datetime(2026, 1, 1), 100)
    paraphrased_subcause = next(
        subcause
        for subcauses in CATCH_ALL_SUBCAUSES.values()
        for subcause in subcauses
        if subcause.paraphrase is not None
    )
    seen_variants = set()
    for seed in range(200):
        _, variant = render_subcause_description(paraphrased_subcause, noise, random.Random(seed))
        seen_variants.add(variant)
    assert "canonical" in seen_variants
    assert paraphrased_subcause.paraphrase is not None
    assert paraphrased_subcause.paraphrase.label in seen_variants


def test_render_subcause_description_richness_one_is_always_canonical() -> None:
    noise = generate_noise_tokens(random.Random(1), datetime(2026, 1, 1), 100)
    for seed in range(200):
        rendered, variant = render_subcause_description(
            _A_SUBCAUSE, noise, random.Random(seed), variant_richness=1
        )
        assert variant == "canonical"
        assert rendered == _A_SUBCAUSE.template.format_map(noise.as_format_mapping())


def test_render_subcause_description_richness_three_uses_exactly_three_labels() -> None:
    noise = generate_noise_tokens(random.Random(1), datetime(2026, 1, 1), 100)
    seen = set()
    for seed in range(500):
        _, variant = render_subcause_description(
            _A_SUBCAUSE, noise, random.Random(seed), variant_richness=3
        )
        seen.add(variant)
    assert seen == {"canonical", "paraphrase_wording", "paraphrase_reordered"}


def test_render_subcause_description_richness_five_uses_all_five_labels() -> None:
    noise = generate_noise_tokens(random.Random(1), datetime(2026, 1, 1), 100)
    seen = set()
    for seed in range(2000):
        _, variant = render_subcause_description(
            _A_SUBCAUSE, noise, random.Random(seed), variant_richness=5
        )
        seen.add(variant)
    assert seen == {
        "canonical",
        "paraphrase_wording",
        "paraphrase_reordered",
        "paraphrase_verbose",
        "paraphrase_terse",
    }


def test_render_subcause_description_richness_weighting_is_nonuniform() -> None:
    noise = generate_noise_tokens(random.Random(1), datetime(2026, 1, 1), 100)
    counts: dict[str, int] = {}
    for seed in range(3000):
        _, variant = render_subcause_description(
            _A_SUBCAUSE, noise, random.Random(seed), variant_richness=5
        )
        counts[variant] = counts.get(variant, 0) + 1
    ordered_labels = [
        "canonical",
        "paraphrase_wording",
        "paraphrase_reordered",
        "paraphrase_verbose",
        "paraphrase_terse",
    ]
    ordered_counts = [counts.get(label, 0) for label in ordered_labels]
    assert all(earlier > later for earlier, later in itertools.pairwise(ordered_counts))


@pytest.mark.parametrize("richness", [0, -1, 6])
def test_render_subcause_description_rejects_out_of_range_richness(richness: int) -> None:
    noise = generate_noise_tokens(random.Random(1), datetime(2026, 1, 1), 100)
    with pytest.raises(ValueError, match="variant_richness"):
        render_subcause_description(_A_SUBCAUSE, noise, random.Random(1), variant_richness=richness)


def test_render_subcause_description_none_richness_matches_omitted_argument() -> None:
    noise = generate_noise_tokens(random.Random(1), datetime(2026, 1, 1), 100)
    explicit = render_subcause_description(
        _A_SUBCAUSE, noise, random.Random(7), variant_richness=None
    )
    omitted = render_subcause_description(_A_SUBCAUSE, noise, random.Random(7))
    assert explicit == omitted
