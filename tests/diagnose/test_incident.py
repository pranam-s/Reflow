"""Tests for reflow.diagnose.incident."""

from datetime import datetime

from reflow.diagnose.incident import IncidentDiagnoser, build_incident_context
from reflow.diagnose.models import RecommendedPosture
from reflow.incident.windows import DetectedIncident
from reflow.taxonomy.methods import PaymentMethod
from tests.diagnose.factories import FakeJsonCompleter
from tests.incident.factories import make_event

_ORIGIN = datetime(2026, 1, 1, 0, 0, 0)


def _make_incident(event_indices: tuple[int, ...]) -> DetectedIncident:
    return DetectedIncident(
        entity=(PaymentMethod.UPI, "State Bank of India", None),
        detector="poisson_surprise",
        start=_ORIGIN,
        end=_ORIGIN,
        bucket_starts=(_ORIGIN,),
        total_count=len(event_indices),
        peak_score=12.5,
        event_indices=event_indices,
    )


def test_build_incident_context_counts_reasons_from_member_events_only() -> None:
    events = [
        make_event(error_reason="payment_timed_out"),
        make_event(error_reason="payment_timed_out"),
        make_event(error_reason="bank_not_available"),
        make_event(error_reason="should_not_be_counted"),
    ]
    incident = _make_incident((0, 1, 2))
    context = build_incident_context(incident, events)
    assert context.method == "upi"
    assert context.bank == "State Bank of India"
    assert context.total_count == 3
    assert context.reason_counts == {"payment_timed_out": 2, "bank_not_available": 1}
    assert context.peak_score == 12.5
    assert context.detector == "poisson_surprise"


def test_incident_diagnoser_makes_one_uncached_call_per_incident() -> None:
    completer = FakeJsonCompleter()
    diagnoser = IncidentDiagnoser(client=completer)
    events = [
        make_event(error_reason="payment_timed_out"),
        make_event(error_reason="bank_not_available"),
    ]
    context_a = build_incident_context(_make_incident((0,)), events)
    context_b = build_incident_context(_make_incident((1,)), events)

    diagnoser.diagnose(context_a)
    diagnoser.diagnose(context_a)
    diagnoser.diagnose(context_b)

    assert diagnoser.calls_made == 3
    assert len(completer.calls) == 3


def test_incident_diagnoser_returns_the_completer_provided_value() -> None:
    completer = FakeJsonCompleter()
    diagnoser = IncidentDiagnoser(client=completer)
    events = [make_event(error_reason="payment_timed_out")]
    context = build_incident_context(_make_incident((0,)), events)
    result = diagnoser.diagnose(context)
    assert result.value.recommended_posture == RecommendedPosture.ESCALATE_TO_ONCALL


def test_incident_diagnoser_total_cost_sums_every_call() -> None:
    completer = FakeJsonCompleter(cost_per_call=0.00002)
    diagnoser = IncidentDiagnoser(client=completer)
    events = [make_event(error_reason="payment_timed_out")]
    context = build_incident_context(_make_incident((0,)), events)
    diagnoser.diagnose(context)
    diagnoser.diagnose(context)
    assert diagnoser.total_cost() == 0.00004


def test_prompt_lists_reason_breakdown_highest_volume_first() -> None:
    completer = FakeJsonCompleter()
    diagnoser = IncidentDiagnoser(client=completer)
    events = [
        make_event(error_reason="rare_reason"),
        make_event(error_reason="common_reason"),
        make_event(error_reason="common_reason"),
    ]
    context = build_incident_context(_make_incident((0, 1, 2)), events)
    diagnoser.diagnose(context)
    prompt = completer.calls[0]["messages"][1]["content"]
    assert prompt.index("common_reason") < prompt.index("rare_reason")


def test_wallet_incident_has_no_bank_scope() -> None:
    events = [make_event(method=PaymentMethod.WALLET, error_reason="bank_not_available")]
    incident = DetectedIncident(
        entity=(PaymentMethod.WALLET, None, None),
        detector="poisson_surprise",
        start=_ORIGIN,
        end=_ORIGIN,
        bucket_starts=(_ORIGIN,),
        total_count=1,
        peak_score=4.0,
        event_indices=(0,),
    )
    context = build_incident_context(incident, events)
    assert context.bank is None
