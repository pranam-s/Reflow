"""Exception hierarchy for :mod:`reflow.execute`.

Mirrors :mod:`reflow.llm.errors`'s shape (a typed hierarchy a caller can
branch on, never a raw SDK or ``requests`` exception escaping uncaught),
adapted to this package's specific verified failure modes: a Razorpay API
call that exhausted its retry budget or hit a non-retryable error, and a
live-call budget guard that this project's own safety cap, not Razorpay's
API, enforces.
"""

from __future__ import annotations

from typing import Any


class ExecuteError(Exception):
    """Base class for every error raised by :mod:`reflow.execute`."""


class MissingCredentialsError(ExecuteError):
    """Raised when live execution is requested with no Razorpay credentials.

    Mirrors :class:`reflow.llm.errors.MissingApiKeyError`: credentials are
    read from ``os.environ`` only (``RAZORPAY_KEY_ID`` /
    ``RAZORPAY_KEY_SECRET``), never from ``.env`` directly, per
    ``CLAUDE.md``.
    """


class GatewayNotConfiguredError(ExecuteError):
    """Raised when live execution is requested but no gateway was supplied.

    Distinct from :class:`MissingCredentialsError`: this fires when a
    caller sets ``dry_run=False`` on a
    :class:`~reflow.execute.executor.BoundedExecutor` constructed with no
    :class:`~reflow.execute.gateway.RazorpayGateway` at all, which is a
    programming error in how the executor was assembled, not a missing
    environment variable.
    """


class ApiCallFailedError(ExecuteError):
    """Raised when a live Razorpay API call ultimately failed.

    Carries everything the installed SDK's own exception classes discard
    (see :mod:`reflow.execute.transport` module docstring): the real HTTP
    status code and the full JSON error body, captured at the transport
    layer rather than parsed by the SDK.

    Attributes:
        status_code: The last observed HTTP status code, or ``None`` if no
            response was ever received (e.g. a connection failure).
        error_body: The last observed full JSON error body, or ``None`` if
            unavailable or non-JSON.
        retry_count: How many retries were attempted before this error was
            raised (``0`` if the first attempt failed non-retryably).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        error_body: dict[str, Any] | None,
        retry_count: int,
    ) -> None:
        """Initialise the error with its captured transport-level detail.

        Args:
            message: A human-readable summary.
            status_code: The last observed HTTP status code, if any.
            error_body: The last observed full JSON error body, if any.
            retry_count: How many retries preceded this error.
        """
        super().__init__(message)
        self.status_code = status_code
        self.error_body = error_body
        self.retry_count = retry_count


class LiveCallBudgetExceededError(ExecuteError):
    """Raised when a run would exceed its configured live-call budget.

    This project's own safety net, independent of anything Razorpay
    enforces: :class:`~reflow.execute.executor.BoundedExecutor` accepts an
    optional ``live_call_budget`` and refuses to make a further live call
    once it is reached, so a batch run cannot accidentally spend far more
    real test-mode calls than intended.
    """
