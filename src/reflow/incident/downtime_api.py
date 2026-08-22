"""Typed models for Razorpay's Payment Downtime API and webhooks.

Verified 2026-08-23 directly against live Razorpay documentation and the
official SDK's source, per :mod:`CLAUDE.md`'s live-docs-over-recall rule,
rather than from training-data recall of a REST API shape:

- Entity fields and the sample response body: fetched live from
  <https://razorpay.com/docs/api/payments/downtime/entity> and
  <https://razorpay.com/docs/api/payments/downtime/fetch-all/>. The fetch-all
  endpoint's own documentation states it "does not accept pagination or
  filtering parameters" (no ``count``/``skip``/``from``/``to``) -- this
  module therefore models only the response shape, never a query-parameter
  type, since there is nothing to parametrise.
- Webhook payload shape (``payment.downtime.started`` / ``.updated`` /
  ``.resolved``): fetched live from
  <https://razorpay.com/docs/webhooks/payloads/payments/>. All three events
  share one entity shape; they differ only in ``status`` (matching the
  event name) and whether ``end`` is populated (``resolved`` populates it,
  the other two leave it ``null``).
- SDK method names: read directly from
  ``razorpay/resources/payment.py`` in the ``razorpay/razorpay-python``
  GitHub source (not installed as a dependency here -- see below):
  ``fetchDownTime()`` (``GET {base_url}/downtimes``) and
  ``fetchDownTimeById(downtime_id)`` (``GET {base_url}/downtimes/{id}``).

**This project declares no dependency on the ``razorpay`` package.** Per
``BUILD_LOG.md``'s 2026-08-22 entry, the official SDK's own exception and
response objects already discard fields this project needs elsewhere in
the taxonomy; :mod:`reflow.taxonomy.signal` responds by modelling the wire
JSON directly instead of trusting SDK objects, and this module follows the
same precedent for downtime data. Nothing here performs, or is tested
against, a live HTTP call: this phase's brief explicitly rules that out
("test mode returns nothing useful for this"), and there is accordingly no
HTTP client in this module to call in the first place -- only the wire
shape, modelled as Pydantic models exactly as
:class:`reflow.taxonomy.signal.FailureSignal` already models the payment
error wire shape.

**Method coverage is narrower than the rest of this project's taxonomy.**
:class:`DowntimeMethod` has exactly three members -- ``card``,
``netbanking``, ``upi`` -- because that is the complete, verified set
Razorpay's downtime documentation names ("Downtime communication covers
cards, netbanking and UPI"). It is deliberately not
:class:`reflow.taxonomy.methods.PaymentMethod` (six members): Wallet,
Cardless EMI, and Emandate incidents can never be corroborated by a
declared :class:`Downtime`, because Razorpay's own API has no way to
express one for those methods. :mod:`reflow.incident.correlate` and
:mod:`reflow.eval.incident` surface this as a real, structural finding
rather than silently widening the enum to make every entity correlatable.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DowntimeMethod(StrEnum):
    """Payment methods Razorpay's Downtime API can declare an outage for."""

    CARD = "card"
    NETBANKING = "netbanking"
    UPI = "upi"


class DowntimeStatus(StrEnum):
    """A :class:`Downtime`'s lifecycle state."""

    SCHEDULED = "scheduled"
    STARTED = "started"
    RESOLVED = "resolved"
    UPDATED = "updated"


class DowntimeSeverity(StrEnum):
    """A :class:`Downtime`'s documented impact level."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class UpiDowntimeFlow(StrEnum):
    """UPI-specific sub-flow a :class:`Downtime` affects, when ``method`` is UPI."""

    COLLECT = "collect"
    INTENT = "intent"
    IN_APP = "in_app"


class Downtime(BaseModel):
    """One Razorpay-declared payment downtime.

    Mirrors the entity returned by ``GET /v1/payments/downtimes`` and
    ``GET /v1/payments/downtimes/:id`` (the SDK's ``fetchDownTime()`` /
    ``fetchDownTimeById()``), and nested identically inside the
    ``payment.downtime.*`` webhook payloads (see
    :class:`DowntimeWebhookEvent`).

    Instances are immutable: a ``Downtime`` represents a fact already
    declared by Razorpay, not a value this project's code should mutate.

    Wire timestamps (``begin``, ``end``, ``created_at``, ``updated_at``)
    are Unix epoch seconds on the wire; Pydantic 2.13's ``datetime``
    coercion parses an ``int``/``float`` directly into a timezone-aware UTC
    ``datetime`` (verified directly against the installed pydantic 2.13.4
    behaviour, not assumed), so callers never handle raw epoch integers.

    Attributes:
        id: Unique identifier of this downtime occurrence.
        entity: Always ``"payment.downtime"``.
        method: The affected payment method.
        begin: When the downtime began.
        end: When the downtime ended, or ``None`` while it is still
            ongoing (``status`` is ``scheduled``, ``started``, or
            ``updated``).
        status: The downtime's current lifecycle state.
        scheduled: Whether this downtime was pre-announced (planned
            maintenance) rather than an unplanned outage.
        severity: Razorpay's documented impact level.
        instrument: Method-specific detail; documented as varying by
            method, with ``{"bank": "<code>"}`` the only shape Razorpay's
            own sample response shows (for Netbanking). Modelled generically
            rather than as a fixed schema, since no second method's shape
            is documented.
        instrument_schema: An array field observed in the webhook payload
            shape; Razorpay's documentation does not further specify its
            semantics beyond its presence, so it is modelled generically
            and flagged as unverified beyond structural presence, in the
            same spirit as :mod:`reflow.taxonomy.methods`'s treatment of
            the ``step`` vocabulary it could not independently verify.
        flow: The affected UPI sub-flow, populated only when ``method`` is
            :attr:`DowntimeMethod.UPI`.
        created_at: When Razorpay recorded this downtime.
        updated_at: When this downtime record was last updated.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    entity: Literal["payment.downtime"] = "payment.downtime"
    method: DowntimeMethod
    begin: datetime
    end: datetime | None = None
    status: DowntimeStatus
    scheduled: bool
    severity: DowntimeSeverity
    instrument: dict[str, str] = Field(default_factory=dict)
    instrument_schema: tuple[str, ...] | None = None
    flow: UpiDowntimeFlow | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def bank(self) -> str | None:
        """Convenience accessor for ``instrument["bank"]``.

        Returns:
            The instrument's ``bank`` value, or ``None`` if absent -- e.g.
            for a UPI or Card downtime whose ``instrument`` names something
            other than a bank code.
        """
        return self.instrument.get("bank")


class DowntimeEventType(StrEnum):
    """The three ``payment.downtime.*`` webhook event names."""

    STARTED = "payment.downtime.started"
    UPDATED = "payment.downtime.updated"
    RESOLVED = "payment.downtime.resolved"


class DowntimeEntityContainer(BaseModel):
    """The ``payload.payment.downtime`` object of a downtime webhook.

    Attributes:
        entity: The declared :class:`Downtime`.
    """

    model_config = ConfigDict(frozen=True)

    entity: Downtime


class DowntimeWebhookPayload(BaseModel):
    """The ``payload`` object of a downtime webhook.

    Attributes:
        payment_downtime: The nested downtime container, keyed on the wire
            by the literal string ``"payment.downtime"`` (not a valid
            Python identifier, hence the alias).
    """

    model_config = ConfigDict(frozen=True)

    payment_downtime: DowntimeEntityContainer = Field(alias="payment.downtime")


class DowntimeWebhookEvent(BaseModel):
    """A ``payment.downtime.started`` / ``.updated`` / ``.resolved`` webhook body.

    Attributes:
        entity: Always ``"event"``.
        account_id: The Razorpay account id the event was sent for.
        event: Which of the three downtime lifecycle events this is.
        contains: Always ``("payment.downtime",)`` on the wire; modelled
            as a general tuple of strings rather than a fixed-length
            literal, matching the general ``contains`` shape Razorpay uses
            across every webhook event type.
        payload: The nested downtime payload.
        created_at: When Razorpay sent this webhook.
    """

    model_config = ConfigDict(frozen=True)

    entity: Literal["event"] = "event"
    account_id: str
    event: DowntimeEventType
    contains: tuple[str, ...]
    payload: DowntimeWebhookPayload
    created_at: datetime

    @property
    def downtime(self) -> Downtime:
        """Convenience accessor for ``payload.payment.downtime.entity``.

        Returns:
            The declared :class:`Downtime` this webhook is about.
        """
        return self.payload.payment_downtime.entity
