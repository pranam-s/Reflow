"""Deterministic noise-token generators for synthetic failure descriptions.

Real Razorpay error descriptions are not static strings: the same
``reason`` produces differently worded, variable-laden text depending on
the amount, the counterparties, and the moment the failure happened. Phase
2 masks exactly this kind of variable text out before clustering, so if the
Phase 1 corpus's descriptions never varied, the masking step would have
nothing to do and any later clustering result would be meaningless. This
module is the source of that variance: every function here takes a
:class:`random.Random` explicitly (never the global ``random`` module) so
that the whole corpus generator stays deterministic given a seed.
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timedelta

_ID_ALPHABET = string.ascii_letters + string.digits

INDIAN_BANKS: tuple[str, ...] = (
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
"""Major Indian banks, used to interpolate realistic bank names into
descriptions and to scope downtime windows. Not exhaustive by design -- a
handful of large banks account for most real transaction volume, and the
corpus should reflect that concentration rather than spreading evenly
across every bank licensed in India."""

VPA_HANDLES: tuple[str, ...] = (
    "@okhdfcbank",
    "@oksbi",
    "@okicici",
    "@okaxis",
    "@ybl",
    "@paytm",
    "@axl",
    "@ibl",
    "@upi",
)
"""UPI PSP handles seen in real VPAs (``name@handle``)."""

_CARD_BIN_PREFIXES_BY_NETWORK: dict[str, tuple[str, ...]] = {
    "visa": ("4",),
    "mastercard": ("51", "52", "53", "54", "55"),
    "rupay": ("60", "65", "81", "82"),
    "amex": ("34", "37"),
}

_FIRST_NAME_FRAGMENTS: tuple[str, ...] = (
    "arav",
    "vihaan",
    "aditi",
    "diya",
    "kabir",
    "meera",
    "rohan",
    "saanvi",
    "farhan",
    "priya",
)


def random_id(rng: random.Random, prefix: str, length: int = 14) -> str:
    """Generate a Razorpay-style entity id.

    Args:
        rng: Deterministic random source.
        prefix: Entity prefix, e.g. ``"pay"`` or ``"order"``.
        length: Number of alphanumeric characters after the underscore.
            Razorpay ids observed in the wild use 14.

    Returns:
        A string of the form ``f"{prefix}_{14 random alphanumerics}"``.
    """
    suffix = "".join(rng.choices(_ID_ALPHABET, k=length))
    return f"{prefix}_{suffix}"


def random_vpa(rng: random.Random) -> str:
    """Generate a synthetic UPI VPA (``name@handle``).

    Args:
        rng: Deterministic random source.

    Returns:
        A lowercase VPA such as ``"arav.42@okhdfcbank"``.
    """
    name = rng.choice(_FIRST_NAME_FRAGMENTS)
    suffix = rng.randint(1, 999)
    handle = rng.choice(VPA_HANDLES)
    return f"{name}.{suffix}{handle}"


def random_card_bin(rng: random.Random) -> str:
    """Generate a plausible 6-digit card BIN.

    Args:
        rng: Deterministic random source.

    Returns:
        A 6-character digit string starting with a real network prefix
        (Visa, Mastercard, RuPay, or Amex).
    """
    network = rng.choice(list(_CARD_BIN_PREFIXES_BY_NETWORK))
    prefix = rng.choice(_CARD_BIN_PREFIXES_BY_NETWORK[network])
    remaining = 6 - len(prefix)
    digits = "".join(rng.choices(string.digits, k=remaining))
    return f"{prefix}{digits}"


def random_bank_name(rng: random.Random) -> str:
    """Choose a random Indian bank name.

    Args:
        rng: Deterministic random source.

    Returns:
        One of :data:`INDIAN_BANKS`.
    """
    return rng.choice(INDIAN_BANKS)


def random_rrn(rng: random.Random) -> str:
    """Generate a plausible 12-digit Retrieval Reference Number.

    Args:
        rng: Deterministic random source.

    Returns:
        A 12-character digit string.
    """
    return "".join(rng.choices(string.digits, k=12))


def random_amount_paise(rng: random.Random) -> int:
    """Generate a realistic transaction amount, in paise.

    Args:
        rng: Deterministic random source.

    Returns:
        An integer number of paise between 100 (INR 1) and 1,000,000
        (INR 10,000). 55% of draws land on a common "sticker" rupee price
        point (e.g. 99, 499, 999) rather than an arbitrary amount, since
        real e-commerce/subscription pricing clusters heavily on such
        values; the remainder are uniform-log amounts to keep the tail
        realistic.
    """
    common_price_points = (49, 99, 199, 299, 499, 599, 999, 1499, 1999, 2999, 4999, 9999)
    if rng.random() < 0.55:
        rupees = rng.choice(common_price_points)
    else:
        rupees = round(rng.uniform(1, 10_000))
    return max(1, rupees) * 100


def random_timestamp(rng: random.Random, start: datetime, end: datetime) -> datetime:
    """Generate a uniformly random timestamp within ``[start, end)``.

    Args:
        rng: Deterministic random source.
        start: Inclusive lower bound.
        end: Exclusive upper bound. Must be after ``start``.

    Returns:
        A timezone-naive :class:`datetime` uniformly distributed in the
        given range.

    Raises:
        ValueError: If ``end`` is not after ``start``.
    """
    span_seconds = (end - start).total_seconds()
    if span_seconds <= 0:
        raise ValueError("end must be after start.")
    offset = rng.uniform(0, span_seconds)
    return start + timedelta(seconds=offset)


def random_customer_id(rng: random.Random) -> str:
    """Generate a synthetic customer id.

    Args:
        rng: Deterministic random source.

    Returns:
        A string of the form ``"cust_<14 alphanumerics>"``, matching
        Razorpay's customer id shape. Purely synthetic: no real names,
        emails, or other PII are embedded.
    """
    return random_id(rng, "cust")
