"""Tests for :mod:`reflow.eval.opacity`."""

from pathlib import Path

import pytest

from reflow.corpus.events import PaymentEvent
from reflow.corpus.generator import generate_corpus
from reflow.corpus.reasons import CATCH_ALL_REASONS
from reflow.eval.opacity import opaque_description
from reflow.signature.mask import mask_description
from reflow.taxonomy.provenance import resolve_vendored_path
from reflow.taxonomy.reasons import ReasonRecord, parse_reason_records

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDS = parse_reason_records(resolve_vendored_path(REPO_ROOT))
RECORD_BY_REASON: dict[str, ReasonRecord] = {}
for _record in RECORDS:
    RECORD_BY_REASON.setdefault(_record.reason, _record)


@pytest.fixture(scope="module")
def events() -> list[PaymentEvent]:
    return list(
        generate_corpus(seed=17, n_events=4_000, reason_records=RECORDS, variant_richness=5)
    )


def test_opaque_description_is_unchanged_for_narrow_reasons(events: list[PaymentEvent]) -> None:
    narrow_events = [event for event in events if event.error_reason not in CATCH_ALL_REASONS]
    assert narrow_events
    for event in narrow_events[:50]:
        record = RECORD_BY_REASON[event.error_reason]
        assert opaque_description(event, record) == event.description


def test_opaque_description_discards_latent_subcause_text(events: list[PaymentEvent]) -> None:
    catchall_events = [event for event in events if event.error_reason in CATCH_ALL_REASONS]
    assert catchall_events
    for event in catchall_events[:50]:
        record = RECORD_BY_REASON[event.error_reason]
        opaque = opaque_description(event, record)
        assert opaque != ""


def test_opaque_description_collapses_to_one_masked_string_per_reason_and_method(
    events: list[PaymentEvent],
) -> None:
    catchall_events = [event for event in events if event.error_reason in CATCH_ALL_REASONS]
    assert catchall_events

    masked_by_key: dict[tuple[str, str], set[str]] = {}
    for event in catchall_events:
        record = RECORD_BY_REASON[event.error_reason]
        opaque = opaque_description(event, record)
        masked = mask_description(opaque)
        key = (event.error_reason, str(event.method))
        masked_by_key.setdefault(key, set()).add(masked)

    for key, masked_variants in masked_by_key.items():
        assert len(masked_variants) == 1, f"{key} produced more than one masked opaque string"


def test_opaque_description_is_deterministic(events: list[PaymentEvent]) -> None:
    catchall_events = [event for event in events if event.error_reason in CATCH_ALL_REASONS]
    event = catchall_events[0]
    record = RECORD_BY_REASON[event.error_reason]
    assert opaque_description(event, record) == opaque_description(event, record)
