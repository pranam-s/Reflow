"""Building an OpenRouter ``json_schema`` response format from a Pydantic model.

Verified live (``BUILD_LOG.md``, 2026-08-22): OpenRouter's ``json_schema``
structured-output mode works and returns complete, valid JSON when a model's
reasoning is bounded or disabled. This module builds the wire shape the
installed ``openrouter`` SDK expects for it
(``openrouter.components.chatformatjsonschemaconfig.ChatFormatJSONSchemaConfig``,
read directly from ``.venv`` rather than assumed): ``{"type": "json_schema",
"json_schema": {"name": ..., "schema": ..., "strict": true}}``.

Every response model in :mod:`reflow.diagnose.models` is defined with
``model_config = ConfigDict(extra="forbid")`` and no optional/defaulted
fields specifically so that :meth:`pydantic.BaseModel.model_json_schema`
emits a schema already compatible with strict mode (every property
required, ``additionalProperties: false``) without this module needing to
post-process the schema.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

JsonSchemaResponseFormat = dict[str, Any]
"""The plain-dict shape ``openrouter``'s typed ``response_format`` parameter
accepts and validates into
``openrouter.components.ChatFormatJSONSchemaConfig``."""


def json_schema_response_format(
    model: type[BaseModel], *, name: str, description: str | None = None
) -> JsonSchemaResponseFormat:
    """Build a strict ``json_schema`` response format for one Pydantic model.

    Args:
        model: The Pydantic model every valid completion must satisfy.
        name: Schema name reported to the model; must match
            ``^[a-zA-Z0-9_-]+$`` and be at most 64 characters, per the
            installed SDK's
            ``ChatJSONSchemaConfig.name`` docstring.
        description: Optional human-readable schema description forwarded
            to the model.

    Returns:
        A plain dict matching the OpenRouter wire shape for a strict
        ``json_schema`` response format.
    """
    json_schema: dict[str, Any] = {
        "name": name,
        "schema": model.model_json_schema(),
        "strict": True,
    }
    if description is not None:
        json_schema["description"] = description
    return {"type": "json_schema", "json_schema": json_schema}
