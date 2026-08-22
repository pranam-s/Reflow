"""Tests for reflow.diagnose.ambiguous."""

from reflow.diagnose.ambiguous import AmbiguousReasonDiagnoser
from reflow.diagnose.models import AmbiguousReasonDiagnosis, Confidence
from reflow.diagnose.tier1 import ReasonRowContext
from reflow.taxonomy.remediation import RemediationClass
from tests.diagnose.factories import FakeJsonCompleter

_CONTEXTS = (
    ReasonRowContext(
        explanation="explanation A",
        next_steps="next steps A",
        candidate_classes=frozenset({RemediationClass.MERCHANT_CONTACT_RAZORPAY}),
        ambiguity_note=None,
    ),
    ReasonRowContext(
        explanation="explanation B",
        next_steps="next steps B",
        candidate_classes=frozenset({RemediationClass.MERCHANT_ACTION}),
        ambiguity_note=None,
    ),
)


def test_diagnose_calls_the_completer_once_per_reason() -> None:
    completer = FakeJsonCompleter()
    diagnoser = AmbiguousReasonDiagnoser(client=completer)
    diagnoser.diagnose("payment_method_not_enabled", _CONTEXTS)
    diagnoser.diagnose("payment_method_not_enabled", _CONTEXTS)
    assert len(completer.calls) == 1
    assert diagnoser.calls_made == 1


def test_diagnose_caches_per_reason_independently() -> None:
    completer = FakeJsonCompleter()
    diagnoser = AmbiguousReasonDiagnoser(client=completer)
    diagnoser.diagnose("payment_method_not_enabled", _CONTEXTS)
    diagnoser.diagnose("server_error", _CONTEXTS)
    assert diagnoser.calls_made == 2
    assert diagnoser.cached_reasons == {"payment_method_not_enabled", "server_error"}


def test_diagnose_returns_the_completer_provided_value() -> None:
    def factory(_response_model: type) -> AmbiguousReasonDiagnosis:
        return AmbiguousReasonDiagnosis(
            remediation_class=RemediationClass.WAIT, confidence=Confidence.HIGH, rationale="r"
        )

    completer = FakeJsonCompleter(factory=factory)
    diagnoser = AmbiguousReasonDiagnoser(client=completer)
    result = diagnoser.diagnose("server_error", _CONTEXTS)
    assert result.value.remediation_class == RemediationClass.WAIT


def test_total_cost_sums_across_distinct_reasons() -> None:
    completer = FakeJsonCompleter(cost_per_call=0.0001)
    diagnoser = AmbiguousReasonDiagnoser(client=completer)
    diagnoser.diagnose("payment_method_not_enabled", _CONTEXTS)
    diagnoser.diagnose("server_error", _CONTEXTS)
    assert diagnoser.total_cost() == 0.0002


def test_format_context_prompt_includes_reason_and_ambiguity_note() -> None:
    completer = FakeJsonCompleter()
    diagnoser = AmbiguousReasonDiagnoser(client=completer)
    contexts = (
        ReasonRowContext(
            explanation="explanation A",
            next_steps="next steps A",
            candidate_classes=frozenset({RemediationClass.WAIT}),
            ambiguity_note="conflicting rows",
        ),
    )
    diagnoser.diagnose("gateway_technical_error", contexts)
    prompt = completer.calls[0]["messages"][1]["content"]
    assert "gateway_technical_error" in prompt
    assert "conflicting rows" in prompt
    assert "explanation A" in prompt
