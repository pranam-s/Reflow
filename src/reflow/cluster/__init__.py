"""Phase 2 clustering candidates: three real clusterers plus the baseline.

Every candidate implements :class:`~reflow.cluster.base.Clusterer`:

- :class:`~reflow.cluster.drain3_clusterer.Drain3Clusterer` -- fixed-depth
  parse-tree template mining.
- :class:`~reflow.cluster.template_hash.TemplateHashClusterer` -- exact
  match on a normalised template hash.
- :class:`~reflow.cluster.tfidf_hdbscan.TfidfHdbscanClusterer` -- TF-IDF
  bag-of-words vectorisation plus density-based (HDBSCAN) clustering.
- :class:`~reflow.cluster.groupby_reason.GroupByReasonClusterer` -- the
  trivial ``GROUP BY (code, source, step, reason)`` baseline, which is not
  a clusterer at all but is scored identically.

See :mod:`reflow.eval.clustering` for the bake-off harness that runs and
scores all four.
"""

from reflow.cluster.base import NOISE_LABEL, Clusterer, ClusterInput
from reflow.cluster.drain3_clusterer import Drain3Clusterer
from reflow.cluster.groupby_reason import GroupByReasonClusterer
from reflow.cluster.template_hash import TemplateHashClusterer
from reflow.cluster.tfidf_hdbscan import TfidfHdbscanClusterer

__all__ = [
    "NOISE_LABEL",
    "ClusterInput",
    "Clusterer",
    "Drain3Clusterer",
    "GroupByReasonClusterer",
    "TemplateHashClusterer",
    "TfidfHdbscanClusterer",
]
