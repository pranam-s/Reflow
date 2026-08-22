"""Normalised template hashing: exact match, no tolerance.

The second bake-off candidate is deliberately the simplest possible real
clusterer: normalise a masked description's incidental whitespace and
casing, hash the result, and group every input whose hash is identical.
Two masked descriptions that differ by even one character -- a different
paraphrase, a reordered clause, a different register -- land in different
clusters. This is the sharpest possible contrast to
:mod:`reflow.cluster.drain3_clusterer` (which tolerates some
token-for-token divergence via a similarity threshold) and to
:mod:`reflow.cluster.tfidf_hdbscan` (which tolerates a great deal of
divergence via bag-of-words similarity), and is expected to fragment hard
on paraphrase/reorder/register variants of the same underlying cause --
exactly the property :mod:`reflow.corpus.reasons` was built to exercise.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Final

from reflow.cluster.base import ClusterInput

_WHITESPACE_RE: Final = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Canonicalise incidental formatting before hashing.

    Args:
        text: A masked description.

    Returns:
        ``text`` with leading/trailing whitespace stripped, every run of
        internal whitespace collapsed to a single space, and case folded.
        This is canonicalisation, not fuzzy matching: two descriptions
        that normalise to the same string are treated as identical; any
        other difference, however small, is not.
    """
    return _WHITESPACE_RE.sub(" ", text.strip()).casefold()


class TemplateHashClusterer:
    """Groups inputs whose normalised masked description hashes identically.

    Attributes:
        name: ``"template_hash"``.
    """

    name = "template_hash"

    def fit_predict(self, inputs: Sequence[ClusterInput]) -> list[int]:
        """Hash-group inputs by their normalised masked description.

        Args:
            inputs: The events to cluster.

        Returns:
            One label per input, assigned in first-seen order of each
            distinct normalised-text hash. Never emits
            :data:`~reflow.cluster.base.NOISE_LABEL`: every input, however
            unique its text, is assigned to some group (its own, if no
            other input matches it exactly).
        """
        label_by_hash: dict[str, int] = {}
        labels: list[int] = []
        for item in inputs:
            digest = hashlib.sha256(_normalise(item.masked_description).encode("utf-8")).hexdigest()
            label = label_by_hash.setdefault(digest, len(label_by_hash))
            labels.append(label)
        return labels
