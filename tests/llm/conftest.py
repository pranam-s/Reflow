"""Shared fixtures for reflow.llm's VCR-recorded tests.

``filter_headers`` strips the ``Authorization`` header from every recorded
request before ``pytest-recording``/``vcrpy`` ever writes a cassette to
disk (see ``vcr.config.Config._build_before_record_request``, read from
``.venv`` before relying on it): the filter runs as part of building the
request that gets serialised, not as a post-hoc scrub, so no cassette this
suite writes can carry a live credential in the first place.
``_strip_set_cookie`` additionally drops the response ``Set-Cookie`` header
OpenRouter's Cloudflare edge attaches to every response (a short-lived bot
-management token, not an OpenRouter credential, but dropped anyway since
it is not needed to replay the interaction). Every committed cassette under
``tests/llm/cassettes/`` was additionally inspected by hand for the
``Authorization`` key and any bearer-token-shaped string; see
``docs/reports/phase4_diagnosis.md`` for that confirmation.
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
    """Redact the Authorization request header and Set-Cookie response header.

    Returns:
        A ``pytest-recording``/``vcrpy`` config dict.
    """
    return {
        "filter_headers": ["authorization"],
        "before_record_response": _strip_set_cookie,
    }
