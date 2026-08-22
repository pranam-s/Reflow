"""Typed parsing of the vendored Razorpay error-reasons spreadsheet.

The spreadsheet has one sheet, a header row, and 114 data rows with three
columns: ``Reason``, ``Explanation``, ``Next Steps``. It is not a clean
lookup table: 4 of the 114 ``Reason`` values repeat (see
:data:`DUPLICATE_REASON_CODES`), two of those repeats carry materially
different ``Explanation``/``Next Steps`` text for the same code, and one
``Reason`` value (``"psp_app_ not_available"``) contains an embedded space
that is almost certainly a vendor typo. This module parses the file
positionally and verbatim -- it does not deduplicate, rename, or otherwise
"clean up" the source data, because doing so would silently discard the
disagreements that :mod:`reflow.taxonomy.remediation` needs to reason about
honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import openpyxl

from reflow.taxonomy.provenance import EXPECTED_DATA_ROW_COUNT

_HEADER_ROW: Final = ("Reason", "Explanation", "Next Steps")


@dataclass(frozen=True, slots=True)
class ReasonRecord:
    """One row of the vendored Razorpay error-reasons spreadsheet.

    Attributes:
        row_index: Zero-based position of this record among the parsed data
            rows, in file order. Stable identifier for rows whose ``reason``
            is not unique (see module docstring).
        reason: The ``Reason`` column value, verbatim, including any vendor
            typos (whitespace is not trimmed or corrected).
        explanation: The ``Explanation`` column value, verbatim.
        next_steps: The ``Next Steps`` column value, verbatim, including
            embedded newlines for rows that render as a bulleted list.
    """

    row_index: int
    reason: str
    explanation: str
    next_steps: str


class ReasonSpreadsheetError(ValueError):
    """Raised when the vendored spreadsheet does not match its expected shape.

    This guards against silently building a taxonomy from a truncated,
    re-vendored, or otherwise unexpectedly reshaped source file.
    """


def parse_reason_records(path: Path) -> list[ReasonRecord]:
    """Parse the vendored error-reasons spreadsheet into typed records.

    Args:
        path: Filesystem path to the vendored ``.xlsx`` file. Must be read
            from local disk -- this function performs no network access.

    Returns:
        A list of :class:`ReasonRecord`, one per non-empty data row, in the
        same order as they appear in the spreadsheet.

    Raises:
        ReasonSpreadsheetError: If the header row does not match the expected
            three columns, if a data row is missing an explanation or next
            steps value, or if the number of parsed rows does not equal
            :data:`reflow.taxonomy.provenance.EXPECTED_DATA_ROW_COUNT`.
    """
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        if worksheet is None:
            raise ReasonSpreadsheetError("Vendored workbook has no active worksheet.")
        rows = worksheet.iter_rows(values_only=True)
        try:
            header = next(rows)
        except StopIteration as exc:
            raise ReasonSpreadsheetError("Vendored workbook has no header row.") from exc
        header_prefix = tuple(header[:3])
        if header_prefix != _HEADER_ROW:
            raise ReasonSpreadsheetError(
                f"Unexpected header row {header_prefix!r}, expected {_HEADER_ROW!r}."
            )
        records: list[ReasonRecord] = []
        for raw_row in rows:
            reason_cell = raw_row[0] if len(raw_row) > 0 else None
            if reason_cell is None:
                continue
            explanation_cell = raw_row[1] if len(raw_row) > 1 else None
            next_steps_cell = raw_row[2] if len(raw_row) > 2 else None
            if not isinstance(explanation_cell, str) or not isinstance(next_steps_cell, str):
                raise ReasonSpreadsheetError(
                    f"Row {len(records)} for reason {reason_cell!r} is missing an "
                    "explanation or next-steps value."
                )
            records.append(
                ReasonRecord(
                    row_index=len(records),
                    reason=str(reason_cell),
                    explanation=explanation_cell,
                    next_steps=next_steps_cell,
                )
            )
    finally:
        workbook.close()

    if len(records) != EXPECTED_DATA_ROW_COUNT:
        raise ReasonSpreadsheetError(
            f"Parsed {len(records)} data rows, expected {EXPECTED_DATA_ROW_COUNT}. "
            "The vendored spreadsheet may have been re-fetched or truncated."
        )
    return records
