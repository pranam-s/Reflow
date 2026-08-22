# Design notes

This document records architectural decisions for `reflow` as they are made. It starts
as a stub in Phase 0 and grows alongside the codebase.

## Architecture

Not yet designed. Phase 0 is scaffolding only: packaging, tooling, and CI. Clustering,
recovery-action selection, execution against Razorpay test-mode APIs, and reporting will
each get a section here once they exist.

## Architecture Decision Records (ADRs)

### ADR-0001: mypy blocks CI, ty is advisory only

**Status:** Accepted (Phase 0)

**Context**

This project runs two type checkers: `mypy` and Astral's `ty`. `ty` is meaningfully
faster and is the checker Astral intends to eventually become the ecosystem default, but
as of this writing it is at version `0.0.x` — pre-1.0, and its own documentation
explicitly warns that it has **no stable API or CLI contract yet** and behavior can
change, including new or altered diagnostics, in any release, including patch releases.

The value this repository provides depends on it reliably cloning and running: `uv sync
--locked && uv run pytest` must work for any contributor at any point in the project's
history. If `ty` were a blocking CI gate, an unrelated `ty` patch upgrade picked up by a
future `uv sync` (or by CI resolving a fresh environment) could turn a previously green
commit red for reasons that have nothing to do with a code change in this repository.
That failure mode is unacceptable for a project whose core promise is reproducible,
runnable history.

**Decision**

- `mypy` is the blocking type gate. `uv run mypy .` must pass in CI; a merge is not
  allowed to land red.
- `ty` runs in CI as `uv run ty check .` with `continue-on-error: true`. Its findings are
  visible in CI output and should be read and, where they reveal a real bug, acted on —
  but a `ty` failure never fails the build.
- This decision is revisited once `ty` reaches a stable 1.0 release with documented
  backward-compatibility guarantees for its diagnostics and CLI.

**Consequences**

- Two type checkers run on every commit, which costs some CI time, in exchange for early
  visibility into what `ty` will eventually enforce.
- A `ty`-only finding does not block a merge; if `ty` and `mypy` disagree, `mypy`'s
  judgment governs until `ty` is promoted.
