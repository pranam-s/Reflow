"""Drain3 fixed-depth parse-tree clustering.

Wraps ``drain3.template_miner.TemplateMiner`` (installed version 0.9.11;
API confirmed by reading ``.venv/Lib/site-packages/drain3/template_miner.py``
and ``template_miner_config.py`` directly, per :mod:`CLAUDE.md`, rather than
assumed from training-data recall). Drain3 is an online, single-pass log
template miner: it groups messages first by token count, then descends a
fixed-depth prefix tree matching tokens position-by-position, and merges a
new message into an existing cluster only if the fraction of matching
tokens clears ``sim_th``. Feeding it every masked description once, in
order, via ``add_log_message``, and reading back each call's returned
``cluster_id`` is exactly the streaming ``fit_predict`` this bake-off needs.

A fresh :class:`~drain3.template_miner.TemplateMiner` is constructed inside
:meth:`Drain3Clusterer.fit_predict` for every call, with an explicitly
constructed :class:`~drain3.template_miner_config.TemplateMinerConfig`
passed in. This is deliberate: ``TemplateMiner.__init__`` only calls
``config.load("drain3.ini")`` when it is *not* given a config object, so
passing one explicitly skips that filesystem read entirely -- there is no
``drain3.ini`` in this repository, and this bake-off must not depend on
one appearing or not appearing in the working directory. All
:class:`~drain3.template_miner_config.TemplateMinerConfig` fields are left
at their library defaults (``sim_th=0.4``, ``depth=4``,
``masking_instructions=[]``, ...): this phase's own masking layer
(:mod:`reflow.signature`) already removes variable tokens before Drain3
ever sees the text, so Drain3's own regex-masking feature would be
redundant, and tuning Drain3's thresholds to this corpus's ground truth
would be exactly the kind of after-the-fact fitting :mod:`CLAUDE.md`
forbids.
"""

from __future__ import annotations

from collections.abc import Sequence

from drain3.template_miner import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from reflow.cluster.base import ClusterInput


class Drain3Clusterer:
    """Online fixed-depth parse-tree clustering via Drain3.

    Attributes:
        name: ``"drain3"``.
    """

    name = "drain3"

    def fit_predict(self, inputs: Sequence[ClusterInput]) -> list[int]:
        """Mine templates from masked descriptions in one streaming pass.

        Args:
            inputs: The events to cluster, fed to a fresh
                :class:`~drain3.template_miner.TemplateMiner` instance in
                order.

        Returns:
            One label per input: the ``cluster_id`` Drain3 assigned that
            message, which may already exist (the message matched an
            earlier template) or be newly created. Never emits
            :data:`~reflow.cluster.base.NOISE_LABEL`: Drain3 has no
            concept of noise, only clusters.
        """
        miner = TemplateMiner(persistence_handler=None, config=TemplateMinerConfig())
        labels: list[int] = []
        for item in inputs:
            result = miner.add_log_message(item.masked_description)
            labels.append(int(result["cluster_id"]))
        return labels
