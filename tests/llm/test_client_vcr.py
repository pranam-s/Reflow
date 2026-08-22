"""VCR-cassette-recorded tests against real OpenRouter models.

Every cassette under ``cassettes/test_client_vcr/`` was recorded once, for
real, against the live OpenRouter API::

    uv run --env-file .env pytest tests/llm/test_client_vcr.py --record-mode=once

and is replayed thereafter with ``pytest-recording``'s default
``--record-mode=none``, so this module costs $0 and needs no network or
credentials in ordinary test runs -- ``vcrpy`` intercepts the ``httpx``
transport before any real connection is attempted. See ``conftest.py`` for
the ``Authorization``-header redaction applied before a cassette is ever
written.

Each test uses ``max_attempts=1`` (or, for the reasoning-mandatory case,
a value that documents it is never reached) so that it corresponds to
exactly one recorded HTTP interaction. Retry/backoff and
schema-validation-failure behaviour are already covered, cheaply and
deterministically with no live-model non-determinism, by
``test_client_unit.py``; what only a real recorded interaction can prove is
that the live API actually behaves the way ``BUILD_LOG.md`` says it does.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, ConfigDict

from reflow.llm.client import LlmClient, user_message
from reflow.llm.config import LlmConfig
from reflow.llm.errors import ReasoningMandatoryError, RetriesExhaustedError

_API_KEY = os.environ.get("OPENROUTER_API_KEY", "sk-or-v1-recorded-cassette-placeholder")
"""Read from ``os.environ`` only, never from ``.env`` directly. A real key
is only needed the one time a cassette is (re-)recorded; every ordinary
test run replays a cassette and never sends this value anywhere."""


class _CapitalDiagnosis(BaseModel):
    """A trivial structured-output schema, unrelated to payments diagnosis.

    Deliberately simple and off-topic from :mod:`reflow.diagnose`'s real
    schemas: these tests exercise ``reflow.llm``'s transport-level
    behaviour (structured output, reasoning configuration, truncation),
    not diagnosis-specific prompt content, which is covered separately in
    ``tests/diagnose``.
    """

    model_config = ConfigDict(extra="forbid")

    country: str
    capital: str


@pytest.mark.vcr
def test_deepseek_structured_output_with_reasoning_disabled() -> None:
    """Deepseek honours ``reasoning_effort="none"`` and returns valid JSON.

    Verified live (``BUILD_LOG.md``, 2026-08-22):
    ``deepseek/deepseek-v4-flash`` accepts a disabled-reasoning request and
    returns complete, valid structured output cheaply.
    """
    client = LlmClient(
        LlmConfig(
            model="deepseek/deepseek-v4-flash",
            api_key=_API_KEY,
            reasoning_effort="none",
            max_completion_tokens=200,
            max_attempts=1,
        )
    )
    result = client.complete_json(
        messages=[user_message("What is the capital of France? Answer as JSON.")],
        response_model=_CapitalDiagnosis,
        schema_name="capital_diagnosis",
    )
    assert result.value.country.lower() == "france"
    assert result.value.capital.lower() == "paris"
    assert result.usage.cost is not None
    assert result.usage.cost < 0.001
    assert result.attempts == 1


@pytest.mark.vcr
def test_gemini_reasoning_mandatory_refusal() -> None:
    """Gemini 3.7 Flash refuses to disable its reasoning.

    Verified live (``BUILD_LOG.md``, 2026-08-22): requesting
    ``google/gemini-3.7-flash`` disable its reasoning returns an HTTP 400
    naming reasoning as mandatory. ``max_attempts`` is set high to prove
    :class:`~reflow.llm.errors.ReasoningMandatoryError` is raised
    immediately rather than retried -- exactly one interaction is
    recorded in this cassette despite the higher attempt budget.
    """
    client = LlmClient(
        LlmConfig(
            model="google/gemini-3.7-flash",
            api_key=_API_KEY,
            reasoning_effort="none",
            max_completion_tokens=200,
            max_attempts=5,
        )
    )
    with pytest.raises(ReasoningMandatoryError):
        client.complete_json(
            messages=[user_message("What is the capital of France? Answer as JSON.")],
            response_model=_CapitalDiagnosis,
            schema_name="capital_diagnosis",
        )


@pytest.mark.vcr
def test_gemini_truncated_json_under_tight_token_budget() -> None:
    """A reasoning-mandatory model can truncate JSON under a tight budget.

    Verified live (``BUILD_LOG.md``, 2026-08-22): a one-sentence diagnosis
    against ``google/gemini-3.7-flash`` spent 364 of 385 completion tokens
    on hidden reasoning and truncated the JSON mid-object. This reproduces
    that failure mode directly rather than merely asserting it from a log
    entry, and proves it surfaces as
    :class:`~reflow.llm.errors.RetriesExhaustedError` (wrapping a
    :class:`~reflow.llm.errors.TruncatedResponseError`), never an
    unhandled exception.
    """
    client = LlmClient(
        LlmConfig(
            model="google/gemini-3.7-flash",
            api_key=_API_KEY,
            max_completion_tokens=30,
            max_attempts=1,
        )
    )
    with pytest.raises(RetriesExhaustedError) as excinfo:
        client.complete_json(
            messages=[user_message("What is the capital of France? Answer as JSON.")],
            response_model=_CapitalDiagnosis,
            schema_name="capital_diagnosis",
        )
    assert excinfo.value.__cause__ is not None
