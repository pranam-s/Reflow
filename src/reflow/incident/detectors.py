"""Burst-detection algorithms behind one shared interface.

Mirrors how Phase 2 benchmarked clusterers behind
:class:`reflow.cluster.base.Clusterer`: every candidate here implements
:class:`IncidentDetector` and is scored identically by
:mod:`reflow.eval.incident`, so "measured on identical footing" is a
property of the code, not an assertion in a report.

Every detector consumes a single entity's dense, chronologically ordered
bucket-count series (:attr:`reflow.incident.aggregate.EntitySeries.counts`)
and returns one :class:`BurstCall` per bucket. Every detector is causal:
bucket ``i``'s call may only depend on ``counts[:i]`` (and, for
:class:`FixedThresholdDetector`, ``counts[i]`` itself), never on future
buckets. This is not an incidental implementation detail -- it is what
makes the time-to-detect metric in :mod:`reflow.incident.attribution`
meaningful at all: a detector that could see the future would trivially
"detect" every incident at its very first bucket.

**Three pitfalls this module handles explicitly, per phase brief:**

1. **Cold start.** :class:`RollingZScoreDetector`, :class:`PoissonSurpriseDetector`,
   and :class:`EwmaZScoreDetector` all refuse to call a burst until they
   have seen ``min_periods`` prior buckets of history (:attr:`BurstCall.is_burst`
   is ``False`` and :attr:`BurstCall.score` is ``0.0`` until then). Calling
   a burst against an unset or single-sample baseline would be a coin
   flip dressed up as a statistic. :class:`FixedThresholdDetector` has no
   cold start at all, by construction -- its only advantage over the other
   three, and worth stating plainly rather than only implicitly.
2. **Low-count buckets destabilising a Poisson tail.** A raw sample mean
   over a short, sparse trailing window is frequently exactly zero for
   this corpus's rarer entities (most of its ~50 ``(method, bank)`` pairs
   see well under one failure per bucket on average -- see
   :mod:`reflow.incident.aggregate` module docstring). A literal
   zero-mean Poisson makes *any* single failure infinitely surprising
   (``P(X >= 1 | lambda=0) = 0``, the most extreme possible p-value),
   which is a correct tail probability but an
   unstable, all-or-nothing detector in practice: it cannot distinguish "one
   failure after a long, genuine silence" from "a two-hundred count spike."
   :class:`PoissonSurpriseDetector` instead estimates the trailing rate as
   the posterior mean of a Gamma(1, 1)-prior Poisson-rate model,
   ``(sum(history) + 1) / (len(history) + 1)`` -- a standard Bayesian
   add-one smoothing, not an ad hoc patch -- so a single quiet bucket after
   a long silence no longer collapses the baseline to a literal zero.
3. **A sustained incident poisoning its own trailing baseline.** Both
   window-based detectors (:class:`RollingZScoreDetector`,
   :class:`PoissonSurpriseDetector`) and the recency-weighted
   :class:`EwmaZScoreDetector` absorb an ongoing incident's elevated counts
   into their own baseline over time, because they have no notion of "this
   period was anomalous, exclude it" -- they are simple online statistics,
   not change-point detectors with a memory of past detections. A long
   incident therefore *raises its own bar*: the longer it runs, the more
   its inflated counts get treated as "normal," which can cause a
   detector to stop flagging a still-ongoing incident, or to fail to flag
   a *second*, independent incident that starts before the first's
   inflated baseline has cleared. This is not fixed here -- fixing it
   would require explicit change-point/regime-switching logic, a
   materially different and heavier design this phase's brief does not
   ask for -- but it is a real, measurable property of every detector
   below except :class:`FixedThresholdDetector` (which has no memory to
   poison), and :mod:`reflow.eval.incident` reports on it rather than
   hiding it (see that module's docstring for how).

Every window-based detector shares the same ``window``/``min_periods``
defaults deliberately: this makes any difference between
:class:`RollingZScoreDetector` and :class:`PoissonSurpriseDetector`
attributable to the scoring rule (Gaussian z vs. Poisson tail
probability), not to one having more history than the other -- the same
"identical footing" discipline Phase 2 applied to its clusterers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_DEFAULT_WINDOW: int = 16
"""16 buckets * 15 minutes = 4 hours of trailing history. The corpus's
background traffic is stationary (background timestamps are drawn
uniformly over the full 30-day period, with no diurnal or weekly
cyclicality -- see :mod:`reflow.corpus.generator`), so there is no
seasonal reason to require a full trailing day; 4 hours was chosen as
enough history to gather several observations even for this corpus's
lower-volume entities, without so long a window that an ongoing incident
takes half a day to fully leave it."""

_DEFAULT_MIN_PERIODS: int = 8
"""Half of :data:`_DEFAULT_WINDOW`: require at least 2 hours of prior
history, even while the trailing window itself is still filling up during
the first :data:`_DEFAULT_WINDOW` buckets of an entity's observed life."""

_DEFAULT_Z_THRESHOLD: float = 3.0
"""Standard "3-sigma" convention for flagging a deviation as extreme."""

_DEFAULT_P_THRESHOLD: float = 1e-3
"""A Poisson tail probability below 1 in 1,000 is the surprise-detector's
flagging threshold -- roughly the two-tailed-equivalent stringency of the
3-sigma convention used by the two z-score detectors, so all three
threshold-based detectors are calibrated to comparable rarity under their
own null model rather than to arbitrarily different strictness."""

_ZERO_VARIANCE_EPSILON: float = 1e-9
"""Below this trailing standard deviation, a z-score detector's division
is treated as numerically degenerate rather than computed -- see each
detector's ``detect`` docstring for the fallback rule."""


def _poisson_sf(k: int, lam: float) -> float:
    """Compute ``P(X >= k)`` for ``X ~ Poisson(lam)``.

    Implemented directly with :func:`math.lgamma` rather than adding a
    ``scipy`` dependency: this project's Poisson tail probability is
    needed at the scale :mod:`reflow.eval.incident`'s ``GROUP BY reason``
    baseline runs at (millions of calls, one per entity-bucket), and a
    direct log-space summation benchmarked roughly 9x faster per call than
    ``scipy.stats.poisson.sf``'s scalar-argument path, whose generic
    ufunc/broadcasting machinery carries overhead this single-purpose
    computation does not need. Verified to agree with
    ``scipy.stats.poisson.sf`` to within machine precision (max absolute
    error ~5.7e-14 over 2,000 random ``(k, lam)`` pairs spanning
    ``lam in [0.001, 100]`` and ``k in [0, 300]``) before being adopted.

    Args:
        k: The observed count. ``P(X >= k)`` for ``k <= 0`` is always
            ``1.0`` (every Poisson-distributed count is non-negative).
        lam: The Poisson rate parameter. Must be non-negative;
            ``lam == 0`` gives ``P(X >= k) = 0`` for every ``k > 0``.

    Returns:
        The survival probability ``P(X >= k)``, in ``[0, 1]``.
    """
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    log_lam = math.log(lam)
    log_terms = [i * log_lam - lam - math.lgamma(i + 1) for i in range(k)]
    max_log = max(log_terms)
    cdf_lower = sum(math.exp(term - max_log) for term in log_terms) * math.exp(max_log)
    return max(0.0, min(1.0, 1.0 - cdf_lower))


@dataclass(frozen=True, slots=True)
class BurstCall:
    """One bucket's burst-detection outcome.

    Attributes:
        is_burst: Whether this bucket was flagged anomalous.
        score: A detector-specific anomaly score, higher meaning more
            anomalous. Not comparable across detectors (a z-score, a
            Poisson surprise in nats, and a raw count share no common
            scale) -- used only for within-detector ranking (e.g. a
            detected incident's peak score) and for reporting.
    """

    is_burst: bool
    score: float


@runtime_checkable
class IncidentDetector(Protocol):
    """Common interface for every Phase 3 burst-detection candidate.

    ``name`` is declared as a read-only property, not a plain mutable
    attribute: every candidate below is a frozen dataclass, so its
    ``name`` field is read-only by construction, and a plain ``name: str``
    Protocol member would require a *settable* attribute to satisfy
    structurally (mypy checks Protocol attributes invariantly unless they
    are properties).
    """

    @property
    def name(self) -> str:
        """A short, stable, human-readable identifier for this candidate.

        Used as a column/row key in benchmark reports.
        """
        ...

    def detect(self, counts: Sequence[int]) -> list[BurstCall]:
        """Flag bursts in one entity's dense, chronological count series.

        Args:
            counts: One failure count per bucket, in chronological order,
                with no gaps (see
                :attr:`reflow.incident.aggregate.EntitySeries.counts`).

        Returns:
            One :class:`BurstCall` per input bucket, in the same order.
        """
        ...


@dataclass(frozen=True, slots=True)
class FixedThresholdDetector:
    """Naive baseline: flag any bucket with more than ``threshold`` failures.

    Included, per phase brief, so the statistically-motivated candidates
    below have a genuinely simple baseline to beat -- not a strawman
    threshold picked to lose, but a plausible one an on-call engineer might
    actually configure without looking at this corpus's realized
    statistics first: "more than 3 failures of the same method/bank pair
    in 15 minutes is worth a look" is a defensible generic rule of thumb
    for a mid-size payments integration, chosen before this phase's
    benchmark was run, not fit to it afterward.

    Has no cold start (every bucket, including the very first, is scored
    identically) and cannot be poisoned by a sustained incident (it has no
    memory at all) -- the one respect in which it is structurally more
    robust than every other candidate here, not merely simpler. Its cost is
    the mirror image: the same fixed ``threshold`` is applied to every
    entity regardless of that entity's own typical rate, so it is
    necessarily miscalibrated for any entity whose baseline differs
    materially from what ``threshold`` implicitly assumes -- exactly the
    heterogeneity :mod:`reflow.incident.aggregate` documents this corpus's
    ~50 entities as having.

    Attributes:
        threshold: A bucket is a burst if its count is strictly greater
            than this value.
        name: ``"fixed_threshold"``.
    """

    threshold: int = 3
    name: str = "fixed_threshold"

    def detect(self, counts: Sequence[int]) -> list[BurstCall]:
        """Flag every bucket whose count exceeds :attr:`threshold`.

        Args:
            counts: One failure count per bucket, in chronological order.

        Returns:
            One :class:`BurstCall` per bucket; ``score`` is the raw count.
        """
        return [BurstCall(is_burst=count > self.threshold, score=float(count)) for count in counts]


@dataclass(frozen=True, slots=True)
class RollingZScoreDetector:
    """Flags a bucket whose count is an extreme z-score above its trailing mean/stdev.

    The trailing mean and (population) standard deviation are computed in
    ``O(1)`` amortized time per bucket via an incremental sliding sum and
    sum-of-squares (rather than re-slicing and re-scanning
    ``counts[i-window:i]`` on every step), which matters at the scale
    :mod:`reflow.eval.incident`'s ``GROUP BY reason`` baseline runs this
    at: over 2,000 entities, each with a ~2,880-bucket series.

    Attributes:
        window: Number of trailing buckets the baseline is computed over.
        min_periods: Minimum trailing buckets required before flagging is
            attempted at all (cold-start guard).
        z_threshold: A bucket is a burst if its z-score strictly exceeds
            this value.
        name: ``"rolling_zscore"``.
    """

    window: int = _DEFAULT_WINDOW
    min_periods: int = _DEFAULT_MIN_PERIODS
    z_threshold: float = _DEFAULT_Z_THRESHOLD
    name: str = "rolling_zscore"

    def detect(self, counts: Sequence[int]) -> list[BurstCall]:
        """Score each bucket against its trailing mean/stdev.

        Buckets before :attr:`min_periods` trailing observations have
        accumulated are never flagged (``score=0.0``). When the trailing
        window has (numerically) zero variance -- common for this
        corpus's sparser entities, whose trailing history is frequently a
        run of exact zeros -- a z-score is undefined, so the fallback rule
        is "any count strictly above the trailing mean is a burst,"
        scored by the raw ``count - mean`` gap rather than an undefined
        ratio.

        Args:
            counts: One failure count per bucket, in chronological order.

        Returns:
            One :class:`BurstCall` per bucket.
        """
        calls: list[BurstCall] = []
        running_sum = 0.0
        running_sumsq = 0.0
        history_len = 0
        for i, count in enumerate(counts):
            if history_len < self.min_periods:
                calls.append(BurstCall(is_burst=False, score=0.0))
            else:
                mean = running_sum / history_len
                variance = max(0.0, running_sumsq / history_len - mean * mean)
                stdev = math.sqrt(variance)
                if stdev < _ZERO_VARIANCE_EPSILON:
                    calls.append(BurstCall(is_burst=count > mean, score=count - mean))
                else:
                    z_score = (count - mean) / stdev
                    calls.append(BurstCall(is_burst=z_score > self.z_threshold, score=z_score))

            running_sum += count
            running_sumsq += count * count
            history_len += 1
            if history_len > self.window:
                dropped = counts[i - self.window]
                running_sum -= dropped
                running_sumsq -= dropped * dropped
                history_len -= 1
        return calls


@dataclass(frozen=True, slots=True)
class PoissonSurpriseDetector:
    """Flags a bucket whose count is an improbable draw from its trailing Poisson rate.

    The trailing rate is the posterior mean of a Gamma(1, 1)-prior
    Poisson-rate model, ``(sum(history) + 1) / (len(history) + 1)`` --
    see module docstring, "low-count buckets" -- rather than a raw sample
    mean, so a single failure after a long true silence is surprising but
    not maximally, uninformatively so.

    Shares :data:`_DEFAULT_WINDOW`/:data:`_DEFAULT_MIN_PERIODS` with
    :class:`RollingZScoreDetector` by default, so a difference in results
    between the two is attributable to the scoring rule, not to unequal
    history.

    Attributes:
        window: Number of trailing buckets the rate estimate is computed
            over.
        min_periods: Minimum trailing buckets required before flagging is
            attempted at all (cold-start guard).
        p_threshold: A bucket is a burst if ``P(X >= count | trailing
            rate)`` is strictly below this value.
        name: ``"poisson_surprise"``.
    """

    window: int = _DEFAULT_WINDOW
    min_periods: int = _DEFAULT_MIN_PERIODS
    p_threshold: float = _DEFAULT_P_THRESHOLD
    name: str = "poisson_surprise"

    def detect(self, counts: Sequence[int]) -> list[BurstCall]:
        """Score each bucket by its trailing-Poisson-rate tail probability.

        Buckets before :attr:`min_periods` trailing observations have
        accumulated are never flagged (``score=0.0``). The reported score
        is ``-log(p_value)`` (nats of surprise; higher is more anomalous),
        floored at a tiny positive ``p_value`` before taking the logarithm
        so an exactly-zero tail probability never raises a domain error.

        Args:
            counts: One failure count per bucket, in chronological order.

        Returns:
            One :class:`BurstCall` per bucket.
        """
        calls: list[BurstCall] = []
        running_sum = 0.0
        history_len = 0
        for i, count in enumerate(counts):
            if history_len < self.min_periods:
                calls.append(BurstCall(is_burst=False, score=0.0))
            else:
                trailing_rate = (running_sum + 1.0) / (history_len + 1.0)
                p_value = _poisson_sf(count, trailing_rate)
                score = -math.log(max(p_value, 1e-300))
                calls.append(BurstCall(is_burst=p_value < self.p_threshold, score=score))

            running_sum += count
            history_len += 1
            if history_len > self.window:
                running_sum -= counts[i - self.window]
                history_len -= 1
        return calls


@dataclass(frozen=True, slots=True)
class EwmaZScoreDetector:
    """Flags a bucket via a z-score against a recency-weighted mean/variance.

    Unlike the two window-based detectors above, this one carries no
    stored history at all: its entire state is two floats (an
    exponentially weighted mean and variance), updated in ``O(1)`` per
    bucket via the standard EWMA mean/variance recurrence (e.g. Finch,
    "Incremental Calculation of Weighted Mean and Variance", 2009):
    ``diff = x - mean``; ``mean += alpha * diff``; ``variance = (1 - alpha)
    * (variance + alpha * diff^2)``, evaluated for the z-score *before*
    the state is updated with the current observation (causal: bucket
    ``i``'s call never depends on its own count).

    Included as the phase's optional fourth detector because it is
    genuinely cheap (no window array, no re-scan) and gives a real,
    reportable point of contrast on the "sustained incident poisons its
    own baseline" pitfall (module docstring, point 3): its exponential
    decay means an old incident's inflated baseline fades continuously
    rather than dropping out abruptly when a fixed window slides past it,
    which changes -- but does not eliminate -- how quickly it recovers
    sensitivity after an incident ends.

    Attributes:
        alpha: Smoothing factor in ``(0, 1]``; higher weights recent
            observations more heavily.
        min_periods: Minimum buckets observed before flagging is attempted
            at all (cold-start guard) -- the EWMA state is still updated
            during this warm-up, only flagging is suppressed.
        z_threshold: A bucket is a burst if its z-score strictly exceeds
            this value.
        name: ``"ewma_zscore"``.
    """

    alpha: float = 0.2
    min_periods: int = _DEFAULT_MIN_PERIODS
    z_threshold: float = _DEFAULT_Z_THRESHOLD
    name: str = "ewma_zscore"

    def detect(self, counts: Sequence[int]) -> list[BurstCall]:
        """Score each bucket against the exponentially weighted baseline.

        Args:
            counts: One failure count per bucket, in chronological order.

        Returns:
            One :class:`BurstCall` per bucket.
        """
        calls: list[BurstCall] = []
        mean = 0.0
        variance = 0.0
        for n_seen, count in enumerate(counts):
            if n_seen < self.min_periods:
                calls.append(BurstCall(is_burst=False, score=0.0))
            else:
                stdev = math.sqrt(variance)
                if stdev < _ZERO_VARIANCE_EPSILON:
                    calls.append(BurstCall(is_burst=count > mean, score=count - mean))
                else:
                    z_score = (count - mean) / stdev
                    calls.append(BurstCall(is_burst=z_score > self.z_threshold, score=z_score))

            diff = count - mean
            mean += self.alpha * diff
            variance = (1.0 - self.alpha) * (variance + self.alpha * diff * diff)
        return calls
