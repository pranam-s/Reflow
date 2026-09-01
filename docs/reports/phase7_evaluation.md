# Phase 7 evaluation report

This is the phase-level evaluation report, distinct from the raw simulation output in
`docs/reports/phase7_simulation.md` and the raw model-comparison output in
`docs/reports/phase7_model_comparison.md`. It states the honesty statement those two reports
point back to, gives the headline comparison and band findings in plain language, reports what
this project's own guardrails cost in foregone recovery, lists what the system could not resolve
and why, and gives the model-default recommendation with its evidence.

## Honesty statement (read this before any number below)

- **Recovery outcomes are simulated by a seeded oracle, never observed from real customers.**
  Every "money recovered" figure anywhere in Phase 7 is scored by
  `reflow.outcome.oracle.RecoveryOracle`, a deterministic, hand-built model. No real Razorpay
  payment was chased, and no real customer paid or did not pay because of anything reported here.
- **What is measured is policy quality against a known-ground-truth world, not real-world
  rupees.** The oracle's probabilities are a stated, inspectable assumption this project made and
  disclosed, not a fact obtained from any external source. A reader who disagrees with the
  assumption can recompute every result under a different one; nothing here is hidden inside an
  opaque number.
- **The oracle exists because Razorpay's test mode exposes only a binary pass/fail toggle per
  payment, not a probability.** There is no sandbox surface that reports "a `card_declined`
  failure recovers 42% of the time if sent a fresh Payment Link immediately." A realistic,
  multi-reason outcome model cannot be *obtained* from the sandbox; it can only be *assumed*,
  honestly and on the record, or not built at all. This module is that honest assumption, built
  once, in the open.
- **Oracle probabilities derive from Razorpay's own vendored `Next Steps` remediation classes**
  (`reflow.taxonomy.remediation.RemediationClass`), the same classification `docs/design.md`
  ADR-0002 and ADR-0004 already built and justified from the vendored spreadsheet's own text --
  not invented per-reason-code numbers. Two free parameters per class (a no-action self-recovery
  floor, and a ceiling for the textbook-correct action), never per reason code, and never tuned
  after seeing a simulation result.
- **Results are reported across a three-point sensitivity band** (pessimistic / central /
  optimistic) precisely so no single assumed probability carries this project's conclusion. Every
  claim below is checked against whether it holds at every point in that band, not only at the
  central estimate, and is reported as holding or not holding accordingly.

## Headline comparison (central band)

| policy | money recovered (INR) | contacts sent | contacts / rupee recovered |
| --- | --- | --- | --- |
| do_nothing | 22,584,778 | 0 | 0.000000 |
| notify_all | 75,677,051 | 47,192 | 0.000624 |
| notify_all_once | 72,722,654 | 44,674 | 0.000614 |
| **reflow** | **71,874,179** | **33,691** | **0.000469** |

- reflow recovers **95.0%** of `notify_all`'s money (**98.8%** of the more realistic,
  single-shot `notify_all_once` baseline's money) while sending **28.6%** fewer contacts than
  `notify_all` (**24.6%** fewer than `notify_all_once`).
- 9,992 of reflow's escalatable candidate actions were suppressed by a guardrail before they ever
  reached a customer.
- reflow is **~25% cheaper per rupee recovered** than `notify_all` (0.000469 vs 0.000624
  contacts per rupee).

## Sensitivity-band findings (does the headline hold everywhere?)

| level | reflow / notify_all money | reflow / notify_all_once money | contact reduction vs notify_all | reflow cost/rupee vs notify_all | reflow beats do_nothing |
| --- | --- | --- | --- | --- | --- |
| pessimistic | 96.1% | **100.95%** | 28.9% fewer | 26.0% cheaper | yes |
| central | 95.0% | 98.83% | 28.6% fewer | 24.8% cheaper | yes |
| optimistic | 97.1% | 99.91% | 28.4% fewer | 26.2% cheaper | yes |

Every one of these findings holds at every point in the band. reflow **never** recovers more
absolute money than `notify_all` at any point in the band -- that comparison is reported as a
loss, not reframed, and stays a loss at every point checked. The same is **not** true of
`notify_all_once`, the more realistic single-shot chase baseline: at the pessimistic level,
reflow recovers **more** absolute money than `notify_all_once` (48,701,612 vs. 48,242,292
rupees, 100.95%), not merely a comparable share of it; only at central (98.83%) and optimistic
(99.91%) does reflow recover slightly less. The true range against `notify_all_once` is
98.8-101.0%, not the 98.2-98.8% previously (and wrongly) stated here -- that earlier figure was
asserted rather than derived from `docs/reports/phase7_simulation.json`, and in being wrong it
happened to hide a result in this project's own favour, which is exactly as much of an accuracy
failure as the reverse would be. What is robust across the whole plausible probability range is:
reflow always beats `do_nothing`; reflow recovers roughly 95-97% of `notify_all`'s rupees while
sending materially fewer contacts; against `notify_all_once` reflow is comparable-to-better,
never far behind and sometimes ahead; and reflow is always cheaper per rupee recovered than both
chase baselines, by a stable ~25-26%.

## What this means, stated plainly

**reflow does not maximise absolute recovery.** A naive agent that messages every failed customer
forever recovers more total rupees in every simulated world this project constructed, because it
never turns down a chase opportunity a guardrail would refuse. reflow's guardrails are designed to
say no -- to quiet hours, to a payment too small to justify another message, to a customer already
contacted too recently, to a rail known to be down, to a case that is a duplicate or already paid
-- and saying no sometimes means walking away from a payment that would, in fact, have come back.
The honest, and stronger, claim this project makes is: **comparable recovery at materially lower
customer-contact cost, robust across the whole plausible probability band.** That is a real
design trade-off with a real, measured cost (see the next section), not a euphemism for reflow
losing quietly.

## The measured cost of reflow's guardrails: recoveries walked away from

Every number above is an aggregate. This section answers a sharper question: of the contacts a
guardrail suppressed, how many were probably worth sending?

For every reflow decision where a guardrail changed an escalatable candidate action
(`recovery_link_now` / `recovery_link_backoff` / `switch_method` / `escalate_human`) into a
non-escalatable final action, a one-off, read-only analysis (built from existing public
`reflow` APIs, not a modification to `reflow.eval.simulate`) additionally scored the *same*
payment attempt's *same* deterministic oracle draw against the pre-guardrail candidate action --
the identical mechanism the closed-loop simulation already uses, since the oracle's draw is
shared across actions by design specifically so this counterfactual is well-defined and
monotonic (see `reflow.outcome.oracle` module docstring).

| level | guardrail-blocked events | would have recovered per oracle | orders affected | orders never recovered by any other path |
| --- | --- | --- | --- | --- |
| pessimistic | 10,148 | 968 (9.5%) | 967 | 937 |
| central | 9,992 | 1,552 (15.5%) | 1,548 | 1,487 |
| optimistic | 9,848 | 1,866 (18.9%) | 1,859 | 1,766 |

At the central estimate, **1,487 of 44,674 orders (3.3%)** never recovered by any path in the
simulation specifically because a guardrail redirected away from an action the same oracle says
would have worked. This is the concrete, measured price of reflow's lower contact volume -- named
and quantified, not folded into an aggregate and left implicit.

## What the system could not resolve, and why

This section is deliberately not a catch-all bucket. Each item below is a distinct, real
limitation with its own mechanism and its own citation.

1. **15 reason codes with genuinely ambiguous vendored text.** Tier 1's deterministic table
   (`reflow.diagnose.tier1`) cannot resolve `authorisation_declined_by_psp`, `card_not_enrolled`,
   `compliance_violation`, `credit_limit_inactive`, `gateway_technical_error`,
   `input_validation_failed`, `invalid_response_from_gateway`, `issuer_technical_error`,
   `mismatch_in_transaction_details`, `mobile_number_invalid`, `payment_method_not_enabled`,
   `server_error`, `transaction_daily_count_exceeded`, `transaction_daily_limit_exceeded`, and
   `upi_app_technical_error` -- either because one row's `Next Steps` text offers more than one
   remediation path, or because two rows for the same reason code disagree. An LLM makes a
   best-fit, cached, per-reason-code guess (ADR-0004); it cannot manufacture certainty the
   vendored source does not contain.
2. **Three catch-all reason codes whose true sub-cause Razorpay itself does not receive.**
   `card_declined` ("the exact reason in this case is not shared with Razorpay"),
   `payment_declined` ("not communicated to Razorpay"), and `payment_failed` ("no specific error
   code received from gateway") are, by Razorpay's own vendored documentation, opaque at the
   source. ADR-0002's opacity ablation measured directly that no clustering candidate recovers
   information here beyond `GROUP BY`, and ADR-0004 records why an LLM is no better positioned:
   it would confidently narrate a plausible sub-cause with no more evidence than a clustering
   algorithm had -- a worse failure mode than a classifier failing visibly.
3. **2 of the 15 ambiguous-reason diagnoses were independently flagged overconfident.** Phase 4's
   judge (a different model family, to avoid self-preference bias) rated `compliance_violation`
   and `transaction_daily_count_exceeded` "questionable": in both cases the vendored text offers a
   genuine second remediation branch (customer-vs-merchant contact; wait-vs-switch-instrument)
   that the diagnosis picked one side of at "high" confidence without surfacing the disjunction.
4. **4 of 113 sampled incident diagnoses were also flagged overconfident.**
   `067_card_IDFC FIRST Bank`, `016_card_Punjab National Bank`, `073_upi_IndusInd Bank`, and
   `098_card_Axis Bank` were rated "questionable" -- never "wrong" -- for assigning "high"
   confidence to a bank-outage hypothesis from as few as 3-6 correlated failures, more certainty
   than that much evidence supports. Separately, the judge's own output for `073_upi_IndusInd
   Bank` degenerated into dozens of repeated tokens -- a real generation-quality defect in the
   judge model itself, not the diagnosis under review, recorded rather than silently discarded.
5. **The escalation ladder gave up on 4 of 50,000 events in Phase 5's single-pass benchmark.**
   `AttemptCapGuardrail` explicitly stops chasing a payment past `attempt_cap=4` attempts rather
   than retrying forever; giving up is rare at this corpus's retry-chain depth but is an explicit,
   audited terminal state, not a silent fall-through. Phase 7's closed-loop simulation runs the
   identical `classify_ladder_terminal_state` logic per decision but its committed `PolicyOutcome`
   report does not re-surface this per-terminal-state breakdown -- a reporting gap in this phase's
   own output, honestly noted rather than implied to be covered.
6. **9,992 guardrail-suppressed contacts at the central estimate, 1,487 orders' worth of which
   never recovered by any other path** -- see the dedicated section above. This is the most
   consequential, and most precisely quantified, item on this list.
7. **`SWITCH_METHOD`'s restriction cannot be mechanically confirmed to render.** Razorpay's API
   accepts a method-restricted Payment Link creation request without error, but the create
   response echoes only `{"checkout": {"name": ""}}` and a subsequent fetch returns
   `options: null` -- confirming the restriction actually appears on the rendered checkout page
   would require opening the URL in a real browser, which is out of scope for this automated
   harness (ADR-0006, `BUILD_LOG.md` 2026-08-23).
8. **`DIFFERENT_INSTRUMENT`-classified reasons cannot get a true instrument-level block.**
   Razorpay's Payment Links API restricts by whole payment method (`options.checkout.method`),
   never by specific card, VPA, or other instrument (verified live 2026-08-23). A reason whose
   textbook fix is "use a different card" gets a generic `RECOVERY_LINK_NOW`, not an action that
   actually excludes the failing instrument, because no such API exists (ADR-0005).
9. **The committed audit trail is a bounded, 503-record sample, not the full corpus.** A full
   50,000-decision JSONL trail is tens of megabytes for no added demonstration value;
   `reflow.eval.execute.run_benchmark` supports the full trail (`audit_sample_size=None`) for a
   caller who wants it, but the committed `docs/reports/phase6_audit_trail.jsonl` is 500 leading
   chronological events plus a guaranteed first example of every guardrail block and final action
   (ADR-0006).
10. **1 of 8 correlatable detected incidents can never be corroborated against Razorpay's own
    Downtime API**, which only declares downtime for Card, Netbanking, and UPI. An incident
    detected on Wallet, Cardless EMI, or Emandate has no declaration shape to check against at
    all -- a structural, verified fact about the live API (ADR-0003), not a detector failure.
11. **No burst detector here has change-point memory.** `poisson_surprise`, the recommended
    detector, and the three alternatives benchmarked against it are all simple online statistics;
    a long-running outage inflates its own trailing rate estimate over time, visible empirically
    in right-skewed time-to-detect tails. A materially heavier regime-switching design would be
    needed to fix this, and this project's brief did not call for building one (ADR-0003).
12. **The recovery oracle assumes independence across an order's repeated attempts.** Each raw
    attempt is scored as an independent Bernoulli trial; recovery odds do not decay or improve
    across an order's own retry history beyond whatever the escalation ladder's action choice
    already implies. A real population would plausibly show diminishing returns as the
    easiest-to-recover customers resolve first. This is not modelled, because doing so would add a
    free decay-rate parameter with no grounding in the vendored taxonomy -- exactly what this
    oracle's whole design exists to avoid inventing (`reflow.outcome.oracle` module docstring).
13. **Quiet hours (21:00-09:00) is a configurable policy default, not a cited legal threshold.**
    This project verified live that Payment Links can restrict method and that the Payments API
    cannot retry; it did not verify a specific TRAI/TCCCPR time-of-day rule against a primary
    source, since the real rule depends on message classification and DLT registration status
    this corpus does not model. A merchant with a verified DLT-registered template should override
    the default (ADR-0005).
14. **Duplicate-`reference_id` recovery matches the SDK's exception description string.** The
    `razorpay` SDK exposes nothing more structured than a message string for this rejection; a
    future wording change on Razorpay's side could silently stop the catch-and-recover path from
    firing (ADR-0006).

## Model comparison and the shipped default

Full data, per-call detail, and provenance: `docs/reports/phase7_model_comparison.{json,md}`
(live run, `uv run --env-file .env python -m reflow.eval.model_compare`, seed `20260822`,
6 ambiguous + 6 deterministic-check reason codes sampled per model, 12 live calls per model, 36
calls total). Every model was called through the exact same
`reflow.diagnose.ambiguous.AmbiguousReasonDiagnoser` production Tier 2 already uses -- never a
reimplemented prompt -- so a difference below is attributable to the model.

| model | total cost | mean latency (s) | total reasoning tokens | first-attempt JSON valid | deterministic-tier agreement |
| --- | --- | --- | --- | --- | --- |
| **deepseek/deepseek-v4-flash** | **$0.000553** | 20.303 | 0 | **100.0%** | 100.0% |
| google/gemini-3.7-flash | $0.019636 | **6.707** | 3,136 | 91.7% | 100.0% |
| openai/gpt-oss-20b | $0.000956 | 15.599 | 4,599 | 66.7% | 100.0% |

**Pre-committed selection rule** (stated in `reflow.eval.model_compare`'s module docstring before
this live run was made, the same discipline ADR-0003's burst-detector selection used): among
models with zero call errors, pick the lowest total measured cost, tie-broken by lower mean
latency.

**By that rule, `deepseek/deepseek-v4-flash` wins**, at roughly 1/35th of `google/gemini-3.7-flash`'s
cost and roughly 1/2 of `openai/gpt-oss-20b`'s, with a perfect first-attempt JSON validity rate
(no truncated- or invalid-JSON retry ever fired) and perfect agreement with Tier 1's deterministic
table on every sampled already-resolved reason code. This mechanical pick agrees with this
project's fuller judgement (see ADR-0007): deepseek is the only one of the three verified live to
honour `reasoning_effort="none"` (`BUILD_LOG.md`, 2026-08-22/23), so it pays for a visible answer
only, never hidden reasoning tokens, on a call site (Tier 2 diagnosis) that is cached per reason
code and not on any customer-facing latency-critical path.

**`deepseek/deepseek-v4-flash` is the recommended, shipped default for Tier 2 diagnosis.**

**The one place the mechanical rule's pick is not the whole story, reported rather than hidden:**
deepseek had the *highest* mean latency of the three (20.3s, individual calls ranging 3.0-64.8s),
despite having reasoning disabled -- slower, and far more variable, than `google/gemini-3.7-flash`'s
6.7s mean (range 3.2-14.5s) despite that model spending 3,136 tokens on mandatory hidden reasoning.
Tier 2's diagnosis calls are cached per reason code and never sit on a customer-facing latency path
(ADR-0004), so this does not change the recommendation, but a deployment that ever put a Tier-2
-shaped call on a latency-sensitive path should re-weigh this, not assume deepseek is uniformly
faster because it is uniformly cheaper.

## Actual spend

- Phase 7 closed-loop simulation (`reflow.eval.simulate`): **$0.00** (reuses Phase 4's
  already-committed, already-paid-for diagnoses; makes no LLM call).
- Phase 7 model comparison (`reflow.eval.model_compare`): **$0.021145** (36 live calls across 3
  models).
- **Total Phase 7 LLM spend: $0.021145**, against a $0.50 cap -- roughly 4.2% of the cap used.
