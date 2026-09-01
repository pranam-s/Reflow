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

### ADR-0002: GROUP BY, not clustering, is the production catch-all root-cause path

**Status:** Accepted (Phase 2)

**Context**

Razorpay's webhook already carries a structured `error_reason` alongside `error_code`,
`error_source`, and `error_step`. A one-line `GROUP BY (code, source, step, reason)` is a
trivial alternative to any clustering for the 102 of 110 unique reasons that are *narrow*
(one mechanism each, by the vendored taxonomy's own text). The open question this phase
was built to answer honestly is whether clustering earns its place on the remaining 8
*catch-all* reasons, where the taxonomy itself is coarse and free text is the only
candidate discriminator.

Three real clusterers were benchmarked behind one interface
(`reflow.cluster.base.Clusterer`) against the `GROUP BY` baseline
(`reflow.cluster.groupby_reason.GroupByReasonClusterer`), scored identically by
`reflow.eval.clustering.run_bakeoff`, on a masked-text pipeline shared by every candidate
(`reflow.signature.mask`) so the bake-off measures clustering, not masking:

- **Drain3** (`reflow.cluster.drain3_clusterer.Drain3Clusterer`) — fixed-depth parse-tree
  template mining, library defaults.
- **Normalised template hashing** (`reflow.cluster.template_hash.TemplateHashClusterer`)
  — exact match on a whitespace/case-normalised hash.
- **TF-IDF + HDBSCAN** (`reflow.cluster.tfidf_hdbscan.TfidfHdbscanClusterer`) —
  `sklearn.cluster.HDBSCAN` (available directly in the installed scikit-learn 1.9.0; no
  separate `hdbscan` package needed) with cosine-metric brute-force distances over a
  TF-IDF vectorisation.

Three axes were swept, all at a fixed seed (`20260822`) and fixed corpus size (50,000
events), full results and provenance committed at
`docs/reports/phase2_clustering_bakeoff.{json,md}`:

- **Axis A (variant richness 1, 3, 5)** — how many independently authored surface
  wordings a latent sub-cause's text is drawn from.
- **Axis B (opacity: transparent vs. opaque)** — the corpus's vendored spreadsheet
  documents, in Razorpay's own words, that it does not know the sub-cause behind several
  catch-all reasons (`card_declined`: "the exact reason ... is not shared with
  Razorpay"; `payment_declined`: "not communicated to Razorpay"; `payment_failed`: "no
  specific error code received from gateway"). The *opaque* arm
  (`reflow.eval.opacity.opaque_description`) re-renders every catch-all event exactly as
  if its reason were narrow, discarding the manufactured sub-cause-specific text
  entirely — a harness-level transformation, never a corpus edit. This is the
  null-hypothesis control: it is the condition Razorpay's own documentation says
  actually holds for these reasons in production, and by the corpus's own definition of
  what makes a reason "catch-all" (no further discriminating detail available), it is
  the realistic condition for every one of the 8 catch-all reasons, not only the three
  explicitly quoted above.
- **Axis C (catch-all share, derived not resampled)** — `reflow.eval.metrics.blended_metric`
  and `find_crossover_share` compute, from the stratified catch-all/narrow metrics
  already measured, the catch-all traffic share at which a candidate's blended
  performance would overtake `GROUP BY`'s.

**Evidence (transparent arm — the corpus as generated)**

At richness 1 (canonical wording only), template hashing and TF-IDF+HDBSCAN both
recovered the true 32 latent sub-causes perfectly (purity/NMI/ARI = 1.000); Drain3 was
close but not perfect (0.888/0.970/0.878, 28 of 32 predicted clusters). `GROUP BY`
managed only 0.319/0.652/0.325 on the same stratum (17 clusters — it cannot see
sub-cause text at all). All three real clusterers' separability degraded materially as
richness rose to 3 and 5 (ARI: Drain3 0.878 -> 0.551 -> 0.440; template hashing 1.000 ->
0.591 -> 0.467; TF-IDF+HDBSCAN 1.000 -> 0.595 -> 0.470) as each method increasingly
fragmented one sub-cause's several wordings into separate predicted clusters (predicted
cluster counts rose from ~28-32 at richness 1 to 91-160 at richness 5, against a true
count of 32 throughout). Under this arm, every real clusterer beat `GROUP BY` on every
richness level and every metric, and Axis C's crossover share was 0 (immediate) in every
case.

**That transparent-arm advantage is largely an identity, not an inference.** Independent
verification outside the test suite counted the distinct masked strings the clusterers
actually see: **32 at richness 1 for 32 sub-causes, and exactly 160 at richness 5** (five
wordings each). Template hashing groups identical strings by definition, so at richness 1
its clusters are a bijection with ground truth — a perfect score there measures the
corpus's one-wording-per-sub-cause construction, not the algorithm. The same identity
explains the apparent degradation: at richness 5 template hashing emitted exactly 160
clusters, one per distinct string, and Drain3 emitted 153. Neither is failing to
generalise; neither was ever generalising.

The substantive reading is that **none of the three candidates merge paraphrases of one
cause.** They partition surface forms. Their transparent-arm "win" therefore depends
entirely on our generator having made surface form a proxy for sub-cause — which is an
artefact of synthesis, and is exactly the condition the opaque arm removes.

**Evidence (opaque arm — the null-hypothesis control, and the realistic condition)**

`GROUP BY` is arm-invariant by construction (it never reads text): its catch-all metrics
were bit-for-bit identical in both arms at every richness level, as designed. Every real
clusterer's performance **collapsed to, or below,** `GROUP BY`'s catch-all baseline:
template hashing and TF-IDF+HDBSCAN scored 0.320/0.647/0.325 (purity/NMI/ARI) against
`GROUP BY`'s 0.319/0.652/0.325 — a difference of ±0.005, i.e. noise, not signal. Drain3
scored 0.296/0.613/0.311, **worse** than `GROUP BY` on every metric. Axis C's crossover
share was `never` for NMI and ARI, for every candidate, at every richness level; the one
`0.001` ("crosses immediately") entries under purity are a metric artefact, not a real
result — purity is trivially inflated by over-fragmentation (see
`reflow.eval.metrics.cluster_purity`'s docstring), and template hashing/TF-IDF's
catch-all purity exceeded `GROUP BY`'s by exactly the amount their mild over-splitting
would predict, while their NMI/ARI (which penalise over-fragmentation) show no advantage
at all. **No candidate showed any sign of recovering sub-cause information it should not
have been able to see under opacity** — the residual near-`GROUP BY` scores are fully
explained by masked text still structurally varying by payment method (a card clause
mentions a BIN, a UPI clause mentions a VPA and RRN, etc.), which is exactly the same
`method`-correlated signal `GROUP BY`'s own `code`/`source`/`step` fields already partly
encode, not sub-cause leakage. This is the corpus's designed-in null hypothesis
confirmed by measurement, exactly as anticipated in `BUILD_LOG.md`'s 2026-08-23 entry.

**Runtime and noise handling**

`GROUP BY` ran the full 50,000-event corpus in 15-35 ms. Drain3 and template hashing ran
the ~8,000-event catch-all stratum in 20-90 ms. TF-IDF+HDBSCAN took 2.0-2.9 s on the same
~8,000 events — 30-100x slower than the other two real clusterers — driven by its
brute-force O(n^2) cosine-distance computation (cosine has no KD-tree/ball-tree support);
this would not scale to a literal 50,000-event catch-all stratum without further
subsampling or a different approach. In the supplementary noise-handling diagnostic (run
on an outlier-enriched sample of the *narrow* stratum, since `PaymentEvent.is_outlier` is
never `True` for a catch-all reason by corpus design — see that attribute's docstring —
so the primary catch-all bake-off has no true outliers to measure recall against at all):
Drain3 and template hashing never emit noise (0 recall by construction); TF-IDF+HDBSCAN
recalled only 2 of 37 true outliers (5.4%) at 4.8% precision — a real, non-flattering,
but genuinely measured capability, and the only one of the four candidates that can
express "leave this unclustered" at all.

**Decision**

`GROUP BY (code, source, step, reason)` is adopted as the production root-cause path for
every reason code, narrow and catch-all alike. **No clustering candidate is adopted for
production catch-all root-causing.** The transparent arm's dramatic clustering win is a
measurement of a condition Razorpay's own vendored documentation says does not hold in
production for catch-all reasons; the opaque arm, which does reflect production, shows
no clustering candidate providing a measurable advantage over the trivial baseline, and
Drain3 measurably worse than it. Per this project's first governing principle, this
negative result is reported as the finding, not adjusted, re-scoped, or re-run until a
clustering candidate wins.

**Alternatives considered and rejected**

- **Drain3** — rejected. Underperforms `GROUP BY` on every metric in the realistic
  (opaque) arm; even in the unrealistic transparent arm it was the weakest of the three
  real clusterers at every richness level.
- **TF-IDF + HDBSCAN** — rejected for production despite being the only candidate able
  to express noise, and despite tying template hashing for best transparent-arm
  separability. It shows no advantage over `GROUP BY` in the realistic (opaque) arm, its
  noise-handling recall/precision were weak (5.4%/4.8%) even where measurable, and its
  O(n^2) brute-force runtime is 30-100x slower than the alternatives and would not scale
  to a larger catch-all volume without further engineering. If Razorpay ever begins
  surfacing richer sub-cause text for catch-all reasons (an external dependency outside
  this project's control), this is the candidate to re-benchmark first, given its
  transparent-arm parity with template hashing and its unique noise-handling capability.
- **Normalised template hashing** — rejected for production for the same reason as
  TF-IDF+HDBSCAN (no advantage over `GROUP BY` under realistic opacity), despite tying
  it for best transparent-arm separability at a fraction of the runtime and with zero
  new dependencies. Also rejected as a reserve candidate ahead of TF-IDF+HDBSCAN should
  opacity ever lift, on the basis that it cannot express noise/outlier handling at all.
- **`GROUP BY (code, source, step, reason)`** — accepted. Sufficient in the condition
  that actually holds in production; free; and, on the narrow stratum (102 of 110 unique
  reasons), already near-perfect (purity 1.000, NMI 0.983, ARI 0.981 against 102 true
  reasons from 140 predicted groups — it over-splits a handful of reasons whose
  remediation classification is itself ambiguous, but never merges two different
  reasons).

**Consequences**

- No new production dependency on `drain3` or `scikit-learn`'s clustering stack; they
  remain in the dependency tree only to support this benchmark and any future
  re-evaluation.
- Axis C's crossover analysis reduces, given the scope decision that clustering is never
  applied to the narrow stratum regardless of which candidate is used there, to a sign
  test on the catch-all-stratum metric alone (see
  `reflow.eval.clustering._compute_crossovers`'s docstring for why this is a structural
  consequence of the scope decision, not a hard-coded shortcut). This is stated plainly
  as a property of the experiment design, not hidden in the arithmetic.
- This decision is revisited if Razorpay's documented behaviour for catch-all reasons
  changes (i.e. if `error_description` begins carrying genuine sub-cause detail for
  `card_declined`, `payment_declined`, `payment_failed`, or the other catch-all codes),
  or if a future phase finds a materially different masking or feature representation
  that survives the opacity ablation where these three did not.

### ADR-0003: Poisson surprise, not the naive threshold, is the recommended incident detector -- despite the naive threshold mechanically "winning"

**Status:** Accepted (Phase 3)

**Context**

Phase 2 (ADR-0002) established that `GROUP BY (code, source, step, reason)` beats
clustering for root-causing individual failures, because Razorpay does not receive the
sub-cause for its own catch-all codes. What survives is a different, temporal/entity
problem: one bank outage emits several distinct reason codes at once (every one of the
corpus's 50 downtime windows spans 3-4 reason codes by construction -- see
`reflow.corpus.downtime` module docstring), and `GROUP BY reason` shatters that one
incident into several small, chronic-looking, individually sub-threshold buckets. This
phase built `reflow.incident` to detect these incidents by correlating failure counts
over `(method, bank)` and 15-minute time buckets (see the `reflow.incident.aggregate`
module docstring for the bucket-width justification), and benchmarked four burst
detectors behind one interface (`reflow.incident.detectors.IncidentDetector`) exactly
as Phase 2 benchmarked clusterers:

- **Fixed threshold** (`FixedThresholdDetector`, default `threshold=3`) -- the naive
  baseline, chosen a priori without consulting this corpus's realized statistics.
- **Rolling z-score** (`RollingZScoreDetector`, 4-hour trailing window, 3-sigma).
- **Poisson surprise** (`PoissonSurpriseDetector`) -- trailing rate estimated as the
  posterior mean of a Gamma(1, 1)-prior Poisson-rate model (`(sum + 1) / (n + 1)`),
  scored by tail probability, flagged below `p < 1e-3`.
- **EWMA z-score** (`EwmaZScoreDetector`, `alpha=0.2`) -- the optional fourth candidate,
  genuinely cheap (`O(1)` memory/update per entity, no stored window).

Every window-based detector shares the same window/`min_periods` defaults so a
difference in results is attributable to the scoring rule, not to unequal history (see
the `reflow.incident.detectors` module docstring). `GROUP BY reason` is implemented as
a comparison baseline in its strongest defensible form: the winning detector's own
algorithm, rerun at `(method, bank, reason)` granularity
(`reflow.incident.aggregate.reason_scoped_entity_key`) -- the finest-grained view a
naive per-reason-code monitor could ever have, decided after the winner is known so it
cannot be tuned to flatter any outcome. Full results, provenance, and per-run metrics:
`docs/reports/phase3_incident_detection.json` and `.md` (seed 20260822, 50,000 events,
train/test split from `reflow.corpus.split`).

**Evidence**

Selection rule, fixed before results were read: pick the detector with the highest
test-split F1 (8 windows at this seed), ties broken by the lower background
false-positive rate. By that rule, **`fixed_threshold` wins** (test precision 1.000,
recall 1.000, F1 1.000). Taken at face value this would close the question. It should
not be taken at face value:

- On the **train split** (42 windows -- roughly 5x the test split's statistical power),
  `fixed_threshold`'s precision **collapses to 0.264** (F1 0.418): 159 detected
  incidents against 42 true windows, i.e. 117 false alarms on ordinary background
  traffic. This is exactly the failure mode `FixedThresholdDetector`'s own docstring
  predicts -- one fixed count threshold cannot be calibrated for all ~50 `(method,
  bank)` entities at once when their background rates differ by orders of magnitude
  (a busy UPI/bank pair vs. a near-silent Emandate/bank pair) -- and it is a measured,
  not merely anticipated, confirmation of that prediction.
- `poisson_surprise` is far more **consistent across splits**: F1 0.662 (train) vs.
  0.640 (test), a gap of 0.022, against `fixed_threshold`'s gap of 0.582. Consistency
  under a pre-committed rule that only inspects the (small) test split is itself
  evidence about which result is signal and which is noise.

  **Independent verification identified the exact mechanism, and it is systematic rather
  than chance.** Both splits cover the *same* 720-hour span across the *same* 72
  `(method, bank)` entities, but the split assigns 42 of 50 windows and roughly 80% of
  background traffic to train, leaving test **four times sparser**: 55.7 vs. 13.8 events
  per hour. Per-bucket counts follow: train p90=2, p99=17; test p90=1, p99=4. The fixed
  threshold is **3**. On train it therefore sits *below* the noise floor and fires on
  ordinary traffic constantly; on test it sits *above* it and fires almost only on real
  incidents.

  This matters more than a small-sample caveat would. **An absolute count threshold is
  scale-dependent by construction**, so its accuracy is a function of merchant volume
  rather than of anything it detects. It would degrade on any merchant busier than the
  test slice, and its apparent perfection is a property of that slice's traffic level,
  not of the detector. `poisson_surprise` normalises against a trailing rate and is
  therefore scale-invariant, which is precisely why its two splits agree to 0.022.
- The two z-score detectors are **not competitive at any scale measured**:
  `rolling_zscore` and `ewma_zscore` score train F1 0.019 and 0.014 respectively, driven
  by the documented zero-trailing-variance fallback ("any count above a flat-zero
  baseline is a burst") flooding false positives on this corpus's many low-volume
  entities (background false-positive rate 0.22-0.26, vs. 0.01-0.02 for
  `poisson_surprise`). Recall stays high for both (0.976-1.000): the two z-score
  detectors are not missing incidents, they are drowning them in noise.
- **Recall was never the hard part for any detector** at this corpus's default event
  volume: every detector scores recall 0.976 or higher on both splits, and median
  time-to-detect is 0 minutes everywhere (most true incidents are intense enough from
  their first bucket to cross even a conservative bar immediately). The real
  differentiator between candidates was **precision** -- how well a detector avoids
  calling background noise an incident -- which is exactly where the naive threshold
  and the two z-score detectors fail and Poisson surprise does not.
- Time-to-detect is right-skewed for every statistically-gated detector, driven by cold
  start rather than a sustained incident poisoning its own baseline: `poisson_surprise`
  train p75 is 0.30 minutes but its max is 11.26 minutes; `rolling_zscore`'s max reaches
  41.26 minutes. `fixed_threshold`, which has no cold start at all, has the tightest
  worst case (max 3.26 minutes on train, 0 on test) -- the one respect in which it is
  genuinely, structurally better, not just apparently so.
- **The cross-reason claim, measured directly against ground truth, independent of
  detection:** all 50 of 50 windows (100%) span more than one reason code, confirming
  the corpus's designed property rather than assuming it. On average **66.4%** of a
  multi-reason window's events belong to a reason other than that window's own single
  most common reason (median 65.3%, pooled/event-weighted 67.6% over 10,000
  window-member events) -- the concrete size of what a `GROUP BY reason` view, taking
  only its biggest bucket as "the incident," would never see as belonging to the same
  cause.
- **The same claim, surviving actual detection, at the winning detector's own
  algorithm:** rerunning `fixed_threshold` at `(method, bank, reason)` granularity keeps
  precision and recall high (train F1 0.997, test F1 1.000) -- most individual reason
  streams still cross a lenient `threshold=3` eventually -- but **fragments one
  incident into 3.74 (train) to 4.62 (test) separate detected alerts on average, with
  100% of windows fragmented into more than one alert** (vs. 0% at `(method, bank)`
  granularity for the same detector). Event-attribution accuracy correspondingly drops
  from 0.998/0.997 (entity-level) to 0.951/0.937 (`GROUP BY`), and detection
  additionally lags by a mean of roughly 1.3 minutes as each thinner per-reason stream
  takes longer to cross the same bar. `GROUP BY reason`'s failure mode is therefore not
  primarily "it misses most of the incident's events" -- it is "it turns one incident
  into 4-5 separate, uncorrelated, individually-smaller alerts an on-call engineer has
  to manually realise are the same outage," at roughly 100-150x the runtime cost of the
  entity-level view (5.6s/3.6s vs. 0.03s, driven purely by the ~2,000-vs-50 entity
  cardinality blow-up of grouping by reason).
- **Downtime-declaration coverage.** A mechanism/coverage demonstration (not an
  independent validation -- the "declared" downtimes are synthesised from this same
  corpus's ground truth, see the `reflow.eval.incident` module docstring) correlated
  the winning detector's test-split incidents against synthetic
  `reflow.incident.downtime_api.Downtime` records restricted to the three methods
  Razorpay's real Downtime API can express (Card, Netbanking, UPI -- verified live,
  2026-08-23). All 7 correlatable incidents corroborated (rate 1.000); 1 of 8 detected
  incidents (on Wallet, Cardless EMI, or Emandate) **could never be corroborated by
  Razorpay's own API regardless of detection quality**, since that API has no
  declaration shape for those methods at all. This is a structural, verified fact about
  the live API, not an artefact of the simulation.

**Decision**

**`poisson_surprise` is adopted as the recommended production incident detector**,
despite `fixed_threshold` winning the pre-committed test-split-F1 selection rule. This
is stated plainly as a case where the mechanical rule and the fuller evidence disagree,
per this project's first governing principle: the rule is reported honestly (it did
pick `fixed_threshold`), and so is the reason it is not being followed here (its win is
a small-test-split artifact that does not survive contact with the 5x-larger train
split, while `poisson_surprise`'s performance is nearly identical across both splits).
`GROUP BY reason` is confirmed, with a real detector rather than only a ground-truth
count, as failing exactly the way the phase's brief anticipated: not by losing most of
the incident's events, but by fragmenting one incident into several separate,
individually-smaller, later-firing alerts.

**Alternatives considered and rejected**

- **Fixed threshold** -- rejected for production despite winning the letter of the
  selection rule, on the strength of the train-split evidence showing severe,
  entity-heterogeneity-driven precision collapse (0.264). Its one genuine advantage --
  no cold start, immune to baseline poisoning, tightest time-to-detect worst case -- is
  real and is why it remains in the benchmark as the naive baseline the others must
  beat, which `poisson_surprise` does everywhere except that single small test split.
- **Rolling z-score** -- rejected. Background false-positive rate of 0.22-0.26 is not
  operationally usable; its zero-trailing-variance fallback (necessary because this
  corpus's sparser entities frequently have an all-zero trailing window) converts to
  "flag any nonzero count," which is barely more discriminating than no baseline at
  all.
- **EWMA z-score** -- rejected for the same reason as rolling z-score (background
  false-positive rate 0.26-0.60, the worst of the four candidates on the test split).
  Its cheap, memory-free design and distinct baseline-recovery behaviour after a
  sustained incident remain a real, reportable point of contrast worth revisiting if a
  future corpus or production deployment has meaningfully denser, less heterogeneous
  per-entity traffic (its degenerate-variance failure mode is a function of sparsity,
  not of the EWMA mechanism itself).
- **`GROUP BY reason`** -- rejected as an incident-detection strategy, confirmed rather
  than assumed: even given its strongest form (the winning detector's own algorithm, at
  finer granularity), it fragments 100% of true incidents into multiple separate
  alerts and costs 100-150x the runtime of the entity-level view, for a smaller gain in
  raw event coverage than the ground-truth cross-reason measurement alone would
  suggest.

**Consequences**

- Production incident detection should run `PoissonSurpriseDetector` at `(method,
  bank)` granularity (`reflow.incident.aggregate.entity_key`) with a 15-minute bucket
  width, not `GROUP BY reason`'s per-reason-code view.
- The naive fixed threshold remains implemented and benchmarked as the baseline the
  others must beat, per phase brief -- it is a legitimate, not embarrassing, outcome
  that it wins a narrowly-stated selection rule on a small held-out sample, and that
  fact is reported rather than the rule quietly being changed to produce a tidier
  answer.
- Cold start is handled uniformly (a detector never flags before `min_periods` trailing
  buckets exist); low-count Poisson instability is handled by Gamma(1, 1) Bayesian
  smoothing of the trailing rate rather than a raw sample mean; a sustained incident
  poisoning its own trailing baseline is explicitly **not** solved by any candidate here
  (all four are simple online statistics with no change-point memory) and is visible
  empirically in the right-skewed time-to-detect tails -- a materially heavier
  change-point/regime-switching design would be required to fix it, which this phase's
  brief did not call for and which is recorded here as a known, unresolved limitation
  rather than quietly worked around.
- This decision is revisited if a future corpus or production traffic pattern is denser
  and less heterogeneous across entities than this one (which could change the z-score
  detectors' zero-variance failure mode), or if `GROUP BY reason`'s fragmentation cost
  is judged acceptable against its zero-new-infrastructure simplicity for a deployment
  that cannot run per-entity burst detection at all.

### ADR-0004: an LLM is invoked at exactly two boundaries, and nowhere structure already resolves it

**Status:** Accepted (Phase 4)

**Context**

ADR-0002 established that `GROUP BY (code, source, step, reason)` beats clustering for
individual-event root-causing, because Razorpay does not transmit the sub-cause behind
its own catch-all codes -- there is nothing for any classifier, LLM included, to
legitimately recover there. ADR-0003 established that a bank outage spans several reason
codes at once and is found by statistical burst detection (`poisson_surprise`) over
`(method, bank)` and time, not by reading event text. This phase had to decide, having
already ruled an LLM out of both of those jobs, where one is actually earned.

`reflow.diagnose.tier1.build_deterministic_table` reconciles every vendored row of
`reflow.taxonomy.remediation` to its reason code (see that module's docstring for why
reconciling by *code*, not by row, is the correct granularity: a real
`PaymentEvent.error_reason` carries no row index, and two of the 110 distinct codes --
`issuer_technical_error` and `payment_method_not_enabled` -- have rows that individually
parse cleanly but disagree with each other, which is invisible unless reconciled at the
code level). That reconciliation leaves exactly two situations no deterministic table or
statistical detector can resolve, and Deliverable 2's brief named them in advance, before
any measurement: **15 reason codes** whose vendored `Next Steps` text is genuinely
ambiguous or self-contradictory, and **every detected incident**, whose probable cause
spans several reason codes by construction and therefore has no single-reason lookup
that could substitute for a judgment about the incident as a whole.

**Evidence**

The full pipeline was run against the real, generated 50,000-event corpus (seed
`20260822`), with real OpenRouter calls end to end -- `deepseek/deepseek-v4-flash` for
both Tier 2 call sites (verified live, via a committed VCR cassette, to actually honour
`reasoning_effort="none"`) and `openai/gpt-oss-20b` as an independent judge (a different
model family, to avoid self-preference bias). Full results, provenance, and per-call
cost: `docs/reports/phase4_diagnosis.{json,md}`.

- **The routing split.** 43,028 of 50,000 events (86.056%) resolved in Tier 1 with zero
  LLM calls. 6,972 events (13.944%) carried one of the 15 escalated reason codes and were
  resolved by Tier 2 -- but that 13.944% of *events* was served by exactly **15 live LLM
  calls total**, not 6,972, because Tier 2's ambiguous-reason result is cached per reason
  code (`reflow.diagnose.ambiguous.AmbiguousReasonDiagnoser`). The distinct-reason-code
  escalation rate (15/110 = 13.6%) and the event-weighted escalation rate (13.944%) are
  close by coincidence of this corpus's mix, not by construction -- there is no reason
  they would have to agree, and this project reports the measured event-weighted number,
  not the reason-code count, as the headline, since it is what a real merchant's traffic
  actually experiences.
- **Incident diagnosis touches a tiny fraction of volume.** `poisson_surprise` detected
  113 incidents across the full corpus. Every one of them received its own live,
  uncached LLM call (113 calls total) -- but 113 incidents against 50,000 events means
  99.774% of events were never part of any incident-level LLM call at all; the incident
  -diagnosis tier's total cost of $0.006948 for this entire run reflects that.
- **Actual cost, measured, not estimated.** This run's total real spend was **$0.009102**
  ($0.000814 one-time for the 15 ambiguous reasons, $0.006948 for 113 incident diagnoses,
  $0.001340 for 16 judge samples). Projected to production volume:
  **$0.0147 per 100,000 events cold-cache** (first-ever run, includes the one-time
  ambiguous-reason cost) and **$0.0139 per 100,000 events warm-cache** (steady state).
  Against this phase's $1.00 spend cap, that is roughly 1/68th of the cap *per 100,000
  events* -- the cap would cover on the order of 6-7 million events' worth of production
  Tier 2 calls at these measured rates. The LLM's cost is a rounding error precisely
  because it is invoked on 13.944% of events (cached down to 15 calls) plus 0.226% of
  events (113 uncached incident calls), never on the other ~86%.
- **The judge found real, calibrated disagreement, not noise.** Sampling 8 ambiguous
  -reason diagnoses and 8 incident diagnoses (16 total, seeded, not exhaustive), the
  independent judge did not endorse 6 of 16 (37.5%). Zero were labelled outright
  `"wrong"`; all 6 were `"questionable"`, and every one of the 6 has a specific,
  legible mechanism: for ambiguous reasons, the Tier 2 model tends to pick *one* of two
  remediation paths the vendored text genuinely offers as alternatives (e.g.
  `compliance_violation`'s customer-vs-merchant branch, `transaction_daily_count_exceeded`'s
  wait-vs-switch-instrument branch) and reports high confidence in that single choice
  rather than surfacing the disjunction; for incidents, the model frequently assigns
  `high` confidence to a bank-outage hypothesis from as few as 3-6 correlated failures,
  which the judge correctly flags as more certain than three events can support. Neither
  failure mode is a hallucinated fact -- both are overconfidence given genuinely
  ambiguous or thin evidence, which is exactly the kind of thing a second, differently
  -biased model is good at catching and a purely mechanical accuracy check is not.
- **A judge output was also observed malformed once, without breaking the pipeline.**
  One of the 16 judge samples (`073_upi_IndusInd Bank`) returned a `concerns` string that
  degenerated into dozens of repeated `"... "` tokens -- a real generation-quality defect
  in `openai/gpt-oss-20b`'s output on that call. It did not break anything downstream:
  `concerns` is an unconstrained string field, so it satisfied the schema and was
  recorded verbatim rather than crashing or silently being dropped, which is itself
  evidence for validating structure strictly (the enum/bool fields) while tolerating free
  -text fields to hold whatever a model actually produces.

**Where an LLM is deliberately not used** (this is the boundary this ADR exists to draw):

- **The 95 of 110 deterministically-resolved reason codes (86.056% of this corpus's
  events).** The vendored `Next Steps` text already specifies one remediation
  unambiguously for these; a `dict` lookup resolves them with 100% precision, $0 cost,
  and no latency. Routing these through an LLM would add cost, latency, and a new
  failure surface (truncation, schema drift, non-determinism) to replace a lookup that
  cannot be wrong within the taxonomy's own terms. This is the largest area in the whole
  pipeline where an LLM was considered and rejected, and it is why the phase's headline
  number is stated as "86% needs no model" rather than buried under the 14% that does.
- **Per-event root-causing of catch-all reasons.** ADR-0002's finding stands and this
  phase did not re-litigate it: an LLM asked to infer a catch-all reason's sub-cause from
  `error_description` would be inferring detail Razorpay's own documentation says it does
  not transmit (`card_declined`: "not shared with Razorpay"; `payment_declined`: "not
  communicated to Razorpay"). An LLM is exactly as blind to that missing signal as
  template hashing or TF-IDF+HDBSCAN were measured to be -- the difference is a
  clustering algorithm fails visibly (near-identical metrics to `GROUP BY`), while an LLM
  would confidently *narrate* a plausible-sounding sub-cause with no more evidence than
  the classifiers had, which is a worse failure mode, not a better one.
- **Burst/incident detection itself.** `poisson_surprise` finds the 113 incidents;
  nothing here asks an LLM to scan raw event streams for anomalies. A statistical test
  purpose-built for count-over-time surprise is cheaper (the entity-level detector runs
  the full corpus in tens of milliseconds, ADR-0003) and more auditable than an LLM would
  be at the same job, and this phase's LLM is invoked only *after* detection, to
  interpret an incident already found by cheaper means -- never to find it.
- **Judging every diagnosis.** The judge samples 16 of 128 real Tier 2 outputs (8 of 15
  ambiguous reasons, 8 of 113 incidents), not all of them. A real deployment producing
  many more incidents than this corpus's 113 would make exhaustive judging progressively
  more expensive for diminishing signal; sampling is the production-shaped choice, made
  here even though this run's actual volume was cheap enough that exhaustive judging
  would also have fit the budget.

**Decision**

The LLM is invoked at exactly two boundaries: once per distinct ambiguous reason code
(cached, 15 calls total, ever, regardless of corpus size), and once per detected
incident (uncached, 113 calls for this corpus, scaling with detected-incident volume,
not event volume). Every other event resolves deterministically. This boundary is kept
because it is where the earlier phases' own findings say structure runs out --
deterministic lookup for reason codes; statistical detection for bursts -- not because an
LLM was hard to avoid using elsewhere.

**Alternatives considered and rejected**

- **Route every event through the LLM for a "double-checked" diagnosis, even
  deterministically-resolved ones.** Rejected: would multiply cost and latency by roughly
  7x (50,000 LLM-touched events instead of 6,972 event-equivalents-worth of 15 cached
  calls plus 113 incident calls) for a class of reason where the deterministic answer is
  already exact within the taxonomy's own terms; the ADR-0002 clustering bake-off already
  showed that adding a model where the ground truth is fully specified buys nothing.
- **Use the LLM to infer catch-all sub-causes per event.** Rejected for the same
  evidentiary reason ADR-0002 rejected clustering there: Razorpay does not transmit the
  signal, so there is nothing to legitimately infer, only to confidently fabricate.
- **Use the LLM as the incident detector (feed it raw event streams and ask "is this an
  outage").** Not benchmarked, because ADR-0003 already has a detector recommendation
  with measured F1 and background false-positive rate; replacing a sub-second statistical
  test with a per-window LLM call would be strictly more expensive with no evidence it
  would be more accurate, and this phase's brief scoped the LLM to interpretation of an
  already-detected incident, not detection itself.
- **Judge every Tier 2 output instead of sampling.** Rejected as the production-shaped
  choice even though this run's volume was small enough to afford it: sampling is what
  scales, and reporting a sampled disagreement rate (37.5% of 16) is honest about being
  an estimate rather than implying a false completeness.
- **Disable reasoning for the judge model the same way as the Tier 2 model.** Rejected
  after `openai/gpt-oss-20b` was found live to also mandate reasoning (`BUILD_LOG.md`,
  2026-08-23) -- `reasoning_effort="none"` is now requested only for models verified live
  to honour it (currently just the Tier 2 model), never assumed from a parameter merely
  being listed as accepted.

**Consequences**

- Production diagnosis cost is dominated by incident volume, not event volume: doubling
  corpus size roughly doubles detected incidents (and their LLM cost) but leaves the
  15-call ambiguous-reason cost unchanged, since that set is fixed by the taxonomy, not
  by traffic. `CostSummary` in `reflow.eval.diagnose` reports both components separately
  for exactly this reason.
- A future reason-code addition or vendored-spreadsheet update could shrink or grow the
  15-code escalation set; `reflow.diagnose.tier1.build_deterministic_table` recomputes it
  from the vendored file rather than hard-coding the count, so this stays measured, not
  assumed.
- This decision is revisited if a production incident volume far exceeds this corpus's
  113-per-50,000-events rate (making the per-incident LLM cost material rather than a
  rounding error), or if a future model verified to honour disabled reasoning becomes
  available for judging at lower cost than `openai/gpt-oss-20b`'s reasoning-enabled rate.

### ADR-0005: a closed seven-action set, a sequential guardrail chain, and an
attempt-number-driven escalation ladder

**Status:** Accepted (Phase 5)

**Context**

Phases 2-4 established what to diagnose and how (`GROUP BY` for root cause, `poisson_surprise`
for incidents, a two-tier deterministic/LLM split for remediation class). This phase turns a
diagnosis into a bounded, audited action, and had to answer three design questions before any
code was written, per this project's second governing principle: what actions can this system
actually take against Razorpay's real APIs; how does a diagnosis become one of those actions
without inventing per-reason special cases everywhere; and how are the phase brief's mandatory
guardrails and stopping rules made independently testable rather than sprinkled through the
decision logic as ad hoc `if` statements.

**Action set, grounded in verified API reality**

`reflow.policy.actions.Action` is a seven-member closed `StrEnum`: `NO_ACTION`,
`WAIT_BANK_RECOVERY`, `RECOVERY_LINK_NOW`, `RECOVERY_LINK_BACKOFF`, `SWITCH_METHOD`,
`ESCALATE_HUMAN`, `RECONCILE`. Two API facts, one already recorded in `BUILD_LOG.md` and one
verified live for this phase, shape it directly:

- **The Payments API cannot retry a failed authorisation** (`BUILD_LOG.md`, 2026-08-22): it only
  fetches or captures an already-authorised payment. There is accordingly no `RETRY_PAYMENT`
  action anywhere in this enum -- every customer-facing recovery action goes through a fresh
  Payment Link instead.
- **Payment Links can restrict which payment method is offered, but not which instrument.**
  Verified live 2026-08-23 against
  <https://razorpay.com/docs/api/payments/payment-links/customise-payment-methods/>: the
  documented mechanism is four boolean toggles nested under `options.checkout.method`
  (`card`, `netbanking`, `upi`, `wallet`) that show or hide a payment method on the link's
  checkout. No parameter restricts a specific card, VPA, or other instrument. This is exactly
  why `SWITCH_METHOD` exists as a distinct, enforceable action (disable the method that just
  failed) while `DIFFERENT_INSTRUMENT`-classified reasons map to a plain `RECOVERY_LINK_NOW`
  instead of a fabricated "switch instrument" action the API has no way to honour --
  `reflow.policy.actions` module docstring records this per-class reasoning in full.

`reflow.policy.actions.base_action_for` is a **pure function of
`reflow.taxonomy.remediation.RemediationClass` alone** -- it never inspects the reason code, the
event's amount, or which tier produced the diagnosis. This is the direct, literal reading of the
phase brief's "the policy layer must not care which tier produced the input": the cleanest way to
guarantee it is to give the base mapping nothing but the class to look at. The one exception the
brief itself names -- `RECONCILE` for duplicate/already-paid cases -- is deliberately *not* built
into this pure function. It is `reflow.policy.guardrails.TerminalReasonGuardrail`'s job, keyed off
`reflow.policy.actions.RECONCILE_REASONS` (`order_already_paid`, `duplicate_request`,
`duplicate_refund_id` -- reason codes whose own vendored name says "duplicate" or "already paid,"
read directly off the taxonomy rather than invented, and deliberately excluding
`duplicate_rrn_found` despite its name, since the taxonomy classifies that row `RETRY_SAME`, not a
duplicate/already-settled case). Making this a guardrail rather than a mapping special case means
the decision to reroute away from human escalation is recorded in the audit trail as a guardrail
firing with a stated reason, not buried invisibly in a lookup table -- and it gave this guardrail
genuine, non-trivial fire counts on the real corpus (647 of 50,000 events, see Evidence) rather
than being a guardrail that could structurally never do anything.

**Guardrails: a sequential chain, not seven independent verdicts**

The brief requires every guardrail to be independently testable, independently configurable, and
to record which rule fired and why -- including when it *passes*. Seven guardrails
(`reflow.policy.guardrails`) are implemented as small, frozen, stateless classes, each a pure
function of `(GuardrailContext, Action) -> GuardrailEvaluation`: attempt cap, per-customer contact
cap, terminal-reason blocklist, cooldown, amount floor, quiet hours, and active-incident
suppression. They run as a **fixed-order sequential chain**
(`reflow.policy.guardrails.default_guardrail_chain`), each guardrail receiving whatever action the
previous one left behind, rather than each guardrail independently voting on the escalation
ladder's original candidate and needing a precedence rule to reconcile disagreements. This was
chosen because Deliverable 4's requirement -- "record every guardrail evaluated with its verdict"
-- does not require every guardrail to see the *same* input; it requires every guardrail's own
verdict, given the pipeline state when it ran, to be recorded truthfully. A chain makes "what
would have happened with zero guardrails" a well-defined quantity (the escalation ladder's own
output, before the first guardrail runs) without inventing a separate precedence-resolution
mechanism for guardrails that might otherwise disagree.

Evaluation order is fixed and documented, not incidental: `TerminalReasonGuardrail` first (is this
reason contact-worthy at all), `ActiveIncidentGuardrail` next (is the rail itself already known to
be down), `AmountFloorGuardrail` (is further spend economically justified), `AttemptCapGuardrail`
(have we already tried enough times), `ContactCapGuardrail` and `CooldownGuardrail` (anti-spam),
and `QuietHoursGuardrail` last, since it only ever *defers* a send within the same case rather than
cancelling it outright, so it should see whatever the rest of the chain has already decided.

**The escalation ladder is driven by observed attempt number, not a simulated action history**

`reflow.policy.ladder.ladder_action` advances a base action along a four-rung sequence
(`RECOVERY_LINK_NOW -> RECOVERY_LINK_BACKOFF -> SWITCH_METHOD -> ESCALATE_HUMAN`) by
`PaymentEvent.attempt_number`, clamping at the last rung. A live Phase 6 deployment would track
"how many times has *this policy* already tried to recover this payment" directly, from its own
past decisions. This phase evaluates the policy offline, against a historical corpus the policy
has never acted on -- there is no action history to count. `attempt_number` is the best available
proxy: a real, ground-truth count of how many times this exact order has already been attempted
(`reflow.corpus.generator`'s retry-chain mechanism), rather than a synthetic counter this offline
evaluation has no way to validate. This is stated as a limitation, not hidden: a production
deployment should replace it with genuine decision history once one exists. The ladder itself
never produces a terminal "give up" -- past its fourth rung it clamps, holding at
`ESCALATE_HUMAN` regardless of how many further attempts are observed. Turning that into an
explicit give-up is `AttemptCapGuardrail`'s job, precisely so "giving up" is a guardrail firing
with a stated reason in the audit trail, not a silent clamp a reader of the ladder alone would
never notice -- Deliverable 3's requirement that giving up be an explicit, not an unhandled
fall-through, is satisfied by construction rather than by convention.

**Compliance note, stated plainly.** `reflow.policy.config`'s quiet-hours window (21:00-09:00) is
an explicitly documented **policy default**, not a cited TRAI/TCCCPR/DND numeric threshold. This
project verified live that Payment Links can restrict method (above) and that the Payments API
cannot retry (`BUILD_LOG.md`); it did **not** verify a specific TRAI time-of-day rule against a
primary source, and the applicable rule for a given message depends on facts this corpus does not
model (transactional-vs-promotional message classification, DLT template registration status).
Fabricating a cited legal threshold this project cannot verify would be worse than stating this
honestly: quiet hours are configurable, and a merchant with a verified DLT-registered template and
time window should override the two default fields with that verified value.

**Evidence**

The full pipeline was run against the real, generated 50,000-event corpus (seed `20260822`),
combining Tier 1's free deterministic table with Phase 4's already-committed, already-paid-for
Tier 2 output for the 15 ambiguous reasons (`reflow.policy.diagnosis_source` -- zero new LLM
calls) and a fresh, free run of the ADR-0003-recommended `poisson_surprise` detector for active
incidents. Total spend for this phase: **$0.00**. Full results and provenance:
`docs/reports/phase5_policy.{json,md}`.

- **Action distribution (candidate, i.e. zero guardrails, vs. final, i.e. with the full
  guardrail chain), across all 50,000 events:** `recovery_link_now` 32,254 -> 13,391;
  `recovery_link_backoff` 4,508 -> 19,137; `switch_method` 8,066 -> 2,720; `escalate_human`
  5,172 -> 4,310; `no_action` 0 -> 2,423; `reconcile` 0 -> 647; `wait_bank_recovery` 0 -> 7,372.
  Every one of the seven closed-set actions occurs at least once with guardrails applied; three
  (`no_action`, `reconcile`, `wait_bank_recovery`) never occur as a *candidate* by construction,
  since nothing in the base remediation-class mapping or the ladder ever proposes them directly
  -- they exist only as guardrail outcomes, exactly as designed.
- **7,372 of 50,000 events (14.7%) reached `wait_bank_recovery`** because
  `active_incident_suppression` fired -- the single most consequential guardrail measured, and
  the concrete size of "the agent deliberately choosing not to act" the phase brief calls out as
  the most interesting decision this system makes.
- **The over-contact reduction is measured, not asserted:** 44,828 events would have received a
  chase contact (`recovery_link_now`/`recovery_link_backoff`/`switch_method`) with zero
  guardrails; 35,248 actually did with the full chain applied -- a reduction of **9,580 contacts
  (21.37%)**.
- **Per-guardrail fire counts:** `quiet_hours` 15,648 (by far the largest, consistent with a
  12-hour default window against uniformly-distributed synthetic timestamps -- roughly half of
  the ~32,000 remaining immediate-send candidates at the point in the chain where it runs);
  `active_incident_suppression` 7,372; `amount_floor` 1,991; `contact_cooldown` 428;
  `terminal_reason_blocklist` 647; `attempt_cap` 4; **`per_customer_contact_cap` 0**.
- **The contact cap's zero-fire result is a real, measured finding, not a bug**, verified
  independently outside the guardrail's own unit tests: only 232 of 15,755 customers in this
  corpus ever have three or more raw failed-payment events within any rolling 24-hour window at
  all (median customer sees 3.17 events spread across the full 30-day generation period), and
  `contact_cooldown`'s tighter, 4-hour, per-contact gate already suppresses same-day
  recontacting aggressively enough that the daily cap of 3 never has anything left to block on
  this corpus's realised density. This is reported as the finding, per this project's first
  governing principle, rather than tuning the default cap downward to manufacture a non-zero
  number for this report -- `tests/policy/test_guardrails.py` exercises `ContactCapGuardrail`'s
  blocking branch directly with a synthetic context regardless of whether this particular corpus
  ever reaches it.
- **The `TERMINAL`-class branch of `terminal_reason_blocklist` also cannot fire on this corpus**,
  for the same reason ADR-0002's remediation-class module already documents: zero of 110 reason
  codes are currently classified `RemediationClass.TERMINAL`. Its duplicate/already-paid branch,
  by contrast, fires 647 times (the concrete count of `order_already_paid` /
  `duplicate_request` / `duplicate_refund_id` events in this corpus), so the guardrail's overall
  zero-vs-nonzero split is itself an honest, structural fact about the current taxonomy, not
  evidence the guardrail is inert -- both branches are exercised directly in
  `tests/policy/test_guardrails.py`.
- **Escalation ladder terminal-state distribution:** `in_progress_link_now` 13,391;
  `in_progress_backoff` 19,137; `in_progress_switch_method` 2,720; `escalated_to_human` 4,310;
  `reconciled` 647; `waiting_on_bank` 7,372; `no_action_other` 2,419; **`gave_up` 4**. Giving up
  is rare at this corpus's default `attempt_cap=4` and `MAX_ATTEMPT_NUMBER=5` retry-chain depth
  (few orders in a 30-day, `RETRY_CONTINUATION_PROBABILITY=0.35` corpus reach a fifth attempt at
  all) but is explicit and non-zero, not an unhandled fall-through.

**Decision**

The seven-action closed set, the pure remediation-class-only base mapping, the sequential
seven-guardrail chain in the documented fixed order, and the attempt-number-driven escalation
ladder are adopted as designed above. Every design choice was written down and justified before
this phase's code was run against the corpus (`reflow.policy`'s module docstrings predate the
benchmark numbers in this ADR), consistent with this project's second governing principle.

**Alternatives considered and rejected**

- **A `RETRY_PAYMENT` action calling the Payments API directly.** Rejected: verified, no such
  API call exists (`BUILD_LOG.md`, 2026-08-22). Inventing one would misrepresent what this system
  can actually do against Razorpay's real surfaces.
- **Building the duplicate/already-paid `RECONCILE` carve-out into `base_action_for` as a
  reason-code special case.** Rejected in favour of making it `TerminalReasonGuardrail`'s job:
  keeps the base mapping a pure, auditable function of remediation class alone, and makes the
  reroute a guardrail firing with a recorded reason rather than an invisible lookup-table
  exception -- and it is the design that produced this guardrail's only non-zero, reportable
  fire count.
- **Per-guardrail independent verdicts against one shared original action, reconciled by a
  precedence rule.** Rejected in favour of a sequential chain: a precedence rule would need its
  own justification for every possible pair of disagreeing guardrails (seven guardrails is 21
  pairs), while a fixed, documented sequential order needs only one linear justification and
  still lets every guardrail's individual verdict be recorded truthfully.
- **A policy-internal action-history counter for the escalation ladder**, simulating what a live
  deployment's own past decisions would track. Rejected for this offline evaluation: there is no
  real action history to simulate correctly (this phase's policy has taken no actions on this
  historical corpus), and a fabricated one could not be validated against anything. Using
  `attempt_number` is a stated limitation, not a hidden one, and is the closest honest proxy
  available.
- **Citing a specific TRAI/TCCCPR time-of-day threshold for quiet hours.** Rejected: not verified
  against a primary source, and the real rule depends on message classification and DLT
  registration status this project does not model. An honestly-labelled configurable policy
  default was chosen instead of a fabricated citation.
- **Tuning the contact-cap or amount-floor defaults after seeing they produced a zero or small
  fire count on this corpus**, to manufacture a more "interesting" number for this report.
  Rejected per this project's first governing principle: the zero-fire result for
  `per_customer_contact_cap` is reported as a genuine, investigated finding (see Evidence) rather
  than quietly tuned away.

**Consequences**

- Phase 6 persists `reflow.policy.decision.Decision` as the audit trail; its shape (input
  diagnosis, candidate action, every guardrail's verdict whether passed or blocked, final action,
  human-readable justification) was designed for that now, per the brief, and
  `reflow.policy.decision.to_dict` already produces a JSON-safe structure with no bespoke
  handling required for any enum, `datetime`, or `timedelta`.
- `reflow.eval.policy`'s report writes only aggregate statistics and a small illustrative sample
  of decisions, not all 50,000 -- the full per-event audit trail is Phase 6's persistence
  responsibility, not this benchmark report's.
- This decision is revisited if a production deployment's real action-history data becomes
  available (replacing the attempt-number ladder proxy with genuine decision history), if a
  merchant supplies a verified DLT-registered-template time-of-day restriction (replacing the
  quiet-hours policy default), or if Razorpay's Payment Links API is ever verified to support
  instrument-level (not just method-level) restriction (which would change the
  `DIFFERENT_INSTRUMENT` mapping from `RECOVERY_LINK_NOW` to a real instrument-restricted send).

### ADR-0006: idempotency by catch-and-recover, not by header; an append-only, hash-chained
audit trail

**Status:** Accepted (Phase 6)

**Context**

Phase 6 makes this project's first real calls against a live external API and delivers this
project's audit trail. Two design questions had to be answered honestly, with evidence, before
writing execution code, per this project's second governing principle: how does bounded execution
stay idempotent against a Payment Links API that (`BUILD_LOG.md`, 2026-08-22) documents no generic
idempotency header; and what does an audit trail need to record, and how, to make "we checked and
it was allowed" as durable and inspectable as a block.

**Idempotency: two live-verified facts shaped the design, and one assumption turned out wrong**

The plan going in was that a deterministic Payment Link `reference_id` (max 40 characters, unique
per link) would behave like a conventional idempotency key: derive it from the payment id, and a
retried call with the same key transparently returns the original response. **Verified live,
2026-08-23, this assumption was wrong.** Creating a second Payment Link with an already-used
`reference_id` does not return the original link -- it raises `razorpay.errors.BadRequestError`
with the message `"payment link with given reference_id: <id> already exists. Please create a
payment link with a different reference_id"`. A deterministic key alone is necessary but not
sufficient; the caller must also catch this specific rejection and recover the existing resource
itself. Verified live the same day: `GET /v1/payment_links?reference_id=<id>`
(`razorpay.Client.payment_link.all({"reference_id": ...})`) does support this lookup, and its
response envelope is `{"payment_links": [...]}` -- confirmed by direct inspection to differ from
the generic `{"count": ..., "items": [...]}` shape most other Razorpay list endpoints use, so this
was read from a real response, not assumed by pattern-matching against other endpoints.

`reflow.execute.reference.derive_reference_id` derives a `"reflow_"` prefix plus 33 hex characters
(a truncated SHA-256 digest of the payment id) -- always exactly the documented 40-character limit,
a pure function of the payment id alone. `reflow.execute.gateway.RazorpayGateway.create_payment_link`
catches exactly the verified duplicate-`reference_id` rejection (matched on the SDK's description
string, since the SDK exposes nothing more structured -- see below) and recovers the pre-existing
link via the `reference_id` filter, rather than surfacing it as a failure.
`reflow.execute.models.ExecutionRecord.idempotent_replay` records when this path fired.
`tests/execute/test_gateway_live.py::test_duplicate_reference_id_is_recovered_not_duplicated`
drives this exact path against the real API and is committed as a VCR cassette, so the recovery
logic is proven against Razorpay's real behaviour, not only against a hand-written mock of it.
Collision-resistance of the derivation itself is checked empirically:
`tests/execute/test_reference.py` hashes every `payment_id` in a full 50,000-event generated corpus
and asserts zero collisions, and `reflow.eval.execute.run_benchmark`'s report repeats this check on
every run rather than asserting it once and trusting it forever.

**Adaptive backoff is keyed off transport-captured HTTP status, never SDK exception type**

The SDK's own retry (`BUILD_LOG.md`, 2026-08-22) never covers an HTTP error status, and no numeric
rate limit is published. Live rate-limiting was reproduced organically while developing this phase
(three rapid sequential Payment Link calls), and the SDK surfaced it as a plain `BadRequestError:
Too many requests` -- the identical exception type and JSON `error.code`
(`BAD_REQUEST_ERROR`) a genuine validation error also raises. The exception type alone cannot tell
"retry me" from "fix your request." `reflow.execute.transport.build_capturing_session` attaches a
`requests` response hook (deliberately not a `Session` subclass overriding `request()` -- the
installed `requests` stub's `Session.request` signature is fully, specifically typed, and a
permissive `**kwargs` override would be an LSP-incompatible override under `mypy --strict`;
`Session.hooks["response"]` is `requests`' own documented, type-compatible extension point for
exactly this) that records the real HTTP status code and full JSON error body the SDK parses and
discards. `reflow.execute.gateway.RazorpayGateway._call_with_retry` retries only when the
*captured* status code is 429 or 5xx, with exponential backoff plus jitter, and raises
`ApiCallFailedError` (carrying the full captured error body, including any
`field`/`source`/`step`/`reason`/`metadata` the SDK's own exception would have discarded)
otherwise.

**The audit trail: one flat record per decision, an explicit verdict for every guardrail, a cheap
hash chain**

`reflow.audit.record.AuditRecord` is assembled from shapes that already existed for other reasons
-- `reflow.corpus.events.PaymentEvent` (the full `(code, source, step, reason)` group, which
`Decision` alone does not carry), `reflow.policy.decision.Decision` (diagnosis, guardrail chain,
final action -- ADR-0005's own consequences section anticipated persisting exactly this),
`reflow.diagnose.router.EventDiagnosis` (for `rationale`), and
`reflow.execute.models.ExecutionRecord` (execution outcome). Every guardrail's verdict is recorded
whether it blocked or passed, matching the phase brief's "record passes, not just blocks"
literally: `reflow.audit.record._guardrail_evaluations_payload` copies
`Decision.guardrail_evaluations` verbatim, and nothing in this pipeline drops a passing verdict
before it reaches the trail.

Tamper evidence is a chained SHA-256 hash (`reflow.audit.record.compute_record_hash`: each record
hashes its own fields plus the *previous* record's hash), not a cryptographic signature or an
external ledger -- the cheap option the phase brief explicitly calls for ("tamper-evident if cheap
to do"), and documented plainly (`reflow.audit.store` module docstring) as detection, not
prevention: a flat file editable by anyone with filesystem access cannot be made tamper-*proof* by
hashing alone. `reflow.audit.store.verify_chain` recomputes every hash independently and reports
the first broken link. `reflow.audit.store.AuditTrailWriter` only ever opens its target file in
append (`"a"`) mode and never seeks backward; resuming an existing trail reads only its last line to
recover the chain tip and next sequence number. Every record round-trips through
`reflow.audit.record.to_dict`/`record_from_dict`, always serialised with `sort_keys=True`, so two
runs over the same input produce byte-identical JSONL lines -- "stable enough to diff" by
construction.

**The committed audit trail is a bounded sample, not the full corpus, stated plainly**

ADR-0005's consequences section anticipated Phase 6 persisting "every `Decision` this engine
produces." `reflow.eval.execute.run_benchmark` supports exactly that (`audit_sample_size=None`).
The report this project actually commits uses a bounded, representative sample instead (500 leading
chronological events, plus a guaranteed first example of every guardrail block and every final
action, from a real run of the same pipeline) -- a full 50,000-record JSONL trail is tens of
megabytes for no added demonstration value over a smaller, still-genuinely-generated sample, and
shipping it silently under an "every decision" framing without saying so would misrepresent what is
committed.

**Decision**

Idempotency is deterministic-key-plus-catch-and-recover, not deterministic-key-alone, because the
latter was verified live to fail. Backoff decisions are keyed off transport-captured HTTP status,
never SDK exception type, because the two were verified live to be indistinguishable by type alone.
The audit trail is one flat, hash-chained, append-only JSONL record per decision, recording every
guardrail's verdict whether it passed or blocked, replayable by `reflow replay <payment_id>` from
nothing but the trail file itself.

**Alternatives considered and rejected**

- **Assume `reference_id` behaves like a conventional idempotency key (silent replay) without
  verifying.** Rejected: exactly the failure mode this project's culture exists to catch --
  verified live instead, and the assumption was wrong.
- **Classify retryability from the SDK's exception type.** Rejected: verified live that a genuine
  rate limit and a genuine bad request both raise `BadRequestError` with `code=BAD_REQUEST_ERROR`;
  only the real HTTP status code (429 vs. 400), available only via transport-level capture, tells
  them apart.
- **A `Session` subclass overriding `request()` for transport capture.** Rejected in favour of a
  response hook: the installed `requests` stub's `Session.request` signature is fully, specifically
  typed, and a permissive `**kwargs` override would violate it under `mypy --strict`;
  `Session.hooks["response"]` is `requests`' own documented, type-compatible extension point for
  exactly this need.
- **A cryptographic signature or external ledger for tamper evidence.** Rejected as disproportionate
  to the phase brief's own "if cheap to do" qualifier; a chained hash gives detectable tamper
  evidence at a fraction of the complexity, honestly labelled as detection rather than prevention.
- **Persist the full 50,000-decision audit trail as the committed artifact.** Rejected for
  repository size with no added demonstration value; the code path exists
  (`audit_sample_size=None`) for a caller who wants it, and the committed report states the
  sampling plainly rather than implying completeness.

**Consequences**

- A future Payment Links idempotency-header release from Razorpay (should one ever ship) would let
  `reflow.execute.gateway` drop the catch-and-recover path in favour of a header; until then, every
  duplicate-create attempt costs one extra API call (the recovery lookup) beyond what a true
  idempotency key would need.
- The duplicate-`reference_id` detection matches on the SDK's description *string*, since the SDK
  surfaces nothing more structured -- a future wording change on Razorpay's side could silently stop
  this path from firing. Recorded here as a real fragility, not hidden.
- This decision is revisited if Razorpay ships a documented idempotency mechanism for Payment Link
  creation, or if a production deployment's audit trail volume makes the flat-JSONL-plus-chained
  -hash design's linear resume/verify cost (reading every prior line to find the chain tip) a real
  bottleneck -- at that point a database-backed or periodically-checkpointed design would be the
  natural next step, not built here on speculation.

### ADR-0007: a seeded outcome oracle grounded in remediation class, a sensitivity band instead of
a point estimate, and a model default chosen on measured cost/latency/reliability evidence

**Status:** Accepted (Phase 7)

**Context**

Phases 2-6 built diagnosis, policy, and bounded execution against Razorpay's real test-mode APIs,
but never closed the loop: nothing in this project had, until now, measured whether any decision
actually *recovered* a payment, because nothing had an outcome model to consult. Razorpay's test
mode itself cannot supply one -- it exposes a binary force-success/force-failure toggle per
payment, never a probability, so "does a fresh Payment Link recover a `card_declined` failure 40%
of the time or 60%" is not a question the sandbox can answer. This phase had to decide, honestly
and in writing before building anything, how to simulate outcomes without either inventing
unfounded numbers or refusing to measure anything at all; how to report a claim built on those
numbers without letting one contested assumption carry it; how to finally close the one concrete
gap ADR-0005 named without pretending an offline evaluation had a real decision history it never
had; and which model to ship as Tier 2's default, a question every prior phase deliberately left
open pending exactly this kind of evidence (ADR-0004's Alternatives section, `BUILD_LOG.md`
2026-08-23).

**The oracle is grounded in `Next Steps` semantics, not invented per-reason numbers**

`reflow.outcome.oracle.RecoveryOracle` assigns exactly two free parameters per
`reflow.taxonomy.remediation.RemediationClass` -- ten classes, twenty numbers total, never one
per reason code (110 of those) and never one per action (seven of those, which would have been
a 70-cell matrix invented from nothing): a no-action self-recovery floor
(`_SELF_RECOVERY_RATE`) and a ceiling for the textbook-correct action
(`_ACTION_CEILING`). Both orderings track the taxonomy the same way ADR-0002 and ADR-0004 already
read it by hand: `RETRY_SAME` ("nothing needs fixing, just reattempt") gets this module's highest
floor and ceiling; `MERCHANT_ACTION` and `MERCHANT_CONTACT_RAZORPAY` (the fix is in the merchant's
or Razorpay's court, never the customer's) get its lowest. Whether a *specific* action taken
against a *specific* class earns full credit toward that ceiling or a much smaller, fixed fraction
(`_NONNATIVE_ACTION_FIT`) is decided by asking `reflow.policy.actions.base_action_for` a single
question -- is this the class's own textbook action -- rather than by hand-writing a
ten-class-by-seven-action grid of mostly-unjustifiable numbers. This is the same discipline
ADR-0002 and ADR-0003 already used: measure from what the taxonomy's own text already says,
never fabricate a number merely because a cell in a matrix needs filling.

**A sensitivity band, not a point estimate, because the primary contested claim is "does acting
help, and by how much"**

Every headline number in `docs/reports/phase7_simulation.md` and this ADR is reported at three
points (`SensitivityLevel.PESSIMISTIC` / `CENTRAL` / `OPTIMISTIC`), scaling two distinct
quantities independently: the *uplift* any action provides over its class's floor (the wide band,
`0.6`/`1.0`/`1.4`, since "how effective is a merchant's specific intervention" is exactly what
this whole project exists to measure and is the most contestable number in the oracle), and the
no-action floor itself (the narrower band, `0.8`/`1.0`/`1.2`, since ambient customer behaviour
absent any intervention is a less contested quantity, but still a real assumption that still
moves rather than being pinned immune from doubt). A band that only widened the case *for* acting
would not survive an attack on the one probability held fixed; this project's own governing
principle (results are not fitted to a headline) required scaling both. Every claim in this
project's reports is checked against whether it holds at all three points, and is reported as
holding, or not, honestly either way -- see Evidence below.

**Evidence**

The full closed-loop simulation (`reflow.eval.simulate`, seed `20260822`, 50,000 events, zero
marginal LLM cost since diagnoses are Phase 4's already-committed ones) ran all four compared
policies at all three sensitivity levels. Full results:
`docs/reports/phase7_simulation.{json,md}` and the synthesised phase report
`docs/reports/phase7_evaluation.{json,md}`.

- **reflow never recovers more absolute money than `notify_all`, at any point in the band**
  (pessimistic 96.1%, central 95.0%, optimistic 97.1% of `notify_all`'s rupees) -- reported as a
  loss, not reframed, per this project's first governing principle.
- **reflow always beats `do_nothing`**, at every point in the band, by a wide margin (roughly
  2.1-3.5x `do_nothing`'s recovered rupees across the band).
- **reflow sends 28.4-28.9% fewer contacts than `notify_all`, and 24.6% fewer than the more
  realistic, single-shot `notify_all_once`, across the whole band**, while recovering 95-97% of
  `notify_all`'s money and 98.2-98.8% of `notify_all_once`'s.
- **reflow is cheaper per rupee recovered than both chase baselines at every point in the band**,
  by a stable ~25-26% margin (contacts-per-rupee-recovered 0.000469 vs `notify_all`'s 0.000624 at
  the central estimate).
- **The cost of reflow's guardrails is measured, not just implied.** A one-off, read-only
  counterfactual analysis (built from existing public `reflow` APIs for this ADR and
  `docs/reports/phase7_evaluation.md`, not a change to `reflow.eval.simulate`) scored every
  guardrail-blocked escalatable candidate action against the same payment attempt's same
  deterministic oracle draw. At the central estimate, 1,552 of 9,992 guardrail-blocked events
  (15.5%) would have recovered under the pre-guardrail action per the same oracle, and 1,487 of
  44,674 orders (3.3%) never recovered by any other path as a result. This is named as the
  concrete price of reflow's lower contact volume, not hidden inside an aggregate.

**The closed loop closes the limitation ADR-0005 flagged**

ADR-0005 built the escalation ladder (`reflow.policy.ladder.ladder_action`) and the attempt-cap
guardrail to advance by `PaymentEvent.attempt_number` -- a ground-truth fact about the corpus's
own retry-chain construction -- and said so as a stated limitation, not a hidden one: "this phase
evaluates the policy offline, against a historical corpus the policy has never acted on -- there
is no action history to count. `attempt_number` is the best available proxy... A production
deployment should replace it with genuine decision history once one exists." `reflow.eval.simulate`
is that replacement, arriving in the phase that finally has one. For every event evaluated under
`PolicyName.REFLOW`, the simulation rebuilds it via `dataclasses.replace` with `attempt_number`
overridden to *this order's own count of chase/escalate actions this simulation has actually
decided so far*, before handing it to the unmodified `PolicyEngine.evaluate` -- **zero changes to
`reflow.policy.engine`, `.guardrails`, `.ladder`, or `.decision`**, because ADR-0005's own
parameterisation (accepting `attempt_number` as a plain input) was already correct; the gap was
entirely in the caller, which now exists. The ladder and the attempt-cap guardrail therefore climb
and cap against genuine decision history for the first time in this project, exactly as ADR-0005
anticipated. One residual approximation remains, stated plainly rather than glossed over: this
closed loop's "genuine decision history" starts fresh at the beginning of the simulated window for
every order, since there is no real merchant history predating a corpus's first event to seed it
with -- a real production deployment's first-ever day would have the identical cold start this
simulation has throughout.

**The model default is chosen on measured evidence, not credibility**

`docs/reports/phase7_model_comparison.{json,md}` ran `deepseek/deepseek-v4-flash`,
`google/gemini-3.7-flash`, and `openai/gpt-oss-20b` through the exact same
`reflow.diagnose.ambiguous.AmbiguousReasonDiagnoser` production Tier 2 already uses, live, against
6 ambiguous and 6 deterministic-check reason codes each (36 calls total, $0.021145 actual spend).
The pre-committed rule (lowest total cost among zero-error models, tie-broken by latency) picks
`deepseek/deepseek-v4-flash`: $0.000553 total against `google/gemini-3.7-flash`'s $0.019636 (about
35x) and `openai/gpt-oss-20b`'s $0.000956, a perfect 100% first-attempt JSON validity rate (no
truncated- or invalid-JSON retry ever fired, versus 91.7% and 66.7% for the other two), and
perfect agreement with Tier 1's deterministic table on every sampled already-resolved reason code
(all three models actually agreed 100% of the time here, independent corroboration that those
reasons are genuinely unambiguous, not merely unambiguous to this project's own parser). This
mechanical pick is also the holistic one: `deepseek/deepseek-v4-flash` is the only model of the
three verified live to honour `reasoning_effort="none"` (`BUILD_LOG.md`, 2026-08-22/23), so its
cost pays for a visible answer only, on a call site that is cached per reason code and never sits
on a customer-facing latency path. **`deepseek/deepseek-v4-flash` is adopted as the shipped Tier 2
default.** Reported honestly rather than smoothed over: deepseek had the *highest* mean latency of
the three measured (20.3s, individual calls ranging 3.0-64.8s) despite reasoning being disabled --
slower and far more variable than `google/gemini-3.7-flash`'s 6.7s mean despite that model's 3,136
reasoning tokens of mandatory hidden work. This does not change the recommendation for a cached,
non-latency-critical call site, but a future call site that is latency-sensitive should re-measure
rather than assume cheap implies fast.

**reflow loses on absolute money, and that is the right design, stated plainly**

A system whose guardrails can refuse to act -- during quiet hours, below an amount floor, within
a cooldown window, against a customer already contacted enough, while a rail is a known outage,
against a duplicate or already-settled case -- will, on any oracle that gives an unsolicited chase
message a positive (even if small) chance of independently helping, recover less absolute money
than a policy that never refuses. `notify_all`'s absolute-money win is not a measurement error or
an artefact of an unfair comparison; it is the mechanical, expected consequence of message volume
correlating positively with recovered money in this oracle, and reflow spending fewer messages by
design. The brief's own governing principle is that this project reports what the code actually
does, not what would make the best headline -- so this ADR states outright that reflow is not the
absolute-recovery-maximising policy among the four compared, and defends *why that is the correct
system to ship anyway*: real customer contact has a cost this project's own guardrails exist to
respect (compliance exposure from off-hours messaging, contact fatigue, spend on payments too
small to justify recovery effort, messaging customers about a rail failure that is not their
fault) that a pure rupees-recovered metric does not price in at all. `notify_all` is not a
deployable policy; it is the naive baseline this project was asked to measure against, precisely
so a reader can see what unbounded contact volume buys and at what implied contact cost.

**Decision**

The outcome oracle's two-parameter-per-class design, grounded in the already-existing
`RemediationClass` taxonomy; the three-point, dual-quantity sensitivity band; the closed-loop
`attempt_number` replacement that finally satisfies ADR-0005's stated limitation with zero changes
to `reflow.policy`; and `deepseek/deepseek-v4-flash` as Tier 2's shipped default are all adopted
as designed and measured above. reflow's headline claim is comparable recovery (95-97% of
`notify_all`'s money, 98%+ of `notify_all_once`'s) at materially lower customer-contact cost
(28%+ fewer contacts, ~25% cheaper per rupee recovered), robust across the full sensitivity band
-- not a win on absolute rupees recovered, which it does not claim and does not achieve.

**Alternatives considered and rejected**

- **A hand-written action-by-class probability matrix (seven actions x ten classes, 70 cells).**
  Rejected in favour of the two-parameter-per-class-plus-fit-scalar design: a 70-cell matrix would
  need 70 individually justified numbers, most of which the vendored taxonomy gives no basis to
  distinguish, which is exactly the kind of invented precision this project's culture exists to
  avoid.
- **A single point-estimate oracle, no sensitivity band.** Rejected: a single assumed probability
  set would let one contested number carry the entire project's headline finding, with no way for
  a reader to see how much of the conclusion depends on it. The band costs three simulation runs
  instead of one and directly answers "does this hold if you doubt the uplift assumption by 40%
  in either direction," which a point estimate cannot.
- **Scaling only the uplift band, holding the no-action floor fixed.** Rejected: a band that only
  widens the case *for* acting invites the fair challenge of why the floor alone was held immune
  from the same scrutiny. Both bands move, at different, independently justified widths.
- **A synthetic, simulation-internal action-history counter for the escalation ladder**, rather
  than genuinely replaying decisions in chronological order per order. Rejected: a counter
  maintained separately from the actual sequential decisions made would risk drifting from what
  the policy actually did; walking each order's events in order and counting real decisions taken
  so far is simpler, verifiably correct, and was already the design `reflow.eval.simulate`'s own
  module docstring committed to before this ADR was written.
- **Picking the model default on reputation or prior familiarity rather than measured evidence.**
  Rejected, per ADR-0004's own deferred-decision framing and this project's second governing
  principle: the default is picked from a live, reproducible comparison table
  (`docs/reports/phase7_model_comparison.json`), with the losing candidates' numbers left visible,
  not from which model sounds most credible.
- **Reframing `notify_all`'s absolute-money win as a reflow win by changing the primary metric
  after seeing the result.** Rejected outright, per this project's first governing principle. The
  primary metric was money recovered before this simulation ran; it lost on that metric; that is
  reported as the finding. The contacts-per-rupee and contact-reduction comparisons are reported
  as genuinely separate, real advantages, not as a metric substituted in after the fact to avoid
  reporting a loss.

**Consequences**

- A future phase deploying reflow against real Razorpay traffic replaces this oracle with actual
  observed recovery outcomes the moment they exist, and should expect the *shape* of the finding
  (comparable recovery, materially fewer contacts) to be a more meaningful thing to validate than
  this simulation's exact percentages, which are only as good as the stated, disclosed assumption
  behind them.
- `deepseek/deepseek-v4-flash` remains Tier 2's default only until a future model is verified live
  to also honour `reasoning_effort="none"` at a lower cost, or until a latency-sensitive call site
  is added to Tier 2 that would make this ADR's latency finding decisive rather than incidental.
- The guardrail opportunity-cost analysis in `docs/reports/phase7_evaluation.md` is a one-off
  script built from existing public APIs, not a committed, tested module; a future phase that
  wants this measurement on every run should promote it into `reflow.eval.simulate` proper with
  its own tests, rather than re-deriving it ad hoc each time.
- This decision is revisited if Razorpay's test mode ever exposes a genuine probabilistic outcome
  surface (removing the need for this oracle entirely), or if a production deployment's real
  contact-cost data (compliance fines, unsubscribe/complaint rates, measured contact fatigue)
  becomes available to replace the qualitative case made here for why reflow's lower contact
  volume is worth its absolute-money cost with a quantitative one.
