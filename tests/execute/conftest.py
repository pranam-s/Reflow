"""Shared fixtures for reflow.execute's VCR-recorded tests.

Mirrors ``tests/llm/conftest.py``'s ``Authorization``-redaction pattern,
with one addition: ``decode_compressed_response=True``. Razorpay's API
gzip-compresses its responses (confirmed by inspecting a first recording
attempt without this option: the cassette stored an unreadable base64
-encoded binary blob for every response body, exactly as
``tests/llm/cassettes/`` already does for OpenRouter). Decoding at record
time means every committed cassette under
``tests/execute/cassettes/test_gateway_live/`` stores its response bodies
as plain, human-readable JSON text -- which is what makes "verify by
reading each committed cassette" (this phase's brief) actually
practical, and is also what lets
``reflow.eval.execute._extract_cassette_interactions`` parse a response
body with a plain ``json.loads`` call, no gzip handling required.
"""

from __future__ import annotations

from typing import Any

import pytest


def _strip_set_cookie(response: dict[str, Any]) -> dict[str, Any]:
    """Drop the ``Set-Cookie`` response header before a cassette is written.

    Args:
        response: The ``vcrpy`` response dict about to be recorded.

    Returns:
        The same dict, with any ``Set-Cookie`` header entry removed.
    """
    headers = response.get("headers") or {}
    for key in [key for key in headers if key.lower() == "set-cookie"]:
        del headers[key]
    return response


@pytest.fixture
def vcr_config() -> dict[str, object]:
    """Redact the Authorization header and decode compressed responses.

    Returns:
        A ``pytest-recording``/``vcrpy`` config dict.
    """
    return {
        "filter_headers": ["authorization"],
        "decode_compressed_response": True,
        "before_record_response": _strip_set_cookie,
    }
