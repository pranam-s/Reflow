"""Transport-level capture of Razorpay HTTP responses.

The installed ``razorpay`` SDK (2.0.1, read directly from
``.venv/Lib/site-packages/razorpay/client.py`` and
``.venv/Lib/site-packages/razorpay/errors.py`` rather than trusting the
README, per ``CLAUDE.md``) parses a failed response's JSON body just far
enough to pick ``error.description`` and ``error.code`` off it, then
raises one of :class:`razorpay.errors.BadRequestError`,
:class:`razorpay.errors.GatewayError`, or
:class:`razorpay.errors.ServerError` -- every one of those exception
classes stores nothing but that message string (``__init__(self,
message=None, *args, **kwargs): super().__init__(message)``). Two things
this project needs are discarded in that process: the HTTP status code
itself (never attached to the exception, and needed to tell a retryable
429/5xx apart from a terminal 4xx, since the SDK's own JSON-``code``
-based classification maps *both* a genuine bad request and a rate limit
to the identical ``BadRequestError`` -- confirmed live, 2026-08-23: three
rapid sequential Payment Link calls against Razorpay's own test-mode API
tripped ``BadRequestError: Too many requests``, indistinguishable by
exception type alone from any other bad request), and any of
``error.field`` / ``error.source`` / ``error.step`` / ``error.reason`` /
``error.metadata`` the response body might carry.

:func:`build_capturing_session` attaches a ``requests`` response hook
(``Session.hooks["response"]``, the library's own documented extension
point -- deliberately not a ``Session`` subclass overriding ``request()``,
since that method's installed type stub is annotated with a long list of
specific keyword parameters that a permissive ``**kwargs`` override would
violate under ``mypy --strict``) that records the most recently completed
response's status code, parsed JSON body, and redacted request headers.
Passed to ``razorpay.Client(session=...)``, which the installed SDK's own
constructor accepts and stores verbatim
(``self.session = session or requests.Session()``), this makes the full
transport-level detail available to :mod:`reflow.execute.gateway`
immediately after any SDK call, success or failure, without modifying the
SDK itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from requests.structures import CaseInsensitiveDict

_REDACTED: str = "[REDACTED]"
_SENSITIVE_HEADER_NAMES: frozenset[str] = frozenset({"authorization"})


@dataclass(frozen=True, slots=True)
class TransportCapture:
    """One HTTP request/response pair's transport-level detail.

    Attributes:
        status_code: The HTTP status code Razorpay actually returned.
        json_body: The parsed response JSON body, or ``None`` if the body
            was empty or not valid JSON (e.g. a ``204 No Content``
            response).
        request_headers: The request's headers, with every header named in
            :data:`_SENSITIVE_HEADER_NAMES` replaced by a fixed redaction
            marker regardless of its original casing -- this is the
            "credentials redacted" request shape the audit trail records.
    """

    status_code: int
    json_body: dict[str, Any] | None
    request_headers: dict[str, str]


def _redact_headers(headers: CaseInsensitiveDict[str | bytes]) -> dict[str, str]:
    """Redact sensitive header values before they are ever stored.

    Args:
        headers: A ``requests`` case-insensitive headers mapping (a
            prepared request's headers may be ``str`` or ``bytes``).

    Returns:
        A plain ``dict`` with every header whose lowercase name is in
        :data:`_SENSITIVE_HEADER_NAMES` replaced by ``"[REDACTED]"``.
    """
    return {
        str(key): (_REDACTED if str(key).lower() in _SENSITIVE_HEADER_NAMES else str(value))
        for key, value in headers.items()
    }


def _parse_json_body(response: requests.Response) -> dict[str, Any] | None:
    """Best-effort parse of a response body as a JSON object.

    Args:
        response: The completed HTTP response.

    Returns:
        The parsed JSON object, or ``None`` if the body is empty, not
        valid JSON, or a JSON value that is not an object (e.g. a bare
        list or scalar).
    """
    if not response.content:
        return None
    try:
        parsed = response.json()
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


class ResponseCapture:
    """A ``requests`` response hook that remembers its most recent call.

    Registered onto a plain ``requests.Session`` via
    :func:`build_capturing_session` rather than implemented as a
    ``Session`` subclass -- see module docstring for why a subclass
    overriding ``request()`` is the wrong shape here.

    Attributes:
        last_capture: The :class:`TransportCapture` for the most recently
            completed response this hook has observed, or ``None`` before
            any request has been made.
    """

    def __init__(self) -> None:
        """Initialise the hook with no prior capture."""
        self.last_capture: TransportCapture | None = None

    def __call__(self, response: requests.Response, **_kwargs: object) -> None:
        """Record one completed response's transport-level detail.

        Args:
            response: The completed HTTP response, supplied by
                ``requests``' own hook dispatch
                (``requests.hooks.dispatch_hook``, read directly from
                ``.venv`` to confirm the call shape: ``hook(response,
                **kwargs)`` where ``kwargs`` carries the send-time
                ``stream``/``verify``/``cert``/``proxies`` values, hence
                this method accepting and ignoring ``**_kwargs``).
            **_kwargs: Ignored; see above.
        """
        self.last_capture = TransportCapture(
            status_code=response.status_code,
            json_body=_parse_json_body(response),
            request_headers=_redact_headers(response.request.headers),
        )


def build_capturing_session() -> tuple[requests.Session, ResponseCapture]:
    """Build a plain ``requests.Session`` with transport capture attached.

    Returns:
        A tuple of ``(session, capture)``: ``session`` is a real, unmodified
        ``requests.Session`` suitable for ``razorpay.Client(session=...)``,
        and ``capture.last_capture`` reflects the most recent response
        that session has completed.
    """
    session = requests.Session()
    capture = ResponseCapture()
    session.hooks["response"].append(capture)
    return session, capture
