"""Phase 3: incident detection by temporal/entity correlation, not text.

Phase 2 established that text clustering does not earn its place on
Razorpay's own corpus: the gateway does not receive the sub-cause for its
catch-all reason codes, so there is no discriminating text to cluster in
production (see ``docs/design.md`` ADR-0002). What survives is a different
problem: a single bank outage emits several distinct reason codes at once,
and ``GROUP BY reason`` shatters one acute incident into multiple
chronic-looking, individually-too-small-to-act-on buckets. Recovering the
incident requires correlating failures over *time* and *entity*
(``method``, ``bank``), not text.

- :mod:`reflow.incident.aggregate` -- buckets raw events into per-entity,
  per-time-bucket failure counts.
- :mod:`reflow.incident.detectors` -- four burst-detection algorithms
  behind one shared interface, benchmarked the same way Phase 2 benchmarked
  clusterers.
- :mod:`reflow.incident.windows` -- merges a detector's per-bucket burst
  calls into contiguous detected incidents.
- :mod:`reflow.incident.attribution` -- attributes events to incidents
  (detected and ground-truth), and measures the cross-reason claim: how
  many incidents span more than one reason code, and what fraction of
  their events ``GROUP BY reason`` would never see as belonging together.
- :mod:`reflow.incident.downtime_api` -- typed models for Razorpay's
  Payment Downtime API and webhooks.
- :mod:`reflow.incident.correlate` -- reconciles detected incidents against
  declared downtimes, treating a declared downtime as corroborating
  evidence, never as a prerequisite.

See :mod:`reflow.eval.incident` for the benchmark harness that runs and
scores every detector.
"""

from reflow.incident.aggregate import (
    BANK_SCOPED_METHODS,
    BUCKET_WIDTH,
    BucketGrid,
    EntityKey,
    EntitySeries,
    build_entity_series,
    entity_key,
    floor_to_bucket,
    reason_scoped_entity_key,
)
from reflow.incident.attribution import (
    CrossReasonSummary,
    DetectorEvaluation,
    FragmentationStats,
    IncidentMatchStats,
    TrueWindow,
    WindowReasonBreakdown,
    background_false_positive_rate,
    compute_fragmentation,
    compute_reason_breakdown,
    evaluate_incidents,
    event_attribution_accuracy,
    reconstruct_true_windows,
    summarize_cross_reason,
)
from reflow.incident.correlate import DowntimeCorrelation, correlate_downtimes
from reflow.incident.detectors import (
    BurstCall,
    EwmaZScoreDetector,
    FixedThresholdDetector,
    IncidentDetector,
    PoissonSurpriseDetector,
    RollingZScoreDetector,
)
from reflow.incident.downtime_api import (
    Downtime,
    DowntimeEventType,
    DowntimeMethod,
    DowntimeSeverity,
    DowntimeStatus,
    DowntimeWebhookEvent,
    UpiDowntimeFlow,
)
from reflow.incident.windows import DetectedIncident, run_detector

__all__ = [
    "BANK_SCOPED_METHODS",
    "BUCKET_WIDTH",
    "BucketGrid",
    "BurstCall",
    "CrossReasonSummary",
    "DetectedIncident",
    "DetectorEvaluation",
    "Downtime",
    "DowntimeCorrelation",
    "DowntimeEventType",
    "DowntimeMethod",
    "DowntimeSeverity",
    "DowntimeStatus",
    "DowntimeWebhookEvent",
    "EntityKey",
    "EntitySeries",
    "EwmaZScoreDetector",
    "FixedThresholdDetector",
    "FragmentationStats",
    "IncidentDetector",
    "IncidentMatchStats",
    "PoissonSurpriseDetector",
    "RollingZScoreDetector",
    "TrueWindow",
    "UpiDowntimeFlow",
    "WindowReasonBreakdown",
    "background_false_positive_rate",
    "build_entity_series",
    "compute_fragmentation",
    "compute_reason_breakdown",
    "correlate_downtimes",
    "entity_key",
    "evaluate_incidents",
    "event_attribution_accuracy",
    "floor_to_bucket",
    "reason_scoped_entity_key",
    "reconstruct_true_windows",
    "run_detector",
    "summarize_cross_reason",
]
