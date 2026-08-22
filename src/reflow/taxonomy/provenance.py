"""Provenance metadata for the vendored Razorpay error-reasons spreadsheet.

Phase 1 parses a single vendored artefact instead of hitting Razorpay's CDN at
runtime, so that CI never depends on external network access. This module
records exactly where that artefact came from and when it was fetched, so the
provenance travels with the data rather than living only in a commit message.
"""

from __future__ import annotations

from pathlib import Path

SOURCE_URL: str = (
    "https://razorpay.com/docs/build/browser/assets/images/payments_error_reasons.xlsx"
)
"""The upstream URL the vendored spreadsheet was downloaded from."""

RETRIEVED_ON: str = "2026-08-22"
"""ISO-8601 date on which :data:`SOURCE_URL` was last fetched to produce the
vendored spreadsheet checked into this repository."""

VENDORED_RELATIVE_PATH: str = "data/razorpay_error_reasons.xlsx"
"""Path to the vendored spreadsheet, relative to the repository root."""

EXPECTED_DATA_ROW_COUNT: int = 114
"""Number of non-empty data rows the vendored spreadsheet is expected to
contain, verified by manual inspection on :data:`RETRIEVED_ON`. Parsing code
asserts against this so a silently truncated or re-vendored file is caught
immediately rather than producing a quietly wrong taxonomy."""


def resolve_vendored_path(repo_root: Path) -> Path:
    """Resolve the absolute path to the vendored spreadsheet.

    Args:
        repo_root: Filesystem path to the root of the ``reflow`` repository.

    Returns:
        The absolute path to the vendored ``.xlsx`` file under ``repo_root``.
    """
    return repo_root / VENDORED_RELATIVE_PATH
