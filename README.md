# reflow

An agent that clusters failed Razorpay payments into root causes, picks a bounded
recovery action, executes it against Razorpay's test-mode APIs, and reports measured
recovery against a baseline.

## Quickstart

```sh
uv sync
uv run pytest
```

## Architecture

To be filled in as clustering, recovery-action selection, and execution land in later
phases. See `docs/design.md` for architecture decision records.

## Results

Not yet available. No results or metrics exist at this phase; this section will report
measured recovery rates against a baseline once the agent runs end to end.

## Evaluation

Not yet available. The evaluation methodology will be documented here once there is
something to evaluate.
