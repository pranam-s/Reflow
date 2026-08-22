"""Correlated-failure downtime windows.

A real Razorpay outage does not show up as one reason code repeated many
times -- it shows up as a *mixture*. A bank's core banking system going
down for an hour plausibly produces some payments failing with
``bank_not_available``, others with ``bank_technical_error``, others
timing out entirely (``payment_timed_out``), and some surfacing as a
generic ``server_error`` on Razorpay's side, all inside the same window,
for the same underlying incident. ``GROUP BY reason`` cannot see that these
four different-looking failure streams are one incident; only
``downtime_window_id`` (recorded here as ground truth) can. This is
deliberate: it is exactly the second of the two things clustering is
supposed to do better than the trivial ``GROUP BY (code, source, step,
reason)`` baseline (see the Phase 1 corpus-design addendum).

Each window is scoped to one payment method and, for methods where it is
meaningful, one bank/issuer name, and spans a contiguous, randomly placed
time interval. While a window is active, event generation
(:mod:`reflow.corpus.events`) draws reasons from the window's
``reason_mixture`` at a much higher rate than the method's ordinary Zipf
distribution would produce, for events matching the window's method (and
bank, when the window specifies one).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from reflow.corpus.methods import METHOD_MIX
from reflow.corpus.tokens import random_bank_name, random_id, random_timestamp
from reflow.taxonomy.methods import PaymentMethod

_REASON_MIXTURES_BY_METHOD: Final[dict[PaymentMethod, tuple[str, ...]]] = {
    PaymentMethod.CARD: (
        "issuer_technical_error",
        "card_declined",
        "payment_timed_out",
        "gateway_technical_error",
    ),
    PaymentMethod.UPI: (
        "psp_not_available",
        "upi_app_technical_error",
        "payment_timed_out",
        "bank_technical_error",
    ),
    PaymentMethod.NETBANKING: (
        "bank_not_available",
        "bank_technical_error",
        "payment_timed_out",
        "server_error",
    ),
    PaymentMethod.EMANDATE: (
        "bank_not_available",
        "bank_technical_error",
        "payment_timed_out",
        "server_error",
    ),
    PaymentMethod.WALLET: (
        "issuer_technical_error",
        "payment_failed",
        "payment_timed_out",
    ),
    PaymentMethod.CARDLESS_EMI: (
        "gateway_technical_error",
        "payment_failed",
        "payment_timed_out",
    ),
}
"""Plausible concurrent reason-code mixture for an outage of each method.
Every mixture spans more than one reason code deliberately -- a
single-reason "mixture" would defeat the purpose described in the module
docstring."""

_METHODS_WITH_NAMED_BANK: Final[frozenset[PaymentMethod]] = frozenset(
    {
        PaymentMethod.CARD,
        PaymentMethod.UPI,
        PaymentMethod.NETBANKING,
        PaymentMethod.EMANDATE,
    }
)
"""Methods for which a downtime window is scoped to one named bank/issuer,
mirroring how Netbanking/Emandate/Card/UPI failures are usually attributed
to a specific issuing or beneficiary bank. Wallet and Cardless EMI windows
are scoped by method only, since their vendored reasons never name a bank."""

_MIN_DURATION: Final[timedelta] = timedelta(minutes=15)
_MAX_DURATION: Final[timedelta] = timedelta(hours=4)


@dataclass(frozen=True, slots=True)
class DowntimeWindow:
    """One synthetic outage incident.

    Attributes:
        window_id: Stable identifier, recorded as ground truth on every
            event generated within this window.
        method: The payment method affected.
        bank: The bank/issuer name affected, or ``None`` for methods where
            downtime is not scoped to a named bank (Wallet, Cardless EMI).
        start: Window start (inclusive).
        end: Window end (exclusive).
        reason_mixture: The 3-4 reason codes this incident produces
            concurrently.
    """

    window_id: str
    method: PaymentMethod
    bank: str | None
    start: datetime
    end: datetime
    reason_mixture: tuple[str, ...]

    def duration_seconds(self) -> float:
        """Window duration, in seconds.

        Returns:
            ``(end - start).total_seconds()``.
        """
        return (self.end - self.start).total_seconds()

    def contains(self, moment: datetime) -> bool:
        """Whether ``moment`` falls inside ``[start, end)``.

        Args:
            moment: The timestamp to test.

        Returns:
            ``True`` if ``start <= moment < end``.
        """
        return self.start <= moment < self.end


def generate_downtime_windows(
    rng: random.Random,
    n_windows: int,
    period_start: datetime,
    period_end: datetime,
) -> list[DowntimeWindow]:
    """Generate a deterministic set of non-overlapping-per-scope outage windows.

    Args:
        rng: Deterministic random source.
        n_windows: Number of windows to generate.
        period_start: Inclusive lower bound for window start times.
        period_end: Exclusive upper bound for window start times.

    Returns:
        A list of ``n_windows`` :class:`DowntimeWindow`, sorted by
        ``start``. Windows may overlap in time across different
        method/bank scopes (two unrelated outages can happen at once) but
        this function does not deliberately overlap windows within the
        same scope. Which method each window affects is drawn from
        :data:`reflow.corpus.methods.METHOD_MIX` rather than uniformly:
        outages should be more common, in absolute count, for high-volume
        methods like UPI than for low-volume ones like Emandate, mirroring
        why the overall corpus is UPI-dominant in the first place.
    """
    windows: list[DowntimeWindow] = []
    method_order = tuple(_REASON_MIXTURES_BY_METHOD)
    method_weights = [METHOD_MIX[method] for method in method_order]
    for _ in range(n_windows):
        method = rng.choices(method_order, weights=method_weights, k=1)[0]
        bank = random_bank_name(rng) if method in _METHODS_WITH_NAMED_BANK else None
        latest_start = period_end - _MIN_DURATION
        start = random_timestamp(rng, period_start, latest_start)
        max_duration_seconds = min(
            _MAX_DURATION.total_seconds(),
            (period_end - start).total_seconds(),
        )
        duration = timedelta(
            seconds=rng.uniform(_MIN_DURATION.total_seconds(), max_duration_seconds)
        )
        base_mixture = _REASON_MIXTURES_BY_METHOD[method]
        mixture_size = rng.randint(3, len(base_mixture))
        reason_mixture = tuple(rng.sample(base_mixture, k=mixture_size))
        windows.append(
            DowntimeWindow(
                window_id=random_id(rng, "dtw", length=10),
                method=method,
                bank=bank,
                start=start,
                end=start + duration,
                reason_mixture=reason_mixture,
            )
        )
    windows.sort(key=lambda window: window.start)
    return windows
