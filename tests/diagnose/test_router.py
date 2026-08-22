"""Tests for reflow.diagnose.router."""

from reflow.diagnose.ambiguous import AmbiguousReasonDiagnoser
from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisRouter, DiagnosisTier
from reflow.diagnose.tier1 import default_deterministic_table
from reflow.taxonomy.remediation import RemediationClass
from tests.diagnose.factories import FakeJsonCompleter
from tests.incident.factories import make_event


def _router(completer: FakeJsonCompleter) -> DiagnosisRouter:
    table = default_deterministic_table()
    return DiagnosisRouter(
        table=table, ambiguous_diagnoser=AmbiguousReasonDiagnoser(client=completer)
    )


def test_diagnose_reason_resolves_deterministic_reason_with_high_confidence() -> None:
    router = _router(FakeJsonCompleter())
    diagnosis = router.diagnose_reason("card_expired")
    assert diagnosis.tier is DiagnosisTier.DETERMINISTIC
    assert diagnosis.remediation_class == RemediationClass.DIFFERENT_INSTRUMENT_OR_METHOD
    assert diagnosis.confidence is Confidence.HIGH
    assert diagnosis.rationale is None


def test_diagnose_reason_escalates_ambiguous_reason_to_llm() -> None:
    completer = FakeJsonCompleter()
    router = _router(completer)
    diagnosis = router.diagnose_reason("server_error")
    assert diagnosis.tier is DiagnosisTier.LLM
    assert diagnosis.rationale is not None
    assert len(completer.calls) == 1


def test_route_computes_event_weighted_split_and_bounds_llm_calls() -> None:
    completer = FakeJsonCompleter()
    router = _router(completer)
    events = (
        [make_event(error_reason="payment_timed_out")] * 100
        + [make_event(error_reason="server_error")] * 5
        + [make_event(error_reason="compliance_violation")] * 3
    )
    stats = router.route(events)
    assert stats.total_events == 108
    assert stats.deterministic_events == 100
    assert stats.llm_events == 8
    assert stats.distinct_reasons_seen == 3
    assert stats.llm_calls_made == 2
    assert stats.escalated_reasons == {"server_error", "compliance_violation"}
    assert len(completer.calls) == 2


def test_route_fractions_are_consistent_with_counts() -> None:
    router = _router(FakeJsonCompleter())
    events = [make_event(error_reason="card_expired")] * 4 + [
        make_event(error_reason="server_error")
    ]
    stats = router.route(events)
    assert stats.deterministic_fraction == 4 / 5
    assert stats.llm_fraction == 1 / 5


def test_route_on_empty_events_never_calls_the_llm() -> None:
    completer = FakeJsonCompleter()
    router = _router(completer)
    stats = router.route([])
    assert stats.total_events == 0
    assert stats.deterministic_fraction == 0.0
    assert stats.llm_fraction == 0.0
    assert completer.calls == []


def test_route_repeated_calls_reuse_the_ambiguous_diagnoser_cache() -> None:
    completer = FakeJsonCompleter()
    router = _router(completer)
    events = [make_event(error_reason="server_error")] * 10
    router.route(events)
    router.route(events)
    assert len(completer.calls) == 1
