"""Tests for reflow.execute.reference."""

from pathlib import Path

from reflow.corpus.generator import generate_corpus
from reflow.execute.reference import REFERENCE_ID_MAX_LENGTH, derive_reference_id
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import parse_reason_records

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDS = parse_reason_records(resolve_vendored_path(REPO_ROOT))


def test_derive_reference_id_is_deterministic() -> None:
    first = derive_reference_id("pay_abcdefghij1234")
    second = derive_reference_id("pay_abcdefghij1234")
    assert first == second


def test_derive_reference_id_differs_for_different_inputs() -> None:
    assert derive_reference_id("pay_a") != derive_reference_id("pay_b")


def test_derive_reference_id_respects_max_length_and_prefix() -> None:
    reference_id = derive_reference_id("pay_abcdefghij1234")
    assert len(reference_id) == REFERENCE_ID_MAX_LENGTH
    assert reference_id.startswith("reflow_")
    digest_part = reference_id.removeprefix("reflow_")
    assert all(character in "0123456789abcdef" for character in digest_part)


def test_derive_reference_id_stable_length_for_varied_input_lengths() -> None:
    for payment_id in ("pay_x", "pay_" + "y" * 40, "pay_" + "z" * 200):
        assert len(derive_reference_id(payment_id)) == REFERENCE_ID_MAX_LENGTH


def test_reference_ids_are_collision_free_across_a_full_generated_corpus() -> None:
    events = list(generate_corpus(seed=20260822, n_events=50_000, reason_records=RECORDS))
    payment_ids = [event.payment_id for event in events]
    assert len(set(payment_ids)) == len(payment_ids), "corpus itself produced duplicate payment ids"

    reference_ids = [derive_reference_id(payment_id) for payment_id in payment_ids]
    assert len(set(reference_ids)) == len(reference_ids)
    assert all(len(reference_id) == REFERENCE_ID_MAX_LENGTH for reference_id in reference_ids)
