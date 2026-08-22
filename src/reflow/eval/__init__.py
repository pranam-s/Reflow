"""Phase 2 and Phase 3 evaluation harnesses and their metrics.

- :mod:`reflow.eval.metrics` -- Phase 2 purity, NMI, ARI, noise handling,
  and the Axis C catch-all-share blending/crossover machinery.
- :mod:`reflow.eval.opacity` -- Phase 2's Axis B opacity-ablation
  null-hypothesis control.
- :mod:`reflow.eval.clustering` -- the Phase 2 harness that runs every
  clustering candidate across every sweep axis and reports the result.
- :mod:`reflow.eval.incident` -- the Phase 3 harness that runs every
  burst-detection candidate against the corpus's correlated-outage windows
  and reports incident-level, event-level, and time-to-detect results.

Both harness modules independently define ``Provenance``, ``to_json_dict``,
``to_markdown``, ``DEFAULT_SEED``, and ``DEFAULT_N_EVENTS`` -- one report
schema per phase. Re-exporting both under their original names here would
silently shadow one phase's symbol with the other's, so Phase 3's versions
are re-exported under an ``Incident``-prefixed alias instead; every other
symbol keeps its original name. Callers who want a single phase's exact
names should import from :mod:`reflow.eval.clustering` or
:mod:`reflow.eval.incident` directly, exactly as this project's own tests
do.
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
from reflow.eval.incident import (
    CORRELATABLE_METHODS,
    GROUPBY_REASON_LABEL_PREFIX,
    SPLITS,
    DetectorReportRow,
    DowntimeCorrelationDemo,
    IncidentReport,
    TimeToDetectDistribution,
)
from reflow.eval.incident import DEFAULT_N_EVENTS as INCIDENT_DEFAULT_N_EVENTS
from reflow.eval.incident import DEFAULT_SEED as INCIDENT_DEFAULT_SEED
from reflow.eval.incident import Provenance as IncidentProvenance
from reflow.eval.incident import run_benchmark as run_incident_benchmark
from reflow.eval.incident import to_json_dict as incident_to_json_dict
from reflow.eval.incident import to_markdown as incident_to_markdown
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
    "CORRELATABLE_METHODS",
    "DEFAULT_N_EVENTS",
    "DEFAULT_SEED",
    "GROUPBY_REASON_LABEL_PREFIX",
    "INCIDENT_DEFAULT_N_EVENTS",
    "INCIDENT_DEFAULT_SEED",
    "NARROW_STRATUM",
    "NOISE_DIAGNOSTIC_SAMPLE_SIZE",
    "OPAQUE_ARM",
    "SPLITS",
    "TRANSPARENT_ARM",
    "BakeoffReport",
    "CandidateRun",
    "ClusteringMetrics",
    "CrossoverResult",
    "DetectorReportRow",
    "DowntimeCorrelationDemo",
    "IncidentProvenance",
    "IncidentReport",
    "NoiseDiagnosticRun",
    "NoiseHandling",
    "Provenance",
    "StratumResult",
    "TimeToDetectDistribution",
    "blended_metric",
    "cluster_purity",
    "compute_metrics",
    "compute_noise_handling",
    "find_crossover_share",
    "incident_to_json_dict",
    "incident_to_markdown",
    "opaque_description",
    "run_bakeoff",
    "run_incident_benchmark",
    "run_noise_diagnostic",
    "to_json_dict",
    "to_markdown",
]
