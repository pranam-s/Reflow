"""Exception hierarchy for :mod:`reflow.llm`.

Every failure mode this module's client can encounter is surfaced as one of
these typed exceptions rather than an uncaught SDK exception or a silent bad
value. This matters specifically because of two verified findings recorded in
``BUILD_LOG.md`` (2026-08-22/23): a reasoning-mandatory model rejects a
request to disable reasoning with an HTTP 400, and a reasoning model can
consume its entire completion-token budget on hidden reasoning and return
truncated or empty content. Both must be recoverable, typed outcomes a caller
can branch on, never a crash.
"""

from __future__ import annotations


class LlmError(Exception):
    """Base class for every error raised by :mod:`reflow.llm`."""


class MissingApiKeyError(LlmError):
    """Raised when no OpenRouter API key is available in the environment."""


class ReasoningMandatoryError(LlmError):
    """Raised when a model refuses to disable or bound its reasoning.

    Verified live (``BUILD_LOG.md``, 2026-08-22): requesting
    ``google/gemini-3.7-flash`` disable its reasoning returns
    ``400 "Reasoning is mandatory for this endpoint and cannot be
    disabled."``. This is a model-capability fact, not a transient failure,
    so :class:`~reflow.llm.client.LlmClient` never retries it -- retrying
    with the same request would fail identically and only spend money on
    reasoning tokens for a call already known to be unusable as configured.
    """


class TruncatedResponseError(LlmError):
    """Raised when a chat completion's content is missing or not valid JSON.

    Covers both verified failure shapes from ``BUILD_LOG.md``: a reasoning
    model that spends its whole completion-token budget on reasoning and
    returns ``content: None``, and one that returns content truncated
    mid-object because reasoning left too little budget for the visible
    answer. Both are retryable: a fresh attempt (optionally after the caller
    raises ``max_completion_tokens``) may succeed where a crash would not
    give the caller that chance.
    """


class SchemaValidationError(LlmError):
    """Raised when a completion is valid JSON but fails the response schema.

    Distinct from :class:`TruncatedResponseError` because the completion is
    syntactically well-formed JSON; it simply does not satisfy the Pydantic
    model the caller asked for (e.g. an out-of-vocabulary enum value). Also
    retryable, since a model can produce a compliant response on a later
    sampling even when ``strict`` structured output is requested.
    """


class RetriesExhaustedError(LlmError):
    """Raised when every retry attempt for one call has failed.

    Wraps whichever :class:`LlmError` the last attempt raised so a caller
    can inspect ``__cause__`` for the underlying reason without this module
    ever letting a raw SDK or JSON-parsing exception escape uncaught.
    """
