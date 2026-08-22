"""Tests for the Phase 1b ``variant_richness`` corpus-generation axis."""

import itertools
from collections import defaultdict
from pathlib import Path

import pytest

from reflow.corpus.generator import generate_corpus
from reflow.corpus.reasons import CATCH_ALL_REASONS, max_variant_richness
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import parse_reason_records

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDS = parse_reason_records(resolve_vendored_path(REPO_ROOT))

_ALL_LABELS_BY_RICHNESS = {
    1: {"canonical"},
    3: {"canonical", "paraphrase_wording", "paraphrase_reordered"},
    5: {
        "canonical",
        "paraphrase_wording",
        "paraphrase_reordered",
        "paraphrase_verbose",
        "paraphrase_terse",
    },
}


@pytest.mark.parametrize("richness", [1, 3, 5])
def test_generate_corpus_is_deterministic_per_richness_level(richness: int) -> None:
    first = list(
        generate_corpus(seed=101, n_events=3_000, reason_records=RECORDS, variant_richness=richness)
    )
    second = list(
        generate_corpus(seed=101, n_events=3_000, reason_records=RECORDS, variant_richness=richness)
    )
    assert first == second


def test_generate_corpus_default_variant_richness_matches_omitted_argument() -> None:
    explicit = list(
        generate_corpus(seed=5, n_events=1_000, reason_records=RECORDS, variant_richness=None)
    )
    omitted = list(generate_corpus(seed=5, n_events=1_000, reason_records=RECORDS))
    assert explicit == omitted


def test_generate_corpus_richness_one_forces_canonical_for_every_latent_subcause() -> None:
    events = list(
        generate_corpus(seed=61, n_events=20_000, reason_records=RECORDS, variant_richness=1)
    )
    catch_all_events = [event for event in events if event.latent_subcause_id is not None]
    assert catch_all_events
    assert {event.description_variant for event in catch_all_events} == {"canonical"}


@pytest.mark.parametrize("richness", [3, 5])
def test_generate_corpus_richness_produces_exactly_the_expected_label_set(richness: int) -> None:
    events = list(
        generate_corpus(seed=67, n_events=50_000, reason_records=RECORDS, variant_richness=richness)
    )
    catch_all_events = [event for event in events if event.latent_subcause_id is not None]
    assert catch_all_events
    observed = {event.description_variant for event in catch_all_events}
    assert observed == _ALL_LABELS_BY_RICHNESS[richness]


def test_generate_corpus_richness_never_exceeds_its_requested_level() -> None:
    events = list(
        generate_corpus(seed=71, n_events=50_000, reason_records=RECORDS, variant_richness=3)
    )
    catch_all_events = [event for event in events if event.latent_subcause_id is not None]
    assert catch_all_events
    observed = {event.description_variant for event in catch_all_events}
    assert observed <= _ALL_LABELS_BY_RICHNESS[5]
    assert "paraphrase_verbose" not in observed
    assert "paraphrase_terse" not in observed


def test_generate_corpus_richness_canonical_is_the_plurality_at_richness_five() -> None:
    events = list(
        generate_corpus(seed=73, n_events=50_000, reason_records=RECORDS, variant_richness=5)
    )
    catch_all_events = [event for event in events if event.latent_subcause_id is not None]
    counts: dict[str, int] = defaultdict(int)
    for event in catch_all_events:
        counts[event.description_variant] += 1
    ordered = [
        "canonical",
        "paraphrase_wording",
        "paraphrase_reordered",
        "paraphrase_verbose",
        "paraphrase_terse",
    ]
    assert all(counts[a] > counts[b] for a, b in itertools.pairwise(ordered))


def test_generate_corpus_richness_preserves_latent_subcause_id_invariants() -> None:
    events = list(
        generate_corpus(seed=79, n_events=20_000, reason_records=RECORDS, variant_richness=5)
    )
    for event in events:
        if event.error_reason in CATCH_ALL_REASONS:
            assert event.latent_subcause_id is not None
        else:
            assert event.latent_subcause_id is None


def test_generate_corpus_richness_preserves_downtime_split_isolation() -> None:
    events = list(
        generate_corpus(seed=83, n_events=20_000, reason_records=RECORDS, variant_richness=3)
    )
    splits_by_window: dict[str, set[str]] = defaultdict(set)
    for event in events:
        if event.downtime_window_id is not None:
            splits_by_window[event.downtime_window_id].add(event.split)
    assert splits_by_window
    for window_id, splits in splits_by_window.items():
        assert len(splits) == 1, f"window {window_id} leaked across splits: {splits}"


def test_generate_corpus_rejects_richness_below_minimum() -> None:
    with pytest.raises(ValueError, match="variant_richness"):
        list(generate_corpus(seed=1, n_events=10, reason_records=RECORDS, variant_richness=0))


def test_generate_corpus_rejects_richness_above_maximum() -> None:
    too_high = max_variant_richness() + 1
    with pytest.raises(ValueError, match="variant_richness"):
        list(
            generate_corpus(seed=1, n_events=10, reason_records=RECORDS, variant_richness=too_high)
        )


def test_generate_corpus_richness_one_and_five_diverge_for_the_same_seed() -> None:
    low = list(generate_corpus(seed=89, n_events=5_000, reason_records=RECORDS, variant_richness=1))
    high = list(
        generate_corpus(seed=89, n_events=5_000, reason_records=RECORDS, variant_richness=5)
    )
    assert low != high
