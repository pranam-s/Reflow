"""TF-IDF bag-of-words vectorisation plus density-based clustering.

Uses ``sklearn.cluster.HDBSCAN`` directly (available since scikit-learn
1.3, confirmed present as a first-class estimator in the installed 1.9.0
via ``help(sklearn.cluster.HDBSCAN)`` -- see :mod:`CLAUDE.md`'s requirement
to verify library APIs against the installed version rather than recall).
scikit-learn ships its own HDBSCAN implementation as of 1.3, so the
separate ``hdbscan`` PyPI package this phase's brief flags as something to
check for is not needed here.

This is the only one of the three real clusterers that can label a point
as noise (:data:`~reflow.cluster.base.NOISE_LABEL`) rather than forcing it
into some cluster -- the property the bake-off's noise-handling metric
exists to measure.

**Metric choice.** ``metric="cosine"`` is used deliberately rather than
the class default (``"euclidean"``): TF-IDF vectors are bag-of-words
counts, and cosine similarity (angle between vectors, ignoring magnitude)
is the standard choice for comparing them, since two descriptions built
from the same vocabulary in different proportions should be considered
similar regardless of length. The installed ``HDBSCAN``'s own docstring
(``metric`` parameter) states that any string accepted by
``sklearn.metrics.pairwise_distances`` is valid, which includes
``"cosine"``; its ``algorithm`` parameter's docstring further states that
whenever the fitted ``X`` is sparse, or the chosen ``metric`` is not valid
for a ``KDTree``/``BallTree`` (cosine is neither), it resolves to the
``"brute"`` algorithm automatically -- so this class neither needs to nor
should hardcode ``algorithm="brute"`` itself. Empirically confirmed
tractable directly on scikit-learn's own sparse TF-IDF output at the
catch-all-stratum sizes this bake-off actually clusters (low thousands of
events): no dimensionality reduction step was needed or added.

``copy=True`` is passed explicitly because the installed 1.9.0's docstring
states the default is changing from ``False`` to ``True`` in a future
1.10 release; pinning the value avoids both the emitted ``FutureWarning``
and a silent behaviour change on a future ``scikit-learn`` upgrade.

Neither ``min_cluster_size`` nor ``max_features`` is tuned against this
corpus's ground truth -- both are held at round, defensible defaults (see
:data:`DEFAULT_MIN_CLUSTER_SIZE`, :data:`DEFAULT_MAX_FEATURES`) for
exactly the reason :mod:`reflow.cluster.drain3_clusterer` gives for
leaving Drain3 at its library defaults.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sklearn.cluster import HDBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer

from reflow.cluster.base import NOISE_LABEL, ClusterInput

DEFAULT_MIN_CLUSTER_SIZE: Final[int] = 5
"""scikit-learn's own ``HDBSCAN`` default, kept rather than overridden."""

DEFAULT_MAX_FEATURES: Final[int] = 5000
"""A round cap on TF-IDF vocabulary size, generous relative to this
corpus's actual catch-all-stratum vocabulary (a few hundred distinct
words), kept only as a safeguard against unbounded memory use on a much
larger or noisier real corpus."""


class TfidfHdbscanClusterer:
    """TF-IDF vectorisation followed by density-based (HDBSCAN) clustering.

    Attributes:
        name: ``"tfidf_hdbscan"``.
    """

    name = "tfidf_hdbscan"

    def __init__(
        self,
        min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
        max_features: int = DEFAULT_MAX_FEATURES,
    ) -> None:
        """Configure the vectoriser and clusterer.

        Args:
            min_cluster_size: Minimum number of members for a group to be
                considered a cluster rather than noise. Forwarded to
                ``sklearn.cluster.HDBSCAN``.
            max_features: Maximum TF-IDF vocabulary size. Forwarded to
                ``sklearn.feature_extraction.text.TfidfVectorizer``.
        """
        self._min_cluster_size = min_cluster_size
        self._max_features = max_features

    def fit_predict(self, inputs: Sequence[ClusterInput]) -> list[int]:
        """Vectorise masked descriptions and cluster them with HDBSCAN.

        Args:
            inputs: The events to cluster.

        Returns:
            One label per input. :data:`~reflow.cluster.base.NOISE_LABEL`
            (``-1``) for inputs HDBSCAN considers noise; otherwise an
            arbitrary but stable non-negative cluster label. HDBSCAN's own
            rarer sentinel values ``-2`` (infinite feature values) and
            ``-3`` (missing data) -- neither of which TF-IDF output can
            actually produce -- are collapsed into ``-1`` as well, so this
            method's label space is exactly
            ``{NOISE_LABEL} | {0, 1, 2, ...}``. Inputs of length 0 or 1 are
            handled without invoking HDBSCAN (which requires at least
            ``min_cluster_size`` samples to find any cluster at all): an
            empty input yields an empty result, and a single input is
            assigned its own cluster (label ``0``) rather than being
            called noise, since a single observation carries no density
            evidence either way.
        """
        if len(inputs) == 0:
            return []
        if len(inputs) == 1:
            return [0]

        texts = [item.masked_description for item in inputs]
        vectorizer = TfidfVectorizer(max_features=self._max_features)
        matrix = vectorizer.fit_transform(texts)

        min_cluster_size = min(self._min_cluster_size, max(2, len(texts) // 2))
        model = HDBSCAN(min_cluster_size=min_cluster_size, metric="cosine", copy=True)
        labels = model.fit_predict(matrix)
        return [max(NOISE_LABEL, int(label)) for label in labels]
