# Phase 4 diagnosis-tier benchmark results

- Generated at: 2026-08-22T22:14:00+00:00
- Command: `uv run --env-file .env python -m reflow.eval.diagnose`
- Seed: 20260822
- Corpus size: 50000
- Tier 2 model: **deepseek/deepseek-v4-flash**
- Judge model: **openai/gpt-oss-20b**
- Judge sample size (per category): 8
- Library versions: openrouter=0.10.8, pydantic=2.13.4, python=3.11.15, reflow=0.1.0
- Note: Tier 1 covers 95 of 110 distinct reason codes; 15 escalate to Tier 2's cached per-reason LLM call -- one more than the taxonomy's own 14 row-flagged-ambiguous rows, because payment_method_not_enabled's two vendored rows are each individually unambiguous but disagree with each other, an ambiguity only visible when reconciling by reason code (see reflow.diagnose.tier1 module docstring).
- Note: Incident diagnoses run the ADR-0003-recommended poisson_surprise detector at (method, bank) granularity over the full generated corpus, then call the LLM once per detected incident, uncached, since no two incidents share an entity/window/reason-code mix.
- Note: The ambiguous-reason LLM cost is a one-time cost: the 15 escalated reason codes are fixed by the vendored taxonomy, not by corpus size, so it is paid at most once ever and then served from cache. The incident-diagnosis cost scales with detected-incident volume, which scales with corpus size/time span. Both are reported separately, and combined two ways: a cold-cache projection (includes the one-time ambiguous-reason cost) and a warm-cache projection (steady state, excludes it) -- see CostSummary.
- Note: The judge model is a different family from the Tier 2 model under test, to avoid self-preference bias, and scores a fixed-size seeded sample of diagnoses rather than every diagnosis produced.

## Routing split (the headline metric)

- Total events routed: 50000
- Deterministic (Tier 1): 43028 (86.0560%)
- Escalated to LLM (Tier 2): 6972 (13.9440%)
- Distinct reason codes seen: 110
- Live LLM calls made to resolve ambiguous reasons: 15
- Escalated reason codes: authorisation_declined_by_psp, card_not_enrolled, compliance_violation, credit_limit_inactive, gateway_technical_error, input_validation_failed, invalid_response_from_gateway, issuer_technical_error, mismatch_in_transaction_details, mobile_number_invalid, payment_method_not_enabled, server_error, transaction_daily_count_exceeded, transaction_daily_limit_exceeded, upi_app_technical_error

## Cost

- Ambiguous-reason calls (one-time): 15
- Ambiguous-reason cost (one-time): $0.000814
- Incidents detected in this run (50000 events): 113
- Incidents actually diagnosed (live calls): 113
- Incident-diagnosis cost (this run): $0.006948
- Judge calls: 16
- Judge cost: $0.001340
- **Actual total spend this run: $0.009102**
- Projected production cost per 100,000 events, cold cache (first-ever run): $0.014710
- Projected production cost per 100,000 events, warm cache (steady state): $0.013896

## Ambiguous-reason diagnoses (Tier 2, cached)

| reason | remediation_class | confidence | cost | reasoning_tokens |
| --- | --- | --- | --- | --- |
| authorisation_declined_by_psp | customer_fix | high | 0.000028 | 0 |
| card_not_enrolled | customer_fix | high | 0.000083 | 0 |
| compliance_violation | merchant_contact_razorpay | low | 0.000041 | 0 |
| credit_limit_inactive | customer_fix | high | 0.000026 | 0 |
| gateway_technical_error | different_method | medium | 0.000050 | 0 |
| input_validation_failed | merchant_action | high | 0.000044 | 0 |
| invalid_response_from_gateway | retry_same | low | 0.000030 | 0 |
| issuer_technical_error | different_method | medium | 0.000122 | 0 |
| mismatch_in_transaction_details | merchant_action | high | 0.000039 | 0 |
| mobile_number_invalid | customer_fix | high | 0.000079 | 0 |
| payment_method_not_enabled | merchant_contact_razorpay | high | 0.000045 | 0 |
| server_error | wait | high | 0.000039 | 0 |
| transaction_daily_count_exceeded | different_instrument_or_method | high | 0.000041 | 0 |
| transaction_daily_limit_exceeded | different_instrument_or_method | medium | 0.000120 | 0 |
| upi_app_technical_error | retry_same | low | 0.000026 | 0 |

## Incident diagnoses (Tier 2, uncached)

| incident | method | bank | total_count | posture | confidence | cost |
| --- | --- | --- | --- | --- | --- | --- |
| 000_card_State Bank of India_2026-07-30T03:00:00 | card | State Bank of India | 3 | monitor | low | 0.000048 |
| 001_card_State Bank of India_2026-08-06T11:00:00 | card | State Bank of India | 3 | contact_provider | high | 0.000069 |
| 002_card_State Bank of India_2026-08-10T22:00:00 | card | State Bank of India | 3 | contact_provider | high | 0.000067 |
| 003_upi_Kotak Mahindra Bank_2026-07-24T11:45:00 | upi | Kotak Mahindra Bank | 5 | contact_provider | high | 0.000088 |
| 004_upi_Kotak Mahindra Bank_2026-08-02T14:15:00 | upi | Kotak Mahindra Bank | 5 | contact_provider | high | 0.000084 |
| 005_upi_Kotak Mahindra Bank_2026-08-04T02:00:00 | upi | Kotak Mahindra Bank | 58 | contact_provider | high | 0.000038 |
| 006_upi_Kotak Mahindra Bank_2026-08-10T15:30:00 | upi | Kotak Mahindra Bank | 140 | contact_provider | high | 0.000072 |
| 007_upi_Kotak Mahindra Bank_2026-08-10T17:45:00 | upi | Kotak Mahindra Bank | 124 | contact_provider | high | 0.000034 |
| 008_upi_Kotak Mahindra Bank_2026-08-15T16:00:00 | upi | Kotak Mahindra Bank | 188 | contact_provider | high | 0.000071 |
| 009_upi_Kotak Mahindra Bank_2026-08-18T08:15:00 | upi | Kotak Mahindra Bank | 171 | contact_provider | high | 0.000052 |
| 010_upi_Kotak Mahindra Bank_2026-08-18T20:00:00 | upi | Kotak Mahindra Bank | 225 | contact_provider | high | 0.000050 |
| 011_upi_Kotak Mahindra Bank_2026-08-19T06:30:00 | upi | Kotak Mahindra Bank | 6 | contact_provider | high | 0.000072 |
| 012_upi_Kotak Mahindra Bank_2026-08-19T15:15:00 | upi | Kotak Mahindra Bank | 5 | failover_method | high | 0.000039 |
| 013_upi_Yes Bank_2026-07-24T23:00:00 | upi | Yes Bank | 61 | contact_provider | high | 0.000048 |
| 014_upi_Yes Bank_2026-08-06T07:15:00 | upi | Yes Bank | 109 | contact_provider | high | 0.000036 |
| 015_upi_Yes Bank_2026-08-12T18:00:00 | upi | Yes Bank | 5 | contact_provider | high | 0.000087 |
| 016_card_Punjab National Bank_2026-07-23T06:30:00 | card | Punjab National Bank | 3 | monitor | high | 0.000048 |
| 017_card_Punjab National Bank_2026-07-29T08:45:00 | card | Punjab National Bank | 168 | contact_provider | high | 0.000053 |
| 018_upi_State Bank of India_2026-07-26T07:45:00 | upi | State Bank of India | 28 | contact_provider | high | 0.000069 |
| 019_upi_State Bank of India_2026-08-02T05:30:00 | upi | State Bank of India | 168 | contact_provider | high | 0.000080 |
| 020_upi_State Bank of India_2026-08-08T01:30:00 | upi | State Bank of India | 259 | contact_provider | high | 0.000070 |
| 021_upi_State Bank of India_2026-08-09T18:30:00 | upi | State Bank of India | 5 | contact_provider | high | 0.000070 |
| 022_upi_State Bank of India_2026-08-10T00:00:00 | upi | State Bank of India | 5 | contact_provider | medium | 0.000136 |
| 023_upi_State Bank of India_2026-08-10T19:45:00 | upi | State Bank of India | 45 | contact_provider | high | 0.000036 |
| 024_card_IndusInd Bank_2026-07-26T03:30:00 | card | IndusInd Bank | 4 | contact_provider | high | 0.000093 |
| 025_card_IndusInd Bank_2026-08-19T06:00:00 | card | IndusInd Bank | 3 | contact_provider | high | 0.000033 |
| 026_card_ICICI Bank_2026-07-31T12:00:00 | card | ICICI Bank | 165 | contact_provider | high | 0.000045 |
| 027_card_ICICI Bank_2026-08-10T17:45:00 | card | ICICI Bank | 3 | contact_provider | medium | 0.000069 |
| 028_card_ICICI Bank_2026-08-15T01:15:00 | card | ICICI Bank | 4 | contact_provider | high | 0.000054 |
| 029_card_ICICI Bank_2026-08-16T20:00:00 | card | ICICI Bank | 3 | contact_provider | medium | 0.000071 |
| 030_card_Yes Bank_2026-07-26T00:15:00 | card | Yes Bank | 3 | contact_provider | high | 0.000067 |
| 031_card_Yes Bank_2026-08-01T02:45:00 | card | Yes Bank | 3 | contact_provider | high | 0.000042 |
| 032_card_Yes Bank_2026-08-08T00:15:00 | card | Yes Bank | 4 | contact_provider | high | 0.000067 |
| 033_card_Yes Bank_2026-08-10T19:15:00 | card | Yes Bank | 3 | contact_provider | high | 0.000069 |
| 034_card_Yes Bank_2026-08-18T14:15:00 | card | Yes Bank | 3 | contact_provider | high | 0.000033 |
| 035_upi_IDFC FIRST Bank_2026-07-28T06:30:00 | upi | IDFC FIRST Bank | 4 | contact_provider | high | 0.000033 |
| 036_upi_IDFC FIRST Bank_2026-07-31T14:45:00 | upi | IDFC FIRST Bank | 104 | contact_provider | high | 0.000074 |
| 037_upi_IDFC FIRST Bank_2026-08-05T17:45:00 | upi | IDFC FIRST Bank | 197 | contact_provider | high | 0.000110 |
| 038_upi_IDFC FIRST Bank_2026-08-06T00:45:00 | upi | IDFC FIRST Bank | 183 | contact_provider | high | 0.000047 |
| 039_upi_HDFC Bank_2026-07-31T01:45:00 | upi | HDFC Bank | 5 | contact_provider | high | 0.000072 |
| 040_upi_HDFC Bank_2026-08-08T07:45:00 | upi | HDFC Bank | 6 | failover_method | high | 0.000051 |
| 041_card_Union Bank of India_2026-07-23T06:00:00 | card | Union Bank of India | 128 | contact_provider | high | 0.000068 |
| 042_card_Union Bank of India_2026-08-16T01:15:00 | card | Union Bank of India | 158 | contact_provider | high | 0.000037 |
| 043_card_Union Bank of India_2026-08-16T15:30:00 | card | Union Bank of India | 3 | monitor | medium | 0.000035 |
| 044_card_Union Bank of India_2026-08-19T22:30:00 | card | Union Bank of India | 3 | contact_provider | high | 0.000037 |
| 045_upi_Axis Bank_2026-08-02T02:15:00 | upi | Axis Bank | 5 | contact_provider | high | 0.000078 |
| 046_upi_Axis Bank_2026-08-07T18:15:00 | upi | Axis Bank | 4 | contact_provider | high | 0.000070 |
| 047_upi_Axis Bank_2026-08-09T13:45:00 | upi | Axis Bank | 6 | contact_provider | high | 0.000036 |
| 048_upi_Axis Bank_2026-08-10T04:45:00 | upi | Axis Bank | 4 | contact_provider | high | 0.000105 |
| 049_wallet_nobank_2026-08-02T16:00:00 | wallet | n/a | 21 | contact_provider | high | 0.000039 |
| 050_wallet_nobank_2026-08-04T15:00:00 | wallet | n/a | 164 | contact_provider | high | 0.000043 |
| 051_wallet_nobank_2026-08-11T01:15:00 | wallet | n/a | 185 | contact_provider | high | 0.000042 |
| 052_wallet_nobank_2026-08-17T10:00:00 | wallet | n/a | 94 | contact_provider | high | 0.000092 |
| 053_wallet_nobank_2026-08-17T11:45:00 | wallet | n/a | 126 | monitor | medium | 0.000055 |
| 054_upi_ICICI Bank_2026-07-23T03:45:00 | upi | ICICI Bank | 5 | contact_provider | high | 0.000060 |
| 055_upi_ICICI Bank_2026-07-26T20:45:00 | upi | ICICI Bank | 6 | contact_provider | high | 0.000039 |
| 056_upi_ICICI Bank_2026-08-02T04:00:00 | upi | ICICI Bank | 30 | contact_provider | high | 0.000042 |
| 057_upi_ICICI Bank_2026-08-02T05:45:00 | upi | ICICI Bank | 92 | contact_provider | high | 0.000038 |
| 058_upi_ICICI Bank_2026-08-09T03:00:00 | upi | ICICI Bank | 117 | failover_method | high | 0.000083 |
| 059_upi_ICICI Bank_2026-08-09T04:45:00 | upi | ICICI Bank | 50 | contact_provider | high | 0.000068 |
| 060_upi_ICICI Bank_2026-08-13T01:15:00 | upi | ICICI Bank | 181 | contact_provider | high | 0.000046 |
| 061_cardless_emi_nobank_2026-07-31T16:00:00 | cardless_emi | n/a | 5 | monitor | medium | 0.000055 |
| 062_cardless_emi_nobank_2026-08-10T22:30:00 | cardless_emi | n/a | 157 | contact_provider | high | 0.000047 |
| 063_cardless_emi_nobank_2026-08-14T06:00:00 | cardless_emi | n/a | 3 | contact_provider | high | 0.000078 |
| 064_card_IDFC FIRST Bank_2026-07-24T08:45:00 | card | IDFC FIRST Bank | 131 | contact_provider | high | 0.000046 |
| 065_card_IDFC FIRST Bank_2026-07-26T14:45:00 | card | IDFC FIRST Bank | 3 | contact_provider | high | 0.000034 |
| 066_card_IDFC FIRST Bank_2026-08-04T08:45:00 | card | IDFC FIRST Bank | 3 | contact_provider | high | 0.000057 |
| 067_card_IDFC FIRST Bank_2026-08-09T13:30:00 | card | IDFC FIRST Bank | 3 | monitor | high | 0.000059 |
| 068_upi_IndusInd Bank_2026-07-28T13:45:00 | upi | IndusInd Bank | 5 | contact_provider | high | 0.000079 |
| 069_upi_IndusInd Bank_2026-07-30T19:00:00 | upi | IndusInd Bank | 5 | contact_provider | high | 0.000090 |
| 070_upi_IndusInd Bank_2026-08-01T01:00:00 | upi | IndusInd Bank | 163 | contact_provider | high | 0.000105 |
| 071_upi_IndusInd Bank_2026-08-09T10:45:00 | upi | IndusInd Bank | 173 | contact_provider | high | 0.000039 |
| 072_upi_IndusInd Bank_2026-08-10T12:45:00 | upi | IndusInd Bank | 225 | contact_provider | high | 0.000075 |
| 073_upi_IndusInd Bank_2026-08-13T00:30:00 | upi | IndusInd Bank | 4 | contact_provider | high | 0.000090 |
| 074_upi_IndusInd Bank_2026-08-14T13:30:00 | upi | IndusInd Bank | 4 | contact_provider | high | 0.000055 |
| 075_upi_IndusInd Bank_2026-08-17T13:45:00 | upi | IndusInd Bank | 240 | contact_provider | high | 0.000046 |
| 076_upi_IndusInd Bank_2026-08-19T16:00:00 | upi | IndusInd Bank | 178 | contact_provider | high | 0.000033 |
| 077_card_Bank of Baroda_2026-08-21T05:30:00 | card | Bank of Baroda | 3 | contact_provider | high | 0.000033 |
| 078_netbanking_Kotak Mahindra Bank_2026-07-26T04:15:00 | netbanking | Kotak Mahindra Bank | 129 | contact_provider | high | 0.000071 |
| 079_netbanking_Kotak Mahindra Bank_2026-07-26T06:30:00 | netbanking | Kotak Mahindra Bank | 70 | contact_provider | high | 0.000050 |
| 080_netbanking_Kotak Mahindra Bank_2026-08-05T16:45:00 | netbanking | Kotak Mahindra Bank | 3 | contact_provider | high | 0.000067 |
| 081_upi_Union Bank of India_2026-07-27T17:00:00 | upi | Union Bank of India | 6 | contact_provider | high | 0.000071 |
| 082_upi_Union Bank of India_2026-07-30T00:00:00 | upi | Union Bank of India | 4 | contact_provider | high | 0.000068 |
| 083_upi_Union Bank of India_2026-08-03T17:00:00 | upi | Union Bank of India | 5 | contact_provider | high | 0.000071 |
| 084_card_HDFC Bank_2026-07-28T23:00:00 | card | HDFC Bank | 3 | contact_provider | high | 0.000041 |
| 085_card_HDFC Bank_2026-08-11T18:15:00 | card | HDFC Bank | 75 | contact_provider | high | 0.000053 |
| 086_card_HDFC Bank_2026-08-14T14:15:00 | card | HDFC Bank | 180 | contact_provider | high | 0.000076 |
| 087_card_HDFC Bank_2026-08-17T21:15:00 | card | HDFC Bank | 3 | contact_provider | high | 0.000035 |
| 088_upi_Canara Bank_2026-07-23T07:30:00 | upi | Canara Bank | 5 | contact_provider | high | 0.000041 |
| 089_upi_Canara Bank_2026-07-30T22:15:00 | upi | Canara Bank | 35 | contact_provider | high | 0.000071 |
| 090_upi_Canara Bank_2026-08-18T02:15:00 | upi | Canara Bank | 3 | contact_provider | high | 0.000032 |
| 091_upi_Bank of Baroda_2026-07-27T05:00:00 | upi | Bank of Baroda | 190 | contact_provider | high | 0.000043 |
| 092_upi_Bank of Baroda_2026-08-03T06:00:00 | upi | Bank of Baroda | 72 | failover_method | high | 0.000060 |
| 093_upi_Bank of Baroda_2026-08-04T12:00:00 | upi | Bank of Baroda | 29 | contact_provider | high | 0.000071 |
| 094_upi_Bank of Baroda_2026-08-05T08:00:00 | upi | Bank of Baroda | 165 | contact_provider | high | 0.000048 |
| 095_upi_Bank of Baroda_2026-08-19T05:15:00 | upi | Bank of Baroda | 5 | contact_provider | high | 0.000051 |
| 096_card_Axis Bank_2026-07-24T23:00:00 | card | Axis Bank | 3 | contact_provider | high | 0.000037 |
| 097_card_Axis Bank_2026-08-13T20:15:00 | card | Axis Bank | 3 | contact_provider | high | 0.000031 |
| 098_card_Axis Bank_2026-08-14T05:45:00 | card | Axis Bank | 3 | contact_provider | high | 0.000068 |
| 099_upi_Punjab National Bank_2026-07-23T04:00:00 | upi | Punjab National Bank | 226 | contact_provider | high | 0.000071 |
| 100_upi_Punjab National Bank_2026-07-24T02:15:00 | upi | Punjab National Bank | 3 | contact_provider | high | 0.000164 |
| 101_upi_Punjab National Bank_2026-07-27T09:00:00 | upi | Punjab National Bank | 5 | contact_provider | high | 0.000054 |
| 102_upi_Punjab National Bank_2026-08-21T07:15:00 | upi | Punjab National Bank | 185 | contact_provider | high | 0.000048 |
| 103_card_Canara Bank_2026-08-12T02:45:00 | card | Canara Bank | 152 | contact_provider | high | 0.000060 |
| 104_card_Canara Bank_2026-08-12T08:15:00 | card | Canara Bank | 171 | contact_provider | high | 0.000088 |
| 105_card_Kotak Mahindra Bank_2026-08-08T04:15:00 | card | Kotak Mahindra Bank | 3 | contact_provider | high | 0.000055 |
| 106_card_Kotak Mahindra Bank_2026-08-09T14:15:00 | card | Kotak Mahindra Bank | 3 | contact_provider | medium | 0.000068 |
| 107_netbanking_ICICI Bank_2026-08-18T00:15:00 | netbanking | ICICI Bank | 153 | contact_provider | high | 0.000093 |
| 108_netbanking_ICICI Bank_2026-08-18T02:30:00 | netbanking | ICICI Bank | 81 | contact_provider | high | 0.000048 |
| 109_netbanking_ICICI Bank_2026-08-20T18:00:00 | netbanking | ICICI Bank | 211 | contact_provider | high | 0.000069 |
| 110_netbanking_ICICI Bank_2026-08-20T21:00:00 | netbanking | ICICI Bank | 30 | contact_provider | high | 0.000054 |
| 111_emandate_Kotak Mahindra Bank_2026-08-11T02:30:00 | emandate | Kotak Mahindra Bank | 127 | contact_provider | high | 0.000075 |
| 112_emandate_HDFC Bank_2026-08-13T01:15:00 | emandate | HDFC Bank | 162 | contact_provider | high | 0.000166 |

## LLM-as-a-judge

- Judge model: **openai/gpt-oss-20b**
- Samples judged: 16
- Disagreements (judge did not endorse the diagnosis): 6
- Disagreement rate: 37.5000%
- Cases the judge labelled "wrong": 0

| kind | subject | diagnosis_confidence | verdict | agrees | concerns |
| --- | --- | --- | --- | --- | --- |
| ambiguous_reason | mismatch_in_transaction_details | high | correct | True |  |
| ambiguous_reason | card_not_enrolled | high | correct | True |  |
| ambiguous_reason | compliance_violation | low | questionable | False | The diagnosis assumes a merchant-level contact in all cases, but the evidence indicates that if the risk check failed at the customer level, the customer should contact their bank. The remediation should be conditional on the 'source' parameter, not a blanket merchant contact. The diagnosis omits the alternative bank contact path, making it only plausibly supported. |
| ambiguous_reason | mobile_number_invalid | high | correct | True |  |
| ambiguous_reason | transaction_daily_count_exceeded | high | questionable | False | The diagnosis omits the equally plausible 'wait 24 hours' remediation option, which is explicitly mentioned in the next steps. While 'different_instrument_or_method' is supported, the confidence level is high despite the omission of another valid alternative. |
| ambiguous_reason | payment_method_not_enabled | high | correct | True |  |
| ambiguous_reason | authorisation_declined_by_psp | high | correct | True |  |
| ambiguous_reason | gateway_technical_error | medium | correct | True |  |
| incident | 067_card_IDFC FIRST Bank_2026-08-09T13:30:00 | high | questionable | False | The evidence shows only three failures with distinct, unrelated reason codes, but there is no direct indication of a counterparty bank glitch. The diagnosis attributes the failures to a transient issue at IDFC FIRST Bank and assigns high confidence, which is not strongly supported by the limited data. While the pattern could plausibly arise from a brief bank-side hiccup, the evidence equally supports user error or a system bug. Therefore the diagnosis is plausible but weakly supported and overconfident, warranting a 'questionable' assessment. |
| incident | 013_upi_Yes Bank_2026-07-24T23:00:00 | high | correct | True |  |
| incident | 016_card_Punjab National Bank_2026-07-23T06:30:00 | high | questionable | False | The diagnosis is plausible given the mixed failure reasons and anomaly score, but the confidence level is high despite the limited data (only three failures). The evidence does not definitively rule out card‑level issues or other causes, so the conclusion may be overconfident and lacks consideration of alternative explanations. |
| incident | 073_upi_IndusInd Bank_2026-08-13T00:30:00 | high | questionable | False | We need to analyze the evidence and evaluate the diagnosis. The diagnosis is about a transient issue at IndusInd Bank's UPI PSP. The reasoning: ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ... .... |
| incident | 098_card_Axis Bank_2026-08-14T05:45:00 | high | questionable | False | The evidence (3 failures, 2 card_declined, 1 compliance_violation) is limited and does not conclusively indicate a bank‑level infrastructure problem. While a mix of reason codes can suggest systemic issues, the small sample size and lack of corroborating incidents elsewhere make the diagnosis plausible but weakly supported. The confidence level is therefore overconfident, and alternative explanations (e.g., user‑card issues, merchant‑side errors) are not ruled out. |
| incident | 089_upi_Canara Bank_2026-07-30T22:15:00 | high | correct | True |  |
| incident | 018_upi_State Bank of India_2026-07-26T07:45:00 | high | correct | True |  |
| incident | 000_card_State Bank of India_2026-07-30T03:00:00 | low | correct | True |  |
