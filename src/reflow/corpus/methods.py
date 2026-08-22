"""Payment-method mix for the synthetic corpus.

Justification for the mix (documented here, not just asserted, since the
brief requires it): India's retail digital-payment volume is dominated by
UPI. NPCI's published transaction-volume data for FY2024-2025 consistently
shows UPI carrying roughly two-thirds of all digital retail payment
*volume* in India, with cards a distant second, netbanking a shrinking
third, and wallets continuing to lose share to UPI (most wallets are
themselves now UPI-interoperable). Cardless EMI and e-mandate (NACH-style
recurring debit) are real but low-volume compared to the four mainstream
methods -- e-mandate in particular is typically low-frequency (monthly
recurring) rather than high-frequency retail traffic.

This module encodes that as a fixed weight table over
:class:`reflow.taxonomy.methods.PaymentMethod`, used to sample which method
a synthetic failed payment used. The weights describe *failed-payment*
volume, not raw transaction volume; this repository has no independent
failure-rate-by-method data to justify skewing away from the overall
volume mix, so the overall volume mix is used directly as the best
available proxy.
"""

from __future__ import annotations

import random

from reflow.taxonomy.methods import PaymentMethod, UpiFlow

METHOD_MIX: dict[PaymentMethod, float] = {
    PaymentMethod.UPI: 0.64,
    PaymentMethod.CARD: 0.20,
    PaymentMethod.NETBANKING: 0.08,
    PaymentMethod.WALLET: 0.05,
    PaymentMethod.CARDLESS_EMI: 0.02,
    PaymentMethod.EMANDATE: 0.01,
}
"""Probability of a synthetic failed payment using each method. Sums to 1.0."""

UPI_FLOW_MIX: dict[UpiFlow, float] = {
    UpiFlow.INTENT: 0.95,
    UpiFlow.COLLECT: 0.05,
}
"""Probability split between UPI Intent and Collect for UPI-method events.

Weighted heavily toward Intent: live Razorpay UPI documentation (fetched
2026-08-22) states NPCI deprecated Collect for new integrations effective
2026-02-28, i.e. before this corpus's build date. A small non-zero share is
kept rather than dropping Collect to 0%, since pre-deprecation integrations
continue to generate Collect traffic for some time after a deprecation
date in practice.
"""

_METHOD_ORDER: tuple[PaymentMethod, ...] = tuple(METHOD_MIX)
_METHOD_WEIGHTS: tuple[float, ...] = tuple(METHOD_MIX.values())
_UPI_FLOW_ORDER: tuple[UpiFlow, ...] = tuple(UPI_FLOW_MIX)
_UPI_FLOW_WEIGHTS: tuple[float, ...] = tuple(UPI_FLOW_MIX.values())


def sample_method(rng: random.Random) -> PaymentMethod:
    """Draw one payment method according to :data:`METHOD_MIX`.

    Args:
        rng: Deterministic random source.

    Returns:
        A :class:`PaymentMethod` sampled with the configured weights.
    """
    return rng.choices(_METHOD_ORDER, weights=_METHOD_WEIGHTS, k=1)[0]


def sample_upi_flow(rng: random.Random) -> UpiFlow:
    """Draw a UPI sub-flow according to :data:`UPI_FLOW_MIX`.

    Args:
        rng: Deterministic random source.

    Returns:
        A :class:`UpiFlow` sampled with the configured weights.
    """
    return rng.choices(_UPI_FLOW_ORDER, weights=_UPI_FLOW_WEIGHTS, k=1)[0]
