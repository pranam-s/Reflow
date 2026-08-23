"""A retrying, transport-capturing wrapper around ``razorpay.Client``.

Two verified facts (``BUILD_LOG.md``, 2026-08-22, and this module's own
docstrings below, verified live 2026-08-23) shape this module directly:

**The SDK's own retry never covers an HTTP error status.**
``razorpay.Client.enable_retry`` is off by default and, when enabled, its
``request()`` loop (read directly from
``.venv/Lib/site-packages/razorpay/client.py``) only retries
``requests.exceptions.ConnectionError`` and ``requests.exceptions.Timeout``
-- every HTTP error status, 429 included, raises immediately via
``BadRequestError``/``GatewayError``/``ServerError`` on the very first
attempt, with no numeric rate limit published to tune a retry policy
against. :class:`RazorpayGateway` therefore never enables the SDK's own
retry and instead implements its own adaptive exponential-backoff-with
-jitter loop around every call, keyed off the *transport-captured* HTTP
status code (:mod:`reflow.execute.transport`) rather than the SDK's
exception type -- verified live, 2026-08-23: three rapid sequential test
-mode Payment Link calls tripped a real rate limit, and the SDK surfaced
it as a plain ``BadRequestError: Too many requests``, textually
indistinguishable from a genuine bad request without the captured status
code.

**A duplicate ``reference_id`` is a hard rejection, not a silent replay.**
Verified live, 2026-08-23: creating a second Payment Link with a
``reference_id`` that already exists raises ``BadRequestError`` with the
message ``"payment link with given reference_id: <id> already exists.
Please create a payment link with a different reference_id"`` --
Razorpay does not transparently return the original link the way a
Stripe-style idempotency key would. :meth:`RazorpayGateway.create_payment_link`
catches exactly this rejection and recovers the existing link via a second,
also verified-live call: ``GET /v1/payment_links?reference_id=<id>``
(``razorpay.Client.payment_link.all({"reference_id": ...})``), which
returns ``{"payment_links": [...]}`` -- a response shape confirmed by
direct inspection to differ from the generic ``{"count": ..., "items":
[...]}`` collection envelope most other Razorpay list endpoints use, so
this project does not assume it without having actually seen it.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Final, Protocol, runtime_checkable

import razorpay
from razorpay.errors import BadRequestError, GatewayError, ServerError
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from reflow.execute.errors import ApiCallFailedError
from reflow.execute.transport import ResponseCapture, build_capturing_session
from reflow.taxonomy.methods import PaymentMethod

RESTRICTABLE_METHODS: Final[frozenset[PaymentMethod]] = frozenset(
    {PaymentMethod.CARD, PaymentMethod.UPI, PaymentMethod.NETBANKING, PaymentMethod.WALLET}
)
"""The only four payment methods a Payment Link can show/hide, verified
live 2026-08-23 against
<https://razorpay.com/docs/api/payments/payment-links/customise-payment-methods/>
and already recorded in ``docs/design.md`` ADR-0005:
:attr:`~reflow.taxonomy.methods.PaymentMethod.CARDLESS_EMI` and
:attr:`~reflow.taxonomy.methods.PaymentMethod.EMANDATE` have no
``options.checkout.method`` toggle at all."""

_RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_SDK_ERRORS: Final[tuple[type[Exception], ...]] = (
    BadRequestError,
    GatewayError,
    ServerError,
    RequestsConnectionError,
    RequestsTimeout,
)
_DUPLICATE_REFERENCE_MARKERS: Final[tuple[str, str]] = ("reference_id", "already exists")


@dataclass(frozen=True, slots=True)
class GatewayCallResult:
    """One successful (possibly recovered) Razorpay API call's full detail.

    Attributes:
        response: The parsed JSON response body -- the created/fetched
            Payment Link entity for a create call, or ``{"success": true}``
            for a notify call.
        http_status: HTTP status code of the settling attempt.
        latency_ms: Wall-clock time of the settling attempt, in
            milliseconds.
        retry_count: Total retries attempted across every phase of this
            call (including, for a recovered duplicate, both the failed
            create attempts and the recovery lookup's own attempts).
        request_headers: The redacted request headers of the settling
            attempt.
        recovered_existing: ``True`` when this result was not a fresh
            creation but a recovery of an already-existing Payment Link
            after Razorpay rejected a duplicate ``reference_id`` (see
            module docstring).
    """

    response: dict[str, Any]
    http_status: int
    latency_ms: float
    retry_count: int
    request_headers: dict[str, str]
    recovered_existing: bool = False


@runtime_checkable
class PaymentLinkGateway(Protocol):
    """Structural interface for anything that can serve :meth:`create_payment_link`.

    :class:`~reflow.execute.executor.BoundedExecutor` depends on this
    Protocol rather than the concrete :class:`RazorpayGateway`, mirroring
    :class:`reflow.llm.client.JsonCompleter`'s own rationale: unit tests
    can supply a lightweight fake gateway with no network, no
    ``razorpay.Client``, and no credentials, while :class:`RazorpayGateway`
    itself satisfies this Protocol structurally, with no extra declaration
    needed.
    """

    def create_payment_link(self, data: dict[str, Any]) -> GatewayCallResult:
        """Create a Payment Link.

        Args:
            data: The Payment Link creation request body.

        Returns:
            The populated :class:`GatewayCallResult`.

        Raises:
            ApiCallFailedError: If creation ultimately failed.
        """
        ...


def _is_duplicate_reference_error(error: ApiCallFailedError) -> bool:
    """Detect the verified duplicate-``reference_id`` rejection shape.

    Args:
        error: An :class:`~reflow.execute.errors.ApiCallFailedError` raised
            by a Payment Link creation attempt.

    Returns:
        ``True`` if ``error``'s message names both a ``reference_id`` and
        the phrase ``"already exists"`` -- the exact shape verified live,
        2026-08-23 (see module docstring).
    """
    message = str(error).lower()
    return all(marker in message for marker in _DUPLICATE_REFERENCE_MARKERS)


@dataclass(slots=True)
class RazorpayGateway:
    """A retrying, transport-capturing wrapper around ``razorpay.Client``.

    Attributes:
        key_id: Razorpay API key id (e.g. from
            :func:`reflow.execute.config.load_credentials`).
        key_secret: Razorpay API key secret. Excluded from this
            dataclass's ``repr`` (``field(repr=False)``) so that
            constructing, logging, or an uncaught exception's traceback
            printing this object can never echo it -- a real risk found
            and fixed during this phase's own live verification, where an
            early traceback's default dataclass ``repr`` printed both
            credential fields in plain text before this field-level
            suppression was added.
        max_retries: Maximum number of retries after the first attempt
            (i.e. up to ``max_retries + 1`` total attempts) for a
            retryable failure.
        base_delay_seconds: Base delay for exponential backoff between
            retries.
        max_delay_seconds: Upper bound on any single backoff delay, before
            jitter is added.
    """

    key_id: str
    key_secret: str = field(repr=False)
    max_retries: int = 5
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 20.0
    _client: razorpay.Client = field(init=False, repr=False)
    _capture: ResponseCapture = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build the underlying SDK client on a capturing session."""
        session, capture = build_capturing_session()
        self._capture = capture
        self._client = razorpay.Client(session=session, auth=(self.key_id, self.key_secret))

    def _backoff_seconds(self, attempt: int) -> float:
        """Compute the jittered exponential-backoff delay for one attempt.

        Args:
            attempt: The 1-based attempt number that just failed.

        Returns:
            ``min(base * 2 ** (attempt - 1), max_delay)`` plus a uniform
            random jitter in ``[0, delay]``, so concurrent callers do not
            retry in lockstep against an already-rate-limited endpoint.
        """
        delay = min(self.base_delay_seconds * (2.0 ** (attempt - 1)), self.max_delay_seconds)
        return delay + random.uniform(0.0, delay)  # noqa: S311 -- jitter, not cryptographic use

    def _call_with_retry(self, operation: Callable[[], dict[str, Any]]) -> GatewayCallResult:
        """Run one SDK operation, retrying transient failures adaptively.

        Args:
            operation: A zero-argument callable performing exactly one SDK
                call and returning its parsed JSON response.

        Returns:
            The populated :class:`GatewayCallResult`.

        Raises:
            ApiCallFailedError: If the first attempt fails non-retryably,
                or every retry attempt is exhausted.
        """
        attempt = 0
        while True:
            attempt += 1
            self._capture.last_capture = None
            start = time.monotonic()
            try:
                response = operation()
            except _RETRYABLE_SDK_ERRORS as exc:
                capture = self._capture.last_capture
                status_code = capture.status_code if capture is not None else None
                network_failure = capture is None
                retryable = network_failure or status_code in _RETRYABLE_STATUS_CODES
                if not retryable or attempt > self.max_retries:
                    raise ApiCallFailedError(
                        str(exc),
                        status_code=status_code,
                        error_body=capture.json_body if capture is not None else None,
                        retry_count=attempt - 1,
                    ) from exc
                time.sleep(self._backoff_seconds(attempt))
                continue
            latency_ms = (time.monotonic() - start) * 1000
            capture = self._capture.last_capture
            return GatewayCallResult(
                response=response,
                http_status=capture.status_code if capture is not None else 0,
                latency_ms=latency_ms,
                retry_count=attempt - 1,
                request_headers=capture.request_headers if capture is not None else {},
            )

    def _recover_existing_by_reference_id(self, reference_id: str) -> GatewayCallResult:
        """Recover an already-created Payment Link by its ``reference_id``.

        Args:
            reference_id: The ``reference_id`` Razorpay reported as a
                duplicate.

        Returns:
            A :class:`GatewayCallResult` wrapping the existing link, with
            ``recovered_existing=True``.

        Raises:
            ApiCallFailedError: If the ``reference_id`` filter call itself
                fails, or returns zero matching links.
        """
        result = self._call_with_retry(
            lambda: self._client.payment_link.all({"reference_id": reference_id})
        )
        links = result.response.get("payment_links") or []
        if not links:
            raise ApiCallFailedError(
                f"reference_id {reference_id!r} was reported as a duplicate on creation, but "
                "no existing Payment Link could be recovered via the reference_id filter.",
                status_code=result.http_status,
                error_body=result.response,
                retry_count=result.retry_count,
            )
        return replace(result, response=links[0], recovered_existing=True)

    def create_payment_link(self, data: dict[str, Any]) -> GatewayCallResult:
        """Create a Payment Link, recovering transparently from a duplicate.

        Args:
            data: The Payment Link creation request body, including its
                deterministic ``reference_id``
                (:func:`reflow.execute.reference.derive_reference_id`).

        Returns:
            The populated :class:`GatewayCallResult`. Its
            ``recovered_existing`` flag is set when this call recovered a
            pre-existing link rather than creating a new one (see module
            docstring).

        Raises:
            ApiCallFailedError: If creation failed for any reason other
                than the verified duplicate-``reference_id`` rejection, or
                if that rejection's recovery lookup itself failed.
        """
        try:
            return self._call_with_retry(lambda: self._client.payment_link.create(data))
        except ApiCallFailedError as exc:
            if not _is_duplicate_reference_error(exc):
                raise
            recovered = self._recover_existing_by_reference_id(data["reference_id"])
            return replace(recovered, retry_count=recovered.retry_count + exc.retry_count)

    def fetch_payment_link(self, payment_link_id: str) -> GatewayCallResult:
        """Fetch a Payment Link by its Razorpay-assigned id.

        Args:
            payment_link_id: The Payment Link id to fetch.

        Returns:
            The populated :class:`GatewayCallResult`.

        Raises:
            ApiCallFailedError: If every retry attempt failed.
        """
        return self._call_with_retry(lambda: self._client.payment_link.fetch(payment_link_id))

    def notify_payment_link(self, payment_link_id: str, medium: str) -> GatewayCallResult:
        """Send or resend a Payment Link notification.

        Args:
            payment_link_id: The Payment Link id to notify about.
            medium: ``"sms"`` or ``"email"`` (Razorpay's own two supported
                values, verified live 2026-08-23 against
                <https://razorpay.com/docs/api/payments/payment-links/resend/>).

        Returns:
            The populated :class:`GatewayCallResult`, whose ``response`` is
            ``{"success": true}`` on success.

        Raises:
            ApiCallFailedError: If every retry attempt failed.
        """
        return self._call_with_retry(
            lambda: self._client.payment_link.notifyBy(payment_link_id, medium)
        )
