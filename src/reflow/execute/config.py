"""Runtime credential loading for :mod:`reflow.execute`, from ``os.environ`` only.

Mirrors :mod:`reflow.llm.config`: per ``CLAUDE.md``, ``.env`` holds live
Razorpay and OpenRouter credentials and must never be read, written, or
printed by any agent or by this codebase. The only supported way to supply
Razorpay credentials to this package is the process environment
(:func:`load_credentials`), populated however the caller likes (``uv run
--env-file .env``, exported shell variables, a secrets manager, and so on)
-- never by this module reading ``.env`` itself.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from reflow.execute.errors import MissingCredentialsError

KEY_ID_ENV_VAR = "RAZORPAY_KEY_ID"
"""The environment variable :func:`load_credentials` reads for the key id."""

KEY_SECRET_ENV_VAR = "RAZORPAY_KEY_SECRET"  # noqa: S105 -- an env var *name*, not a credential
"""The environment variable :func:`load_credentials` reads for the key secret. Ruff's hardcoded
-password heuristic (S105) flags this line because the variable name contains ``SECRET``; the
value is the name of an environment variable to read, never a credential value itself, so the
suppression above is correct rather than a real finding."""


def load_credentials(env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Load the Razorpay ``(key_id, key_secret)`` pair from the environment.

    Args:
        env: The mapping to read from. Defaults to ``os.environ``; tests
            pass a plain ``dict`` so no real credential is ever required
            to exercise this function.

    Returns:
        A ``(key_id, key_secret)`` tuple, both non-empty.

    Raises:
        MissingCredentialsError: If either :data:`KEY_ID_ENV_VAR` or
            :data:`KEY_SECRET_ENV_VAR` is unset or empty.
    """
    source = env if env is not None else os.environ
    key_id = source.get(KEY_ID_ENV_VAR)
    key_secret = source.get(KEY_SECRET_ENV_VAR)
    if not key_id or not key_secret:
        raise MissingCredentialsError(
            f"{KEY_ID_ENV_VAR} and {KEY_SECRET_ENV_VAR} must both be set to make a live "
            "Razorpay call (e.g. `uv run --env-file .env ...`); this codebase never reads "
            ".env itself."
        )
    return key_id, key_secret
