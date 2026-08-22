"""A thin, provider-agnostic client over the official ``openrouter`` SDK.

Deliverable 1 of Phase 4 (see ``BUILD_LOG.md`` and ``docs/design.md`` for the
findings this module was designed against): structured (``json_schema``)
output, first-class usage/cost accounting, and truncated/invalid JSON and
schema-validation failures treated as retryable outcomes rather than crashes.
The model served by any :class:`~reflow.llm.client.LlmClient` is always
chosen by its caller's :class:`~reflow.llm.config.LlmConfig` -- this package
never hardcodes a default model.

- :mod:`reflow.llm.config` -- :class:`~reflow.llm.config.LlmConfig` and
  :func:`~reflow.llm.config.load_api_key`, which reads the OpenRouter API key
  from ``os.environ`` only.
- :mod:`reflow.llm.errors` -- the typed exception hierarchy every failure
  mode surfaces as.
- :mod:`reflow.llm.schema` -- builds a strict ``json_schema`` response
  format from a Pydantic model.
- :mod:`reflow.llm.client` -- :class:`~reflow.llm.client.LlmClient`, the
  sync/async structured-output client itself.
"""

from reflow.llm.client import (
    JsonCompleter,
    LlmClient,
    LlmJsonResult,
    LlmUsage,
    Message,
    system_message,
    user_message,
)
from reflow.llm.config import API_KEY_ENV_VAR, LlmConfig, load_api_key
from reflow.llm.errors import (
    LlmError,
    MissingApiKeyError,
    ReasoningMandatoryError,
    RetriesExhaustedError,
    SchemaValidationError,
    TruncatedResponseError,
)
from reflow.llm.schema import JsonSchemaResponseFormat, json_schema_response_format

__all__ = [
    "API_KEY_ENV_VAR",
    "JsonCompleter",
    "JsonSchemaResponseFormat",
    "LlmClient",
    "LlmConfig",
    "LlmError",
    "LlmJsonResult",
    "LlmUsage",
    "Message",
    "MissingApiKeyError",
    "ReasoningMandatoryError",
    "RetriesExhaustedError",
    "SchemaValidationError",
    "TruncatedResponseError",
    "json_schema_response_format",
    "load_api_key",
    "system_message",
    "user_message",
]
