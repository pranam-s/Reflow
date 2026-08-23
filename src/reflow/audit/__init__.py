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
