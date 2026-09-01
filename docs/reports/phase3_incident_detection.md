# Phase 3 incident-detection benchmark results

- Generated at: 2026-09-01T10:06:22+00:00
- Command: `uv run python -m reflow.eval.incident`
- Seed: 20260822
- Corpus size: 50000
- Splits: ['train', 'test']
- Library versions: pydantic=2.12.5, python=3.11.15, reflow=0.1.0
- Note: Bucket width is fixed at 15 minutes for every detector and split -- see reflow.incident.aggregate module docstring for the justification.
- Note: The GROUP BY reason baseline reruns the single detector that wins the entity-level comparison (by test-split F1) at (method, bank, reason) granularity, decided after that winner is known -- see this module's docstring for why that is the fair, not a flattering, choice.
- Note: The downtime-correlation demonstration synthesises declared downtimes from this corpus's own ground-truth test-split windows; it is a mechanism/API-coverage demonstration, not an independent validation against real Razorpay declarations -- see _run_downtime_correlation_demo.
- Note: Every reported window-level statistic (precision/recall/F1, time-to-detect) on the test split is computed over a small number of true windows (order 10 at the default corpus size); read its distribution, not only its point estimate.
- Winner (by test-split F1): **fixed_threshold**

## Detector results

| detector | split | n_entities | n_true_windows | n_detected | precision | recall | f1 | event_attr_acc | background_fpr | ttd_median_min | ttd_mean_min | mean_fragments_per_window | fraction_windows_fragmented | runtime_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fixed_threshold | train | 50 | 42 | 159 | 0.264 | 1.000 | 0.418 | 0.998 | 0.021 | 0.000 | 0.197 | 1.00 | 0.000 | 0.1481 |
| rolling_zscore | train | 50 | 42 | 4389 | 0.010 | 1.000 | 0.019 | 0.263 | 0.221 | 0.000 | 1.859 | 1.02 | 0.024 | 0.2419 |
| poisson_surprise | train | 50 | 42 | 99 | 0.495 | 1.000 | 0.662 | 0.734 | 0.010 | 0.000 | 0.826 | 1.17 | 0.167 | 0.2031 |
| ewma_zscore | train | 50 | 42 | 5633 | 0.007 | 0.976 | 0.014 | 0.147 | 0.262 | 0.000 | 0.312 | 0.98 | 0.000 | 0.1782 |
| fixed_threshold | test | 50 | 8 | 8 | 1.000 | 1.000 | 1.000 | 0.997 | 0.001 | 0.000 | 0.000 | 1.00 | 0.000 | 0.0798 |
| rolling_zscore | test | 50 | 8 | 3730 | 0.002 | 1.000 | 0.004 | 0.249 | 0.538 | 0.000 | 0.000 | 1.00 | 0.000 | 0.2657 |
| poisson_surprise | test | 50 | 8 | 17 | 0.471 | 1.000 | 0.640 | 0.766 | 0.004 | 0.000 | 0.000 | 1.00 | 0.000 | 0.1892 |
| ewma_zscore | test | 50 | 8 | 4447 | 0.002 | 1.000 | 0.004 | 0.136 | 0.601 | 0.000 | 0.000 | 1.00 | 0.000 | 0.2485 |

## GROUP BY reason baseline (winning detector, reason-scoped granularity)

| detector | split | n_entities | n_true_windows | n_detected | precision | recall | f1 | event_attr_acc | background_fpr | ttd_median_min | ttd_mean_min | mean_fragments_per_window | fraction_windows_fragmented | runtime_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| groupby_reason+fixed_threshold | train | 2236 | 42 | 158 | 0.994 | 1.000 | 0.997 | 0.951 | 0.001 | 0.000 | 1.337 | 3.74 | 1.000 | 5.3322 |
| groupby_reason+fixed_threshold | test | 1474 | 8 | 37 | 1.000 | 1.000 | 1.000 | 0.937 | 0.000 | 0.000 | 1.329 | 4.62 | 1.000 | 3.3448 |

## Cross-reason claim (ground truth, detector-independent)

| scope | n_windows | n_multi_reason | multi_reason_fraction | mean_invisible_fraction | median_invisible_fraction | overall_invisible_fraction |
| --- | --- | --- | --- | --- | --- | --- |
| all | 50 | 50 | 1.000 | 0.664 | 0.653 | 0.676 |
| train | 42 | 42 | 1.000 | 0.661 | 0.651 | 0.672 |
| test | 8 | 8 | 1.000 | 0.679 | 0.709 | 0.691 |

## Downtime-correlation demonstration (test split, winning detector)

Synthetic declared downtimes are derived from this corpus's own ground-truth test-split windows -- a mechanism/API-coverage demonstration, not an independent validation. See this module's docstring.

- Declared downtimes synthesised: 7
- Detected incidents evaluated: 8
- Detected incidents on a correlatable method: 7
- Detected incidents Razorpay's Downtime API cannot ever declare (Wallet/Cardless EMI/Emandate): 1
- Corroborated by a declared downtime: 7
- Corroboration rate among correlatable incidents: 1.000
