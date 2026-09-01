"""Loading every extra fact the HTML report needs beyond ``reflow demo``'s own data.

Reuses :func:`reflow.demo.data.load_demo_data` for the corpus, root-cause,
incident, routing, results, and limitations facts the demo and this report
both present, so the two never disagree about a shared number by drifting
out of sync. This module adds exactly what the demo does not need: the
full three-point sensitivity-band outcome table (12 rows: 4 policies x 3
levels) and the Phase 5 guardrail action-distribution/fire-count data,
both read from already-committed report artefacts, never computed fresh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.metadata import metadata, version
from pathlib import Path
from typing import Any

from reflow.demo.data import DEFAULT_AUDIT_TRAIL_PATH as _DEFAULT_AUDIT_TRAIL_PATH
from reflow.demo.data import DEFAULT_PHASE2_REPORT_PATH as _DEFAULT_PHASE2_REPORT_PATH
from reflow.demo.data import DEFAULT_PHASE3_REPORT_PATH as _DEFAULT_PHASE3_REPORT_PATH
from reflow.demo.data import DEFAULT_PHASE4_REPORT_PATH as _DEFAULT_PHASE4_REPORT_PATH
from reflow.demo.data import (
    DEFAULT_PHASE7_EVALUATION_REPORT_PATH as _DEFAULT_PHASE7_EVALUATION_REPORT_PATH,
)
from reflow.demo.data import PINNED_GUARDRAIL_PAYMENT_ID as _PINNED_GUARDRAIL_PAYMENT_ID
from reflow.demo.data import DemoData, load_demo_data
from reflow.version import get_version

_REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_PHASE5_REPORT_PATH: Path = _REPO_ROOT / "docs" / "reports" / "phase5_policy.json"
DEFAULT_PHASE7_SIMULATION_REPORT_PATH: Path = (
    _REPO_ROOT / "docs" / "reports" / "phase7_simulation.json"
)
DEFAULT_OUTPUT_PATH: Path = _REPO_ROOT / "docs" / "reports" / "phase8_report.html"

REPORT_GENERATED_ON: str = "2026-09-01"
"""The fixed date this report was generated and committed. Not
``datetime.now()``: this file is generated once and checked in, exactly
like every other Phase 2-7 report, so its provenance date is a fact about
when it was produced, not a value that should change on every re-render."""

REGENERATE_COMMAND: str = "uv run python -m reflow.report"


@dataclass(frozen=True, slots=True)
class PolicyOutcomeRow:
    """One (policy, sensitivity level) row of the full simulation outcome table.

    Attributes:
        policy: The policy name (``do_nothing``, ``notify_all``,
            ``notify_all_once``, or ``reflow``).
        sensitivity_level: ``"pessimistic"``, ``"central"``, or
            ``"optimistic"``.
        money_recovered_rupees: Rupees recovered under this policy and
            level.
        contacts_sent: Customer contacts sent.
    """

    policy: str
    sensitivity_level: str
    money_recovered_rupees: float
    contacts_sent: int


@dataclass(frozen=True, slots=True)
class GuardrailFireRow:
    """One guardrail's fire/pass counts across the full corpus.

    Attributes:
        name: The guardrail's stable identifier.
        fired: How many events this guardrail blocked.
        passed: How many events this guardrail passed unchanged.
    """

    name: str
    fired: int
    passed: int


@dataclass(frozen=True, slots=True)
class ActionDistribution:
    """The action distribution before and after the full guardrail chain.

    Attributes:
        candidate_counts: Action -> count, before any guardrail runs (the
            escalation ladder's own output).
        final_counts: Action -> count, after the full guardrail chain.
    """

    candidate_counts: dict[str, int]
    final_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class ReportData:
    """Every fact the HTML pipeline report needs.

    Attributes:
        demo: The shared facts also used by ``reflow demo``
            (:class:`reflow.demo.data.DemoData`).
        policy_outcomes: The full 12-row sensitivity-band outcome table.
        guardrail_fires: Per-guardrail fire/pass counts, in evaluation
            order.
        action_distribution: See :class:`ActionDistribution`.
        over_contact_reduction: Contacts avoided by the full guardrail
            chain vs. zero guardrails.
        over_contact_reduction_rate: The same, as a fraction.
        generated_on: The fixed date this report was generated
            (:data:`REPORT_GENERATED_ON`).
        regenerate_command: The command that reproduces this report
            (:data:`REGENERATE_COMMAND`).
        python_requires: The project's declared supported Python range
            (``requires-python`` in ``pyproject.toml``, e.g. ``">=3.11"``),
            not the interpreter that happened to render this file. See
            :func:`_python_requires` for why the running interpreter is
            deliberately not stamped here.
        reflow_version: The installed ``reflow`` package version.
        pydantic_version: The installed ``pydantic`` package version.
        rich_version: The installed ``rich`` package version.
    """

    demo: DemoData
    policy_outcomes: tuple[PolicyOutcomeRow, ...]
    guardrail_fires: tuple[GuardrailFireRow, ...]
    action_distribution: ActionDistribution
    over_contact_reduction: int
    over_contact_reduction_rate: float
    generated_on: str
    regenerate_command: str
    python_requires: str
    reflow_version: str
    pydantic_version: str
    rich_version: str


def _python_requires() -> str:
    """Return the project's declared supported Python range, not the running interpreter.

    This report is a committed, checked-in artefact regenerated by
    ``uv run python -m reflow.report`` and verified byte-for-byte against
    that regeneration (``tests/report/test_html.py::
    test_committed_report_matches_the_generator_output``), on a CI matrix
    that runs both Python 3.11 and 3.13. Stamping ``platform.python_version()``
    (or ``sys.version_info``) would make that byte-equality check fail
    deterministically on whichever interpreter did not generate the
    committed copy, since the two interpreters' patch versions differ
    (e.g. ``3.11.15`` vs. ``3.13.15``) even though every other fact in this
    report is identical between them. The project's ``requires-python``
    range (read from installed package metadata, which mirrors
    ``pyproject.toml``, rather than hard-coded here to avoid drift) is
    stable across that whole matrix and is also the more useful
    provenance fact for a reader: which Python versions this project
    supports, not which one happened to render this file.

    Returns:
        The ``Requires-Python`` value from the installed ``reflow``
        package's own metadata (e.g. ``">=3.11"``).

    Raises:
        KeyError: If the installed package metadata has no
            ``Requires-Python`` field, which would mean ``pyproject.toml``
            no longer declares one. Uses ``__getitem__`` rather than the
            ``PackageMetadata.get`` method, which ``typeshed`` (see
            ``importlib/metadata/_meta.pyi``) only declares from Python
            3.12 onward, unlike ``__getitem__``, which this project's
            unpinned ``mypy`` (see ADR on ``[tool.mypy]`` in
            ``docs/design.md``) must type-check correctly under 3.11 too.
    """
    requires_python = metadata("reflow")["Requires-Python"]
    if not requires_python:
        raise KeyError("installed 'reflow' package metadata has no Requires-Python field")
    return str(requires_python)


def _load_json(path: Path) -> dict[str, Any]:
    """Load and parse one committed JSON report.

    Args:
        path: Filesystem path to the report.

    Returns:
        The parsed JSON document as a dict.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
    """
    with path.open(encoding="utf-8") as handle:
        loaded: Any = json.load(handle)
    return dict(loaded)


def _load_policy_outcomes(phase7_simulation_report: dict[str, Any]) -> tuple[PolicyOutcomeRow, ...]:
    """Build the full sensitivity-band outcome table from the Phase 7 simulation report.

    Args:
        phase7_simulation_report: The parsed ``phase7_simulation.json``
            document.

    Returns:
        One :class:`PolicyOutcomeRow` per (policy, sensitivity level).
    """
    return tuple(
        PolicyOutcomeRow(
            policy=str(outcome["policy"]),
            sensitivity_level=str(outcome["sensitivity_level"]),
            money_recovered_rupees=float(outcome["money_recovered_rupees"]),
            contacts_sent=int(outcome["contacts_sent"]),
        )
        for outcome in phase7_simulation_report["outcomes"]
    )


def _load_guardrail_fires(phase5_report: dict[str, Any]) -> tuple[GuardrailFireRow, ...]:
    """Build per-guardrail fire/pass counts from the Phase 5 policy report.

    Args:
        phase5_report: The parsed ``phase5_policy.json`` document.

    Returns:
        One :class:`GuardrailFireRow` per guardrail, in evaluation order.
    """
    return tuple(
        GuardrailFireRow(
            name=str(entry["name"]), fired=int(entry["fired"]), passed=int(entry["passed"])
        )
        for entry in phase5_report["guardrail_fires"]
    )


def _load_action_distribution(phase5_report: dict[str, Any]) -> ActionDistribution:
    """Build the before/after action distribution from the Phase 5 policy report.

    Args:
        phase5_report: The parsed ``phase5_policy.json`` document.

    Returns:
        The populated :class:`ActionDistribution`.
    """
    distribution = phase5_report["action_distribution"]
    return ActionDistribution(
        candidate_counts={
            str(action): int(count) for action, count in distribution["candidate_counts"].items()
        },
        final_counts={
            str(action): int(count) for action, count in distribution["final_counts"].items()
        },
    )


def load_report_data(
    *,
    phase2_report_path: Path = _DEFAULT_PHASE2_REPORT_PATH,
    phase3_report_path: Path = _DEFAULT_PHASE3_REPORT_PATH,
    phase4_report_path: Path = _DEFAULT_PHASE4_REPORT_PATH,
    phase5_report_path: Path = DEFAULT_PHASE5_REPORT_PATH,
    phase7_evaluation_report_path: Path = _DEFAULT_PHASE7_EVALUATION_REPORT_PATH,
    phase7_simulation_report_path: Path = DEFAULT_PHASE7_SIMULATION_REPORT_PATH,
    audit_trail_path: Path = _DEFAULT_AUDIT_TRAIL_PATH,
    guardrail_payment_id: str = _PINNED_GUARDRAIL_PAYMENT_ID,
    generated_on: str = REPORT_GENERATED_ON,
) -> ReportData:
    """Load every fact the HTML pipeline report needs from committed artefacts.

    Performs only local filesystem reads and installed-package version
    lookups: no network access, no credential lookup, no LLM call, and no
    corpus regeneration.

    Args:
        phase2_report_path: Path to the Phase 2 clustering bake-off report.
        phase3_report_path: Path to the Phase 3 incident-detection report.
        phase4_report_path: Path to the Phase 4 diagnosis report.
        phase5_report_path: Path to the Phase 5 policy report.
        phase7_evaluation_report_path: Path to the Phase 7 evaluation
            report.
        phase7_simulation_report_path: Path to the Phase 7 simulation
            report.
        audit_trail_path: Path to the committed audit-trail JSONL sample.
        guardrail_payment_id: The pinned payment id for the guardrail
            section.
        generated_on: The date to stamp this report's provenance with.

    Returns:
        The fully populated :class:`ReportData`.

    Raises:
        FileNotFoundError: If any report or the audit trail is missing.
        reflow.audit.replay.PaymentNotFoundError: If ``guardrail_payment_id``
            has no record in the audit trail.
    """
    demo = load_demo_data(
        phase2_report_path=phase2_report_path,
        phase3_report_path=phase3_report_path,
        phase4_report_path=phase4_report_path,
        phase7_evaluation_report_path=phase7_evaluation_report_path,
        audit_trail_path=audit_trail_path,
        guardrail_payment_id=guardrail_payment_id,
    )
    phase5_report = _load_json(phase5_report_path)
    phase7_simulation_report = _load_json(phase7_simulation_report_path)
    return ReportData(
        demo=demo,
        policy_outcomes=_load_policy_outcomes(phase7_simulation_report),
        guardrail_fires=_load_guardrail_fires(phase5_report),
        action_distribution=_load_action_distribution(phase5_report),
        over_contact_reduction=int(phase5_report["over_contact"]["reduction"]),
        over_contact_reduction_rate=float(phase5_report["over_contact"]["reduction_rate"]),
        generated_on=generated_on,
        regenerate_command=REGENERATE_COMMAND,
        python_requires=_python_requires(),
        reflow_version=get_version(),
        pydantic_version=version("pydantic"),
        rich_version=version("rich"),
    )
