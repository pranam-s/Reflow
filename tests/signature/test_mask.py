"""Tests for :mod:`reflow.signature.mask`."""

import random
from datetime import datetime

import pytest

from reflow.corpus import tokens as tok
from reflow.corpus.descriptions import NoiseTokens, render_narrow_description
from reflow.corpus.generator import generate_corpus
from reflow.corpus.reasons import CATCH_ALL_SUBCAUSES
from reflow.signature.mask import (
    ALL_PLACEHOLDERS,
    AMOUNT_PLACEHOLDER,
    BANK_PLACEHOLDER,
    CARD_BIN_PLACEHOLDER,
    CUSTOMER_ID_PLACEHOLDER,
    GENERIC_ID_PLACEHOLDER,
    KNOWN_INSTITUTIONS,
    ORDER_ID_PLACEHOLDER,
    PAYMENT_ID_PLACEHOLDER,
    RRN_PLACEHOLDER,
    TIMESTAMP_PLACEHOLDER,
    VPA_PLACEHOLDER,
    mask_description,
    mask_descriptions,
)
from reflow.taxonomy.methods import PaymentMethod


@pytest.mark.parametrize("timestamp_text", ["2026-01-05T10:22:07", "2026-12-31T23:59:59Z"])
def test_mask_description_replaces_timestamp(timestamp_text: str) -> None:
    masked = mask_description(f"Failure at {timestamp_text} occurred.")
    assert timestamp_text not in masked
    assert TIMESTAMP_PLACEHOLDER in masked


def test_mask_description_replaces_amount() -> None:
    masked = mask_description("Payment declined for Rs.199.00 today.")
    assert masked == f"Payment declined for {AMOUNT_PLACEHOLDER} today."


@pytest.mark.parametrize("amount_text", ["Rs.1.00", "Rs.99999.99", "INR 250.00", "₹75.50"])
def test_mask_description_replaces_amount_variants(amount_text: str) -> None:
    masked = mask_description(f"Amount was {amount_text} for this transaction.")
    assert AMOUNT_PLACEHOLDER in masked
    assert amount_text not in masked


def test_mask_description_replaces_payment_and_order_ids() -> None:
    rng = random.Random(7)
    payment_id = tok.random_id(rng, "pay")
    order_id = tok.random_id(rng, "order")
    text = f"Payment {payment_id}, order {order_id}, failed."
    masked = mask_description(text)
    assert payment_id not in masked
    assert order_id not in masked
    assert PAYMENT_ID_PLACEHOLDER in masked
    assert ORDER_ID_PLACEHOLDER in masked


def test_mask_description_replaces_customer_id() -> None:
    rng = random.Random(9)
    customer_id = tok.random_id(rng, "cust")
    masked = mask_description(f"Customer {customer_id} retried the payment.")
    assert customer_id not in masked
    assert CUSTOMER_ID_PLACEHOLDER in masked


def test_mask_description_replaces_unknown_prefixed_id_generically() -> None:
    masked = mask_description("Reference ref_AbC123XYZ99 attached.")
    assert "ref_AbC123XYZ99" not in masked
    assert GENERIC_ID_PLACEHOLDER in masked


def test_mask_description_replaces_vpa() -> None:
    rng = random.Random(3)
    vpa = tok.random_vpa(rng)
    masked = mask_description(f"VPA {vpa} could not be resolved.")
    assert vpa not in masked
    assert VPA_PLACEHOLDER in masked


def test_mask_description_replaces_rrn() -> None:
    rng = random.Random(4)
    rrn = tok.random_rrn(rng)
    masked = mask_description(f"RRN {rrn} was logged for this attempt.")
    assert rrn not in masked
    assert RRN_PLACEHOLDER in masked


def test_mask_description_replaces_card_bin_after_bin_keyword() -> None:
    rng = random.Random(5)
    card_bin = tok.random_card_bin(rng)
    masked = mask_description(f"The card (BIN {card_bin}) was declined.")
    assert card_bin not in masked
    assert CARD_BIN_PLACEHOLDER in masked
    assert "BIN" in masked


def test_mask_description_does_not_mask_bare_six_digit_number() -> None:
    masked = mask_description("Error code 123456 was returned.")
    assert "123456" in masked
    assert CARD_BIN_PLACEHOLDER not in masked


@pytest.mark.parametrize("bank", KNOWN_INSTITUTIONS)
def test_mask_description_replaces_every_known_bank(bank: str) -> None:
    masked = mask_description(f"{bank} reported a technical error.")
    assert bank not in masked
    assert BANK_PLACEHOLDER in masked


def test_mask_description_leaves_plain_text_unchanged() -> None:
    text = "This card has expired and cannot be used for this payment."
    assert mask_description(text) == text


def test_mask_description_is_deterministic() -> None:
    text = (
        "State Bank of India declined payment pay_abcdefgh1234 for Rs.499.00 "
        "at 2026-08-05T10:00:00."
    )
    assert mask_description(text) == mask_description(text)


def test_mask_descriptions_masks_each_text_in_order() -> None:
    texts = ["Rs.10.00 failed.", "HDFC Bank declined it."]
    masked = mask_descriptions(texts)
    assert masked == [mask_description(texts[0]), mask_description(texts[1])]


def test_all_placeholders_are_angle_bracketed() -> None:
    for placeholder in ALL_PLACEHOLDERS:
        assert placeholder.startswith("<")
        assert placeholder.endswith(">")


def _build_noise(rng: random.Random, amount_paise: int, created_at: datetime) -> NoiseTokens:
    return NoiseTokens(
        payment_id=tok.random_id(rng, "pay"),
        order_id=tok.random_id(rng, "order"),
        amount_paise=amount_paise,
        created_at=created_at,
        bank=tok.random_bank_name(rng),
        vpa=tok.random_vpa(rng),
        card_bin=tok.random_card_bin(rng),
        rrn=tok.random_rrn(rng),
    )


def test_mask_description_collapses_full_rendered_description_to_bare_template() -> None:
    subcause = CATCH_ALL_SUBCAUSES["payment_failed"][0]

    noise_one = _build_noise(random.Random(101), 19_900, datetime(2026, 8, 5, 10, 0, 0))
    text_one = subcause.template.format_map(noise_one.as_format_mapping())

    noise_two = _build_noise(random.Random(202), 250_000, datetime(2026, 1, 1, 0, 0, 0))
    text_two = subcause.template.format_map(noise_two.as_format_mapping())

    assert mask_description(text_one) == mask_description(text_two)


def test_mask_description_on_generated_corpus_removes_generated_tokens() -> None:
    events = list(generate_corpus(seed=42, n_events=200, variant_richness=3))
    for event in events:
        masked = mask_description(event.description)
        assert event.payment_id not in masked
        assert event.order_id not in masked
        if event.vpa is not None:
            assert event.vpa not in masked
        if event.card_bin is not None:
            assert event.card_bin not in masked


def test_narrow_reason_alt_phrasing_is_unaffected_by_masking_when_token_free() -> None:
    rng = random.Random(0)
    noise = NoiseTokens(
        payment_id="pay_ignored0000",
        order_id="order_ignored000",
        amount_paise=100,
        created_at=datetime(2026, 1, 1),
        bank="HDFC Bank",
        vpa="a.1@ybl",
        card_bin="411234",
        rrn="000000000000",
    )
    text, _label = render_narrow_description(
        "authentication_failed",
        "Authentication could not be completed for the payment.",
        PaymentMethod.CARD,
        noise,
        rng,
    )
    masked = mask_description(text)
    assert "HDFC Bank" not in masked
    assert "pay_ignored0000" not in masked
