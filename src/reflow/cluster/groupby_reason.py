"""The trivial ``GROUP BY (code, source, step, reason)`` baseline.

Razorpay's own webhook already carries a structured ``error_reason``
alongside ``error_code``/``error_source``/``error_step``. Grouping failed
payments by that four-field tuple is a one-line alternative to any
clustering, and is the primary hypothesis this phase's bake-off tests
against: does clustering earn its place over this baseline, and where
exactly. :class:`GroupByReasonClusterer` implements it behind the same
:class:`~reflow.cluster.base.Clusterer` interface as the three genuine
clusterers so the bake-off harness can call it, and score it, identically.
"""

from __future__ import annotations

from collections.abc import Sequence

from reflow.cluster.base import ClusterInput


class GroupByReasonClusterer:
    """Assigns one label per unique ``(code, source, step, reason)`` tuple.

    Attributes:
        name: ``"groupby_reason"``.
    """

    name = "groupby_reason"

    def fit_predict(self, inputs: Sequence[ClusterInput]) -> list[int]:
        """Group inputs by their ``(code, source, step, reason)`` tuple.

        Args:
            inputs: The events to group. ``masked_description`` is ignored
                entirely -- this baseline never looks at text.

        Returns:
            One label per input, assigned in first-seen order of each
            distinct ``(code, source, step, reason)`` tuple. Never emits
            :data:`~reflow.cluster.base.NOISE_LABEL`: every input is
            assigned to some group.
        """
        label_by_key: dict[tuple[str, str, str, str], int] = {}
        labels: list[int] = []
        for item in inputs:
            key = (str(item.code), str(item.source), str(item.step), item.reason)
            label = label_by_key.setdefault(key, len(label_by_key))
            labels.append(label)
        return labels
