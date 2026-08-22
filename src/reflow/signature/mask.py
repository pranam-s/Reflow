"""Deterministic masking of variable tokens out of failure descriptions.

Every candidate in the Phase 2 clustering bake-off (:mod:`reflow.cluster`)
consumes the *same* masked text, produced by this module and nothing else.
That is the point: if masking quality varied between candidates, the
bake-off would measure masking, not clustering. :func:`mask_description` is
therefore a single, pure, regex-based pipeline with no learned component and
no randomness, so it is deterministic and independently testable in
isolation from every clusterer.

The corpus (:mod:`reflow.corpus`) renders exactly seven kinds of variable
token into ``description`` text (see
:class:`reflow.corpus.descriptions.NoiseTokens`): amounts, payment ids,
order ids, bank/institution names, UPI VPAs, card BINs, and Retrieval
Reference Numbers, plus ISO-8601 timestamps. This module masks all seven,
plus a customer id and a generic fallback for any other Razorpay-style
``prefix_alphanumeric`` id, on the basis that a masking layer built only to
the seven token kinds actually present in one synthetic corpus would be
overfit to that corpus rather than a genuinely reusable preprocessing step.

Each token kind is replaced by a single stable placeholder (``<AMOUNT>``,
``<PAYMENT_ID>``, ...), never by the literal value. Masking rules are
applied in a fixed order -- timestamps, then amounts, then ids, then VPAs,
then Retrieval Reference Numbers, then card BINs, then bank names -- chosen
so that a rule that has already fired never leaves behind digits or
substrings that a later, less specific rule could misinterpret (for
example, ids are masked before Retrieval Reference Numbers so that a
14-character alphanumeric id can never be mistaken for a bare 12-digit
Retrieval Reference Number).

The bank/institution gazetteer (:data:`KNOWN_INSTITUTIONS`) independently
lists the same major Indian banks :mod:`reflow.corpus.tokens` draws from to
render ``description`` text, rather than importing that module's constant.
This is deliberate, not an oversight: masking should not structurally
depend on the synthetic-data generator it is being evaluated against. A
real deployment would maintain its own gazetteer of known counterparty
names for exactly the same reason.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

TIMESTAMP_PLACEHOLDER: Final[str] = "<TIMESTAMP>"
AMOUNT_PLACEHOLDER: Final[str] = "<AMOUNT>"
PAYMENT_ID_PLACEHOLDER: Final[str] = "<PAYMENT_ID>"
ORDER_ID_PLACEHOLDER: Final[str] = "<ORDER_ID>"
CUSTOMER_ID_PLACEHOLDER: Final[str] = "<CUSTOMER_ID>"
GENERIC_ID_PLACEHOLDER: Final[str] = "<ID>"
VPA_PLACEHOLDER: Final[str] = "<VPA>"
CARD_BIN_PLACEHOLDER: Final[str] = "<CARD_BIN>"
RRN_PLACEHOLDER: Final[str] = "<RRN>"
BANK_PLACEHOLDER: Final[str] = "<BANK>"

ALL_PLACEHOLDERS: Final[tuple[str, ...]] = (
    TIMESTAMP_PLACEHOLDER,
    AMOUNT_PLACEHOLDER,
    PAYMENT_ID_PLACEHOLDER,
    ORDER_ID_PLACEHOLDER,
    CUSTOMER_ID_PLACEHOLDER,
    GENERIC_ID_PLACEHOLDER,
    VPA_PLACEHOLDER,
    CARD_BIN_PLACEHOLDER,
    RRN_PLACEHOLDER,
    BANK_PLACEHOLDER,
)
"""Every placeholder :func:`mask_description` can emit, in application order."""

KNOWN_INSTITUTIONS: Final[tuple[str, ...]] = (
    "State Bank of India",
    "HDFC Bank",
    "ICICI Bank",
    "Axis Bank",
    "Punjab National Bank",
    "Kotak Mahindra Bank",
    "Bank of Baroda",
    "Canara Bank",
    "Union Bank of India",
    "IDFC FIRST Bank",
    "Yes Bank",
    "IndusInd Bank",
)
"""Major Indian banks masked out of descriptions as institution names.

Independently authored against the same real-world set of major Indian
banks :mod:`reflow.corpus.tokens.INDIAN_BANKS` draws from, rather than
importing it -- see module docstring for why the duplication is
deliberate.
"""

_TIMESTAMP_RE: Final = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?\b")

_AMOUNT_RE: Final = re.compile(r"(?:Rs\.|INR|₹)\s?\d[\d,]*\.\d{2}", re.IGNORECASE)

_ID_PREFIX_PLACEHOLDERS: Final[dict[str, str]] = {
    "pay": PAYMENT_ID_PLACEHOLDER,
    "order": ORDER_ID_PLACEHOLDER,
    "cust": CUSTOMER_ID_PLACEHOLDER,
}
_PREFIXED_ID_RE: Final = re.compile(r"\b(pay|order|cust)_[A-Za-z0-9]{6,}\b")
_GENERIC_ID_RE: Final = re.compile(r"\b[a-z]{2,12}_[A-Za-z0-9]{6,}\b")

_VPA_RE: Final = re.compile(r"\b[A-Za-z][A-Za-z0-9._-]*@[A-Za-z][A-Za-z0-9]*\b")

_RRN_RE: Final = re.compile(r"\b\d{12}\b")

_CARD_BIN_RE: Final = re.compile(r"(\bBIN\s+)\d{6}\b")

_BANK_RE: Final = re.compile(
    r"\b(?:"
    + "|".join(re.escape(name) for name in sorted(KNOWN_INSTITUTIONS, key=len, reverse=True))
    + r")\b"
)


def _replace_prefixed_id(match: re.Match[str]) -> str:
    """Map one matched ``prefix_alphanumeric`` id to its specific placeholder.

    Args:
        match: A match of :data:`_PREFIXED_ID_RE`, whose first group is the
            id's Razorpay-style entity prefix (``pay``, ``order``, or
            ``cust``).

    Returns:
        The placeholder registered for that prefix in
        :data:`_ID_PREFIX_PLACEHOLDERS`.
    """
    return _ID_PREFIX_PLACEHOLDERS[match.group(1)]


def mask_description(text: str) -> str:
    """Replace every variable token in a failure description with a placeholder.

    Args:
        text: A raw (unmasked) failure description, such as
            :attr:`reflow.corpus.events.PaymentEvent.description`.

    Returns:
        ``text`` with every recognised amount, id, VPA, Retrieval Reference
        Number, card BIN, bank/institution name, and ISO-8601 timestamp
        replaced by its stable placeholder from :data:`ALL_PLACEHOLDERS`.
        Text containing none of these tokens is returned unchanged.
    """
    masked = _TIMESTAMP_RE.sub(TIMESTAMP_PLACEHOLDER, text)
    masked = _AMOUNT_RE.sub(AMOUNT_PLACEHOLDER, masked)
    masked = _PREFIXED_ID_RE.sub(_replace_prefixed_id, masked)
    masked = _GENERIC_ID_RE.sub(GENERIC_ID_PLACEHOLDER, masked)
    masked = _VPA_RE.sub(VPA_PLACEHOLDER, masked)
    masked = _RRN_RE.sub(RRN_PLACEHOLDER, masked)
    masked = _CARD_BIN_RE.sub(r"\1" + CARD_BIN_PLACEHOLDER, masked)
    return _BANK_RE.sub(BANK_PLACEHOLDER, masked)


def mask_descriptions(texts: Iterable[str]) -> list[str]:
    """Mask a batch of failure descriptions.

    Args:
        texts: Raw failure descriptions.

    Returns:
        One masked string per input, in the same order, each produced by
        :func:`mask_description`.
    """
    return [mask_description(text) for text in texts]
