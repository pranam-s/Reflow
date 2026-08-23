"""Deterministic idempotency key derivation for Payment Link creation.

Razorpay documents a generic ``Idempotency-Key`` header for exactly three
surfaces -- transfers, refunds, and payouts -- and Payment Link creation is
not among them (verified live and recorded in ``BUILD_LOG.md``,
2026-08-22). The substitute this project uses is Payment Links' own
``reference_id`` field: a caller-supplied string, unique per link, capped
at a documented 40 characters.

**Verified live, 2026-08-23: ``reference_id`` uniqueness is enforced as a
hard rejection, not a silent idempotent replay.** Creating a second
Payment Link with a ``reference_id`` that already exists does not return
the original link -- it raises ``razorpay.errors.BadRequestError`` with
the message ``"payment link with given reference_id: <id> already exists.
Please create a payment link with a different reference_id"``. This is a
materially different contract from, say, a Stripe-style idempotency key
(same request, same key, same response, transparently). It means a
deterministic ``reference_id`` alone is necessary but not sufficient for
idempotent recovery: the caller must also catch this specific rejection
and recover the existing link itself, which is exactly what
:meth:`reflow.execute.gateway.RazorpayGateway.create_payment_link` does
(see that module's docstring for the recovery path, also verified live).
"""

from __future__ import annotations

import hashlib
from typing import Final

REFERENCE_ID_MAX_LENGTH: Final[int] = 40
"""Razorpay's documented maximum ``reference_id`` length (verified live,
2026-08-23, against the Create Standard Payment Link API reference)."""

_PREFIX: Final[str] = "reflow_"
_DIGEST_HEX_LENGTH: Final[int] = REFERENCE_ID_MAX_LENGTH - len(_PREFIX)


def derive_reference_id(payment_id: str) -> str:
    """Derive a stable, collision-resistant Payment Link ``reference_id``.

    A pure function of ``payment_id`` alone: the same payment id always
    derives the same ``reference_id``, in this process or any other, which
    is exactly the property idempotent retry needs -- an execution attempt
    that is retried (by this process crashing and restarting, or by a
    caller re-running the same decision) reuses the same key rather than
    minting a fresh one, so Razorpay's own uniqueness rejection (see
    module docstring) is what turns a retried request into a detectable
    duplicate rather than a second, customer-confusing link.

    Args:
        payment_id: The original failed payment's Razorpay-style id
            (:attr:`reflow.corpus.events.PaymentEvent.payment_id`).

    Returns:
        A ``"reflow_"`` prefix followed by the first
        :data:`_DIGEST_HEX_LENGTH` hex characters of ``payment_id``'s
        SHA-256 digest -- always exactly :data:`REFERENCE_ID_MAX_LENGTH`
        characters, using only lowercase hex digits and underscores (no
        character-set restriction is documented for ``reference_id``, but
        this keeps the value unambiguous and safe to embed anywhere).
        Truncating to 33 hex characters retains 132 bits of digest
        entropy: the birthday-bound probability of two distinct
        ``payment_id`` values colliding stays negligible even at corpus
        sizes many orders of magnitude larger than this project's; this
        claim is backed empirically, not just asserted, by
        ``tests/execute/test_reference.py``, which hashes every
        ``payment_id`` in a full generated corpus and asserts zero
        collisions.
    """
    digest = hashlib.sha256(payment_id.encode("utf-8")).hexdigest()
    return f"{_PREFIX}{digest[:_DIGEST_HEX_LENGTH]}"
