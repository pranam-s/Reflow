"""The shared clustering interface every Phase 2 bake-off candidate implements.

The bake-off (:mod:`reflow.eval.clustering`) compares three genuine
clusterers -- Drain3 (:mod:`reflow.cluster.drain3_clusterer`), normalised
template hashing (:mod:`reflow.cluster.template_hash`), and TF-IDF +
HDBSCAN (:mod:`reflow.cluster.tfidf_hdbscan`) -- against the trivial
``GROUP BY (code, source, step, reason)`` baseline
(:mod:`reflow.cluster.groupby_reason`), which is not a clusterer at all.
Putting all four behind one :class:`Clusterer` protocol is what lets the
harness call every candidate through exactly one code path and compute
every metric the same way, so "measured on identical footing" is a
property of the code, not an assertion in a report.

:class:`ClusterInput` is why the protocol can host all four: the three real
clusterers only ever look at ``masked_description``, while
:class:`~reflow.cluster.groupby_reason.GroupByReasonClusterer` only ever
looks at ``code``/``source``/``step``/``reason`` and ignores the text
entirely. Carrying both on every input, rather than giving the baseline a
different call signature, is what keeps the harness's call site singular.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep

NOISE_LABEL: Final[int] = -1
"""The predicted-label value reserved for "this point is noise, not a
member of any cluster" -- the ``sklearn``/HDBSCAN convention. Only
:class:`~reflow.cluster.tfidf_hdbscan.TfidfHdbscanClusterer` ever emits it;
every other candidate's label space is disjoint from it by construction."""


@dataclass(frozen=True, slots=True)
class ClusterInput:
    """One event's worth of input to a clustering candidate.

    Attributes:
        masked_description: The event's ``description``, after
            :func:`reflow.signature.mask.mask_description`. Consumed by
            every candidate except
            :class:`~reflow.cluster.groupby_reason.GroupByReasonClusterer`.
        code: The event's top-level error classification.
        source: The event's error source attribution.
        step: The event's payment lifecycle step.
        reason: The event's vendored reason code. Consumed only by
            :class:`~reflow.cluster.groupby_reason.GroupByReasonClusterer`.
    """

    masked_description: str
    code: ErrorCode
    source: ErrorSource
    step: ErrorStep
    reason: str


@runtime_checkable
class Clusterer(Protocol):
    """Common interface for every Phase 2 bake-off candidate.

    Attributes:
        name: A short, stable, human-readable identifier for this
            candidate, used as a column/row key in bake-off reports.
    """

    name: str

    def fit_predict(self, inputs: Sequence[ClusterInput]) -> list[int]:
        """Cluster a batch of inputs in one pass.

        Args:
            inputs: The events to cluster, in a fixed order.

        Returns:
            One integer cluster label per input, in the same order.
            :data:`NOISE_LABEL` denotes "not assigned to any cluster" for
            candidates that can express that; every other value is an
            arbitrary but stable label shared by every input assigned to
            the same cluster.
        """
        ...
