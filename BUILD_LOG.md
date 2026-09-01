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

### CI went red on 3.13 only, and the matrix is the reason we knew

**What.** Phase 2's PR passed every gate locally and passed CI on Python 3.11, then failed on 3.13:

```
.venv/lib/python3.13/site-packages/numpy/__init__.pyi:737: error:
Type statement is only supported in Python 3.12 and greater  [syntax]
```

**Evidence.** Reproduced locally with `uv run --python 3.13 mypy .`. The cause is a version skew the
universal lockfile resolves differently per interpreter: **numpy 2.4.6 on 3.11, numpy 2.5.2 on 3.13**.
The newer stubs use PEP 695 `type` statements, and `[tool.mypy] python_version = "3.11"` told mypy to
parse everything — including third-party stubs — as 3.11, where that syntax does not exist. Nothing in
our own code was wrong.

**Consequence.** Removed the pinned `python_version` so mypy analyses under whichever interpreter it is
running on, which is the correct semantics for a version matrix: the 3.11 job checks 3.11, the 3.13 job
checks 3.13. Pinning it meant the 3.13 job was never really checking 3.13. Also added an explicit
`exclude` for `.venv`. Verified `mypy` and the full suite green under both interpreters before pushing.

**Why it is worth recording.** A single-version CI would have shipped this silently, and the repo's
whole promise is that a reviewer can clone it and have everything work. This is the matrix paying for
itself on its first real disagreement.

### Gemini 3.7 Flash cannot turn reasoning off, and it changes the model economics

**What.** The plan named `google/gemini-3.7-flash` as the shipped default for the diagnosis tier, on the
grounds that it is the recognisable, credible choice. Smoke-testing structured output before Phase 4
showed that assumption was expensive.

**Evidence.** Requesting `reasoning: {"enabled": false}` returns
`400 "Reasoning is mandatory for this endpoint and cannot be disabled."` Left enabled, a single
one-sentence diagnosis consumed **364 of 385 completion tokens on reasoning**, cost $0.00077, and still
truncated the JSON mid-object at `max_tokens: 400`. The same request against
`deepseek/deepseek-v4-flash` with reasoning disabled returned complete, valid structured output in 330
tokens for **$0.0000378 — roughly 20x cheaper**.

**Consequence.** No default is being pre-committed. The client stays provider-agnostic with the model
selected by config, and the Phase 7 benchmark picks the default on evidence, the same way the clustering
bake-off did. Two hard constraints fall out for Phase 4: `max_tokens` must be generous enough to survive
reasoning overhead on models that mandate it, and truncated JSON must be treated as a retryable failure
rather than a crash. `json_schema` structured output itself works on both models, so the diagnosis
contract is safe either way.

### The winning burst detector won because the test split was quieter, not because it was better

**What.** Phase 3's pre-committed selection rule was highest test-split F1. By that rule
`fixed_threshold` won outright with F1 1.000, against `poisson_surprise` at 0.640.

**Evidence.** Its train-split precision collapses to 0.264 — 159 detections against 42 true windows.
Independent verification found the mechanism, and it is systematic rather than small-sample chance.
Both splits cover the **same 720 hours across the same 72 `(method, bank)` entities**, but the split
assigns 42 of 50 windows and about 80% of background traffic to train, leaving test **four times
sparser**: 55.7 vs 13.8 events per hour. Per-bucket counts follow — train p90=2, p99=17; test p90=1,
p99=4 — against a fixed threshold of **3**. On train that sits below the noise floor; on test it sits
above it.

**Consequence.** An absolute count threshold is scale-dependent by construction: its accuracy tracks
merchant volume rather than anything it detects, and it would degrade on any merchant busier than the
test slice. `poisson_surprise` normalises against a trailing rate, is scale-invariant, and its two
splits agree to 0.022 — so it is recommended for production **despite losing the mechanical rule**.
ADR-0003 records both the rule's verdict and the reason for overriding it.

**Why it is worth recording.** A pre-committed selection rule is supposed to stop you rationalising
after the fact. Here the rule itself was flawed, because selecting on an 8-window test split has almost
no statistical power. Following it blindly would have shipped a detector that fails on busy merchants;
overriding it silently would have made the pre-commitment theatre. Reporting both is the only honest
option.

### The official `openrouter` SDK cannot express OpenRouter's own documented `reasoning.enabled` field

**What.** Phase 4's client (`reflow.llm`) needs to disable reasoning for models that support it,
reproducing the `reasoning: {"enabled": false}` behaviour this build log already recorded live against
raw HTTP. The installed SDK (`openrouter==0.10.8`) does not let it.

**Evidence.** Read directly from `.venv`: `openrouter.components.chatrequest.ChatRequestReasoning`, the
type the SDK's `Chat.send()`/`send_async()` actually validate a `reasoning=` argument against for the
Chat Completions endpoint, declares only `effort` and `summary` -- not `enabled`, `max_tokens`, or
`exclude`, all of which OpenRouter's own documentation describes for the same wire parameter. The SDK's
base Pydantic model config does not set `extra="forbid"`, so passing `{"enabled": False}` through the
typed `reasoning=` argument is not rejected -- it is silently dropped, which would make a caller's
explicit intent to disable reasoning silently no-op rather than fail loudly.

**Consequence.** `reflow.llm.LlmClient` uses the SDK's separate, fully-typed `reasoning_effort`
top-level shorthand instead (`"none"`, documented by OpenRouter as disabling reasoning entirely for
effort-controllable models). Verified live via a committed VCR cassette
(`tests/llm/cassettes/test_client_vcr/`) that this reproduces both halves of the earlier finding exactly:
`deepseek/deepseek-v4-flash` honours it and returns valid structured JSON; `google/gemini-3.7-flash`
rejects it with the same "Reasoning is mandatory for this endpoint and cannot be disabled." refusal,
surfaced as a typed `ReasoningMandatoryError`, never a crash.

### Reasoning-mandatory is not a Gemini-only quirk -- it crashed the first live Phase 4 benchmark run

**What.** `openai/gpt-oss-20b` was chosen as the LLM-as-a-judge model specifically because it is a
different model family from the Tier 2 model under test (`deepseek/deepseek-v4-flash`), to avoid
self-preference bias. The first full live run of `reflow.eval.diagnose` crashed partway through with
`ReasoningMandatoryError` when the judge phase started, after already spending real money on 15
ambiguous-reason and 30 incident diagnoses that were then discarded because the run never reached the
point of writing a report.

**Evidence.** `openai/gpt-oss-20b` rejects `reasoning_effort="none"` with the identical "Reasoning is
mandatory for this endpoint and cannot be disabled." message `google/gemini-3.7-flash` gives. This was
not anticipated: its `supported_parameters` (from a live `models.list()` call) lists `reasoning_effort`
as supported, which says nothing about whether every value of that parameter -- including `"none"` -- is
honoured.

**Consequence.** `reasoning_effort="none"` is now requested only for the Tier 2 model, which has been
live-verified via a committed cassette to actually honour it; the judge client is left at its provider
-default reasoning behaviour with a generous `max_completion_tokens=1500` instead. More generally: this
project now treats "does this model actually honour a disabled-reasoning request" as a per-model fact
requiring its own live verification, never assumed from a parameter merely being listed as supported.
`reflow.eval.diagnose.run_benchmark` also gained an optional `progress` callback and `main()` now runs
Python unbuffered, so a long live run's progress -- and a crash like this one -- is visible in real time
rather than silently buffered until process exit.

### A capped benchmark run would have silently understated the production cost projection

**What.** To bound wall-clock time and spend on early live runs, `reflow.eval.diagnose.run_benchmark`
gained a `max_incident_diagnoses` cap. The first version of the cost-projection math computed "cost per
100,000 events" directly from the cost of the incidents actually diagnosed under that cap, without
accounting for the incidents detected but not diagnosed.

**Evidence.** At a 30-incident cap against 113 incidents genuinely detected in the same 50,000-event
corpus, the projected per-100k-events cost was computed from only 30 calls' worth of spend -- silently
understating the true production cost by roughly 3.8x had the cap ever shipped in a real projection.

**Consequence.** `CostSummary` now separately tracks `n_incidents_detected` (before any cap) and
`n_incidents_diagnosed` (after), and the cost projection extrapolates the *average* observed cost per
diagnosed incident across every *detected* incident, not only the ones actually paid for. The final
report was generated with no cap at all (all 113 detected incidents diagnosed for real), so this
particular run's numbers were never actually understated -- but the bug would have silently mis-projected
cost on any future capped run had it shipped uncorrected, which is exactly the kind of thing a single
successful run does not surface on its own.

### The taxonomy's own "14 ambiguous reasons" undercounts by one at the granularity a real event carries

**What.** `reflow.taxonomy.remediation`'s `CoverageReport.ambiguous` lists 14 rows it could not resolve
to a single remediation class. A real `PaymentEvent.error_reason` carries no row index, only the bare
reason code, and Phase 4's Tier 1/Tier 2 boundary has to be drawn at that granularity.

**Evidence.** `payment_method_not_enabled` appears twice in the vendored spreadsheet. Neither row is
individually ambiguous (one resolves cleanly to `merchant_contact_razorpay`, the other to
`merchant_action`), so neither is in the taxonomy module's own 14-row ambiguous list -- but the two rows
disagree with each other, which is invisible to a per-row ambiguity check and only surfaces when
reconciling by reason code, exactly what `reflow.diagnose.tier1.build_deterministic_table` does.

**Consequence.** Phase 4's Tier 2 ambiguous-reason cache holds 15 entries, not 14: one more live LLM
call, ever, than the taxonomy module's own framing would suggest. Reported plainly in
`reflow.diagnose.tier1`'s module docstring and in `docs/reports/phase4_diagnosis.md` rather than rounded
to match the phase brief's "14 ambiguous reasons" framing.

### `uv run --python 3.13` fails with a Windows file-lock error when another `uv run` holds the same `.venv`

**What.** Running `uv run --python 3.13 mypy .` while a separate, still-running `uv run --env-file .env
python -m reflow.eval.diagnose` background process was live against the same project failed immediately.

**Evidence.** `error: failed to remove directory '...\.venv\Scripts': Access is denied. (os error 5)` --
`uv` attempts to rebuild/relink `.venv` for the requested interpreter and cannot, because the concurrent
process still has files inside it open on Windows (POSIX allows removing an open file; Windows does not).

**Consequence.** Not a code bug; a sequencing constraint specific to this OS. The two `uv run` invocations
against one `.venv` must not overlap here -- the 3.13 verification pass was run only after every live
benchmark process had fully exited, not concurrently with one.

### Payment Links restrict which method is offered, not which instrument

**What.** Deliverable 1's `SWITCH_METHOD` action assumes a Payment Link can be restricted away from a
specific payment method. Needed to verify this rather than assume it, and separately needed to know
whether an instrument-level restriction (e.g. "not this card") exists, since `DIFFERENT_INSTRUMENT`
-classified reasons would otherwise need their own enforceable action.

**Evidence.** Fetched live, 2026-08-23:
<https://razorpay.com/docs/api/payments/payment-links/customise-payment-methods/> documents exactly
four boolean toggles nested under `options.checkout.method` -- `card`, `netbanking`, `upi`, `wallet` --
that show or hide a payment method on the link's checkout. No parameter names a specific card, VPA, or
other instrument. Separately, `create-standard`'s own top-level request parameters (fetched live the
same day) do not include any method-restriction field at all -- the mechanism lives under the separate
`options.checkout` customisation layer, not the base creation call.

**Consequence.** `SWITCH_METHOD` is real and enforceable (disable the method that just failed).
`DIFFERENT_INSTRUMENT`-classified reasons map to a plain `RECOVERY_LINK_NOW` instead of a fabricated
"switch instrument" action the API cannot honour. Recorded in `docs/design.md` ADR-0005 and in
`reflow.policy.actions`'s module docstring.

### The per-customer contact cap fires zero times on the 50,000-event corpus, and it is not a bug

**What.** Phase 5's `ContactCapGuardrail` (default: block a 4th chase contact to one customer within a
rolling 24-hour window) fired exactly 0 times across the full corpus, while `CooldownGuardrail` (a
4-hour minimum gap between contacts) fired 428 times. A zero-fire guardrail is the kind of thing that
looks, at a glance, like a wiring bug.

**Evidence.** Checked directly, independent of the guardrail's own code: only 232 of 15,755 customers in
the generated corpus ever have three or more raw failed-payment events within *any* rolling 24-hour
window at all (median customer sees 3.17 events total, spread across the full 30-day generation period).
`CooldownGuardrail`'s tighter, per-contact 4-hour gate already suppresses same-day recontacting
aggressively enough that the daily cap of 3 never has anything left to block at this corpus's realised
customer-visit density.

**Consequence.** Reported as a genuine, investigated finding in `docs/design.md` ADR-0005 rather than
quietly tuning the default cap downward to manufacture a non-zero number -- per this project's first
governing principle, the finding is reported, not the code fitted to a more flattering result.
`tests/policy/test_guardrails.py` exercises `ContactCapGuardrail`'s blocking branch directly with a
synthetic context, so the guardrail's correctness does not depend on this corpus ever reaching it.

### Two research passes appeared to contradict each other on Payment Link method restriction; both were right

**What.** An early research pass concluded that restricting a Payment Link to one payment method is done
via `options.checkout.config.display.blocks.*.instruments` with `show_default_blocks: false`, and that
"there is no flat `options.checkout.method` field." Phase 5 concluded the opposite — that
`options.checkout.method` booleans are exactly how it works. `SWITCH_METHOD` depends on which is true.

**Evidence.** The Create Payment Link reference does not document `options` as a request parameter at
all; it links out to **two separate pages**:
- `customise-payment-methods/` — *Options and **Method** Parameters*: show or hide whole payment
  methods via `options.checkout.method`.
- `customise-options-config/` — *Options and **Config** Parameters*: granular restriction by card
  network, issuer, BIN and card type.

**Consequence.** Both findings were accurate; each pass had read one page. These are different features
at different granularity, not competing accounts of one feature. `SWITCH_METHOD` needs whole-method
switching, so it uses `options.checkout.method`. The config/blocks mechanism is the right tool only if
instrument-level restriction is ever needed, which the action set does not require.

**Why it is worth recording.** Two sources agreeing is weak evidence; two sources disagreeing is a
prompt to go read the primary reference rather than to pick a side. Had this been resolved by trusting
the more recent agent, the reasoning would have been right by luck. It also means Phase 6 implements
against a verified shape instead of a plausible one.

### A live Razorpay credential leaked through a dataclass's default `repr` in an uncaught traceback

**What.** While recording Phase 6's live-verification cassettes, one test (`notify_email`) hit a real
rate limit and raised uncaught. Pytest's traceback printer shows every local variable's `repr()` for the
failing frame, and `RazorpayGateway` was a plain `@dataclass` with no `repr=False` on `key_id`/
`key_secret` -- so the traceback printed both the real test-mode key id and key secret in plain text into
this session's tool output.

**Evidence.** The traceback line read `self = RazorpayGateway(key_id='...', key_secret='...', ...)` with
both fields fully populated. Confirmed by inspecting `RazorpayGateway`'s dataclass field declarations
directly: neither credential field excluded itself from `repr`.

**Consequence.** Both `key_secret` fixed immediately (`field(repr=False)`) in
`reflow.execute.gateway.RazorpayGateway`, and, on the same principle, `reflow.llm.config.LlmConfig.api_key`
(a pre-existing Phase 4 field with the identical latent exposure, never actually triggered before now) --
fixed defensively rather than left as a known-but-unexercised risk. Regression tests assert `repr()` never
contains either secret (`tests/execute/test_gateway.py::test_gateway_repr_never_exposes_the_key_secret`,
`tests/llm/test_config.py::test_llm_config_repr_never_exposes_the_api_key`). The exposed key is a
Razorpay **test-mode** credential (per Razorpay's own model, test-mode entities and credentials are
entirely separate from live and move no real money), so this is not a live-payments exposure, but it is a
real credential leak and the test-mode key involved should still be rotated in the Razorpay dashboard as a
precaution; this report does not repeat the value anywhere.

**Why it matters.** This is exactly the failure mode CLAUDE.md's "never echo a value" rule exists to
prevent, and it happened through a code path (an uncaught exception's default object `repr`) that has
nothing to do with logging or printing credentials on purpose -- a reminder that credential-bearing
dataclasses need `repr=False` on the sensitive field by construction, not only "don't print it" discipline
at every call site.

### Razorpay's Payment Link `reference_id` is a uniqueness constraint, not a Stripe-style idempotent replay

**What.** The plan assumed a deterministic `reference_id` alone would behave like a conventional
idempotency key: retry with the same key, get the same response back.

**Evidence.** Verified live, 2026-08-23: creating a second Payment Link with an already-used
`reference_id` raises `razorpay.errors.BadRequestError`: `"payment link with given reference_id: <id>
already exists. Please create a payment link with a different reference_id"`. It does not return the
original link. Also verified live the same session: `GET /v1/payment_links?reference_id=<id>`
(`razorpay.Client.payment_link.all({"reference_id": ...})`) does support this exact filter, and its
response is `{"payment_links": [...]}` -- a different envelope shape than the generic
`{"count": ..., "items": [...]}` most other Razorpay list endpoints use, confirmed by reading the actual
response rather than assumed from the pattern other endpoints follow.

**Consequence.** `reflow.execute.gateway.RazorpayGateway.create_payment_link` implements catch-and-recover:
on the specific duplicate-`reference_id` rejection, it looks the existing link up via the `reference_id`
filter and returns it (`GatewayCallResult.recovered_existing=True`) rather than treating the rejection as
a failure. Recorded as ADR-0006 in `docs/design.md`. `tests/execute/test_gateway_live.py::
test_duplicate_reference_id_is_recovered_not_duplicated` drives this exact path against the real API.

### The SDK's error-code classification cannot distinguish a genuine bad request from a live rate limit

**What.** While probing the API by hand (three rapid sequential Payment Link calls), a real rate limit
was tripped organically, not manufactured.

**Evidence.** The SDK raised `razorpay.errors.BadRequestError: Too many requests` -- the identical
exception class and JSON `error.code` (`BAD_REQUEST_ERROR`) a genuine validation error also raises,
confirmed by reading `razorpay/client.py`'s `request()` method directly: it classifies purely off
`error.code`, never the HTTP status. Re-confirmed with transport-level capture during cassette recording
(`tests/execute/cassettes/test_gateway_live/test_notify_payment_link_email_live.yaml`'s first, later
-replaced interaction recorded the real HTTP status: 429).

**Consequence.** `reflow.execute.gateway.RazorpayGateway` never branches on SDK exception type for
retry decisions; it branches on the transport-captured real HTTP status code
(`reflow.execute.transport.build_capturing_session`), which is the only thing that actually distinguishes
the two cases. Recorded as part of ADR-0006.

### `vcrpy` needed `decode_compressed_response=True`, or every Razorpay cassette body would be an unreadable gzip blob

**What.** The first cassette recorded without this option stored its response body as `!!binary |`
base64-encoded gzip data (the same shape already seen in `tests/llm/cassettes/`), which is both
unreadable for the "verify by reading each committed cassette" requirement and unparseable by a plain
`json.loads` in `reflow.eval.execute._extract_cassette_interactions`.

**Evidence.** Read `vcr/config.py` directly: `decode_compressed_response` (default `False`) is a real,
supported option that decodes the response body before it is ever written to the cassette.

**Consequence.** `tests/execute/conftest.py`'s `vcr_config` fixture sets it explicitly. Every cassette
under `tests/execute/cassettes/test_gateway_live/` stores its response bodies as plain, human-readable
JSON text, verified by reading each one directly.

### Method-restriction acceptance cannot be confirmed from the API's own responses alone

**What.** After live-verifying (2026-08-23, `docs/design.md`'s Phase 5 ADR) that `options.checkout.method`
is the documented mechanism for restricting a Payment Link's payment methods, this phase tried to also
verify mechanically, via the API, that a restriction actually took effect.

**Evidence.** A Payment Link created with `options.checkout.method.upi=false` returned a create response
whose `options` field contained only `{"checkout": {"name": ""}}` -- no echo of the `method` restriction
at all -- and a subsequent `fetch` of the same link returned `options: null` entirely.

**Consequence.** This project cannot claim, from API responses alone, that a method restriction visibly
took effect on the rendered checkout page -- that would require opening the real checkout URL in a
browser, which is out of scope for this automated harness. What is verified is narrower and stated
plainly: Razorpay's API accepts the documented request shape without error
(`tests/execute/test_gateway_live.py::test_create_method_restricted_payment_link_live`), not that the
restriction is confirmed to render. This gap is disclosed here and in `docs/reports/phase6_execution.md`
rather than overclaimed.

### `ty` flags `razorpay.Client.payment_link` as unresolved, for the same reason it already flags `drain3`

**What.** `uv run ty check .` reports four `unresolved-attribute` findings against
`self._client.payment_link` in `reflow.execute.gateway`.

**Evidence.** Read `razorpay/client.py` directly: every resource (`payment_link`, `payment`, `order`, ...)
is attached with `setattr(self, name, Klass(self))` inside `Client.__init__`, driven by a
`RESOURCE_CLASSES` dict built from module introspection at import time -- never declared as a static
class-level attribute or in a stub. `ty`'s static analysis has no way to see an attribute assigned this
dynamically, the same class of limitation already recorded in this log for `drain3.TemplateMiner`'s
`persistence_handler` parameter.

**Consequence.** Left as-is, per ADR-0001: `ty` is advisory only and never drives a rewrite of correct
code (verified against the installed SDK's real, intended calling convention -- `Client(session=...,
auth=...)` then `.payment_link.create(...)`, exactly as `razorpay`'s own README and every other resource
in this codebase's dependency tree is used) to satisfy a third-party library's own dynamically-typed
shape. `mypy` -- the blocking gate -- has no issue here at all, since `razorpay.*` is listed under
`ignore_missing_imports` in `pyproject.toml`, which is the correct treatment for an unstubbed dependency.

### A live credential printed itself into a traceback

**What.** `RazorpayGateway` was a plain dataclass holding `key_id` and `key_secret`. An uncaught
exception during development produced a pytest traceback that rendered the dataclass `repr`, printing a
live Razorpay test-mode secret in plain text.

**Evidence.** Python's generated `__repr__` includes every field by default. Nothing in the code was
"logging a secret" — the exposure came free with the dataclass.

**Consequence.** `field(repr=False)` on `key_secret`, and defensively on `reflow.llm.config.LlmConfig.api_key`,
which carried the identical latent exposure from Phase 4 and had simply never been triggered. Regression
tests assert both. Verified afterwards: the credential appears nowhere in the working tree and nowhere in
git history, and the whole suite passes with every credential unset.

**Why it is worth recording.** The dangerous ones are not the secrets you print, they are the ones a
default `__repr__` prints for you when something else goes wrong. Any dataclass holding a credential
needs `repr=False` at the moment it is written, not after an exception finds it. This was a test-mode
key with no money at risk, and it should still be rotated.

### reference_id is not an idempotency key, and finding that out required trying it

**What.** The design used a deterministic Payment Link `reference_id` as an idempotency key, on the
assumption that resubmitting one would return the original link — Stripe-style.

**Evidence.** Live test-mode call: Razorpay **rejects** the second request outright with
`"...already exists. Please create a payment link with a different reference_id"`. It does not replay.

**Consequence.** A catch-and-recover path instead: on that specific rejection, fetch the existing link
rather than treating it as failure. Verified live and committed as a cassette. Recorded in ADR-0006 so
the distinction between "idempotent" and "unique-constrained" is explicit.

### The SDK cannot tell a rate limit from a bad request

**What.** Adaptive backoff needs to distinguish 429 from 400. Both surface identically.

**Evidence.** Discovered by organically tripping a real 429 while probing the API. The SDK raises
`BadRequestError` with `code=BAD_REQUEST_ERROR` for both; only the transport-level HTTP status
distinguishes them, and the SDK discards that too.

**Consequence.** Backoff keys off the transport-captured status code, not the exception type. This is
the second distinct consequence of the same root cause recorded earlier: the SDK parses rich error
information and throws it away.

### Two smaller live findings

- **`payment_link.all()` returns `{"payment_links": [...]}`**, not the generic `{"count", "items"}`
  envelope Razorpay uses for other collections. Confirmed live rather than assumed.
- **`SWITCH_METHOD`'s restriction cannot be mechanically proven to render.** The create response echoes
  only `{"checkout": {"name": ""}}` and fetch returns `options: null`. The API accepts the request, but
  confirming the checkout page visibly restricts methods would need a real browser. Disclosed rather
  than claimed.

---

## 2026-09-01

### The naive spam baseline recovers more absolute money than reflow, at every point in the sensitivity band

**What.** Phase 7's closed-loop simulation (`reflow.eval.simulate`) was expected to show reflow winning
on some money-recovered comparison. It does not. `notify_all` -- message every failed customer forever,
no guardrail of any kind -- recovers more absolute rupees than reflow at all three sensitivity levels:
96.1% (pessimistic), 95.0% (central), 97.1% (optimistic) of `notify_all`'s money is the best reflow ever
achieves.

**Evidence.** Full results: `docs/reports/phase7_simulation.{json,md}`. Central band: `notify_all`
recovers ₹75,677,051 with 47,192 contacts; reflow recovers ₹71,874,179 (95.0%) with 33,691 contacts
(28.6% fewer) and 9,992 guardrail-prevented contacts. This holds at every point in the band, not only the
central estimate -- it was checked at all three specifically so a single favourable probability could not
be responsible for the result either way.

**Consequence.** Reported as the finding, per this project's first governing principle -- not reframed,
not re-scoped, not re-run with different guardrail defaults until reflow wins. The honest, and still
substantive, claim is comparable recovery (95-97% of `notify_all`'s money, 98%+ of the more realistic
`notify_all_once` baseline's money) at materially lower contact cost (28%+ fewer contacts, ~25% cheaper
per rupee recovered), robust across the whole band. `docs/design.md` ADR-0007 records this in full,
including why a guardrail-bounded policy losing on absolute money is the correct design, not an
embarrassing result to explain away.

### The guardrails' cost is a real, non-zero number of foregone recoveries, and it was worth measuring exactly

**What.** reflow's aggregate guardrail-prevented-contact count (9,992 at the central estimate) says
guardrails suppressed a lot of chase attempts, but says nothing about how many of those would actually
have recovered money. Left unmeasured, this is a plausible-sounding but unquantified cost.

**Evidence.** A one-off, read-only analysis (built from existing public `reflow.outcome.oracle` and
`reflow.policy` APIs, not a change to `reflow.eval.simulate`) scored every guardrail-blocked escalatable
candidate action against the same payment attempt's same deterministic oracle draw used for the actual
decision -- well-defined and monotonic by the oracle's own design (`reflow.outcome.oracle` module
docstring: a fixed draw shared across actions means a strictly more effective action can never recover
less often). At the central estimate: 1,552 of 9,992 guardrail-blocked events (15.5%) would have
recovered under the pre-guardrail action per the same oracle; 1,487 of 44,674 orders (3.3%) never
recovered by any other path in the simulation as a result.

**Consequence.** This number is now the concrete, cited cost of reflow's lower contact volume in
`docs/reports/phase7_evaluation.md` and `docs/design.md` ADR-0007, rather than a hand-waved "guardrails
have some cost." Recorded as a candidate for promotion into `reflow.eval.simulate` proper (with its own
tests) in a future phase, since this run computed it as an ad hoc script rather than a committed,
regression-tested measurement.

### The cheapest model was not the fastest one, and it was not close

**What.** Phase 7's live, three-model comparison (`reflow.eval.model_compare`) was expected to confirm
`deepseek/deepseek-v4-flash`'s cost advantage, already documented 2026-08-22/23 (~20x cheaper than a
reasoning-mandatory model on a single smoke-test call). It did, more starkly than expected (~35x cheaper
than `google/gemini-3.7-flash` over 12 real calls) -- but it also surfaced something not previously
measured: deepseek had the *highest* mean latency of the three models compared (20.3s), despite reasoning
being disabled, with individual calls ranging from 3.0s to 64.8 seconds.

**Evidence.** `docs/reports/phase7_model_comparison.{json,md}`, live run, 36 calls across
`deepseek/deepseek-v4-flash`, `google/gemini-3.7-flash`, and `openai/gpt-oss-20b`. `deepseek/deepseek-v4-flash`:
$0.000553 total cost, 20.303s mean latency, 100% first-attempt JSON validity. `google/gemini-3.7-flash`:
$0.019636 total cost, 6.707s mean latency (the fastest and tightest of the three), despite 3,136 tokens
spent on mandatory hidden reasoning across the 12 calls.

**Consequence.** `deepseek/deepseek-v4-flash` is still adopted as Tier 2's shipped default (ADR-0007):
it is the only one of the three verified live to honour `reasoning_effort="none"`, has a perfect
first-attempt JSON validity rate, and Tier 2's calls are cached per reason code, never on a
customer-facing latency path. But "cheap implies fast" is now known, measured, and stated to be false for
this model on this endpoint, and a future call site that is latency-sensitive should re-measure rather
than assume otherwise.

### All three compared models agreed perfectly with Tier 1's deterministic table, on reasons Tier 1 never sends them

**What.** Phase 7's model comparison deliberately asked each candidate model to diagnose a small sample
of reason codes Tier 1 already resolves deterministically (never sent to an LLM in production), purely
to get a ground-truth-backed agreement number distinct from the judge's plausibility-only endorsement
rate. All three models -- including the two mandatory-reasoning ones -- agreed with Tier 1's known-correct
answer on all 6 sampled deterministic reason codes, every time.

**Evidence.** `docs/reports/phase7_model_comparison.json`, `deterministic_agreement_rate: 1.0` for
`deepseek/deepseek-v4-flash`, `google/gemini-3.7-flash`, and `openai/gpt-oss-20b` alike.

**Consequence.** Independent corroboration, not assumed, that ADR-0002/ADR-0004's 95-of-110
deterministically-resolved reason codes really are unambiguous in a way an independent model also sees,
not merely unambiguous to this project's own rule-based parser reading the same vendored text.
