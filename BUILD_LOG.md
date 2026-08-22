# Build log

A dated record of what actually broke, what the evidence was, and what changed as a result.
Written as it happened, not reconstructed afterwards.

---

## 2026-08-22

### Razorpay's own Python SDK discards the error taxonomy it documents

**What.** The design depends on `(code, source, step, reason)` as the root-cause label. The official
`razorpay` SDK parses the JSON error body and keeps only `error.description` on its exception classes.
`field`, `source`, `step`, `reason` and `metadata` are read and thrown away.

**Evidence.** Read `razorpay/errors.py` and the `request()` path in `razorpay/client.py` at v2.0.1
directly, rather than trusting the README. No exception class carries those attributes.

**Consequence.** SDK exceptions are unusable as a taxonomy source. Live failure signal has to come from
**webhook payloads**, which do preserve the fields. That in turn surfaced a second problem: webhooks use
`error_code` / `error_source` / `error_step` / `error_reason`, while the synchronous API error object
uses the bare names. `reflow.taxonomy.signal.FailureSignal` now normalises both into one model.

### No generic idempotency header exists

**What.** Planned to use an `Idempotency-Key` header on Payment Link creation.

**Evidence.** Razorpay supports idempotency on exactly three surfaces — `X-Transfer-Idempotency`,
`X-Refund-Idempotency`, `X-Payout-Idempotency`. Payment Links are not among them.

**Consequence.** Idempotency rebuilt on the Payment Link `reference_id` field, derived deterministically
from the payment id and capped at its documented 40-character limit.

### The SDK's retry does not cover rate limiting

**What.** Assumed `enable_retry` would handle 429s.

**Evidence.** It is off by default, and when enabled retries only `ConnectionError` and `Timeout`. Every
HTTP error status, 429 included, raises immediately on the first attempt.

**Consequence.** Own backoff-with-jitter required. No numeric rate limit is published for the Payments
API, so it has to be adaptive rather than tuned to a documented ceiling.

### A reasoning model spent its entire output budget thinking

**What.** Smoke-testing OpenRouter, `deepseek-v4-flash` returned `content: None` for a trivial prompt.

**Evidence.** `usage.completion_tokens_details.reasoning_tokens: 9` against a `max_tokens: 10` cap. The
model consumed the whole budget reasoning and had nothing left to emit.

**Consequence.** The diagnosis tier must budget for reasoning tokens or disable reasoning explicitly.
Separately, the model-comparison table has to report reasoning tokens as their own column, or the cheap
models' true cost will be understated.

### The central claim had a hole: GROUP BY does most of it

**What.** The plan's headline was "50,000 failures cluster into ~25 root causes." Razorpay's webhook
already carries a structured `error_reason`, so for ~110 of 114 codes the reason *is* the root cause.
A one-line `GROUP BY` reproduces most of the result without any clustering at all.

**Evidence.** Reading the taxonomy: only a handful of codes are genuinely coarse.

**Consequence.** Claim narrowed and sharpened. `GROUP BY (code, source, step, reason)` is now the
**primary path**, and clustering is scoped to catch-all codes only, where free text is the sole
discriminator. `GROUP BY` also becomes an explicit benchmarked baseline. Related framing error caught at
the same time: incident detection is temporal/entity correlation, not text clustering — Drain3 was never
going to solve it, and it is now a separate module.

### The vendored spreadsheet has real data defects

**What.** Razorpay's official error-reasons spreadsheet is not clean.

**Evidence.** 114 rows but 110 unique reason codes. `funds_blocked_by_mandate` and `psp_not_available`
are exact duplicates. `issuer_technical_error` and `payment_method_not_enabled` each appear twice with
**materially conflicting** remediation advice. Row 90's code is `psp_app_ not_available`, with an
embedded space. Two rows' `Next Steps` appear copy-pasted from unrelated rows and contradict their own
`Explanation`.

**Consequence.** Preserved verbatim and flagged rather than silently repaired — a parser that quietly
fixes its input is a parser you cannot trust. The conflicting and copy-pasted rows are recorded in the
ambiguous set, which is exactly the input the LLM routing tier is meant to handle.

### Smaller ones

- **pytest has no standalone `importmode` ini key.** The only supported route is
  `addopts = ["--import-mode=importlib"]`. Live docs contradicted the obvious guess.
- **`astral-sh/setup-uv` publishes no floating major tag** — only `v10.0.0` and `v10.0.1`, unlike
  `actions/checkout` which does maintain `v7`. Pinned to a full SHA, which is better practice anyway.
- **A mypy per-module override was silently inactive.** Without `tests/__init__.py`, mypy did not resolve
  test modules into the `tests` package, so the `tests.*` override never applied and mypy reported an
  unused section rather than an error. Silent misconfiguration, not a failure.
- **NPCI deprecated UPI Collect for new integrations on 2026-02-28**, before this project's build date.
  The corpus reflects a 95/5 Intent/Collect mix instead of treating them as equals.
- **`ty` false-positives on a deliberate frozen-model mutation.** A test mutates a frozen pydantic model
  to assert it raises `ValidationError`; `ty` reads that as a static read-only violation. Left as-is —
  `ty` is advisory precisely so a beta checker never drives a rewrite.
- **Per-method `step` vocabularies could not be independently verified.** Razorpay renders them as flow
  diagrams rather than extractable text. Used as documented and marked unverified in source.

---

## 2026-08-23

### Razorpay documents that it does not know the cause of its own catch-all failures

**What.** The corpus generates distinguishing free text for the latent sub-causes inside catch-all
reason codes, on the assumption that such text exists in production. For the most important catch-alls
it does not.

**Evidence.** Razorpay's own `Explanation` column, read from the vendored spreadsheet:
`card_declined` — "The exact reason in this case is **not shared with Razorpay**."
`payment_declined` — "The exact reason in this case is **not communicated to Razorpay**."
`payment_failed` — "**No specific error code received from gateway** in this case."

If Razorpay never receives the sub-cause, `error_description` cannot carry text that distinguishes one
sub-cause from another. A clustering result on our corpus would therefore be measuring recovery of
detail that, in production, is simply absent.

**Why this is worse than the earlier `GROUP BY` problem.** That one was fixed by scoping the claim. This
one is a flaw in the premise, and no amount of tuning the corpus fixes it — a richer corpus just makes
the artefact more convincing.

**Consequence.** Phase 2 runs an **opacity ablation**: the bake-off executes twice, once on the corpus
as generated and once with catch-all descriptions collapsed to generic reason-level text matching
Razorpay's documented behaviour. Implemented in the evaluation harness, not the corpus, so the
freeze-before-clustering guarantee is untouched.

The expected finding is that text clustering adds little precisely where Razorpay is opaque — which
makes temporal and entity correlation the substantive result rather than a side module. That is a
better answer than a clustering score: when the gateway will not tell you *why*, you infer it from
*when* and *where*, and you prove which approach earned its place by measuring both.

### The opacity ablation confirmed the expected finding — and found a worse one

**What.** Ran the full bake-off (`uv run python -m reflow.eval.clustering`, seed `20260822`, 50,000
events, richness 1/3/5, both arms). Full results at `docs/reports/phase2_clustering_bakeoff.{json,md}`.

**Evidence.** In the transparent arm, all three clusterers beat `GROUP BY` on the catch-all stratum by a
wide margin (e.g. template hashing and TF-IDF+HDBSCAN hit ARI 1.000 vs. `GROUP BY`'s 0.325 at richness
1). In the opaque arm — the condition Razorpay's own documentation says actually holds — template
hashing and TF-IDF+HDBSCAN collapsed to within ±0.005 of `GROUP BY`'s catch-all ARI/NMI/purity at every
richness level (statistical noise, not signal), and **Drain3 scored measurably worse than `GROUP BY`**
(ARI 0.311 vs. 0.325). Anticipated that clustering would add "little"; did not anticipate that one
candidate would be worse than the baseline it was meant to beat.

**Consequence.** ADR-0002 in `docs/design.md` records the decision: `GROUP BY` is the production
catch-all root-cause path; no clustering candidate is adopted. See that ADR for the full evidence,
per-candidate rejection reasons, and revisit conditions.

### The corpus's only true-outlier ground truth is structurally outside clustering's scope

**What.** The bake-off's noise/outlier-handling metric needs events flagged `is_outlier=True` to score
recall against. `PaymentEvent.is_outlier` is, by design (see its docstring), never `True` for a
catch-all reason — catch-all sub-causes are deliberately substantial, multi-cause clusters, not one-off
singletons. Since this phase's brief also scopes clustering to the catch-all stratum only, the primary
bake-off literally cannot exercise this metric: zero true outliers exist anywhere it looks.

**Evidence.** Confirmed empirically before writing any evaluation code: a 50,000-event corpus at this
seed has 36-37 true outliers, all in the narrow stratum, none in the catch-all stratum.

**Consequence.** Added `reflow.eval.clustering.run_noise_diagnostic`, a supplementary, explicitly
out-of-primary-scope measurement on an outlier-enriched sample of the *narrow* stratum, reported in its
own table rather than folded into the primary results. This is a real limitation of the corpus/brief
combination, not something to route around silently: it is stated in the generated report's provenance
notes and in this log rather than only in code comments (of which there are none, per project rule).

### `sklearn.cluster.HDBSCAN` with `metric="cosine"` is O(n^2) by construction

**What.** Assumed TF-IDF + HDBSCAN would scale to "50,000 events" the same way the other candidates do.

**Evidence.** The installed `HDBSCAN`'s own docstring: cosine similarity has no KD-tree/ball-tree
support, so fitting resolves to the `"brute"` algorithm, i.e. a full pairwise distance computation.
Empirically fine at the catch-all stratum's actual observed size (~8,000 events, 2-3 seconds) but a
literal 50,000-event catch-all stratum would require a dense ~2.5-billion-entry distance matrix.

**Consequence.** Reported honestly rather than silently subsampled away: the catch-all stratum's actual
size at this corpus's default 50,000 events happens to stay tractable, so no subsampling was needed for
the primary bake-off, but this would not hold at a much larger catch-all share or corpus size. Disclosed
in every generated report's provenance notes.

### `ty` flags a type bug inside `drain3` itself, not in this repository's code

**What.** `uv run ty check .` reports `TemplateMiner.__init__`'s `persistence_handler=None` argument as
an `invalid-argument-type` against the parameter `persistence_handler: PersistenceHandler = None`.

**Evidence.** Read `drain3/template_miner.py` directly: the library's own signature declares the
parameter as `PersistenceHandler` (not `PersistenceHandler | None`) while defaulting it to `None` and
documenting `None` as "no persistence is applied" — an imprecise annotation in the third-party library,
not a bug in `reflow.cluster.drain3_clusterer`, which uses the documented, intended calling convention.

**Consequence.** Left as-is, per ADR-0001: `ty` is advisory only and never drives a rewrite of correct
code to satisfy a third-party library's own imprecise type hint.

### The clustering bake-off's transparent-arm win turned out to be an identity

**What.** Phase 2 reported that template hashing and TF-IDF+HDBSCAN recovered all 32 latent
sub-causes perfectly at richness 1. Read at face value that is an impressive result. It is not a
result at all.

**Evidence.** Independent verification outside the test suite counted the distinct masked strings the
clusterers actually receive: exactly **32 at richness 1** for 32 sub-causes, and exactly **160 at
richness 5** for the same 32 sub-causes at five wordings each. Template hashing groups identical
strings by definition, so at richness 1 its output is a bijection with ground truth. At richness 5 it
emitted exactly 160 clusters — one per distinct string. Drain3 emitted 153.

**Consequence.** None of the three candidates merge paraphrases of a single cause; they partition
surface forms. The apparent degradation from richness 1 to 5 is not a failure to generalise, because
none of them was generalising. Their transparent-arm advantage exists only because the generator made
surface form a proxy for sub-cause, which is an artefact of synthesis. ADR-0002 now says so explicitly
rather than letting a 1.000 stand unqualified.

**Why it mattered to catch.** An unflagged perfect score is the first thing a reviewer would probe,
and "we did not notice it was definitional" is a much worse answer than not having run the experiment.

### The opacity control was verified valid, not assumed

**What.** The whole negative result rests on the opaque arm genuinely removing sub-cause signal. If it
leaked, the conclusion would be unsupported.

**Evidence.** Checked directly: under opacity, masked text is byte-identical for every
`(reason, method)` pair — 24 distinct strings across 34 keys, zero violations, at both richness 1 and
5 — while 33 of those 34 keys contain more than one sub-cause. There is provably nothing for any
algorithm to recover.

**Consequence.** The finding that clustering matches `GROUP BY` under opacity is structural, not a
measurement artefact. Any candidate scoring above `GROUP BY` there would have indicated leakage; none
did, and Drain3 scored below it.
