"""Unit tests for reflow.llm.client's retry/parsing logic, with no network.

Every test replaces ``LlmClient``'s internal ``openrouter`` SDK's ``chat``
attribute with a small fake exposing only ``send``, so the retry loop, JSON
parsing, schema validation, and reasoning-mandatory detection are exercised
directly against the public :meth:`LlmClient.complete_json` without ever
opening a real HTTP connection. Live-provider-specific behaviour (what a
real reasoning-mandatory refusal or a real truncated response actually
looks like on the wire) is covered separately by the VCR-cassette tests in
``test_client_vcr.py``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from openrouter import components
from openrouter import errors as openrouter_errors
from pydantic import BaseModel, ConfigDict

from reflow.llm.client import LlmClient
from reflow.llm.config import LlmConfig
from reflow.llm.errors import (
    ReasoningMandatoryError,
    RetriesExhaustedError,
)


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


def _chat_result(
    content: str | None,
    *,
    finish_reason: str | None = "stop",
    reasoning_tokens: int | None = None,
    cost: float | None = 0.0001,
) -> components.ChatResult:
    details = None
    if reasoning_tokens is not None:
        details = components.ChatUsageCompletionTokensDetails(reasoning_tokens=reasoning_tokens)
    usage = components.ChatUsage(
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        completion_tokens_details=details,
        cost=cost,
    )
    message = components.ChatAssistantMessage(role="assistant", content=content)
    choice = components.ChatChoice(finish_reason=finish_reason, index=0, message=message)
    return components.ChatResult(
        choices=[choice],
        created=0,
        id="chatcmpl-test",
        model="fake/model",
        object="chat.completion",
        system_fingerprint=None,
        usage=usage,
    )


def _openrouter_error(message: str, status_code: int) -> openrouter_errors.OpenRouterError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status_code=status_code, text=message, request=request)
    return openrouter_errors.OpenRouterError(message, response)


@dataclass
class _FakeChat:
    """Replaces ``OpenRouter().chat``: returns/raises queued items in order."""

    queue: list[components.ChatResult | Exception] = field(default_factory=list)
    calls: int = 0
    last_kwargs: dict[str, Any] = field(default_factory=dict)

    def send(self, **kwargs: Any) -> components.ChatResult:
        self.calls += 1
        self.last_kwargs = kwargs
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def send_async(self, **kwargs: Any) -> components.ChatResult:
        return self.send(**kwargs)


def _client(**overrides: Any) -> tuple[LlmClient, _FakeChat]:
    """Build an ``LlmClient`` whose internal SDK ``chat`` object is a fake.

    ``LlmClient`` has no public seam for injecting a fake transport (unlike
    :mod:`reflow.diagnose`, which depends on the
    :class:`~reflow.llm.client.JsonCompleter` Protocol precisely so its own
    tests can do this cleanly): it is the thing that wraps the real SDK, so
    testing it without real network access means substituting the private
    ``_sdk.chat`` attribute directly. ``_FakeChat`` does not subclass the
    real, code-generated ``openrouter.chat.Chat``, so this assignment is a
    deliberate structural-duck-typing substitution mypy cannot verify;
    suppressed narrowly rather than declaring a heavier Protocol only ever
    used by this one test module.

    Args:
        **overrides: Overrides for :class:`~reflow.llm.config.LlmConfig`'s
            defaults.

    Returns:
        A tuple of the client and the fake chat object driving its
        responses.
    """
    defaults: dict[str, Any] = {
        "model": "fake/model",
        "api_key": "test-key",
        "max_attempts": 3,
        "retry_base_delay_seconds": 0.0,
    }
    defaults.update(overrides)
    client = LlmClient(LlmConfig(**defaults))
    fake_chat = _FakeChat()
    client._sdk.chat = fake_chat  # type: ignore[assignment]
    return client, fake_chat


def _messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "hello"}]


def test_complete_json_success_first_attempt() -> None:
    client, fake_chat = _client()
    fake_chat.queue.append(_chat_result('{"text": "ok"}', reasoning_tokens=5))
    result = client.complete_json(
        messages=_messages(), response_model=_Answer, schema_name="answer"
    )
    assert result.value.text == "ok"
    assert result.attempts == 1
    assert result.usage.reasoning_tokens == 5
    assert result.usage.cost == 0.0001
    assert result.model == "fake/model"
    assert fake_chat.calls == 1


def test_complete_json_retries_transient_error_then_succeeds() -> None:
    client, fake_chat = _client()
    fake_chat.queue.append(_openrouter_error("upstream hiccup", 502))
    fake_chat.queue.append(_chat_result('{"text": "recovered"}'))
    result = client.complete_json(
        messages=_messages(), response_model=_Answer, schema_name="answer"
    )
    assert result.value.text == "recovered"
    assert result.attempts == 2
    assert fake_chat.calls == 2


def test_complete_json_truncated_json_is_retryable_not_a_crash() -> None:
    client, fake_chat = _client(max_attempts=2)
    fake_chat.queue.append(_chat_result("{not valid json", finish_reason="length"))
    fake_chat.queue.append(_chat_result('{"text": "second try"}'))
    result = client.complete_json(
        messages=_messages(), response_model=_Answer, schema_name="answer"
    )
    assert result.value.text == "second try"
    assert result.attempts == 2


def test_complete_json_empty_content_is_treated_as_truncated() -> None:
    client, fake_chat = _client(max_attempts=1)
    fake_chat.queue.append(_chat_result(None, finish_reason="stop"))
    with pytest.raises(RetriesExhaustedError):
        client.complete_json(messages=_messages(), response_model=_Answer, schema_name="answer")


def test_complete_json_exhausts_retries_on_persistent_truncation() -> None:
    client, fake_chat = _client(max_attempts=2)
    fake_chat.queue.append(_chat_result("not json at all"))
    fake_chat.queue.append(_chat_result("still not json"))
    with pytest.raises(RetriesExhaustedError) as excinfo:
        client.complete_json(messages=_messages(), response_model=_Answer, schema_name="answer")
    assert fake_chat.calls == 2
    assert excinfo.value.__cause__ is not None


def test_complete_json_schema_validation_failure_is_retryable() -> None:
    client, fake_chat = _client(max_attempts=2)
    fake_chat.queue.append(_chat_result('{"wrong_field": 1}'))
    fake_chat.queue.append(_chat_result('{"text": "valid now"}'))
    result = client.complete_json(
        messages=_messages(), response_model=_Answer, schema_name="answer"
    )
    assert result.value.text == "valid now"
    assert result.attempts == 2


def test_complete_json_schema_validation_failure_exhausts_retries() -> None:
    client, fake_chat = _client(max_attempts=2)
    fake_chat.queue.append(_chat_result('{"wrong_field": 1}'))
    fake_chat.queue.append(_chat_result('{"wrong_field": 2}'))
    with pytest.raises(RetriesExhaustedError):
        client.complete_json(messages=_messages(), response_model=_Answer, schema_name="answer")


def test_complete_json_reasoning_mandatory_is_never_retried() -> None:
    client, fake_chat = _client(max_attempts=5)
    fake_chat.queue.append(
        _openrouter_error("Reasoning is mandatory for this endpoint and cannot be disabled.", 400)
    )
    with pytest.raises(ReasoningMandatoryError):
        client.complete_json(messages=_messages(), response_model=_Answer, schema_name="answer")
    assert fake_chat.calls == 1


def test_complete_json_ordinary_bad_request_is_retried_not_treated_as_reasoning_mandatory() -> None:
    client, fake_chat = _client(max_attempts=2)
    fake_chat.queue.append(_openrouter_error("invalid model parameter", 400))
    fake_chat.queue.append(_chat_result('{"text": "ok"}'))
    result = client.complete_json(
        messages=_messages(), response_model=_Answer, schema_name="answer"
    )
    assert result.value.text == "ok"


def test_complete_json_async_success() -> None:
    client, fake_chat = _client()
    fake_chat.queue.append(_chat_result('{"text": "async ok"}'))

    async def _run() -> str:
        result = await client.complete_json_async(
            messages=_messages(), response_model=_Answer, schema_name="answer"
        )
        return result.value.text

    assert asyncio.run(_run()) == "async ok"


def test_complete_json_async_reasoning_mandatory() -> None:
    client, fake_chat = _client(max_attempts=3)
    fake_chat.queue.append(
        _openrouter_error("Reasoning is mandatory for this endpoint and cannot be disabled.", 400)
    )

    async def _run() -> None:
        await client.complete_json_async(
            messages=_messages(), response_model=_Answer, schema_name="answer"
        )

    with pytest.raises(ReasoningMandatoryError):
        asyncio.run(_run())
    assert fake_chat.calls == 1


def test_backoff_seconds_is_zero_when_base_delay_is_zero() -> None:
    client, _ = _client(retry_base_delay_seconds=0.0)
    assert client._backoff_seconds(1) == 0.0
    assert client._backoff_seconds(4) == 0.0


def test_backoff_seconds_grows_with_attempt() -> None:
    client, _ = _client(retry_base_delay_seconds=1.0)
    first = client._backoff_seconds(1)
    second = client._backoff_seconds(2)
    assert first >= 1.0
    assert second >= 2.0


def test_request_kwargs_omit_unset_temperature_and_reasoning_effort() -> None:
    client, fake_chat = _client(temperature=None, reasoning_effort=None)
    fake_chat.queue.append(_chat_result('{"text": "ok"}'))
    client.complete_json(messages=_messages(), response_model=_Answer, schema_name="answer")
    assert "temperature" not in fake_chat.last_kwargs
    assert "reasoning_effort" not in fake_chat.last_kwargs


def test_request_kwargs_include_temperature_and_reasoning_effort_when_set() -> None:
    client, fake_chat = _client(temperature=0.2, reasoning_effort="none")
    fake_chat.queue.append(_chat_result('{"text": "ok"}'))
    client.complete_json(messages=_messages(), response_model=_Answer, schema_name="answer")
    assert fake_chat.last_kwargs["temperature"] == 0.2
    assert fake_chat.last_kwargs["reasoning_effort"] == "none"


def test_extract_usage_handles_missing_usage_block() -> None:
    client, fake_chat = _client()
    result_without_usage = components.ChatResult(
        choices=[
            components.ChatChoice(
                finish_reason="stop",
                index=0,
                message=components.ChatAssistantMessage(role="assistant", content='{"text": "ok"}'),
            )
        ],
        created=0,
        id="chatcmpl-no-usage",
        model="fake/model",
        object="chat.completion",
        system_fingerprint=None,
        usage=None,
    )
    fake_chat.queue.append(result_without_usage)
    result = client.complete_json(
        messages=_messages(), response_model=_Answer, schema_name="answer"
    )
    assert result.usage.prompt_tokens == 0
    assert result.usage.cost is None
    assert result.usage.reasoning_tokens is None


def test_complete_json_no_choices_is_treated_as_truncated() -> None:
    client, fake_chat = _client(max_attempts=1)
    empty_result = components.ChatResult(
        choices=[],
        created=0,
        id="chatcmpl-empty",
        model="fake/model",
        object="chat.completion",
        system_fingerprint=None,
        usage=None,
    )
    fake_chat.queue.append(empty_result)
    with pytest.raises(RetriesExhaustedError):
        client.complete_json(messages=_messages(), response_model=_Answer, schema_name="answer")


def test_complete_json_async_retries_transient_error_then_succeeds() -> None:
    client, fake_chat = _client()
    fake_chat.queue.append(_openrouter_error("upstream hiccup", 502))
    fake_chat.queue.append(_chat_result('{"text": "async recovered"}'))

    async def _run() -> str:
        result = await client.complete_json_async(
            messages=_messages(), response_model=_Answer, schema_name="answer"
        )
        return result.value.text

    assert asyncio.run(_run()) == "async recovered"
    assert fake_chat.calls == 2


def test_complete_json_async_exhausts_retries() -> None:
    client, fake_chat = _client(max_attempts=2)
    fake_chat.queue.append(_chat_result("not json"))
    fake_chat.queue.append(_chat_result("still not json"))

    async def _run() -> None:
        await client.complete_json_async(
            messages=_messages(), response_model=_Answer, schema_name="answer"
        )

    with pytest.raises(RetriesExhaustedError):
        asyncio.run(_run())
    assert fake_chat.calls == 2


def test_client_context_manager_closes_underlying_sdk() -> None:
    with LlmClient(LlmConfig(model="fake/model", api_key="test-key")) as client:
        assert client is not None


def test_client_async_context_manager_closes_underlying_sdk() -> None:
    async def _run() -> None:
        async with LlmClient(LlmConfig(model="fake/model", api_key="test-key")) as client:
            assert client is not None

    asyncio.run(_run())
