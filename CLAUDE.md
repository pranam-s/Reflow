# CLAUDE.md

This file is the standing contract for any agent (Claude or otherwise) working in this
repository. Read it before making changes. It is project law, not a suggestion.

## What reflow is

`reflow` is an agent that groups failed Razorpay payments into root causes by
structured `(code, source, step, reason)` fields (Phase 2 found that clustering free
text loses to this `GROUP BY` on Razorpay's own catch-all reasons and dropped it from
the production path -- see ADR-0002), detects incidents by correlating failure bursts
over time and `(method, bank)` rather than by reading event text (ADR-0003), diagnoses
each failure through a two-tier deterministic-first/LLM-escalation split (ADR-0004),
picks a bounded, guardrailed recovery action from a closed action set and executes it
against Razorpay's test-mode APIs (ADR-0005/ADR-0006), and reports measured, simulated
recovery against baselines with every decision preserved in an append-only, replayable
audit trail (ADR-0007). It was built in phases, each one designed and evaluated before
being coded, with every phase's decisions recorded as an ADR in `docs/design.md`; the
project is now complete, and this file continues to govern any further change made to it.

## Governing principles

These two govern every phase, above and before the hard rules below. They are not
negotiable in wording's *meaning*, even where the wording itself may be refined:

1. **We create the headline out of the code, not fit the code to a headline.** No
   result in this project is decided in advance. If a benchmark says our preferred
   approach loses, that is the finding, and it gets reported as such. Data, metrics,
   and evaluation criteria are never tuned after the fact to produce a desired number.
2. **Design and evaluate first, then code, then test, then the rest of the SDLC.** An
   approach is chosen and justified in writing before implementation begins.
   Alternatives that were considered and rejected are recorded, along with the reason
   each was rejected, so a later reader can see the decision was made honestly rather
   than reverse-engineered from whatever got built.

## Hard rules

- **No comments in code.** Not one, anywhere in `src/` or `tests/`. Every module, class,
  function, and method instead gets a complete Google-style docstring: summary line,
  `Args`, `Returns`, `Raises` sections as applicable. Pragmas (`# noqa`, `# type: ignore`,
  `# pragma: no cover`) are tolerated only where genuinely unavoidable, must name the
  specific rule being suppressed (never bare), and the reason must be stated in the
  enclosing docstring.
- **Always consult live docs or installed source for module/library APIs.** Never answer
  from training-data recall for tool configuration syntax or library call signatures.
  Use the `context7` MCP tools and/or fetch the live official docs, or read the installed
  package source under `.venv`, before writing configuration or calling an unfamiliar API.
  Config that "looks plausible" but doesn't match the installed version's real interface
  is the primary failure mode in this project.
- **All commands go through `uv run`** (or `uv sync`, `uv add`, `uv lock`). Do not invoke
  `python`, `pytest`, `ruff`, `mypy`, or `ty` directly outside of `uv run` — the project's
  reproducibility guarantee is the committed `uv.lock`, and bypassing `uv run` bypasses it.
- **Coverage floor is 90%** on core logic, measured with branch coverage via
  `coverage.py`, scoped to `src/reflow`. `# pragma: no cover` is allowed only for CLI glue
  (argument parsing, `if __name__ == "__main__":` entry points) and each use must be
  justified in the enclosing docstring.
- **mypy blocks CI. `ty` is advisory only.** See `docs/design.md` for the ADR explaining
  why. Never make a `ty` finding block a merge; never quietly rewrite working code just to
  please a beta type checker's opinion.
- **Conventional Commits** for every commit message (`feat:`, `fix:`, `chore:`, `docs:`,
  `test:`, `refactor:`, etc.), including the subject line only needing to describe the
  change — see <https://www.conventionalcommits.org/en/v1.0.0/>.
- **Never commit secrets.** `.env` holds live Razorpay and OpenRouter credentials and is
  gitignored; it must never be read, printed, edited, or committed by an agent. Use
  `.env.example` as the template for any new environment variable and keep it free of
  real values.

## Workflow expectations

- New runtime dependencies are added only in the phase that actually uses them, via
  `uv add`, never hand-edited into `pyproject.toml`.
- No version pinning of dependencies beyond the loose lower bounds `uv add` writes by
  default. Reproducibility comes from `uv.lock`, which must be committed and kept current
  (`uv sync --locked` is what CI runs, and it fails loudly on a stale lockfile).
- Before reporting a change as done, run, in order:
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`,
  `uv run ty check .` (advisory, report but do not block on it), and
  `uv run pytest --cov --cov-report=term-missing`.
- Style references are vendored/linked under `docs/style/README.md`. Architectural
  decisions are recorded as ADRs in `docs/design.md`.
