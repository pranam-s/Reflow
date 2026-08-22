"""Phase 2 evaluation: the clustering bake-off harness and its metrics.

- :mod:`reflow.eval.metrics` -- purity, NMI, ARI, noise handling, and the
  Axis C catch-all-share blending/crossover machinery.
- :mod:`reflow.eval.opacity` -- the Axis B opacity-ablation null-hypothesis
  control.
- :mod:`reflow.eval.clustering` -- the harness that runs every candidate
  across every sweep axis and reports the result.
"""

from reflow.eval.clustering import (
    ARMS,
    CATCHALL_STRATUM,
    DEFAULT_N_EVENTS,
    DEFAULT_SEED,
    NARROW_STRATUM,
    NOISE_DIAGNOSTIC_SAMPLE_SIZE,
    OPAQUE_ARM,
    TRANSPARENT_ARM,
    BakeoffReport,
    CandidateRun,
    CrossoverResult,
    NoiseDiagnosticRun,
    Provenance,
    StratumResult,
    run_bakeoff,
    run_noise_diagnostic,
    to_json_dict,
    to_markdown,
)
from reflow.eval.metrics import (
    ClusteringMetrics,
    NoiseHandling,
    blended_metric,
    cluster_purity,
    compute_metrics,
    compute_noise_handling,
    find_crossover_share,
)
from reflow.eval.opacity import opaque_description

__all__ = [
    "ARMS",
    "CATCHALL_STRATUM",
    "DEFAULT_N_EVENTS",
    "DEFAULT_SEED",
    "NARROW_STRATUM",
    "NOISE_DIAGNOSTIC_SAMPLE_SIZE",
    "OPAQUE_ARM",
    "TRANSPARENT_ARM",
    "BakeoffReport",
    "CandidateRun",
    "ClusteringMetrics",
    "CrossoverResult",
    "NoiseDiagnosticRun",
    "NoiseHandling",
    "Provenance",
    "StratumResult",
    "blended_metric",
    "cluster_purity",
    "compute_metrics",
    "compute_noise_handling",
    "find_crossover_share",
    "opaque_description",
    "run_bakeoff",
    "run_noise_diagnostic",
    "to_json_dict",
    "to_markdown",
]
