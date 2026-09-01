"""The append-only audit trail: Deliverable 2 of Phase 6.

One :class:`~reflow.audit.record.AuditRecord` per diagnosed event, chained
by a SHA-256 hash over each record's own fields plus the previous record's
hash, so tampering with any historical entry is detectable
(:func:`reflow.audit.store.verify_chain`) without needing a database or an
external ledger. See :mod:`reflow.audit.record` for the record schema and
:mod:`reflow.audit.store` for the append-only file format and its
tamper-evidence guarantees and limits. :mod:`reflow.audit.replay`
reconstructs and renders one payment's complete chain for ``reflow replay
<payment_id>`` (Deliverable 3).
"""

from __future__ import annotations

from reflow.audit.record import (
    SCHEMA_VERSION,
    AuditRecord,
    build_audit_record,
    compute_record_hash,
    record_from_dict,
    record_payload_without_hash,
)
from reflow.audit.record import to_dict as audit_record_to_dict
from reflow.audit.replay import PaymentNotFoundError, find_records_for_payment, render_replay
from reflow.audit.store import (
    AuditTrailWriter,
    ChainVerificationResult,
    iter_audit_records,
    verify_chain,
)

__all__ = [
    "SCHEMA_VERSION",
    "AuditRecord",
    "AuditTrailWriter",
    "ChainVerificationResult",
    "PaymentNotFoundError",
    "audit_record_to_dict",
    "build_audit_record",
    "compute_record_hash",
    "find_records_for_payment",
    "iter_audit_records",
    "record_from_dict",
    "record_payload_without_hash",
    "render_replay",
    "verify_chain",
]
