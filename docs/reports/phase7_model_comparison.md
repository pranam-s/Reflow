# Phase 7 model-comparison results

- Generated at: 2026-09-01T03:16:51+00:00
- Command: `uv run --env-file .env python -m reflow.eval.model_compare`
- Models compared: deepseek/deepseek-v4-flash, google/gemini-3.7-flash, openai/gpt-oss-20b
- Ambiguous-reason sample size: 6
- Deterministic-reason sample size: 6
- Sample seed: 20260822
- Library versions: openrouter=0.10.8, pydantic=2.13.4, python=3.11.15, reflow=0.1.0
- Note: This is a small, seeded, labelled sample, not an exhaustive comparison -- see module docstring for the sample-size rationale and the $0.50 Phase 7 spend cap it is bounded by.
- Note: Every model is called through the exact same reflow.diagnose.ambiguous.AmbiguousReasonDiagnoser used in production Tier 2, never a reimplemented prompt, so a difference in the numbers is attributable to the model, not to a divergent harness.
- Note: The deterministic-tier agreement check is an evaluation-only probe: it asks a model to diagnose reason codes Tier 1 already resolves for free, purely to get a ground-truth-backed agreement number, distinct from the judge's plausibility-only endorsement rate elsewhere.
- Note: reasoning_effort='none' is requested only for models verified live to honour it (reflow.eval.model_compare.REASONING_EFFORT_NONE_VERIFIED_MODELS); every other model is left at its provider default with a generous max_completion_tokens, per BUILD_LOG.md 2026-08-22/23.
- Note: The default-model recommendation follows a mechanical, pre-committed selection rule stated in this module's docstring before any live call was made -- see docs/design.md ADR-0007 for whether that mechanical pick agrees with this project's fuller, holistic judgement.

- Ambiguous reasons sampled: card_not_enrolled, compliance_violation, mismatch_in_transaction_details, mobile_number_invalid, payment_method_not_enabled, transaction_daily_count_exceeded
- Deterministic reasons sampled: card_network_not_enabled, collect_on_mcc_blocked, credit_failed, payment_declined_due_to_high_traffic, payment_timed_out, upi_collect_not_enabled

## Aggregate comparison

| model | calls | errors | total cost | mean latency (s) | total reasoning tokens | mean reasoning tokens | first-attempt JSON valid | deterministic agreement |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek/deepseek-v4-flash | 12 | 0 | $0.000553 | 20.303 | 0 | 0.0 | 1.0000 | 1.0000 |
| google/gemini-3.7-flash | 12 | 0 | $0.019636 | 6.707 | 3136 | 261.3 | 0.9167 | 1.0000 |
| openai/gpt-oss-20b | 12 | 0 | $0.000956 | 15.599 | 4599 | 383.2 | 0.6667 | 1.0000 |

**Recommended default model: `deepseek/deepseek-v4-flash`**

Pre-committed rule: among models with zero call errors, pick the lowest total measured cost, tie-broken by lower mean latency. deepseek/deepseek-v4-flash wins at $0.000553 total across 12 calls, 20.303s mean latency.

## deepseek/deepseek-v4-flash: per-call detail

| reason | kind | model class | expected class | agrees | confidence | cost | latency (s) | reasoning tokens | attempts | finish_reason | error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| card_not_enrolled | ambiguous | different_instrument_or_method | n/a | None | high | 0.000084 | 2.995 | 0 | 1 | stop |  |
| compliance_violation | ambiguous | merchant_contact_razorpay | n/a | None | low | 0.000041 | 4.225 | 0 | 1 | stop |  |
| mismatch_in_transaction_details | ambiguous | merchant_action | n/a | None | low | 0.000036 | 33.860 | 0 | 1 | stop |  |
| mobile_number_invalid | ambiguous | customer_fix | n/a | None | high | 0.000050 | 64.822 | 0 | 1 | stop |  |
| payment_method_not_enabled | ambiguous | merchant_contact_razorpay | n/a | None | high | 0.000034 | 32.256 | 0 | 1 | stop |  |
| transaction_daily_count_exceeded | ambiguous | wait | n/a | None | high | 0.000039 | 44.236 | 0 | 1 | stop |  |
| card_network_not_enabled | deterministic_check | merchant_contact_razorpay | merchant_contact_razorpay | True | high | 0.000051 | 4.079 | 0 | 1 | stop |  |
| collect_on_mcc_blocked | deterministic_check | different_method | different_method | True | low | 0.000024 | 9.408 | 0 | 1 | stop |  |
| credit_failed | deterministic_check | customer_fix | customer_fix | True | high | 0.000032 | 29.195 | 0 | 1 | stop |  |
| payment_declined_due_to_high_traffic | deterministic_check | retry_same | retry_same | True | high | 0.000033 | 3.985 | 0 | 1 | stop |  |
| payment_timed_out | deterministic_check | retry_same | retry_same | True | high | 0.000027 | 11.907 | 0 | 1 | stop |  |
| upi_collect_not_enabled | deterministic_check | merchant_action | merchant_action | True | high | 0.000103 | 2.662 | 0 | 1 | stop |  |

## google/gemini-3.7-flash: per-call detail

| reason | kind | model class | expected class | agrees | confidence | cost | latency (s) | reasoning tokens | attempts | finish_reason | error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| card_not_enrolled | ambiguous | different_instrument_or_method | n/a | None | high | 0.002501 | 14.516 | 477 | 2 | stop |  |
| compliance_violation | ambiguous | merchant_contact_razorpay | n/a | None | medium | 0.002280 | 7.089 | 384 | 1 | stop |  |
| mismatch_in_transaction_details | ambiguous | merchant_action | n/a | None | medium | 0.001579 | 9.005 | 228 | 1 | stop |  |
| mobile_number_invalid | ambiguous | customer_contact_issuer_bank | n/a | None | high | 0.002687 | 10.146 | 517 | 1 | stop |  |
| payment_method_not_enabled | ambiguous | merchant_contact_razorpay | n/a | None | high | 0.001712 | 7.008 | 275 | 1 | stop |  |
| transaction_daily_count_exceeded | ambiguous | different_instrument_or_method | n/a | None | high | 0.001856 | 4.768 | 323 | 1 | stop |  |
| card_network_not_enabled | deterministic_check | merchant_contact_razorpay | merchant_contact_razorpay | True | high | 0.001043 | 3.789 | 116 | 1 | stop |  |
| collect_on_mcc_blocked | deterministic_check | different_method | different_method | True | high | 0.001223 | 8.499 | 174 | 1 | stop |  |
| credit_failed | deterministic_check | customer_fix | customer_fix | True | high | 0.001123 | 4.199 | 142 | 1 | stop |  |
| payment_declined_due_to_high_traffic | deterministic_check | retry_same | retry_same | True | high | 0.001273 | 3.151 | 184 | 1 | stop |  |
| payment_timed_out | deterministic_check | retry_same | retry_same | True | high | 0.001337 | 4.736 | 206 | 1 | stop |  |
| upi_collect_not_enabled | deterministic_check | merchant_action | merchant_action | True | high | 0.001020 | 3.582 | 110 | 1 | stop |  |

## openai/gpt-oss-20b: per-call detail

| reason | kind | model class | expected class | agrees | confidence | cost | latency (s) | reasoning tokens | attempts | finish_reason | error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| card_not_enrolled | ambiguous | customer_fix | n/a | None | high | 0.000086 | 27.338 | 563 | 2 | stop |  |
| compliance_violation | ambiguous | merchant_contact_razorpay | n/a | None | high | 0.000050 | 13.418 | 191 | 1 | stop |  |
| mismatch_in_transaction_details | ambiguous | merchant_action | n/a | None | high | 0.000051 | 16.147 | 287 | 1 | stop |  |
| mobile_number_invalid | ambiguous | customer_contact_issuer_bank | n/a | None | high | 0.000069 | 20.466 | 439 | 2 | stop |  |
| payment_method_not_enabled | ambiguous | merchant_contact_razorpay | n/a | None | high | 0.000279 | 15.713 | 697 | 2 | stop |  |
| transaction_daily_count_exceeded | ambiguous | different_instrument_or_method | n/a | None | high | 0.000208 | 35.946 | 1425 | 2 | stop |  |
| card_network_not_enabled | deterministic_check | merchant_contact_razorpay | merchant_contact_razorpay | True | high | 0.000026 | 2.321 | 70 | 1 | stop |  |
| collect_on_mcc_blocked | deterministic_check | different_method | different_method | True | high | 0.000047 | 5.459 | 256 | 1 | stop |  |
| credit_failed | deterministic_check | customer_fix | customer_fix | True | high | 0.000051 | 16.227 | 305 | 1 | stop |  |
| payment_declined_due_to_high_traffic | deterministic_check | retry_same | retry_same | True | high | 0.000031 | 13.264 | 130 | 1 | stop |  |
| payment_timed_out | deterministic_check | retry_same | retry_same | True | high | 0.000029 | 16.488 | 124 | 1 | stop |  |
| upi_collect_not_enabled | deterministic_check | merchant_action | merchant_action | True | high | 0.000029 | 4.401 | 112 | 1 | stop |  |
