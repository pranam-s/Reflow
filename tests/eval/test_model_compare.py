"""Tests for reflow.eval.model_compare.

Every test uses a scripted, network-free completer in place of a real
:class:`reflow.llm.client.LlmClient`, so this module makes no network calls
and needs no credentials -- consistent with :func:`reflow.eval.model_compare.run_model_comparison`'s
own design (every model's completer is a caller-supplied parameter).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from reflow.diagnose.models import AmbiguousReasonDiagnosis, Confidence
from reflow.diagnose.tier1 import default_deterministic_table
from reflow.eval.model_compare import (
    DEFAULT_SAMPLE_SEED,
    run_model_comparison,
    to_json_dict,
    to_markdown,
)
from reflow.llm.client import LlmJsonResult, LlmUsage, Message
from reflow.llm.errors import RetriesExhaustedError
from reflow.taxonomy.remediation import RemediationClass

_SMALL_TABLE = default_deterministic_table()


@dataclass
class _ScriptedCompleter:
    remediation_class: RemediationClass = RemediationClass.MERCHANT_CONTACT_RAZORPAY
    cost_per_call: float | None = 0.00004
    reasoning_tokens: int | None = 0
    attempts: int = 1
    finish_reason: str | None = "stop"
    model_name: str = "fake/model"
    fail_first_n: int = 0
    calls: list[str] = field(default_factory=list)

    def complete_json(
        self,
        *,
        messages: Sequence[Message],
        response_model: type[BaseModel],
        schema_name: str,
        description: str | None = None,
    ) -> LlmJsonResult[Any]:
        self.calls.append(schema_name)
        if len(self.calls) <= self.fail_first_n:
            raise RetriesExhaustedError("scripted failure")
        value = AmbiguousReasonDiagnosis(
            remediation_class=self.remediation_class,
            confidence=Confidence.HIGH,
            rationale="scripted",
        )
        usage = LlmUsage(
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            reasoning_tokens=self.reasoning_tokens,
            cost=self.cost_per_call,
        )
        return LlmJsonResult(
            value=value,
            usage=usage,
            model=self.model_name,
            attempts=self.attempts,
            finish_reason=self.finish_reason,
        )


def test_run_model_comparison_samples_and_reports_agreement() -> None:
    completer = _ScriptedCompleter(remediation_class=RemediationClass.CUSTOMER_FIX)
    report = run_model_comparison(
        model_clients={"fake/model": completer},
        n_ambiguous_sample=3,
        n_deterministic_sample=4,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )

    assert len(report.ambiguous_reasons_sampled) == 3
    assert len(report.deterministic_reasons_sampled) == 4
    assert report.ambiguous_reasons_sampled == tuple(sorted(report.ambiguous_reasons_sampled))

    (aggregate,) = report.models
    assert aggregate.n_calls == 7
    assert aggregate.n_errors == 0
    assert aggregate.n_successes == 7
    assert aggregate.total_cost > 0.0
    assert aggregate.mean_reasoning_tokens == 0.0

    expected_matches = sum(
        1
        for reason in report.deterministic_reasons_sampled
        if _SMALL_TABLE.deterministic[reason] == RemediationClass.CUSTOMER_FIX
    )
    assert aggregate.deterministic_agreement_rate == expected_matches / 4


def test_sample_returns_everything_when_k_exceeds_population() -> None:
    completer = _ScriptedCompleter()
    report = run_model_comparison(
        model_clients={"fake/model": completer},
        n_ambiguous_sample=1000,
        n_deterministic_sample=0,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )
    assert set(report.ambiguous_reasons_sampled) == set(_SMALL_TABLE.escalated)
    assert report.deterministic_reasons_sampled == ()

    (aggregate,) = report.models
    assert aggregate.deterministic_agreement_rate is None


def test_no_calls_at_all_does_not_crash_and_reports_zero_latency() -> None:
    completer = _ScriptedCompleter()
    report = run_model_comparison(
        model_clients={"fake/model": completer},
        n_ambiguous_sample=0,
        n_deterministic_sample=0,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )
    (aggregate,) = report.models
    assert aggregate.n_calls == 0
    assert aggregate.mean_latency_seconds == 0.0
    assert aggregate.first_attempt_json_valid_rate is None
    assert aggregate.mean_reasoning_tokens is None


def test_errors_are_recorded_and_excluded_from_cost() -> None:
    completer = _ScriptedCompleter(cost_per_call=0.001, fail_first_n=1)
    report = run_model_comparison(
        model_clients={"fake/model": completer},
        n_ambiguous_sample=2,
        n_deterministic_sample=0,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )
    (aggregate,) = report.models
    assert aggregate.n_calls == 2
    assert aggregate.n_errors == 1
    assert aggregate.n_successes == 1
    assert aggregate.total_cost == 0.001
    failed_call = aggregate.calls[0]
    assert failed_call.error is not None
    assert failed_call.model_remediation_class is None
    assert failed_call.cost is None


def test_pick_default_prefers_zero_errors_and_lower_cost() -> None:
    cheap_clean = _ScriptedCompleter(cost_per_call=0.00001, model_name="cheap")
    expensive_flaky = _ScriptedCompleter(cost_per_call=0.01, fail_first_n=1, model_name="flaky")
    report = run_model_comparison(
        model_clients={"cheap_ok": cheap_clean, "flaky_expensive": expensive_flaky},
        n_ambiguous_sample=2,
        n_deterministic_sample=0,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )
    assert report.recommended_default_model == "cheap_ok"
    assert "zero call errors" in report.recommendation_rationale


def test_pick_default_falls_back_to_fewest_errors_when_every_model_fails() -> None:
    fewer_errors = _ScriptedCompleter(fail_first_n=1, model_name="a")
    more_errors = _ScriptedCompleter(fail_first_n=5, model_name="b")
    report = run_model_comparison(
        model_clients={"model_a": fewer_errors, "model_b": more_errors},
        n_ambiguous_sample=2,
        n_deterministic_sample=0,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )
    assert report.recommended_default_model == "model_a"
    assert "No model completed every sampled call with zero errors" in (
        report.recommendation_rationale
    )


def test_first_attempt_json_valid_rate_reflects_retries() -> None:
    completer = _ScriptedCompleter(attempts=2)
    report = run_model_comparison(
        model_clients={"fake/model": completer},
        n_ambiguous_sample=2,
        n_deterministic_sample=0,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )
    (aggregate,) = report.models
    assert aggregate.first_attempt_json_valid_rate == 0.0


def test_to_json_dict_round_trips() -> None:
    import json

    completer = _ScriptedCompleter()
    report = run_model_comparison(
        model_clients={"fake/model": completer},
        n_ambiguous_sample=2,
        n_deterministic_sample=2,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )
    payload = json.dumps(to_json_dict(report))
    parsed = json.loads(payload)
    assert parsed["recommended_default_model"] == "fake/model"
    assert parsed["provenance"]["models"] == ["fake/model"]


def test_to_markdown_includes_headline_sections() -> None:
    completer = _ScriptedCompleter()
    report = run_model_comparison(
        model_clients={"fake/model": completer},
        n_ambiguous_sample=2,
        n_deterministic_sample=2,
        sample_seed=DEFAULT_SAMPLE_SEED,
    )
    markdown = to_markdown(report)
    assert "# Phase 7 model-comparison results" in markdown
    assert "## Aggregate comparison" in markdown
    assert "Recommended default model" in markdown
    assert "fake/model" in markdown
