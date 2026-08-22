"""The opacity ablation: Phase 2's null-hypothesis control.

Razorpay's own vendored spreadsheet documents that it does not know the
sub-cause behind several of its own catch-all reason codes: ``card_declined``
("the exact reason in this case is not shared with Razorpay"),
``payment_declined`` ("not communicated to Razorpay"), and ``payment_failed``
("no specific error code received from gateway"). If Razorpay never
receives the sub-cause, a real ``error_description`` for one of these
reasons cannot contain text distinguishing one sub-cause from another --
the Phase 1 corpus generates such distinguishing text anyway (on the
explicit assumption that it exists), so a clustering result computed on it
as generated would measure recovery of detail that, in production, is
simply absent. See ``BUILD_LOG.md`` (2026-08-23 entry) for the full
reasoning.

:func:`opaque_description` implements the control: for a catch-all event,
it discards the latent-sub-cause-specific rendering entirely and re-renders
the event exactly as if its reason were narrow, via
:func:`reflow.corpus.descriptions.render_narrow_description` -- the same
function every genuinely narrow (single-cause) reason already uses. This
is a transformation applied by the evaluation harness to already-generated
events, never a change to how the corpus itself generates or stores
events, so the corpus's freeze-before-clustering guarantee is untouched.

Because the noise clause appended after the base sentence still carries the
event's real payment id, order id, amount, timestamp, and (for some
methods) bank/VPA, the raw opaque text is not byte-identical across events
sharing a reason -- but every one of those varying tokens is exactly what
:mod:`reflow.signature` masks out before any clusterer sees it. After
masking, two catch-all events sharing a ``(reason, method)`` pair produce
byte-identical text under this control, which is the operationally correct
statement of "sub-causes are textually indistinguishable": it is what a
clusterer actually observes, not merely what a human reading raw text
would see.
"""

from __future__ import annotations

import random

from reflow.corpus.descriptions import NoiseTokens, render_narrow_description
from reflow.corpus.events import PaymentEvent
from reflow.corpus.reasons import CATCH_ALL_REASONS
from reflow.taxonomy.reasons import ReasonRecord

_DUMMY_RRN: str = "000000000000"
"""Placeholder Retrieval Reference Number used when re-rendering a
catch-all event's opaque description. Its value is arbitrary because
:mod:`reflow.signature` masks any 12-digit run out regardless of value --
see module docstring."""


def opaque_description(event: PaymentEvent, reason_record: ReasonRecord) -> str:
    """Render an event's description as if its reason were narrow, not catch-all.

    Args:
        event: The generated event. Only its already-realized fields
            (``bank``, ``payment_id``, ``order_id``, ``amount``,
            ``created_at``, ``vpa``, ``card_bin``, ``method``,
            ``error_reason``) are used; no new randomness is drawn from
            it.
        reason_record: The vendored reason record for
            ``event.error_reason``, whose ``explanation`` text supplies the
            base sentence, identically to how every narrow reason is
            already rendered.

    Returns:
        ``event.description`` unchanged if ``event.error_reason`` is not a
        member of :data:`reflow.corpus.reasons.CATCH_ALL_REASONS`.
        Otherwise, a freshly rendered description built from
        ``reason_record.explanation``'s canonical first sentence plus the
        same per-method noise clause every narrow reason gets, discarding
        the original latent-sub-cause-specific text entirely.

    Note:
        Uses :class:`random.Random`, which ruff's ``S311`` rule flags as
        unsuitable for cryptographic use; suppressed below (``# noqa:
        S311``) because ``render_narrow_description`` only consults its
        ``rng`` argument to choose between the canonical and an alternate
        phrasing for the eight reasons listed in
        :data:`reflow.corpus.reasons.NARROW_REASON_ALT_PHRASINGS`, none of
        which is a catch-all reason -- so for every call this function
        actually makes, the ``rng`` argument is never read, and its seed
        is consequently immaterial to the result.
    """
    if event.error_reason not in CATCH_ALL_REASONS:
        return event.description

    noise = NoiseTokens(
        payment_id=event.payment_id,
        order_id=event.order_id,
        amount_paise=event.amount,
        created_at=event.created_at,
        bank=event.bank,
        vpa=event.vpa or "",
        card_bin=event.card_bin or "",
        rrn=_DUMMY_RRN,
    )
    text, _variant_label = render_narrow_description(
        event.error_reason,
        reason_record.explanation,
        event.method,
        noise,
        random.Random(0),  # noqa: S311
    )
    return text
