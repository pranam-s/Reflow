"""The ``reflow`` command-line entry point.

Three subcommands:

- ``reflow execute`` -- runs the Phase 6 bounded-execution benchmark
  (:func:`reflow.eval.execute.run_benchmark`), always dry-run (see that
  module's docstring for why live execution is deliberately not exposed
  here: this benchmark spans a whole generated corpus, and this project's
  live-call budget is a small, fixed, already-spent number proven once
  via committed cassettes, not something a corpus-wide CLI invocation
  should be able to threaten).
- ``reflow replay <payment_id>`` -- Deliverable 3: reconstructs and prints
  one payment's complete decision chain from the append-only audit trail
  (:mod:`reflow.audit.replay`).
- ``reflow demo`` -- Phase 8 Deliverable 1: the single scripted command the
  pitch video records, narrating this project's whole arc from committed
  Phase 2/3/4/6/7 report artefacts (:mod:`reflow.demo`). No credential is
  read, no network call is made, and no LLM is ever invoked here.

Argument parsing and process wiring are CLI glue, excluded from the
coverage floor per ``CLAUDE.md``'s carve-out for ``if __name__ ==
"__main__":``-style entry points; the logic each subcommand delegates to
is fully covered by ``tests/eval/test_execute.py``, ``tests/demo/``, and
``tests/test_cli.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console

from reflow.audit.replay import PaymentNotFoundError, find_records_for_payment, render_replay
from reflow.demo.data import load_demo_data
from reflow.demo.pacing import FAST, PACED
from reflow.demo.runner import run_demo
from reflow.eval.execute import (
    DEFAULT_AUDIT_TRAIL_HEAD,
    DEFAULT_AUDIT_TRAIL_PATH,
    DEFAULT_N_EVENTS,
    DEFAULT_SEED,
    run_benchmark,
    to_json_dict,
    to_markdown,
)
from reflow.policy.diagnosis_source import DEFAULT_PHASE4_REPORT_PATH


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``reflow`` argument parser.

    Returns:
        The configured :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="reflow",
        description="Bounded execution and audit trail for reflow's recovery actions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    execute_parser = subparsers.add_parser(
        "execute", help="Run the bounded executor over a generated corpus (always dry-run)."
    )
    execute_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    execute_parser.add_argument("--n-events", type=int, default=DEFAULT_N_EVENTS)
    execute_parser.add_argument("--phase4-report", type=Path, default=DEFAULT_PHASE4_REPORT_PATH)
    execute_parser.add_argument("--audit-path", type=Path, default=DEFAULT_AUDIT_TRAIL_PATH)
    execute_parser.add_argument("--audit-sample-size", type=int, default=DEFAULT_AUDIT_TRAIL_HEAD)
    execute_parser.add_argument("--output-dir", type=Path, default=None)

    replay_parser = subparsers.add_parser(
        "replay", help="Reconstruct and print one payment's complete decision chain."
    )
    replay_parser.add_argument("payment_id")
    replay_parser.add_argument("--audit-path", type=Path, default=DEFAULT_AUDIT_TRAIL_PATH)

    demo_parser = subparsers.add_parser(
        "demo",
        help="Run the scripted, narrated demo of reflow's full pipeline (no credentials, "
        "no network, no LLM calls).",
    )
    demo_parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip narration pauses (for CI/testing). Never changes what is printed.",
    )

    return parser


def execute_command(args: argparse.Namespace, *, console: Console) -> int:
    """Run the ``reflow execute`` subcommand.

    Args:
        args: Parsed CLI arguments.
        console: Where to print the summary line.

    Returns:
        Process exit code (always ``0``; this subcommand raises on any
        unrecoverable failure rather than returning non-zero).
    """
    report = run_benchmark(
        seed=args.seed,
        n_events=args.n_events,
        phase4_report_path=args.phase4_report,
        audit_trail_path=args.audit_path,
        audit_sample_size=args.audit_sample_size,
    )
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "phase6_execution.json").write_text(
            json.dumps(to_json_dict(report), indent=2), encoding="utf-8"
        )
        (args.output_dir / "phase6_execution.md").write_text(to_markdown(report), encoding="utf-8")
    console.print(
        f"Evaluated {report.n_events_evaluated} events; persisted "
        f"{report.n_audit_records_persisted} audit records at {report.audit_trail_path}; "
        f"chain valid: {report.audit_chain_valid}."
    )
    return 0


def replay_command(args: argparse.Namespace, *, console: Console) -> int:
    """Run the ``reflow replay`` subcommand.

    Args:
        args: Parsed CLI arguments.
        console: Where to render the replay.

    Returns:
        ``0`` on success, ``1`` if ``args.payment_id`` has no audit record.
    """
    try:
        records = find_records_for_payment(args.audit_path, args.payment_id)
    except PaymentNotFoundError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1
    except FileNotFoundError:
        console.print(
            f"[bold red]Error:[/bold red] no audit trail found at {args.audit_path}. Run "
            "`reflow execute` first, or pass --audit-path."
        )
        return 1
    render_replay(console, records)
    return 0


def demo_command(args: argparse.Namespace, *, console: Console) -> int:
    """Run the ``reflow demo`` subcommand.

    Loads every fact the demo narrates from committed Phase 2/3/4/6/7
    report artefacts (:func:`reflow.demo.data.load_demo_data`) -- no
    credential is read from the environment, no network call is made, and
    no LLM is invoked anywhere in this path.

    Args:
        args: Parsed CLI arguments.
        console: Where to render the demo.

    Returns:
        ``0`` on success.
    """
    data = load_demo_data()
    pace = FAST if args.fast else PACED
    run_demo(console=console, data=data, pace=pace)
    return 0


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover
    """The ``reflow`` console-script entry point.

    Excluded from the coverage floor per ``CLAUDE.md``'s CLI-glue
    carve-out: this function only parses arguments, builds a real
    ``Console`` bound to ``sys.stdout``, and dispatches -- every branch it
    dispatches to is covered directly by ``tests/test_cli.py`` calling
    :func:`execute_command`/:func:`replay_command` with an in-memory
    console instead.

    Args:
        argv: Command-line arguments, excluding the program name. Defaults
            to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    console = Console() if sys.stdout.isatty() else Console(width=120)
    if args.command == "execute":
        return execute_command(args, console=console)
    if args.command == "replay":
        return replay_command(args, console=console)
    return demo_command(args, console=console)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
