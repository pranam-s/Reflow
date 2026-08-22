"""Phase 1 label space: the Razorpay failure taxonomy.

This package parses Razorpay's vendored error-reasons spreadsheet into typed
records (:mod:`reflow.taxonomy.reasons`), classifies each reason into a
bounded remediation class derived from its own text
(:mod:`reflow.taxonomy.remediation`), encodes the per-payment-method
``source``/``step`` vocabulary and top-level ``code`` enum
(:mod:`reflow.taxonomy.methods`), and normalises Razorpay's two error wire
shapes into one canonical model (:mod:`reflow.taxonomy.signal`).

No clustering, no LLM calls, and no live API calls happen anywhere in this
package -- it is pure, deterministic label-space construction from the
vendored spreadsheet at ``data/razorpay_error_reasons.xlsx``.
"""

from reflow.taxonomy.methods import (
    SOURCES_BY_METHOD,
    STEPS_BY_METHOD,
    UPI_STEPS_BY_FLOW,
    ErrorCode,
    ErrorSource,
    ErrorStep,
    PaymentMethod,
    UpiFlow,
    steps_for_method,
)
from reflow.taxonomy.provenance import (
    EXPECTED_DATA_ROW_COUNT,
    RETRIEVED_ON,
    SOURCE_URL,
    VENDORED_RELATIVE_PATH,
    resolve_vendored_path,
)
from reflow.taxonomy.reasons import ReasonRecord, ReasonSpreadsheetError, parse_reason_records
from reflow.taxonomy.remediation import (
    AmbiguousReason,
    CoverageReport,
    ReasonClassification,
    RemediationClass,
    TaxonomyDriftError,
    build_coverage_report,
    classify_reasons,
)
from reflow.taxonomy.signal import FailureSignal

__all__ = [
    "EXPECTED_DATA_ROW_COUNT",
    "RETRIEVED_ON",
    "SOURCES_BY_METHOD",
    "SOURCE_URL",
    "STEPS_BY_METHOD",
    "UPI_STEPS_BY_FLOW",
    "VENDORED_RELATIVE_PATH",
    "AmbiguousReason",
    "CoverageReport",
    "ErrorCode",
    "ErrorSource",
    "ErrorStep",
    "FailureSignal",
    "PaymentMethod",
    "ReasonClassification",
    "ReasonRecord",
    "ReasonSpreadsheetError",
    "RemediationClass",
    "TaxonomyDriftError",
    "UpiFlow",
    "build_coverage_report",
    "classify_reasons",
    "parse_reason_records",
    "resolve_vendored_path",
    "steps_for_method",
]
