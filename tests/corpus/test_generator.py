"""Tests for reflow.corpus.generator."""

import itertools
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

from reflow.corpus.events import PaymentEvent
from reflow.corpus.generator import DEFAULT_N_EVENTS, generate_corpus
from reflow.corpus.methods import METHOD_MIX
from reflow.corpus.reasons import CATCH_ALL_REASONS
from reflow.taxonomy.methods import PaymentMethod
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import parse_reason_records

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDS = parse_reason_records(resolve_vendored_path(REPO_ROOT))


def test_generate_corpus_returns_an_iterator_not_a_list() -> None:
    result = generate_corpus(seed=1, n_events=10, reason_records=RECORDS)
    assert isinstance(result, Iterator)
    assert not isinstance(result, list)


def test_generate_corpus_supports_partial_consumption() -> None:
    result = generate_corpus(seed=1, n_events=5_000, reason_records=RECORDS)
    first_five = list(itertools.islice(result, 5))
    assert len(first_five) == 5
    assert all(isinstance(event, PaymentEvent) for event in first_five)


def test_generate_corpus_zero_events_yields_nothing() -> None:
    assert list(generate_corpus(seed=1, n_events=0, reason_records=RECORDS)) == []


def test_generate_corpus_produces_requested_count() -> None:
    events = list(generate_corpus(seed=1, n_events=2_000, reason_records=RECORDS))
    assert len(events) == 2_000


def test_generate_corpus_is_deterministic_for_same_seed() -> None:
    first = list(generate_corpus(seed=42, n_events=1_500, reason_records=RECORDS))
    second = list(generate_corpus(seed=42, n_events=1_500, reason_records=RECORDS))
    assert first == second


def test_generate_corpus_different_seeds_diverge() -> None:
    first = list(generate_corpus(seed=1, n_events=1_500, reason_records=RECORDS))
    second = list(generate_corpus(seed=2, n_events=1_500, reason_records=RECORDS))
    assert first != second


def test_generate_corpus_events_are_chronologically_ordered() -> None:
    events = list(generate_corpus(seed=3, n_events=2_000, reason_records=RECORDS))
    timestamps = [event.created_at for event in events]
    assert timestamps == sorted(timestamps)


def test_generate_corpus_default_size_completes_quickly() -> None:
    start = time.monotonic()
    events = list(generate_corpus(seed=7, n_events=DEFAULT_N_EVENTS, reason_records=RECORDS))
    elapsed = time.monotonic() - start
    assert len(events) == DEFAULT_N_EVENTS
    assert elapsed < 60.0


def test_method_mix_is_approximately_respected() -> None:
    events = list(generate_corpus(seed=11, n_events=20_000, reason_records=RECORDS))
    counts = Counter(event.method for event in events)
    for method, expected_share in METHOD_MIX.items():
        observed_share = counts[method] / len(events)
        assert abs(observed_share - expected_share) < 0.05


def test_catch_all_reasons_have_a_meaningful_but_not_dominant_share() -> None:
    events = list(generate_corpus(seed=13, n_events=20_000, reason_records=RECORDS))
    catch_all_count = sum(1 for event in events if event.error_reason in CATCH_ALL_REASONS)
    share = catch_all_count / len(events)
    assert 0.0 < share < 0.6


def test_catch_all_events_span_multiple_latent_subcauses() -> None:
    events = list(generate_corpus(seed=17, n_events=20_000, reason_records=RECORDS))
    subcauses_by_reason: dict[str, set[str]] = defaultdict(set)
    for event in events:
        if event.latent_subcause_id is not None:
            subcauses_by_reason[event.error_reason].add(event.latent_subcause_id)
    for reason in CATCH_ALL_REASONS:
        if reason in subcauses_by_reason:
            assert len(subcauses_by_reason[reason]) >= 2


def test_narrow_reasons_never_carry_a_latent_subcause() -> None:
    events = list(generate_corpus(seed=19, n_events=10_000, reason_records=RECORDS))
    for event in events:
        if event.error_reason not in CATCH_ALL_REASONS:
            assert event.latent_subcause_id is None


def test_downtime_windows_produce_multi_reason_correlated_spikes() -> None:
    events = list(generate_corpus(seed=23, n_events=20_000, reason_records=RECORDS))
    reasons_by_window: dict[str, set[str]] = defaultdict(set)
    counts_by_window: Counter[str] = Counter()
    for event in events:
        if event.downtime_window_id is not None:
            reasons_by_window[event.downtime_window_id].add(event.error_reason)
            counts_by_window[event.downtime_window_id] += 1
    assert reasons_by_window
    multi_reason_windows = [
        window_id for window_id, reasons in reasons_by_window.items() if len(reasons) >= 2
    ]
    assert multi_reason_windows
    assert max(counts_by_window.values()) >= 5


def test_no_downtime_window_leaks_across_the_split() -> None:
    events = list(generate_corpus(seed=29, n_events=20_000, reason_records=RECORDS))
    splits_by_window: dict[str, set[str]] = defaultdict(set)
    for event in events:
        if event.downtime_window_id is not None:
            splits_by_window[event.downtime_window_id].add(event.split)
    for window_id, splits in splits_by_window.items():
        assert len(splits) == 1, f"window {window_id} leaked across splits: {splits}"


def test_every_event_has_a_resolved_split() -> None:
    events = list(generate_corpus(seed=31, n_events=5_000, reason_records=RECORDS))
    for event in events:
        assert event.split in {"train", "test"}


def test_retry_chains_reuse_order_id_for_attempts_above_one() -> None:
    events = list(generate_corpus(seed=37, n_events=20_000, reason_records=RECORDS))
    by_order: dict[str, list[PaymentEvent]] = defaultdict(list)
    for event in events:
        by_order[event.order_id].append(event)
    multi_attempt_orders = [
        order_events for order_events in by_order.values() if len(order_events) > 1
    ]
    assert multi_attempt_orders
    for order_events in multi_attempt_orders:
        customers = {event.customer_id for event in order_events}
        assert len(customers) == 1
        attempts = sorted(event.attempt_number for event in order_events)
        assert attempts == list(range(1, len(attempts) + 1))


def test_default_n_events_constant_is_fifty_thousand() -> None:
    assert DEFAULT_N_EVENTS == 50_000


def test_some_events_are_genuine_outliers() -> None:
    events = list(generate_corpus(seed=43, n_events=50_000, reason_records=RECORDS))
    outliers = [event for event in events if event.is_outlier]
    assert outliers
    assert len(outliers) < 0.02 * len(events)
    for event in outliers:
        assert event.error_reason not in CATCH_ALL_REASONS
        assert event.downtime_window_id is None


def test_outlier_keys_actually_occur_rarely_among_background_events() -> None:
    events = list(generate_corpus(seed=47, n_events=50_000, reason_records=RECORDS))
    background = [event for event in events if event.downtime_window_id is None]
    counts: Counter[tuple[PaymentMethod, str]] = Counter(
        (event.method, event.error_reason) for event in background
    )
    for event in background:
        if event.is_outlier:
            assert counts[(event.method, event.error_reason)] <= 2


def test_description_variant_covers_canonical_and_both_paraphrase_styles() -> None:
    events = list(generate_corpus(seed=53, n_events=20_000, reason_records=RECORDS))
    variants = {event.description_variant for event in events}
    assert variants == {"canonical", "paraphrase_wording", "paraphrase_reordered"}


def test_description_variant_canonical_is_the_common_case() -> None:
    events = list(generate_corpus(seed=59, n_events=20_000, reason_records=RECORDS))
    canonical_share = sum(1 for e in events if e.description_variant == "canonical") / len(events)
    assert canonical_share > 0.7


def test_upi_events_use_only_upi_valid_steps() -> None:
    from reflow.taxonomy.methods import UPI_STEPS_BY_FLOW

    events = list(generate_corpus(seed=41, n_events=10_000, reason_records=RECORDS))
    all_upi_steps: set[object] = set()
    all_upi_steps = all_upi_steps.union(*UPI_STEPS_BY_FLOW.values())
    for event in events:
        if event.method is PaymentMethod.UPI:
            assert event.error_step in all_upi_steps
