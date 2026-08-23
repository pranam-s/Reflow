"""Runtime configuration for :mod:`reflow.llm`, loaded from ``os.environ`` only.

Per ``CLAUDE.md``: ``.env`` holds live credentials and must never be read,
written, or printed by any agent or by this codebase. The only supported way
to supply an OpenRouter API key to this module is the process environment
(:func:`load_api_key`), which a human or the shell -- never this repository's
own code -- populates however it likes (exported variables, ``uv run
--env-file``, a secrets manager, and so on).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from reflow.llm.errors import MissingApiKeyError

API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
"""The environment variable :func:`load_api_key` reads."""


def load_api_key(env: Mapping[str, str] | None = None) -> str:
    """Load the OpenRouter API key from the process environment.

    Args:
        env: The mapping to read from. Defaults to ``os.environ``; tests
            pass a plain ``dict`` so no real credential is ever required to
            exercise this function.

    Returns:
        The non-empty API key string.

    Raises:
        MissingApiKeyError: If :data:`API_KEY_ENV_VAR` is unset or empty.
    """
    source = env if env is not None else os.environ
    api_key = source.get(API_KEY_ENV_VAR)
    if not api_key:
        raise MissingApiKeyError(
            f"{API_KEY_ENV_VAR} is not set. Export it in the process environment "
            "(e.g. `uv run --env-file .env ...`); this codebase never reads .env itself."
        )
    return api_key


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """Everything one :class:`~reflow.llm.client.LlmClient` needs to run.

    No field here defaults to a specific model: per this phase's brief, the
    provider-agnostic client never pre-commits a default model, since Phase 7
    picks a production default on evidence the same way ``docs/design.md``
    ADR-0002 and ADR-0003 picked their defaults.

    Attributes:
        model: OpenRouter model slug (e.g. ``"deepseek/deepseek-v4-flash"``),
            chosen entirely by the caller.
        api_key: OpenRouter API key, e.g. from :func:`load_api_key`. Excluded
            from this dataclass's ``repr`` (``field(repr=False)``, added in
            Phase 6 after a live Razorpay credential was found to leak
            through an analogous dataclass's default ``repr`` in an
            uncaught exception's traceback -- see
            :class:`reflow.execute.gateway.RazorpayGateway`'s
            ``key_secret`` field docstring) so constructing, logging, or an
            uncaught exception printing this object can never echo it.
        reasoning_effort: Forwarded verbatim to the OpenRouter SDK's
            top-level ``reasoning_effort`` shorthand (equivalent to
            ``reasoning.effort``; see
            :mod:`reflow.llm.client` module docstring for why this project
            uses that shorthand rather than the richer
            ``reasoning: {"enabled": ...}`` wire object). ``"none"``
            requests that reasoning be disabled entirely; per OpenRouter's
            own documentation this is honoured by effort-controllable
            models and rejected (see
            :class:`~reflow.llm.errors.ReasoningMandatoryError`) by models
            that mandate reasoning. ``None`` leaves the provider's default
            behaviour untouched.
        max_completion_tokens: Upper bound on completion tokens, covering
            both hidden reasoning and the visible JSON answer for models
            that share one budget across both (the exact mechanism behind
            the truncated-JSON finding in ``BUILD_LOG.md``). Must be
            generous enough to survive mandatory reasoning overhead.
        temperature: Sampling temperature, or ``None`` to omit it and use
            the provider's default.
        max_attempts: Maximum number of attempts (the first call plus
            retries) for one logical request before
            :class:`~reflow.llm.errors.RetriesExhaustedError` is raised.
        retry_base_delay_seconds: Base delay for exponential backoff between
            attempts. ``0.0`` makes retries instantaneous, which is what
            every test in this repository uses so the suite costs no wall
            -clock time.
        timeout_ms: Per-request timeout in milliseconds, or ``None`` to use
            the SDK's own default.
    """

    model: str
    api_key: str = field(repr=False)
    reasoning_effort: str | None = None
    max_completion_tokens: int = 1024
    temperature: float | None = 0.0
    max_attempts: int = 3
    retry_base_delay_seconds: float = 0.5
    timeout_ms: int | None = None
