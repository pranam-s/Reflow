"""A thin, provider-agnostic OpenRouter chat-completion client.

Built directly on the official ``openrouter`` Python SDK (installed version
read from ``.venv`` before writing any of this module, per ``CLAUDE.md``),
which is httpx- and Pydantic-based and exposes both a synchronous and an
asynchronous chat-completion method (:meth:`Chat.send` /
:meth:`Chat.send_async` on ``openrouter.chat.Chat`). This module wraps those
two methods with exactly the behaviour this project's diagnosis tier needs
and nothing else: structured (``json_schema``) output validated against a
caller-supplied Pydantic model, first-class usage/cost accounting, and a
retry loop that treats truncated or schema-invalid JSON as a recoverable
failure rather than a crash.

**Why ``reasoning_effort``, not ``reasoning: {"enabled": false}``.** The
installed SDK's typed Chat Completions request model
(``openrouter.components.chatrequest.ChatRequestReasoning``, read directly
from ``.venv``) models only ``effort`` and ``summary`` for this endpoint --
not the richer ``enabled`` / ``max_tokens`` / ``exclude`` wire object
OpenRouter's own documentation describes for the ``reasoning`` parameter.
Since the SDK's base model config does not set ``extra="forbid"``, Pydantic
silently drops an unrecognised ``enabled`` key rather than raising, which
would make a caller's intent to disable reasoning silently no-op if sent
through that field. The fully-typed, SDK-native ``reasoning_effort``
top-level shorthand parameter is used instead: OpenRouter's own docs state
it is "equivalent to setting reasoning.effort", and that setting effort to
``"none"`` "disables the reasoning process entirely" (primarily honoured by
OpenAI o-series/GPT-5 and Grok-style effort-controllable models). A model
that mandates reasoning rejects this the same way it was verified to reject
``enabled: false`` in ``BUILD_LOG.md`` (2026-08-22): an HTTP 400 whose
message names reasoning as mandatory, surfaced here as
:class:`~reflow.llm.errors.ReasoningMandatoryError`.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from openrouter import OpenRouter
from openrouter import errors as openrouter_errors
from openrouter.components import ChatResult
from pydantic import BaseModel, ValidationError

from reflow.llm.config import LlmConfig
from reflow.llm.errors import (
    LlmError,
    ReasoningMandatoryError,
    RetriesExhaustedError,
    SchemaValidationError,
    TruncatedResponseError,
)
from reflow.llm.schema import json_schema_response_format

T = TypeVar("T", bound=BaseModel)

Message = Mapping[str, str]
"""One chat message, e.g. ``{"role": "system", "content": "..."}`` or
``{"role": "user", "content": "..."}``. This project's diagnosis tier only
ever sends system/user turns, never tool calls or multi-turn history."""

_REASONING_MANDATORY_MARKER = "reasoning is mandatory"


def system_message(content: str) -> Message:
    """Build a system-role chat message.

    Args:
        content: The system prompt text.

    Returns:
        A ``{"role": "system", "content": content}`` message.
    """
    return {"role": "system", "content": content}


def user_message(content: str) -> Message:
    """Build a user-role chat message.

    Args:
        content: The user prompt text.

    Returns:
        A ``{"role": "user", "content": content}`` message.
    """
    return {"role": "user", "content": content}


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """Token and cost accounting for one chat completion, as first-class fields.

    Attributes:
        prompt_tokens: Prompt tokens billed.
        completion_tokens: Completion tokens billed, including any hidden
            reasoning tokens the provider counts against the same budget.
        total_tokens: ``prompt_tokens + completion_tokens`` as reported by
            the provider.
        reasoning_tokens: Tokens spent on hidden reasoning, or ``None`` if
            the provider did not report
            ``usage.completion_tokens_details.reasoning_tokens``.
        cost: OpenRouter's reported dollar cost for this call, or ``None``
            if not reported (e.g. some free-tier responses).
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int | None
    cost: float | None


@dataclass(frozen=True, slots=True)
class LlmJsonResult(Generic[T]):
    """The outcome of one successful structured-output chat completion.

    Attributes:
        value: The parsed, schema-validated response.
        usage: Token and cost accounting for the attempt that succeeded.
        model: The model slug OpenRouter reports having actually served
            the request (may differ from the requested slug for router
            aliases).
        attempts: Total attempts made, including the successful one.
        finish_reason: The provider's reported completion finish reason
            (e.g. ``"stop"``, ``"length"``), or ``None`` if unreported.
    """

    value: T
    usage: LlmUsage
    model: str
    attempts: int
    finish_reason: str | None


@runtime_checkable
class JsonCompleter(Protocol):
    """Structural interface for anything that can serve :meth:`complete_json`.

    :mod:`reflow.diagnose` depends on this Protocol rather than the concrete
    :class:`LlmClient`, so its unit tests can supply a lightweight fake
    completer with no network, no ``openrouter`` SDK object, and no
    credentials, while :class:`LlmClient` itself satisfies it structurally
    with no extra declaration needed.
    """

    def complete_json(
        self,
        *,
        messages: Sequence[Message],
        response_model: type[T],
        schema_name: str,
        description: str | None = None,
    ) -> LlmJsonResult[T]:
        """Request one structured-output completion.

        Args:
            messages: The conversation to send.
            response_model: The Pydantic model the parsed content must
                satisfy.
            schema_name: Name reported to the model for the response
                schema.
            description: Optional schema description forwarded to the
                model.

        Returns:
            The validated :class:`LlmJsonResult`.
        """
        ...


def _is_reasoning_mandatory_error(error: openrouter_errors.OpenRouterError) -> bool:
    """Detect the verified reasoning-mandatory refusal shape.

    Args:
        error: An error raised by the ``openrouter`` SDK.

    Returns:
        ``True`` if ``error`` is the HTTP 400 "Reasoning is mandatory for
        this endpoint and cannot be disabled." refusal verified in
        ``BUILD_LOG.md`` (2026-08-22).
    """
    return error.status_code == 400 and _REASONING_MANDATORY_MARKER in error.message.lower()


def _extract_usage(chat_result: ChatResult) -> LlmUsage:
    """Extract token/cost usage from a completed chat result.

    Args:
        chat_result: The SDK's parsed chat-completion response.

    Returns:
        The populated :class:`LlmUsage`, with every optional field ``None``
        when the provider did not report it.
    """
    usage = chat_result.usage
    if usage is None:
        return LlmUsage(
            prompt_tokens=0, completion_tokens=0, total_tokens=0, reasoning_tokens=None, cost=None
        )
    reasoning_tokens: int | None = None
    details = usage.completion_tokens_details
    if details:
        candidate = details.reasoning_tokens
        if isinstance(candidate, int):
            reasoning_tokens = candidate
    cost = usage.cost if isinstance(usage.cost, int | float) else None
    return LlmUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        reasoning_tokens=reasoning_tokens,
        cost=float(cost) if cost is not None else None,
    )


def _to_result(chat_result: ChatResult, response_model: type[T], attempts: int) -> LlmJsonResult[T]:
    """Parse and schema-validate one chat result into an :class:`LlmJsonResult`.

    Args:
        chat_result: The SDK's parsed chat-completion response.
        response_model: The Pydantic model the content must satisfy.
        attempts: Total attempts made so far, including this one.

    Returns:
        The populated :class:`LlmJsonResult`.

    Raises:
        TruncatedResponseError: If there are no choices, or the message
            content is missing, empty, non-text, or not valid JSON.
        SchemaValidationError: If the content is valid JSON but does not
            satisfy ``response_model``.
    """
    if not chat_result.choices:
        raise TruncatedResponseError("Completion returned no choices.")
    choice = chat_result.choices[0]
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise TruncatedResponseError(
            f"Completion content was empty or non-text (finish_reason={choice.finish_reason!r})."
        )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise TruncatedResponseError(f"Completion content was not valid JSON: {exc}") from exc
    try:
        value = response_model.model_validate(parsed)
    except ValidationError as exc:
        raise SchemaValidationError(str(exc)) from exc
    finish_reason = None if choice.finish_reason is None else str(choice.finish_reason)
    return LlmJsonResult(
        value=value,
        usage=_extract_usage(chat_result),
        model=chat_result.model,
        attempts=attempts,
        finish_reason=finish_reason,
    )


class LlmClient:
    """A provider-agnostic OpenRouter client for one configured model.

    Sync and async structured-output completions share one retry policy:
    truncated/invalid JSON and schema-validation failures are retried up to
    :attr:`~reflow.llm.config.LlmConfig.max_attempts` times with exponential
    backoff; a verified reasoning-mandatory refusal is never retried, since
    retrying an unchanged request against a model that has already rejected
    that exact configuration cannot succeed.
    """

    def __init__(self, config: LlmConfig) -> None:
        """Initialise the client.

        Args:
            config: This client's configuration, including the model it is
                bound to.
        """
        self._config = config
        self._sdk = OpenRouter(api_key=config.api_key, timeout_ms=config.timeout_ms)

    def close(self) -> None:
        """Close the underlying synchronous and asynchronous HTTP clients.

        ``OpenRouter.__exit__`` carries no type annotations in the installed
        SDK (verified in ``.venv/Lib/site-packages/openrouter/sdk.py``), so
        mypy strict mode flags calling it as an untyped call; suppressed
        narrowly since the call itself is correct.
        """
        self._sdk.__exit__(None, None, None)  # type: ignore[no-untyped-call]

    async def aclose(self) -> None:
        """Close the underlying asynchronous HTTP client.

        See :meth:`close` for why the untyped-call suppression is needed.
        """
        await self._sdk.__aexit__(None, None, None)  # type: ignore[no-untyped-call]

    def __enter__(self) -> LlmClient:
        """Enter the client as a context manager.

        Returns:
            This client.
        """
        return self

    def __exit__(self, *_exc_info: object) -> None:
        """Exit the context manager, closing the underlying HTTP client."""
        self.close()

    async def __aenter__(self) -> LlmClient:
        """Enter the client as an async context manager.

        Returns:
            This client.
        """
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Exit the async context manager, closing the underlying HTTP client."""
        await self.aclose()

    def _request_kwargs(
        self, messages: Sequence[Message], response_format: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the keyword arguments shared by the sync and async send paths.

        Args:
            messages: The conversation to send.
            response_format: The ``json_schema`` response format dict.

        Returns:
            A kwargs dict containing only the keys this client wants to set
            explicitly, leaving every other SDK parameter at its own
            default rather than overriding it with an explicit ``None``.
        """
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": [dict(message) for message in messages],
            "response_format": response_format,
            "max_completion_tokens": self._config.max_completion_tokens,
        }
        if self._config.temperature is not None:
            kwargs["temperature"] = self._config.temperature
        if self._config.reasoning_effort is not None:
            kwargs["reasoning_effort"] = self._config.reasoning_effort
        return kwargs

    def _backoff_seconds(self, attempt: int) -> float:
        """Compute the exponential-backoff delay before the next attempt.

        Args:
            attempt: The attempt number that just failed (1-based).

        Returns:
            A delay in seconds, ``0.0`` when
            :attr:`~reflow.llm.config.LlmConfig.retry_base_delay_seconds` is
            non-positive (used by every test in this repository so retries
            never add wall-clock time).
        """
        base = self._config.retry_base_delay_seconds
        if base <= 0:
            return 0.0
        return base * (2.0 ** (attempt - 1)) + random.uniform(0.0, base)  # noqa: S311

    def complete_json(
        self,
        *,
        messages: Sequence[Message],
        response_model: type[T],
        schema_name: str,
        description: str | None = None,
    ) -> LlmJsonResult[T]:
        """Request one structured-output completion, synchronously.

        Args:
            messages: The conversation to send.
            response_model: The Pydantic model the parsed content must
                satisfy.
            schema_name: Name reported to the model for the response
                schema.
            description: Optional schema description forwarded to the
                model.

        Returns:
            The validated :class:`LlmJsonResult`.

        Raises:
            ReasoningMandatoryError: If the model refuses to honour this
                client's reasoning configuration. Never retried.
            RetriesExhaustedError: If every attempt failed with a retryable
                error.
        """
        response_format = json_schema_response_format(
            response_model, name=schema_name, description=description
        )
        request_kwargs = self._request_kwargs(messages, response_format)
        last_error: Exception | None = None
        for attempt in range(1, self._config.max_attempts + 1):
            try:
                chat_result = self._sdk.chat.send(**request_kwargs)
                return _to_result(chat_result, response_model, attempt)
            except openrouter_errors.OpenRouterError as exc:
                if _is_reasoning_mandatory_error(exc):
                    raise ReasoningMandatoryError(str(exc)) from exc
                last_error = exc
            except LlmError as exc:
                last_error = exc
            if attempt < self._config.max_attempts:
                time.sleep(self._backoff_seconds(attempt))
        raise RetriesExhaustedError(
            f"LLM call to {self._config.model!r} failed after "
            f"{self._config.max_attempts} attempt(s): {last_error}"
        ) from last_error

    async def complete_json_async(
        self,
        *,
        messages: Sequence[Message],
        response_model: type[T],
        schema_name: str,
        description: str | None = None,
    ) -> LlmJsonResult[T]:
        """Request one structured-output completion, asynchronously.

        Args:
            messages: The conversation to send.
            response_model: The Pydantic model the parsed content must
                satisfy.
            schema_name: Name reported to the model for the response
                schema.
            description: Optional schema description forwarded to the
                model.

        Returns:
            The validated :class:`LlmJsonResult`.

        Raises:
            ReasoningMandatoryError: If the model refuses to honour this
                client's reasoning configuration. Never retried.
            RetriesExhaustedError: If every attempt failed with a retryable
                error.
        """
        response_format = json_schema_response_format(
            response_model, name=schema_name, description=description
        )
        request_kwargs = self._request_kwargs(messages, response_format)
        last_error: Exception | None = None
        for attempt in range(1, self._config.max_attempts + 1):
            try:
                chat_result = await self._sdk.chat.send_async(**request_kwargs)
                return _to_result(chat_result, response_model, attempt)
            except openrouter_errors.OpenRouterError as exc:
                if _is_reasoning_mandatory_error(exc):
                    raise ReasoningMandatoryError(str(exc)) from exc
                last_error = exc
            except LlmError as exc:
                last_error = exc
            if attempt < self._config.max_attempts:
                await asyncio.sleep(self._backoff_seconds(attempt))
        raise RetriesExhaustedError(
            f"LLM call to {self._config.model!r} failed after "
            f"{self._config.max_attempts} attempt(s): {last_error}"
        ) from last_error
