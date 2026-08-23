"""The append-only, hash-chained audit-trail store.

Deliverable 2's requirements, taken literally: **append-only** (never
rewrite history), **tamper-evident if cheap** (a chained hash, not a
cryptographic signature or a separate ledger service -- cheap enough not
to balloon this phase's scope), **replayable** (:mod:`reflow.audit.replay`
reconstructs one payment's whole chain from exactly what is stored here,
nothing more), and **stable enough to diff** (every record round-trips
through :func:`reflow.audit.record.to_dict` with sorted keys, so the same
logical run always produces byte-identical JSONL lines).

**Format: one JSON object per line (JSONL), opened in append mode only.**
:class:`AuditTrailWriter` never opens its target file for writing except
in ``"a"`` mode, and never seeks backward -- there is no code path in this
module that can overwrite or delete an existing line, which is the
concrete meaning of "append-only" for a flat file. Resuming an existing
trail (:meth:`AuditTrailWriter.open`) reads only the last line to recover
the hash chain's tip and the next sequence number, never rewriting
anything already on disk.

**Tamper evidence, and its honest limits.** Each record's ``record_hash``
covers every field of that record plus the *previous* record's hash
(:func:`reflow.audit.record.compute_record_hash`), so altering, deleting,
or reordering any historical line breaks the hash chain from that point
forward -- :func:`verify_chain` detects this by recomputing every hash
independently and comparing. This is **detection, not prevention**: a flat
file editable by anyone with filesystem access cannot be made tamper*proof*
by hashing alone (that needs a separate write-once medium or an external
anchor, e.g. periodically publishing the chain tip somewhere append-only
this project does not operate). Chained hashing is the cheap, honest
middle ground the phase brief explicitly calls for ("tamper-evident if
cheap to do"), not a claim of tamper-proofing this module does not make.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from reflow.audit.record import (
    AuditRecord,
    build_audit_record,
    compute_record_hash,
    record_from_dict,
    record_payload_without_hash,
    to_dict,
)
from reflow.corpus.events import PaymentEvent
from reflow.diagnose.router import EventDiagnosis
from reflow.execute.models import ExecutionRecord
from reflow.policy.decision import Decision


def iter_audit_records(path: Path) -> Iterator[AuditRecord]:
    """Read every record from an audit-trail JSONL file, in file order.

    Args:
        path: The trail file to read.

    Yields:
        Each :class:`~reflow.audit.record.AuditRecord`, in the order it
        appears in the file (i.e. ``sequence`` order, since records are
        only ever appended).

    Raises:
        FileNotFoundError: If ``path`` does not exist.
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            yield record_from_dict(json.loads(stripped))


def _last_record(path: Path) -> AuditRecord | None:
    """Read only the final record of an existing trail file.

    Args:
        path: The trail file to read.

    Returns:
        The last :class:`~reflow.audit.record.AuditRecord` in the file, or
        ``None`` if the file does not exist or has no records yet.
    """
    if not path.exists():
        return None
    last: AuditRecord | None = None
    for record in iter_audit_records(path):
        last = record
    return last


@dataclass(slots=True)
class ChainVerificationResult:
    """The outcome of verifying one trail file's tamper-evident hash chain.

    Attributes:
        n_records: Total records checked.
        valid: ``True`` if every record's hash and chain link matched;
            ``False`` if :attr:`first_broken_sequence` is set.
        first_broken_sequence: The ``sequence`` of the first record whose
            own hash or ``prev_hash`` link failed to verify, or ``None``
            if ``valid`` is ``True``.
        detail: A human-readable explanation of the first break, or
            ``None`` if ``valid`` is ``True``.
    """

    n_records: int
    valid: bool
    first_broken_sequence: int | None
    detail: str | None


def verify_chain(path: Path) -> ChainVerificationResult:
    """Independently recompute and check every record's hash chain link.

    Args:
        path: The trail file to verify.

    Returns:
        The populated :class:`ChainVerificationResult`.
    """
    expected_prev_hash: str | None = None
    count = 0
    for record in iter_audit_records(path):
        count += 1
        if record.prev_hash != expected_prev_hash:
            return ChainVerificationResult(
                n_records=count,
                valid=False,
                first_broken_sequence=record.sequence,
                detail=(
                    f"record {record.sequence} has prev_hash={record.prev_hash!r}, expected "
                    f"{expected_prev_hash!r} from the preceding record."
                ),
            )
        recomputed = compute_record_hash(record.prev_hash, record_payload_without_hash(record))
        if recomputed != record.record_hash:
            return ChainVerificationResult(
                n_records=count,
                valid=False,
                first_broken_sequence=record.sequence,
                detail=(
                    f"record {record.sequence} has record_hash={record.record_hash!r}, but "
                    f"recomputing over its own stored fields yields {recomputed!r} -- its "
                    "content was altered after being written."
                ),
            )
        expected_prev_hash = record.record_hash
    return ChainVerificationResult(
        n_records=count, valid=True, first_broken_sequence=None, detail=None
    )


class AuditTrailWriter:
    """Appends hash-chained :class:`~reflow.audit.record.AuditRecord` entries.

    Never opens its target file except in append mode, and never seeks or
    rewrites -- see module docstring. Use :meth:`open` to resume an
    existing trail (recovering its hash-chain tip and next sequence
    number from the file's own last line) or start a fresh one.
    """

    def __init__(self, handle: TextIO, *, next_sequence: int, last_hash: str | None) -> None:
        """Initialise the writer from an already-opened append-mode handle.

        Args:
            handle: An open, append-mode text file handle.
            next_sequence: The sequence number the next appended record
                should use.
            last_hash: The current chain tip (the last written record's
                ``record_hash``), or ``None`` for an empty trail.
        """
        self._handle = handle
        self._next_sequence = next_sequence
        self._last_hash = last_hash

    @classmethod
    def open(cls, path: Path) -> AuditTrailWriter:
        """Open (creating if necessary) an audit trail for appending.

        Args:
            path: The trail file to open. Its parent directory is created
                if missing.

        Returns:
            A writer positioned to append the next record, with its
            sequence counter and hash-chain tip recovered from any
            existing content.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _last_record(path)
        next_sequence = existing.sequence + 1 if existing is not None else 0
        last_hash = existing.record_hash if existing is not None else None
        handle = path.open("a", encoding="utf-8")
        return cls(handle, next_sequence=next_sequence, last_hash=last_hash)

    def append(
        self,
        *,
        decision: Decision,
        event: PaymentEvent,
        diagnosis: EventDiagnosis,
        execution: ExecutionRecord | None,
        recorded_at: str | None = None,
    ) -> AuditRecord:
        """Build and append one hash-chained audit record.

        Args:
            decision: The event's policy decision.
            event: The diagnosed event.
            diagnosis: The diagnosis that produced ``decision``.
            execution: The bounded executor's outcome, or ``None``.
            recorded_at: UTC ISO-8601 timestamp override, for reproducible
                tests.

        Returns:
            The :class:`~reflow.audit.record.AuditRecord` that was
            appended.
        """
        record = build_audit_record(
            decision=decision,
            event=event,
            diagnosis=diagnosis,
            execution=execution,
            sequence=self._next_sequence,
            prev_hash=self._last_hash,
            recorded_at=recorded_at,
        )
        self._handle.write(json.dumps(to_dict(record), sort_keys=True, separators=(",", ":")))
        self._handle.write("\n")
        self._handle.flush()
        self._next_sequence += 1
        self._last_hash = record.record_hash
        return record

    def close(self) -> None:
        """Close the underlying file handle."""
        self._handle.close()

    def __enter__(self) -> AuditTrailWriter:
        """Enter as a context manager.

        Returns:
            This writer.
        """
        return self

    def __exit__(self, *_exc_info: object) -> None:
        """Exit the context manager, closing the underlying file handle."""
        self.close()
