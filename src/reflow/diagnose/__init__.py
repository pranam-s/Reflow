"""Phase 4: the two-tier diagnosis pipeline.

Phase 2 (``docs/design.md`` ADR-0002) established that ``GROUP BY (code,
source, step, reason)`` beats clustering for individual-event root-causing.
Phase 3 (ADR-0003) established that a bank outage spans several reason
codes at once, and recommended the ``poisson_surprise`` detector for
finding those incidents. Neither phase needed an LLM. This package is
where an LLM is finally introduced, and only exactly where structure
genuinely runs out:

- :mod:`reflow.diagnose.tier1` -- the deterministic remediation-class
  lookup built by reconciling every vendored row of
  :mod:`reflow.taxonomy.remediation` to its reason code. No LLM call. Covers
  95 of 110 distinct reason codes.
- :mod:`reflow.diagnose.ambiguous` -- Tier 2 for the 15 reason codes that
  will not reconcile: one cached LLM call per reason code, never per event.
- :mod:`reflow.diagnose.incident` -- Tier 2 for a detected incident: one LLM
  call per incident, since an incident's entity/window/reason-code mix is
  the one diagnosis a per-reason ``GROUP BY`` view structurally cannot
  produce.
- :mod:`reflow.diagnose.router` -- combines Tier 1 and the ambiguous-reason
  Tier 2 into the phase's headline measurement: what fraction of events
  resolve deterministically versus escalate to the LLM.
- :mod:`reflow.diagnose.models` -- the Pydantic response models every LLM
  call in this package validates its output against.

See :mod:`reflow.eval.diagnose` for the benchmark harness that runs and
reports on all of the above, and :mod:`reflow.eval.judge` for the
independent-model judge that scores Tier 2 output quality.
"""

from reflow.diagnose.ambiguous import AmbiguousReasonDiagnoser
from reflow.diagnose.incident import IncidentContext, IncidentDiagnoser, build_incident_context
from reflow.diagnose.models import (
    AmbiguousReasonDiagnosis,
    Confidence,
    IncidentDiagnosis,
    JudgeVerdict,
    JudgeVerdictLabel,
    RecommendedPosture,
)
from reflow.diagnose.router import DiagnosisRouter, DiagnosisTier, EventDiagnosis, RoutingStats
from reflow.diagnose.tier1 import (
    DeterministicTable,
    ReasonRowContext,
    build_deterministic_table,
    default_deterministic_table,
)

__all__ = [
    "AmbiguousReasonDiagnoser",
    "AmbiguousReasonDiagnosis",
    "Confidence",
    "DeterministicTable",
    "DiagnosisRouter",
    "DiagnosisTier",
    "EventDiagnosis",
    "IncidentContext",
    "IncidentDiagnoser",
    "IncidentDiagnosis",
    "JudgeVerdict",
    "JudgeVerdictLabel",
    "ReasonRowContext",
    "RecommendedPosture",
    "RoutingStats",
    "build_deterministic_table",
    "build_incident_context",
    "default_deterministic_table",
]
