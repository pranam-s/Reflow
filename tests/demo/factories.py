"""A fabricated :class:`~reflow.demo.data.DemoData` factory for reflow.demo tests.

Not a test module itself (no ``test_`` prefix), mirroring
``tests/execute/factories.py``'s pattern: a plain helper other test
modules in this package import, so :mod:`reflow.demo.narrative` and
:mod:`reflow.demo.runner` can be unit-tested against small, known numbers
without depending on the real committed report files
(:mod:`tests.demo.test_data` already covers loading those for real).
"""

from __future__ import annotations

import dataclasses

from reflow.audit.record import AuditRecord, build_audit_record
from reflow.demo.data import (
    ClusterMetrics,
    CorpusData,
    DemoData,
    IncidentData,
    LimitationsData,
    ResultsData,
    RootCauseData,
    RoutingData,
)
from reflow.diagnose.models import Confidence
from reflow.diagnose.router import DiagnosisTier, EventDiagnosis
from reflow.policy.actions import Action
from reflow.policy.guardrails import GuardrailEvaluation
from reflow.taxonomy.remediation import RemediationClass
from tests.execute.factories import make_decision, make_event


def make_guardrail_record(
    *, payment_id: str = "pay_demo_test", bank: str = "Test Bank"
) -> AuditRecord:
    """Build a fabricated audit record for the demo's guardrail beat.

    Includes one blocked and one passed guardrail evaluation, so tests
    exercising this fixture see the same ``BLOCKED``/``PASSED`` shape the
    real, committed pinned record does.

    Args:
        payment_id: The payment id to stamp the record with.
        bank: The counterparty bank name.

    Returns:
        A fully populated :class:`~reflow.audit.record.AuditRecord`.
    """
    event = make_event(payment_id=payment_id, bank=bank)
    base_decision = make_decision(
        event=event,
        in_active_incident=True,
        final_action=Action.WAIT_BANK_RECOVERY,
        candidate_action=Action.RECOVERY_LINK_NOW,
    )
    decision = dataclasses.replace(
        base_decision,
        guardrail_evaluations=(
            GuardrailEvaluation(
                name="terminal_reason_blocklist",
                blocked=False,
                action_before=Action.RECOVERY_LINK_NOW,
                action_after=Action.RECOVERY_LINK_NOW,
                reason="not on the terminal/reconcile blocklist.",
            ),
            GuardrailEvaluation(
                name="active_incident_suppression",
                blocked=True,
                action_before=Action.RECOVERY_LINK_NOW,
                action_after=Action.WAIT_BANK_RECOVERY,
                reason="an active incident is open on this (method, bank).",
            ),
        ),
    )
    diagnosis = EventDiagnosis(
        reason=event.error_reason,
        tier=DiagnosisTier.DETERMINISTIC,
        remediation_class=RemediationClass.RETRY_SAME,
        confidence=Confidence.HIGH,
        rationale=None,
    )
    return build_audit_record(
        decision=decision,
        event=event,
        diagnosis=diagnosis,
        execution=None,
        sequence=0,
        prev_hash=None,
        recorded_at="2026-01-01T00:00:00+00:00",
    )


def make_demo_data() -> DemoData:
    """Build a small, internally-consistent fabricated :class:`DemoData`.

    Returns:
        A fully populated :class:`~reflow.demo.data.DemoData`.
    """
    record = make_guardrail_record()
    return DemoData(
        seed=20260822,
        corpus=CorpusData(n_events=50000, taxonomy_row_count=114, distinct_reasons_seen=110),
        root_cause=RootCauseData(
            narrow_purity=1.0,
            narrow_nmi=0.983,
            narrow_ari=0.981,
            narrow_n_true_clusters=102,
            narrow_n_predicted_clusters=140,
            catchall_groupby=ClusterMetrics(purity=0.319, nmi=0.652, ari=0.325),
            catchall_drain3=ClusterMetrics(purity=0.296, nmi=0.613, ari=0.311),
            catchall_template_hash=ClusterMetrics(purity=0.320, nmi=0.647, ari=0.325),
            catchall_tfidf_hdbscan=ClusterMetrics(purity=0.320, nmi=0.647, ari=0.325),
        ),
        incident=IncidentData(
            poisson_train_precision=0.495,
            poisson_train_recall=1.0,
            poisson_train_f1=0.662,
            poisson_test_precision=0.471,
            poisson_test_recall=1.0,
            poisson_test_f1=0.640,
            groupby_reason_fragments_train_mean=3.738,
            groupby_reason_fragments_test_mean=4.625,
        ),
        routing=RoutingData(
            total_events=50000,
            deterministic_events=43028,
            llm_events=6972,
            deterministic_fraction=0.86056,
            n_escalated_reasons=15,
            ambiguous_reason_calls=15,
            incident_diagnosis_calls=113,
        ),
        results=ResultsData(
            reflow_money_rupees=71874179.0,
            notify_all_money_rupees=75677051.0,
            notify_all_once_money_rupees=72722654.0,
            do_nothing_money_rupees=22584778.0,
            reflow_as_fraction_of_notify_all_money=0.9497,
            reflow_contacts=33691,
            notify_all_contacts=47192,
            notify_all_once_contacts=44674,
        ),
        limitations=LimitationsData(
            guardrail_blocked_events=9992,
            would_have_recovered_events=1552,
            orders_never_recovered=1487,
        ),
        guardrail_payment_id=record.payment_id,
        guardrail_records=(record,),
    )
