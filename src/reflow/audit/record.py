"""The audit-trail record schema: one entry, the whole decision chain.

Deliverable 2's brief is explicit about what "worth anything" means for an
audit trail: it must capture the whole chain an agent walked to reach one
decision, not just the decision itself -- the event and its ``(code,
source, step, reason)`` group (ADR-0002's production root-cause path), any
incident correlation (ADR-0003), the diagnosis with its tier and
confidence (ADR-0004), **every guardrail evaluated, including those that
passed** (ADR-0005 -- "we checked and it was allowed" is exactly what
makes a trail worth anything, not only its blocks), the final action, and
the execution outcome (Deliverable 1). :class:`AuditRecord` is one flat,
JSON-safe dataclass covering every one of those, built directly from
:class:`~reflow.policy.decision.Decision` (which already carries the
diagnosis and guardrail chain),
:class:`~reflow.corpus.events.PaymentEvent` (for the full ``(code, source,
step, reason)`` group -- ``Decision`` itself only carries the bare
``error_reason``), and an optional
:class:`~reflow.execute.models.ExecutionRecord`.

Flat rather than nested: every field is a plain ``str``/``int``/``float``/
``bool``/``None`` or a tuple/dict of those, so two records serialise to
byte-identical JSON given byte-identical input, and a line-based diff
across two runs of the same corpus is meaningful rather than noise from
incidental key reordering (:func:`to_dict` is consumed by
:mod:`reflow.audit.store`, which always writes with ``sort_keys=True``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from reflow.corpus.events import PaymentEvent
from reflow.diagnose.router import EventDiagnosis
from reflow.execute.models import ExecutionRecord, execution_record_to_dict
from reflow.policy.decision import Decision

SCHEMA_VERSION = 1
"""Bumped only on a breaking field change to :class:`AuditRecord`."""


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One append-only audit-trail entry: a payment's complete decision chain.

    Attributes:
        schema_version: See :data:`SCHEMA_VERSION`.
        sequence: 0-based position of this record within its trail file.
        recorded_at: UTC ISO-8601 timestamp of when this record was built
            (distinct from ``created_at``, the diagnosed event's own
            timestamp).
        payment_id: The diagnosed payment's id.
        order_id: The diagnosed payment's order id.
        customer_id: The diagnosed payment's customer id.
        method: The payment method, as its string value.
        bank: The counterparty bank, or ``None``.
        amount: The payment amount, in paise.
        created_at: The event's own timestamp, ISO-8601.
        attempt_number: The event's 1-based attempt number.
        error_code: The event's ``error.code`` (ADR-0002's ``GROUP BY``
            key, part 1 of 4).
        error_source: The event's ``error.source`` (part 2 of 4).
        error_step: The event's ``error.step`` (part 3 of 4).
        error_reason: The event's ``error.reason`` (part 4 of 4, and the
            reason code the diagnosis tier resolved).
        in_active_incident: Whether this event was attributed to an active
            incident on its ``(method, bank)`` entity
            (:func:`reflow.policy.engine.detect_active_incident_indices`,
            ADR-0003's ``poisson_surprise`` detector).
        diagnosis_tier: Which tier produced the diagnosis
            (``"deterministic"`` or ``"llm"``).
        remediation_class: The resolved remediation class, as its string
            value.
        diagnosis_confidence: The diagnosis's confidence, as its string
            value.
        diagnosis_rationale: The LLM's rationale, or ``None`` for a
            deterministic diagnosis.
        guardrail_evaluations: Every guardrail's verdict, in evaluation
            order, as JSON-safe dicts -- **including every guardrail that
            passed**, not only the ones that blocked something.
        base_action: The remediation-class-only action, before the
            escalation ladder or any guardrail.
        candidate_action: The escalation ladder's output -- "what would
            have been sent with zero guardrails."
        final_action: The action remaining after every guardrail has run.
        ladder_terminal_state: The richer terminal-state classification
            (see :func:`reflow.policy.decision.classify_ladder_terminal_state`).
        justification: A human-readable prose summary of how
            ``final_action`` was reached.
        execution: The bounded executor's outcome for ``final_action``, as
            a JSON-safe dict, or ``None`` if this record was built before
            execution ran.
        prev_hash: The previous record's ``record_hash`` in this same
            trail file, or ``None`` for the first record.
        record_hash: This record's own hash, computed over every field
            above plus ``prev_hash`` (:func:`compute_record_hash`) -- the
            tamper-evident chain (see :mod:`reflow.audit.store` module
            docstring).
    """

    schema_version: int
    sequence: int
    recorded_at: str
    payment_id: str
    order_id: str
    customer_id: str
    method: str
    bank: str | None
    amount: int
    created_at: str
    attempt_number: int
    error_code: str
    error_source: str
    error_step: str
    error_reason: str
    in_active_incident: bool
    diagnosis_tier: str
    remediation_class: str
    diagnosis_confidence: str
    diagnosis_rationale: str | None
    guardrail_evaluations: tuple[dict[str, Any], ...]
    base_action: str
    candidate_action: str
    final_action: str
    ladder_terminal_state: str
    justification: str
    execution: dict[str, Any] | None
    prev_hash: str | None
    record_hash: str


def _guardrail_evaluations_payload(decision: Decision) -> tuple[dict[str, Any], ...]:
    """Render a decision's guardrail chain as JSON-safe dicts.

    Args:
        decision: The decision to read.

    Returns:
        One dict per guardrail evaluated, in evaluation order, each naming
        the guardrail, whether it blocked, the action before/after, and
        its stated reason -- present whether or not it blocked anything.
    """
    return tuple(
        {
            "name": evaluation.name,
            "blocked": evaluation.blocked,
            "action_before": evaluation.action_before.value,
            "action_after": evaluation.action_after.value,
            "reason": evaluation.reason,
        }
        for evaluation in decision.guardrail_evaluations
    )


def _canonical_json(payload: dict[str, Any]) -> str:
    """Render a payload as canonical, hash-stable JSON.

    Args:
        payload: The JSON-safe dict to render.

    Returns:
        A compact JSON string with sorted keys, so the same logical
        payload always serialises to the same bytes.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_record_hash(prev_hash: str | None, payload: dict[str, Any]) -> str:
    """Compute one record's tamper-evident hash.

    Args:
        prev_hash: The previous record's ``record_hash`` in the same
            trail file, or ``None`` for the first record.
        payload: Every field of the record *except* ``record_hash``
            itself, as a JSON-safe dict.

    Returns:
        ``sha256(f"{prev_hash or ''}|{canonical_json(payload)}")``, hex
        -encoded -- chaining each record onto the last so that editing,
        reordering, or deleting any historical record changes every later
        record's hash and is therefore detectable by
        :func:`reflow.audit.store.verify_chain`.
    """
    canonical = _canonical_json(payload)
    digest_input = f"{prev_hash or ''}|{canonical}".encode()
    return hashlib.sha256(digest_input).hexdigest()


def build_audit_record(
    *,
    decision: Decision,
    event: PaymentEvent,
    diagnosis: EventDiagnosis,
    execution: ExecutionRecord | None,
    sequence: int,
    prev_hash: str | None,
    recorded_at: str | None = None,
) -> AuditRecord:
    """Build one complete, hash-chained :class:`AuditRecord`.

    Args:
        decision: The event's policy decision (diagnosis, guardrail chain,
            final action).
        event: The diagnosed event (``event.payment_id`` must match
            ``decision.payment_id``) -- supplies the full ``(code, source,
            step, reason)`` group ``Decision`` alone does not carry.
        diagnosis: The same :class:`~reflow.diagnose.router.EventDiagnosis`
            that produced ``decision`` (``diagnosis.reason`` must match
            ``decision.error_reason``) -- supplies ``rationale``, which
            ``Decision`` itself does not carry.
        execution: The bounded executor's outcome for
            ``decision.final_action``, or ``None`` if this record is built
            before execution runs.
        sequence: This record's 0-based position in its trail file.
        prev_hash: The previous record's ``record_hash``, or ``None`` for
            the first record in a trail.
        recorded_at: UTC ISO-8601 timestamp to stamp this record with.
            Defaults to the current time; tests pass a fixed value so the
            resulting hash is reproducible.

    Returns:
        The fully populated, hash-chained :class:`AuditRecord`.
    """
    stamp = recorded_at if recorded_at is not None else datetime.now(UTC).isoformat()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "recorded_at": stamp,
        "payment_id": decision.payment_id,
        "order_id": decision.order_id,
        "customer_id": decision.customer_id,
        "method": decision.method,
        "bank": decision.bank,
        "amount": decision.amount,
        "created_at": decision.created_at,
        "attempt_number": decision.attempt_number,
        "error_code": event.error_code.value,
        "error_source": event.error_source.value,
        "error_step": event.error_step.value,
        "error_reason": decision.error_reason,
        "in_active_incident": decision.in_active_incident,
        "diagnosis_tier": decision.diagnosis_tier,
        "remediation_class": decision.remediation_class,
        "diagnosis_confidence": decision.diagnosis_confidence,
        "diagnosis_rationale": diagnosis.rationale,
        "guardrail_evaluations": list(_guardrail_evaluations_payload(decision)),
        "base_action": decision.base_action.value,
        "candidate_action": decision.candidate_action.value,
        "final_action": decision.final_action.value,
        "ladder_terminal_state": decision.ladder_terminal_state.value,
        "justification": decision.justification,
        "execution": execution_record_to_dict(execution) if execution is not None else None,
        "prev_hash": prev_hash,
    }
    record_hash = compute_record_hash(prev_hash, payload)
    return AuditRecord(
        schema_version=SCHEMA_VERSION,
        sequence=sequence,
        recorded_at=stamp,
        payment_id=decision.payment_id,
        order_id=decision.order_id,
        customer_id=decision.customer_id,
        method=decision.method,
        bank=decision.bank,
        amount=decision.amount,
        created_at=decision.created_at,
        attempt_number=decision.attempt_number,
        error_code=event.error_code.value,
        error_source=event.error_source.value,
        error_step=event.error_step.value,
        error_reason=decision.error_reason,
        in_active_incident=decision.in_active_incident,
        diagnosis_tier=decision.diagnosis_tier,
        remediation_class=decision.remediation_class,
        diagnosis_confidence=decision.diagnosis_confidence,
        diagnosis_rationale=diagnosis.rationale,
        guardrail_evaluations=_guardrail_evaluations_payload(decision),
        base_action=decision.base_action.value,
        candidate_action=decision.candidate_action.value,
        final_action=decision.final_action.value,
        ladder_terminal_state=decision.ladder_terminal_state.value,
        justification=decision.justification,
        execution=payload["execution"],
        prev_hash=prev_hash,
        record_hash=record_hash,
    )


def to_dict(record: AuditRecord) -> dict[str, Any]:
    """Serialise an :class:`AuditRecord` to a JSON-safe dict.

    Args:
        record: The record to serialise.

    Returns:
        A plain-value structure suitable for ``json.dumps``, with the same
        field set :func:`build_audit_record` hashed (plus ``record_hash``
        itself).
    """
    return {
        "schema_version": record.schema_version,
        "sequence": record.sequence,
        "recorded_at": record.recorded_at,
        "payment_id": record.payment_id,
        "order_id": record.order_id,
        "customer_id": record.customer_id,
        "method": record.method,
        "bank": record.bank,
        "amount": record.amount,
        "created_at": record.created_at,
        "attempt_number": record.attempt_number,
        "error_code": record.error_code,
        "error_source": record.error_source,
        "error_step": record.error_step,
        "error_reason": record.error_reason,
        "in_active_incident": record.in_active_incident,
        "diagnosis_tier": record.diagnosis_tier,
        "remediation_class": record.remediation_class,
        "diagnosis_confidence": record.diagnosis_confidence,
        "diagnosis_rationale": record.diagnosis_rationale,
        "guardrail_evaluations": list(record.guardrail_evaluations),
        "base_action": record.base_action,
        "candidate_action": record.candidate_action,
        "final_action": record.final_action,
        "ladder_terminal_state": record.ladder_terminal_state,
        "justification": record.justification,
        "execution": record.execution,
        "prev_hash": record.prev_hash,
        "record_hash": record.record_hash,
    }


def record_from_dict(payload: dict[str, Any]) -> AuditRecord:
    """Reconstruct an :class:`AuditRecord` from its serialised dict form.

    Args:
        payload: A dict previously produced by :func:`to_dict` (e.g.
            parsed back from one JSONL line).

    Returns:
        The reconstructed :class:`AuditRecord`.
    """
    return AuditRecord(
        schema_version=payload["schema_version"],
        sequence=payload["sequence"],
        recorded_at=payload["recorded_at"],
        payment_id=payload["payment_id"],
        order_id=payload["order_id"],
        customer_id=payload["customer_id"],
        method=payload["method"],
        bank=payload["bank"],
        amount=payload["amount"],
        created_at=payload["created_at"],
        attempt_number=payload["attempt_number"],
        error_code=payload["error_code"],
        error_source=payload["error_source"],
        error_step=payload["error_step"],
        error_reason=payload["error_reason"],
        in_active_incident=payload["in_active_incident"],
        diagnosis_tier=payload["diagnosis_tier"],
        remediation_class=payload["remediation_class"],
        diagnosis_confidence=payload["diagnosis_confidence"],
        diagnosis_rationale=payload["diagnosis_rationale"],
        guardrail_evaluations=tuple(payload["guardrail_evaluations"]),
        base_action=payload["base_action"],
        candidate_action=payload["candidate_action"],
        final_action=payload["final_action"],
        ladder_terminal_state=payload["ladder_terminal_state"],
        justification=payload["justification"],
        execution=payload["execution"],
        prev_hash=payload["prev_hash"],
        record_hash=payload["record_hash"],
    )


def record_payload_without_hash(record: AuditRecord) -> dict[str, Any]:
    """Reconstruct the exact payload :func:`compute_record_hash` hashed.

    Args:
        record: The record to reconstruct the payload for.

    Returns:
        The same dict shape :func:`build_audit_record` passed to
        :func:`compute_record_hash`, used by
        :func:`reflow.audit.store.verify_chain` to recompute and check
        each record's hash independently.
    """
    payload = to_dict(record)
    del payload["record_hash"]
    return payload
