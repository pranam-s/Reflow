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
