# Phase 2 clustering bake-off results

- Generated at: 2026-08-22T19:16:26+00:00
- Command: `uv run python -m reflow.eval.clustering`
- Seed: 20260822
- Corpus size: 50000
- Richness levels swept: [1, 3, 5]
- Arms swept: ['transparent', 'opaque']
- Library versions: drain3=0.9.11, numpy=2.4.6, python=3.11.15, reflow=0.1.0, scikit-learn=1.9.0, scipy=1.17.1
- Note: The three genuine clusterers are run only on the catch-all stratum (observed as ~8,000 of 50,000 events at this seed), never the full corpus; GROUP BY is run on the full corpus. See the 'Scope' section of this module's docstring for why.
- Note: The noise/outlier-handling diagnostic table is a supplementary, out-of-primary-scope measurement on a subsample of the narrow stratum (target size 4,000, every true outlier deliberately kept -- see _sample_narrow_stratum_for_noise_diagnostic), not the primary catch-all bake-off, because PaymentEvent.is_outlier is never True for a catch-all reason by corpus design. Its precision figures are inflated relative to true deployment outlier prevalence by the deliberate enrichment; recall is not.
- Note: TfidfHdbscanClusterer's cosine-metric HDBSCAN computes pairwise distances by brute force (O(n^2); cosine has no KD-tree/ball-tree support), which is tractable at the catch-all stratum's actual observed size (~8,000) but would not scale to a literal 50,000-event catch-all stratum without further subsampling, a different metric, or a dimensionality-reduction step.

## Results by candidate x richness x arm x stratum

| candidate | richness | arm | stratum | n | purity | nmi | ari | pred_clusters | true_clusters | noise_recall | noise_precision | runtime_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| groupby_reason | 1 | transparent | catchall | 8004 | 0.319 | 0.652 | 0.325 | 17 | 32 | n/a | n/a | 0.0167 |
| groupby_reason | 1 | transparent | narrow | 41996 | 1.000 | 0.983 | 0.981 | 140 | 102 | 0.000 | n/a | 0.0167 |
| drain3 | 1 | transparent | catchall | 8004 | 0.888 | 0.970 | 0.878 | 28 | 32 | n/a | n/a | 0.0580 |
| template_hash | 1 | transparent | catchall | 8004 | 1.000 | 1.000 | 1.000 | 32 | 32 | n/a | n/a | 0.0653 |
| tfidf_hdbscan | 1 | transparent | catchall | 8004 | 1.000 | 1.000 | 1.000 | 32 | 32 | n/a | n/a | 2.4009 |
| groupby_reason | 1 | opaque | catchall | 8004 | 0.319 | 0.652 | 0.325 | 17 | 32 | n/a | n/a | 0.0241 |
| groupby_reason | 1 | opaque | narrow | 41996 | 1.000 | 0.983 | 0.981 | 140 | 102 | 0.000 | n/a | 0.0241 |
| drain3 | 1 | opaque | catchall | 8004 | 0.296 | 0.613 | 0.311 | 20 | 32 | n/a | n/a | 0.0663 |
| template_hash | 1 | opaque | catchall | 8004 | 0.320 | 0.647 | 0.325 | 24 | 32 | n/a | n/a | 0.0446 |
| tfidf_hdbscan | 1 | opaque | catchall | 8004 | 0.320 | 0.647 | 0.325 | 24 | 32 | n/a | n/a | 2.8202 |
| groupby_reason | 3 | transparent | catchall | 8004 | 0.319 | 0.652 | 0.325 | 17 | 32 | n/a | n/a | 0.0311 |
| groupby_reason | 3 | transparent | narrow | 41996 | 1.000 | 0.983 | 0.981 | 140 | 102 | 0.000 | n/a | 0.0311 |
| drain3 | 3 | transparent | catchall | 8004 | 0.932 | 0.846 | 0.551 | 91 | 32 | n/a | n/a | 0.0814 |
| template_hash | 3 | transparent | catchall | 8004 | 1.000 | 0.864 | 0.591 | 96 | 32 | n/a | n/a | 0.0823 |
| tfidf_hdbscan | 3 | transparent | catchall | 8004 | 1.000 | 0.867 | 0.595 | 92 | 32 | n/a | n/a | 2.2887 |
| groupby_reason | 3 | opaque | catchall | 8004 | 0.319 | 0.652 | 0.325 | 17 | 32 | n/a | n/a | 0.0322 |
| groupby_reason | 3 | opaque | narrow | 41996 | 1.000 | 0.983 | 0.981 | 140 | 102 | 0.000 | n/a | 0.0322 |
| drain3 | 3 | opaque | catchall | 8004 | 0.296 | 0.613 | 0.311 | 20 | 32 | n/a | n/a | 0.0739 |
| template_hash | 3 | opaque | catchall | 8004 | 0.320 | 0.647 | 0.325 | 24 | 32 | n/a | n/a | 0.0467 |
| tfidf_hdbscan | 3 | opaque | catchall | 8004 | 0.320 | 0.647 | 0.325 | 24 | 32 | n/a | n/a | 2.6712 |
| groupby_reason | 5 | transparent | catchall | 8004 | 0.319 | 0.652 | 0.325 | 17 | 32 | n/a | n/a | 0.0314 |
| groupby_reason | 5 | transparent | narrow | 41996 | 1.000 | 0.983 | 0.981 | 140 | 102 | 0.000 | n/a | 0.0314 |
| drain3 | 5 | transparent | catchall | 8004 | 0.938 | 0.802 | 0.440 | 153 | 32 | n/a | n/a | 0.0930 |
| template_hash | 5 | transparent | catchall | 8004 | 1.000 | 0.818 | 0.467 | 160 | 32 | n/a | n/a | 0.0577 |
| tfidf_hdbscan | 5 | transparent | catchall | 8004 | 0.997 | 0.819 | 0.470 | 141 | 32 | n/a | 0.000 | 2.1551 |
| groupby_reason | 5 | opaque | catchall | 8004 | 0.319 | 0.652 | 0.325 | 17 | 32 | n/a | n/a | 0.0247 |
| groupby_reason | 5 | opaque | narrow | 41996 | 1.000 | 0.983 | 0.981 | 140 | 102 | 0.000 | n/a | 0.0247 |
| drain3 | 5 | opaque | catchall | 8004 | 0.296 | 0.613 | 0.311 | 20 | 32 | n/a | n/a | 0.0876 |
| template_hash | 5 | opaque | catchall | 8004 | 0.320 | 0.647 | 0.325 | 24 | 32 | n/a | n/a | 0.0481 |
| tfidf_hdbscan | 5 | opaque | catchall | 8004 | 0.320 | 0.647 | 0.325 | 24 | 32 | n/a | n/a | 2.8845 |

## Axis C: catch-all-share crossover vs GROUP BY

| candidate | richness | arm | metric | candidate_catchall | groupby_catchall | groupby_narrow | crossover_share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| drain3 | 1 | transparent | purity | 0.888 | 0.319 | 1.000 | 0.001 |
| drain3 | 1 | transparent | nmi | 0.970 | 0.652 | 0.983 | 0.001 |
| drain3 | 1 | transparent | ari | 0.878 | 0.325 | 0.981 | 0.001 |
| template_hash | 1 | transparent | purity | 1.000 | 0.319 | 1.000 | 0.001 |
| template_hash | 1 | transparent | nmi | 1.000 | 0.652 | 0.983 | 0.001 |
| template_hash | 1 | transparent | ari | 1.000 | 0.325 | 0.981 | 0.001 |
| tfidf_hdbscan | 1 | transparent | purity | 1.000 | 0.319 | 1.000 | 0.001 |
| tfidf_hdbscan | 1 | transparent | nmi | 1.000 | 0.652 | 0.983 | 0.001 |
| tfidf_hdbscan | 1 | transparent | ari | 1.000 | 0.325 | 0.981 | 0.001 |
| drain3 | 1 | opaque | purity | 0.296 | 0.319 | 1.000 | never |
| drain3 | 1 | opaque | nmi | 0.613 | 0.652 | 0.983 | never |
| drain3 | 1 | opaque | ari | 0.311 | 0.325 | 0.981 | never |
| template_hash | 1 | opaque | purity | 0.320 | 0.319 | 1.000 | 0.001 |
| template_hash | 1 | opaque | nmi | 0.647 | 0.652 | 0.983 | never |
| template_hash | 1 | opaque | ari | 0.325 | 0.325 | 0.981 | never |
| tfidf_hdbscan | 1 | opaque | purity | 0.320 | 0.319 | 1.000 | 0.001 |
| tfidf_hdbscan | 1 | opaque | nmi | 0.647 | 0.652 | 0.983 | never |
| tfidf_hdbscan | 1 | opaque | ari | 0.325 | 0.325 | 0.981 | never |
| drain3 | 3 | transparent | purity | 0.932 | 0.319 | 1.000 | 0.001 |
| drain3 | 3 | transparent | nmi | 0.846 | 0.652 | 0.983 | 0.001 |
| drain3 | 3 | transparent | ari | 0.551 | 0.325 | 0.981 | 0.001 |
| template_hash | 3 | transparent | purity | 1.000 | 0.319 | 1.000 | 0.001 |
| template_hash | 3 | transparent | nmi | 0.864 | 0.652 | 0.983 | 0.001 |
| template_hash | 3 | transparent | ari | 0.591 | 0.325 | 0.981 | 0.001 |
| tfidf_hdbscan | 3 | transparent | purity | 1.000 | 0.319 | 1.000 | 0.001 |
| tfidf_hdbscan | 3 | transparent | nmi | 0.867 | 0.652 | 0.983 | 0.001 |
| tfidf_hdbscan | 3 | transparent | ari | 0.595 | 0.325 | 0.981 | 0.001 |
| drain3 | 3 | opaque | purity | 0.296 | 0.319 | 1.000 | never |
| drain3 | 3 | opaque | nmi | 0.613 | 0.652 | 0.983 | never |
| drain3 | 3 | opaque | ari | 0.311 | 0.325 | 0.981 | never |
| template_hash | 3 | opaque | purity | 0.320 | 0.319 | 1.000 | 0.001 |
| template_hash | 3 | opaque | nmi | 0.647 | 0.652 | 0.983 | never |
| template_hash | 3 | opaque | ari | 0.325 | 0.325 | 0.981 | never |
| tfidf_hdbscan | 3 | opaque | purity | 0.320 | 0.319 | 1.000 | 0.001 |
| tfidf_hdbscan | 3 | opaque | nmi | 0.647 | 0.652 | 0.983 | never |
| tfidf_hdbscan | 3 | opaque | ari | 0.325 | 0.325 | 0.981 | never |
| drain3 | 5 | transparent | purity | 0.938 | 0.319 | 1.000 | 0.001 |
| drain3 | 5 | transparent | nmi | 0.802 | 0.652 | 0.983 | 0.001 |
| drain3 | 5 | transparent | ari | 0.440 | 0.325 | 0.981 | 0.001 |
| template_hash | 5 | transparent | purity | 1.000 | 0.319 | 1.000 | 0.001 |
| template_hash | 5 | transparent | nmi | 0.818 | 0.652 | 0.983 | 0.001 |
| template_hash | 5 | transparent | ari | 0.467 | 0.325 | 0.981 | 0.001 |
| tfidf_hdbscan | 5 | transparent | purity | 0.997 | 0.319 | 1.000 | 0.001 |
| tfidf_hdbscan | 5 | transparent | nmi | 0.819 | 0.652 | 0.983 | 0.001 |
| tfidf_hdbscan | 5 | transparent | ari | 0.470 | 0.325 | 0.981 | 0.001 |
| drain3 | 5 | opaque | purity | 0.296 | 0.319 | 1.000 | never |
| drain3 | 5 | opaque | nmi | 0.613 | 0.652 | 0.983 | never |
| drain3 | 5 | opaque | ari | 0.311 | 0.325 | 0.981 | never |
| template_hash | 5 | opaque | purity | 0.320 | 0.319 | 1.000 | 0.001 |
| template_hash | 5 | opaque | nmi | 0.647 | 0.652 | 0.983 | never |
| template_hash | 5 | opaque | ari | 0.325 | 0.325 | 0.981 | never |
| tfidf_hdbscan | 5 | opaque | purity | 0.320 | 0.319 | 1.000 | 0.001 |
| tfidf_hdbscan | 5 | opaque | nmi | 0.647 | 0.652 | 0.983 | never |
| tfidf_hdbscan | 5 | opaque | ari | 0.325 | 0.325 | 0.981 | never |

## Supplementary: noise/outlier-handling diagnostic (narrow stratum sample)

| candidate | n | true_outliers | predicted_noise | recall | precision | runtime_s |
| --- | --- | --- | --- | --- | --- | --- |
| drain3 | 4000 | 37 | 0 | 0.000 | n/a | 0.0360 |
| template_hash | 4000 | 37 | 0 | 0.000 | n/a | 0.0198 |
| tfidf_hdbscan | 4000 | 37 | 42 | 0.054 | 0.048 | 0.6409 |
