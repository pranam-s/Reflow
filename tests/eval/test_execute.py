"""Tests for reflow.eval.execute."""

from __future__ import annotations

import json
from pathlib import Path

from reflow.audit.store import iter_audit_records, verify_chain
from reflow.eval.execute import run_benchmark, to_json_dict, to_markdown
from reflow.execute.models import ExecutionOutcome

_SEED = 20260822
_SMALL_N_EVENTS = 4000


def test_run_benchmark_is_always_dry_run(tmp_path: Path) -> None:
    report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=tmp_path / "trail.jsonl"
    )
    assert ExecutionOutcome.EXECUTED.value not in report.dry_run_outcome_counts
    assert ExecutionOutcome.FAILED.value not in report.dry_run_outcome_counts
    assert sum(report.dry_run_outcome_counts.values()) == _SMALL_N_EVENTS
    assert report.n_events_evaluated == _SMALL_N_EVENTS


def test_reference_id_check_is_collision_free(tmp_path: Path) -> None:
    report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=tmp_path / "trail.jsonl"
    )
    check = report.reference_id_check
    assert check.n_events == _SMALL_N_EVENTS
    assert check.n_unique_reference_ids == _SMALL_N_EVENTS
    assert check.collision_free is True
    assert check.max_length == 40


def test_audit_trail_is_persisted_and_chain_valid(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=path, audit_sample_size=50
    )
    assert report.audit_chain_valid is True
    assert report.n_audit_records_persisted > 0
    assert verify_chain(path).valid is True
    records = list(iter_audit_records(path))
    assert len(records) == report.n_audit_records_persisted


def test_audit_sample_size_none_persists_every_decision(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=path, audit_sample_size=None
    )
    assert report.n_audit_records_persisted == _SMALL_N_EVENTS


def test_rerunning_the_benchmark_starts_a_fresh_trail_not_an_appended_one(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    first_report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=path, audit_sample_size=10
    )
    second_report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=path, audit_sample_size=10
    )
    assert second_report.n_audit_records_persisted == first_report.n_audit_records_persisted
    assert len(list(iter_audit_records(path))) == second_report.n_audit_records_persisted


def test_example_payment_ids_are_present_in_the_persisted_trail(tmp_path: Path) -> None:
    path = tmp_path / "trail.jsonl"
    report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=path, audit_sample_size=200
    )
    trail_payment_ids = {record.payment_id for record in iter_audit_records(path)}
    assert report.example_payment_ids
    for key, payment_id in report.example_payment_ids.items():
        assert payment_id in trail_payment_ids, key


def test_live_verification_reports_zero_when_no_cassettes_exist(tmp_path: Path) -> None:
    report = run_benchmark(
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        audit_trail_path=tmp_path / "trail.jsonl",
        live_cassette_dir=tmp_path / "no_such_dir",
    )
    assert report.live_verification.n_cassette_files == 0
    assert report.live_verification.n_interactions == 0
    assert report.live_verification.short_urls == ()


def test_live_verification_reports_real_committed_cassette_evidence(tmp_path: Path) -> None:
    report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=tmp_path / "trail.jsonl"
    )
    live = report.live_verification
    assert live.n_cassette_files >= 5
    assert live.n_interactions >= 9
    assert len(live.short_urls) > 0
    assert all(url.startswith("https://rzp.io/") for url in live.short_urls)


def test_to_json_dict_round_trips_through_json(tmp_path: Path) -> None:
    report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=tmp_path / "trail.jsonl"
    )
    payload = to_json_dict(report)
    reloaded = json.loads(json.dumps(payload))
    assert reloaded["n_events_evaluated"] == _SMALL_N_EVENTS
    assert reloaded["provenance"]["seed"] == _SEED


def test_live_verification_tolerates_malformed_cassette_bodies(tmp_path: Path) -> None:
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()
    (cassette_dir / "malformed.yaml").write_text(
        """
interactions:
- request:
    method: POST
    uri: https://api.razorpay.com/v1/payment_links
  response:
    body:
      string: ''
    status:
      code: 200
- request:
    method: POST
    uri: https://api.razorpay.com/v1/payment_links
  response:
    body:
      string: 'not json'
    status:
      code: 200
- request:
    method: POST
    uri: https://api.razorpay.com/v1/payment_links
  response:
    body:
      string: '[1, 2, 3]'
    status:
      code: 200
- request:
    method: POST
    uri: https://api.razorpay.com/v1/payment_links
  response:
    body:
      string: '{"id": "plink_no_url"}'
    status:
      code: 200
version: 1
""",
        encoding="utf-8",
    )

    report = run_benchmark(
        seed=_SEED,
        n_events=_SMALL_N_EVENTS,
        audit_trail_path=tmp_path / "trail.jsonl",
        live_cassette_dir=cassette_dir,
    )

    assert report.live_verification.n_interactions == 4
    assert report.live_verification.short_urls == ()


def test_to_markdown_contains_expected_sections(tmp_path: Path) -> None:
    report = run_benchmark(
        seed=_SEED, n_events=_SMALL_N_EVENTS, audit_trail_path=tmp_path / "trail.jsonl"
    )
    markdown = to_markdown(report)
    assert "# Phase 6 bounded-execution benchmark results" in markdown
    assert "## Dry-run execution outcomes" in markdown
    assert "## Idempotency key (reference_id) collision check" in markdown
    assert "## Persisted audit trail" in markdown
    assert "## Live test-mode verification" in markdown
