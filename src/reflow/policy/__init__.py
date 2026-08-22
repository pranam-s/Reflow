"""Phase 5: the policy engine, guardrails, and stopping rules.

Phase 4 (``docs/design.md`` ADR-0004) produced a diagnosis for every
event -- deterministically for 95 of 110 reason codes, via a cached LLM
call for the other 15, and via a per-incident LLM call for every detected
incident. This package is where those diagnoses become bounded, audited
recovery decisions:

- :mod:`reflow.policy.actions` -- the closed seven-action set, and the
  pure, remediation-class-only mapping from diagnosis to base action.
  Grounded in what Razorpay's Payments/Payment Links APIs actually permit:
  there is no ``RETRY_PAYMENT`` action, because no such API call exists.
- :mod:`reflow.policy.ladder` -- the escalation ladder: how a base action
  intensifies across repeated attempts on the same order, from a fresh
  recovery link through backoff, a method switch, and human escalation.
- :mod:`reflow.policy.guardrails` -- seven independently testable,
  independently configurable guardrails, each recording a verdict whether
  or not it blocks anything.
- :mod:`reflow.policy.config` -- every guardrail's configurable threshold
  in one place, with each default's rationale stated plainly, including
  where a rationale is a documented policy choice rather than a verified
  external requirement (see that module's docstring on Indian telecom
  compliance and quiet hours).
- :mod:`reflow.policy.decision` -- the :class:`~reflow.policy.decision.Decision`
  audit record every evaluation emits, designed for Phase 6 to persist.
- :mod:`reflow.policy.diagnosis_source` -- builds a full reason-code
  diagnosis table at $0 marginal LLM cost, by combining Tier 1's free
  deterministic table with Phase 4's already-committed Tier 2 output.
- :mod:`reflow.policy.engine` -- :class:`~reflow.policy.engine.PolicyEngine`,
  the stateful orchestrator tying every piece above into one
  ``evaluate``/``evaluate_batch`` call.

See :mod:`reflow.eval.policy` for the benchmark harness that runs this
package over the full corpus and reports the phase's headline
measurements.
"""

from reflow.policy.actions import (
    CHASE_ACTIONS,
    RECONCILE_REASONS,
    Action,
    UnmappedRemediationClassError,
    base_action_for,
)
from reflow.policy.config import PolicyConfig
from reflow.policy.decision import Decision, LadderTerminalState, classify_ladder_terminal_state
from reflow.policy.decision import to_dict as decision_to_dict
from reflow.policy.diagnosis_source import (
    AmbiguousDiagnosisRecord,
    MissingAmbiguousDiagnosisError,
    build_offline_diagnoses,
    diagnose_reason,
    load_ambiguous_diagnosis_records,
)
from reflow.policy.engine import PolicyEngine, detect_active_incident_indices
from reflow.policy.guardrails import (
    ActiveIncidentGuardrail,
    AmountFloorGuardrail,
    AttemptCapGuardrail,
    ContactCapGuardrail,
    CooldownGuardrail,
    Guardrail,
    GuardrailContext,
    GuardrailEvaluation,
    QuietHoursGuardrail,
    TerminalReasonGuardrail,
    default_guardrail_chain,
)
from reflow.policy.ladder import LADDER_ORDER, ladder_action

__all__ = [
    "CHASE_ACTIONS",
    "LADDER_ORDER",
    "RECONCILE_REASONS",
    "Action",
    "ActiveIncidentGuardrail",
    "AmbiguousDiagnosisRecord",
    "AmountFloorGuardrail",
    "AttemptCapGuardrail",
    "ContactCapGuardrail",
    "CooldownGuardrail",
    "Decision",
    "Guardrail",
    "GuardrailContext",
    "GuardrailEvaluation",
    "LadderTerminalState",
    "MissingAmbiguousDiagnosisError",
    "PolicyConfig",
    "PolicyEngine",
    "QuietHoursGuardrail",
    "TerminalReasonGuardrail",
    "UnmappedRemediationClassError",
    "base_action_for",
    "build_offline_diagnoses",
    "classify_ladder_terminal_state",
    "decision_to_dict",
    "default_guardrail_chain",
    "detect_active_incident_indices",
    "diagnose_reason",
    "ladder_action",
    "load_ambiguous_diagnosis_records",
]
