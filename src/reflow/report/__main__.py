"""Regenerate ``docs/reports/phase8_report.html`` from committed report artefacts.

Run as ``uv run python -m reflow.report``. Makes no network call, reads no
credential, and invokes no LLM -- every fact it writes already exists in a
committed Phase 2-7 report or the committed audit-trail sample.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reflow.report.data import DEFAULT_OUTPUT_PATH, load_report_data
from reflow.report.html import build_report_html
from reflow.report.validate import validate_report_html


def main() -> int:  # pragma: no cover
    """Build, validate, and write the HTML pipeline report.

    CLI entry point: argument parsing and file writing are glue code, not
    core logic, so this function is excluded from the coverage floor per
    ``CLAUDE.md``'s CLI-glue carve-out -- ``build_report_html`` and
    ``validate_report_html`` are both fully covered by
    ``tests/report/``.

    Returns:
        ``0`` if the generated report passes every validator check, ``1``
        otherwise (the file is still written either way, so a failing
        check can be inspected).
    """
    parser = argparse.ArgumentParser(
        description="Regenerate the Phase 8 accessible HTML pipeline report."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    data = load_report_data()
    html_text = build_report_html(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_text, encoding="utf-8")

    result = validate_report_html(html_text)
    for check in result.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")
    print(f"Wrote {args.output}; validator {'PASSED' if result.all_passed else 'FAILED'}.")
    return 0 if result.all_passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
