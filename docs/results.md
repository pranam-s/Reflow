# Results, in full

This is the detailed companion to [`README.md`](../README.md)'s condensed claims: the
complete sensitivity band, the guardrails' measured cost at every level, the full
per-finding evidence, the complete prior-art comparison, and one table mapping every
number in this project's documentation to the exact command and report that produced it.
Every figure below is traced to `docs/reports/*`; nothing here is asserted without a
citation.

## Honesty statement

Every "money recovered" figure anywhere in this project is scored by a seeded,
deterministic oracle (`reflow.outcome.oracle.RecoveryOracle`), never observed from a real
customer or a live Razorpay call. Razorpay's test mode exposes only a binary
force-success/force-failure toggle per payment, never a probability — there is no sandbox
surface that answers "does a fresh Payment Link recover a `card_declined` failure 40% of
the time or 60%." That number can only be assumed, honestly and on the record, or not
measured at all. The oracle assumes it, in the open: two free parameters per
`RemediationClass` (ten classes, twenty numbers total, never one per reason code and
never one per action), grounded in the same vendored `Next Steps` text `docs/design.md`
ADR-0002 and ADR-0004 already classified by hand — never tuned after seeing a simulation
result. Every headline number is checked across a three-point sensitivity band
(pessimistic/central/optimistic) specifically so no single assumed probability carries
the conclusion. Full statement:
[`docs/reports/phase7_evaluation.md`](reports/phase7_evaluation.md#honesty-statement-read-this-before-any-number-below).

## The full sensitivity band

| policy | money recovered (central) | money recovered (pessimistic) | money recovered (optimistic) |
| --- | --- | --- | --- |
| `do_nothing` | ₹22,584,778 | ₹18,259,548 | ₹27,327,498 |
| `notify_all` | ₹75,677,051 | ₹50,662,109 | ₹98,088,700 |
| `notify_all_once` | ₹72,722,654 | ₹48,242,292 | ₹95,306,938 |
| `reflow` | ₹71,874,179 | ₹48,701,612 | ₹95,225,149 |

| level | reflow / `notify_all` money | reflow / `notify_all_once` money | contact reduction vs `notify_all` | reflow cost/rupee vs `notify_all` | reflow beats `do_nothing` |
| --- | --- | --- | --- | --- | --- |
| pessimistic | 96.1% | **100.95%** | 28.9% fewer | 26.0% cheaper | yes |
| central | 95.0% | 98.83% | 28.6% fewer | 24.8% cheaper | yes |
| optimistic | 97.1% | 99.91% | 28.4% fewer | 26.2% cheaper | yes |

reflow **never** recovers more absolute money than `notify_all` at any point in the band
— that comparison is reported as a loss, not reframed, and stays a loss at every point
checked. The same is **not** true of `notify_all_once`, the more realistic single-shot
chase baseline: at the pessimistic level, reflow recovers **more** absolute money than
`notify_all_once` (₹48,701,612 vs. ₹48,242,292, 100.95%), not merely a comparable share of
it; only at central (98.83%) and optimistic (99.91%) does reflow recover slightly less.
What is robust across the whole band: reflow always beats `do_nothing` by roughly
2.7-3.5x; reflow recovers 95-97% of `notify_all`'s rupees while sending materially fewer
contacts; against `notify_all_once` reflow is comparable-to-better, never far behind and
sometimes ahead; and reflow is always cheaper per rupee recovered than both chase
baselines, by a stable ~25-26%. Source:
[`docs/reports/phase7_simulation.md`](reports/phase7_simulation.md),
[`docs/reports/phase7_evaluation.md`](reports/phase7_evaluation.md).

## The measured cost of the guardrails, at every level

For every reflow decision where a guardrail changed an escalatable candidate action into
a non-escalatable final action, the same payment attempt's same deterministic oracle draw
was also scored against the pre-guardrail candidate — the identical mechanism the
closed-loop simulation already uses, since the oracle's draw is shared across actions by
design specifically so this counterfactual is well-defined and monotonic.

| level | guardrail-blocked events | would have recovered per oracle | orders never recovered by any other path |
| --- | --- | --- | --- |
| pessimistic | 10,148 | 968 (9.5%) | 937 |
| central | 9,992 | 1,552 (15.5%) | 1,487 (3.3% of 44,674 orders) |
| optimistic | 9,848 | 1,866 (18.9%) | 1,766 |

At the central estimate, reflow's guardrails walked away from **1,552 recoveries** and
**1,487 orders (3.3%)** never recovered by any other path in the simulation as a direct
result. This is the named, quantified price of reflow's lower contact volume, not folded
into an aggregate. Source: `docs/reports/phase7_evaluation.md`, "The measured cost of
reflow's guardrails" section — a one-off, read-only analysis built from existing
`reflow.outcome.oracle`/`reflow.policy` APIs, not yet a committed, tested module (see
ADR-0007's consequences for the plan to promote it).

## What the system could not resolve, and why

The full, itemised list of every genuine limitation this project found in itself — 14
items, each with its own mechanism and citation, including the guardrail cost above — is
already written out in full and is not duplicated here:
[`docs/reports/phase7_evaluation.md`](reports/phase7_evaluation.md#what-the-system-could-not-resolve-and-why).

## Every finding, in full

Razorpay's own stated judging bar for this track is reported as: **"if you force an LLM
into a problem that a simple rule-based system would solve better, you will be marked
down."** This project's answer to that bar is not a design choice argued in the abstract —
it is a benchmark run against its own preferred approach, where it lost, and that is
reported.

### The clustering survey: the structured field already had the answer

Several clustering approaches were surveyed; three real clusterers (Drain3, normalised
template hashing, TF-IDF+HDBSCAN) were implemented and benchmarked against the trivial
`GROUP BY (code, source, step, reason)` baseline, on the catch-all reason codes where free
text is the *only* thing left to discriminate on. Under the condition Razorpay's own
vendored documentation says actually holds in production — that Razorpay does not receive
the sub-cause behind `card_declined`, `payment_declined`, or `payment_failed` at all —
there is no sub-cause signal in the text for any of them to find, so every candidate
converges on the baseline or falls below it:

| candidate | opaque-arm ARI (catch-all) | vs. `GROUP BY`'s 0.325 |
| --- | --- | --- |
| `GROUP BY` (baseline) | 0.325 | — |
| Normalised template hashing | 0.325 | tied within noise (±0.005) |
| TF-IDF + HDBSCAN | 0.325 | tied within noise (±0.005) |
| **Drain3** | **0.311** | **below baseline (no signal to find)** |

In the transparent arm (the corpus's generated text, unmasked), the same three clusterers
appear to win decisively — template hashing and TF-IDF+HDBSCAN both hit ARI 1.000 against
`GROUP BY`'s 0.325 at the lowest wording-richness level. That win turned out to be an
identity, not an inference: independent verification counted the distinct masked strings
the clusterers actually see, and found exactly 32 at richness 1 for 32 true sub-causes —
template hashing groups identical strings by definition, so a perfect score there measures
the corpus's one-wording-per-sub-cause construction, not the algorithm. None of the three
candidates merge paraphrases of one cause; they partition surface forms. Their
transparent-arm advantage depends entirely on surface form being a proxy for sub-cause,
which is an artefact of synthesis — exactly the condition the opaque arm above removes,
and the opaque arm is the one Razorpay's own documentation says actually holds.

On the narrow stratum (102 of 110 reason codes where the taxonomy is not coarse), `GROUP
BY` is already near-perfect for free: purity 1.000, NMI 0.983, ARI 0.981. TF-IDF+HDBSCAN's
brute-force cosine distance computation took 2.0-2.9 seconds on the ~8,000-event catch-all
stratum alone — 30-100x slower than the other two real clusterers, and would not scale to
a literal 50,000-event catch-all stratum without subsampling. No clustering candidate is
adopted anywhere in reflow's production root-causing path. `GROUP BY` is. Full sweep across
richness levels 1/3/5 and both arms:
[`docs/reports/phase2_clustering_bakeoff.md`](reports/phase2_clustering_bakeoff.md);
decision and rejection reasons: `docs/design.md` ADR-0002.

### The routing split: 86.056% of events never touch an LLM

Of 50,000 corpus events, 43,028 (**86.056%**) resolve through a plain deterministic table
lookup, $0 cost, zero latency, zero non-determinism. The other 13.944% carry one of 15
genuinely ambiguous reason codes, escalated to a cached LLM call — 15 calls, ever,
regardless of corpus size. Incident-level diagnosis adds one uncached LLM call per
detected incident (113 for this corpus). **Total LLM calls across the entire 50,000-event
run: 128** (15 + 113) — not 50,000, and not 6,972. This run's total real spend was
**$0.009102** ($0.000814 one-time for the 15 ambiguous reasons, $0.006948 for 113 incident
diagnoses, $0.001340 for 16 judge samples) — projected to **$0.0147 per 100,000 events**
cold-cache, **$0.0139 per 100,000 events** warm-cache. Sampling 8 ambiguous-reason
diagnoses and 8 incident diagnoses (16 total), an independent, different-model-family judge
did not endorse 6 of 16 (37.5%) — zero labelled outright "wrong," all 6 "questionable" for
overconfidence given genuinely ambiguous or thin evidence, never a hallucinated fact. Full
routing detail and per-call cost:
[`docs/reports/phase4_diagnosis.md`](reports/phase4_diagnosis.md); the boundary decision:
`docs/design.md` ADR-0004.

### Incident detection: `GROUP BY reason` fragments what temporal correlation catches whole

All 50 of 50 ground-truth downtime windows in the corpus span 3-4 distinct reason codes at
once — a single bank outage, several different-looking failure buckets. A per-reason-code
`GROUP BY` view — even given the *winning* detector's own algorithm, run at the finest
granularity a naive per-reason monitor could have — never misses most of an incident's
events, but it fragments **each single incident into 3.74 (train) to 4.62 (test) separate
alerts on average, 100% of the time**, roughly 100-150x slower to compute than the
entity-level view. The recommended production detector, `poisson_surprise` over `(method,
bank)`, sees each incident as one incident, and was chosen over a naive fixed-threshold
detector that mechanically won a pre-committed test-split selection rule but whose
precision collapsed to 0.264 on the larger, five-times-more-powerful training split — an
absolute count threshold is scale-dependent by construction, `poisson_surprise` is not.
Full results:
[`docs/reports/phase3_incident_detection.md`](reports/phase3_incident_detection.md);
decision: `docs/design.md` ADR-0003.

## Prior art, in full

A reviewer's first reaction may reasonably be "Razorpay already ships this." Two real
products are worth naming, fairly:

- **Agent Studio** (launched at FTX'26, built on Anthropic's Claude Agent SDK) ships a
  **Subscription Recovery Agent** and two **Abandoned Cart Conversion Agents**. These are
  genuinely capable, production products.
- The **Failed Payment Recovery** dashboard feature sends a recovery message on payment
  failure, citing Razorpay's own figure that "20-25% of payments fail due to avoidable
  reasons, and half of those customers wouldn't return without a nudge."

Both are, by design, a **blanket rule: on failure, send a link.** That rule is exactly
this project's `notify_all` baseline — the one reflow measures itself against and loses to
on absolute rupees, honestly, above. What reflow adds is not a better version of the same
idea; it is a different layer underneath it:

- **reflow root-causes before acting** — `GROUP BY (code, source, step, reason)`, not free
  text, not a guess (ADR-0002), then a two-tier deterministic/LLM diagnosis that touches an
  LLM on 13.944% of events, cached down to 128 total calls for 50,000 events (ADR-0004).
- **reflow refuses to act during a live outage** — 7,372 times on this corpus, via
  Poisson-surprise incident detection over `(method, bank)`, not by reading event text
  (ADR-0003), rather than messaging a customer about a rail failure that is not their
  fault and that a fresh link cannot fix.
- **Every guardrail decision is recorded, including every pass, not just every block** —
  an append-only, hash-chained audit trail, replayable per payment with `reflow replay
  <payment_id>` (ADR-0006).
- **reflow reports that it recovers less money than blanket messaging**, honestly, across
  a full sensitivity band, rather than presenting only the comparison that flatters it.

**The Razorpay MCP server was evaluated and not adopted.** Its tool surface
([`razorpay/razorpay-mcp-server`](https://github.com/razorpay/razorpay-mcp-server)) covers
payments, orders, refunds, payment links, settlements, and QR codes — but has no
failure-reason or retry tool, because no such capability exists on Razorpay's API surface
at all (verified directly against the Payments API, `BUILD_LOG.md`, 2026-09-01). reflow
talks to Razorpay's REST API and webhook payloads directly for the same reason.

## Reproduce every number

Every command below is deterministic (seed `20260822`) and reproduces the exact committed
report. The two marked **(live LLM)** cost real money when they were originally run —
their output is already committed; you do not need to re-run them to see the numbers, and
running them again will make new, real OpenRouter calls.

| Claim | Command | Report |
| --- | --- | --- |
| ₹71.87M vs ₹75.68M, 95.0% at 71.4% contact, sensitivity band | `uv run python -m reflow.eval.simulate` | `docs/reports/phase7_simulation.{json,md}` |
| Guardrail cost: 1,552 recoveries, 1,487 orders (3.3%) | ad hoc script over `reflow.outcome.oracle`/`reflow.policy` (see ADR-0007) | `docs/reports/phase7_evaluation.md` |
| Clustering bake-off: 3 clusterers vs `GROUP BY` | `uv run python -m reflow.eval.clustering` | `docs/reports/phase2_clustering_bakeoff.{json,md}` |
| Incident detection: fragmentation, downtime correlation | `uv run python -m reflow.eval.incident` | `docs/reports/phase3_incident_detection.{json,md}` |
| Routing split: 86.056%, 128 LLM calls **(live LLM)** | `uv run --env-file .env python -m reflow.eval.diagnose` | `docs/reports/phase4_diagnosis.{json,md}` |
| Model default (deepseek, ~35x cheaper) **(live LLM)** | `uv run --env-file .env python -m reflow.eval.model_compare` | `docs/reports/phase7_model_comparison.{json,md}` |
| Guardrail chain fire counts, action distribution | `uv run python -m reflow.eval.policy` | `docs/reports/phase5_policy.{json,md}` |
| Bounded execution, idempotency check, audit trail | `uv run python -m reflow.eval.execute` (dry-run, $0) | `docs/reports/phase6_execution.{json,md}`, `docs/reports/phase6_audit_trail.jsonl` |
| Replay one payment's full decision chain | `uv run reflow replay <payment_id>` | reads the audit trail directly |
| Accessible HTML report, structural/contrast validation | `uv run python -m reflow.report` | `docs/reports/phase8_report.html` |
| Full pipeline demo, no creds/network/LLM | `uv run reflow demo` (`--fast` for instant output) | narrates the reports above |
| Test suite, coverage floor, both interpreters | `uv run pytest --cov --cov-report=term-missing` | CI: `.github/workflows/ci.yml`, matrix 3.11 + 3.13 |

`docs/design.md` also has an "External citations" section: Razorpay's own downtime-detection
engineering blog, the ADA anomaly platform, Optimizer, NPCI's OC-149 circular, RBI's TAT
circular (cited to mark a boundary reflow is deliberately *not* in), and Razorpay's own
"20-25% of payments fail due to avoidable reasons" figure — every claim sourced, and marked
primary or secondary.
