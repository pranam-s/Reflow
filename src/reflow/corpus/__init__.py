"""Phase 1 synthetic corpus: seeded, deterministic, streaming.

This package generates synthetic failed-payment events for the label
space built in :mod:`reflow.taxonomy`. It does not cluster, call an LLM,
or call any live API -- it only produces the corpus that later phases will
consume, plus the ground truth (remediation-relevant fields, latent
sub-cause ids, downtime window ids, and train/test split) those phases
need in order to be evaluated honestly.

See :mod:`reflow.corpus.generator` for the top-level entry point and its
design rationale, :mod:`reflow.corpus.reasons` for the method-affinity and
catch-all/latent-sub-cause design, :mod:`reflow.corpus.downtime` for the
correlated-outage model, and :mod:`reflow.corpus.split` for the train/test
policy.
"""

from reflow.corpus.downtime import DowntimeWindow, generate_downtime_windows
from reflow.corpus.events import PaymentEvent, build_event
from reflow.corpus.generator import DEFAULT_N_EVENTS, generate_corpus
from reflow.corpus.methods import METHOD_MIX, UPI_FLOW_MIX, sample_method, sample_upi_flow
from reflow.corpus.reasons import (
    CATCH_ALL_REASONS,
    CATCH_ALL_SUBCAUSES,
    MIN_VARIANT_RICHNESS,
    SUPPORTED_VARIANT_RICHNESS_LEVELS,
    LatentSubcause,
    max_variant_richness,
    subcause_wordings,
)
from reflow.corpus.split import TEST, TRAIN, assign_splits

__all__ = [
    "CATCH_ALL_REASONS",
    "CATCH_ALL_SUBCAUSES",
    "DEFAULT_N_EVENTS",
    "METHOD_MIX",
    "MIN_VARIANT_RICHNESS",
    "SUPPORTED_VARIANT_RICHNESS_LEVELS",
    "TEST",
    "TRAIN",
    "UPI_FLOW_MIX",
    "DowntimeWindow",
    "LatentSubcause",
    "PaymentEvent",
    "assign_splits",
    "build_event",
    "generate_corpus",
    "generate_downtime_windows",
    "max_variant_richness",
    "sample_method",
    "sample_upi_flow",
    "subcause_wordings",
]
