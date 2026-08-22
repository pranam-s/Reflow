# Phase 5 policy-engine benchmark results

- Generated at: 2026-08-22T23:13:29+00:00
- Command: `uv run python -m reflow.eval.policy`
- Seed: 20260822
- Corpus size: 50000
- Phase 4 report: `L:\projects\buildathon\Reflow\docs\reports\phase4_diagnosis.json`
- Library versions: pydantic=2.13.4, python=3.11.15, reflow=0.1.0
- Note: No LLM call and no live Razorpay API call is made anywhere in this benchmark. The 15 ambiguous reason codes' remediation classes are loaded from the already-committed Phase 4 report at zero marginal spend -- see reflow.policy.diagnosis_source module docstring.
- Note: Active-incident detection reruns the ADR-0003-recommended poisson_surprise detector at (method, bank) granularity over the full corpus: a pure statistical computation, not an LLM call, and the same detector/granularity Phase 3 and Phase 4 used.
- Note: Guardrail fire counts and the over-contact reduction compare each decision's escalation -ladder candidate_action (what would have been sent with zero guardrails) against its final_action (what the full guardrail chain actually decided).
- Note: The terminal_reason_blocklist guardrail's TERMINAL-class branch cannot fire on this corpus: reflow.taxonomy.remediation currently classifies zero of 110 reason codes as TERMINAL. Its duplicate/already-paid branch (order_already_paid, duplicate_request, duplicate_refund_id) can and does fire; both branches are exercised directly in tests/policy/test_guardrails.py independent of what this corpus happens to contain.
- Note: example_decisions is a small, illustrative sample (the first decision each guardrail blocked, plus one fully-passed decision), not the full per-event audit trail -- Phase 6 persists every Decision this engine produces; this report is a benchmark summary.

## Action distribution across the closed set

| action | candidate (no guardrails) | final (with guardrails) |
| --- | --- | --- |
| escalate_human | 5172 | 4310 |
| no_action | 0 | 2423 |
| reconcile | 0 | 647 |
| recovery_link_backoff | 4508 | 19137 |
| recovery_link_now | 32254 | 13391 |
| switch_method | 8066 | 2720 |
| wait_bank_recovery | 0 | 7372 |

- Events reaching `wait_bank_recovery` because an incident was active: **7372**

## Guardrail fire counts

| guardrail | fired (blocked) | passed | overrides (before->after: count) |
| --- | --- | --- | --- |
| terminal_reason_blocklist | 647 | 49353 | escalate_human->reconcile: 647 |
| active_incident_suppression | 7372 | 42628 | recovery_link_backoff->wait_bank_recovery: 788; recovery_link_now->wait_bank_recovery: 4122; switch_method->wait_bank_recovery: 2462 |
| amount_floor | 1991 | 48009 | escalate_human->no_action: 211; recovery_link_backoff->no_action: 168; recovery_link_now->no_action: 1347; switch_method->no_action: 265 |
| attempt_cap | 4 | 49996 | escalate_human->no_action: 4 |
| per_customer_contact_cap | 0 | 50000 | n/a |
| contact_cooldown | 428 | 49572 | recovery_link_backoff->no_action: 63; recovery_link_now->no_action: 304; switch_method->no_action: 61 |
| quiet_hours | 15648 | 34352 | recovery_link_now->recovery_link_backoff: 13090; switch_method->recovery_link_backoff: 2558 |

## Over-contact reduction

- Contacts that would have been sent with zero guardrails: **44828**
- Contacts actually sent with guardrails: **35248**
- Reduction: **9580** (21.3706%)

## Escalation ladder terminal-state distribution

| terminal state | count |
| --- | --- |
| escalated_to_human | 4310 |
| gave_up | 4 |
| in_progress_backoff | 19137 |
| in_progress_link_now | 13391 |
| in_progress_switch_method | 2720 |
| no_action_other | 2419 |
| reconciled | 647 |
| waiting_on_bank | 7372 |

## Example decisions (illustrative sample, not the full audit trail)

| final_action | error_reason | justification |
| --- | --- | --- |
| recovery_link_backoff | psp_not_available | error_reason='psp_not_available' (tier=deterministic) resolved to remediation_class=different_instrument -> base_action=recovery_link_now. Escalation ladder selected candidate_action=recovery_link_now. quiet_hours blocked (recovery_link_now -> recovery_link_backoff): event hour 0 falls within the configured quiet-hours window [21, 9) (policy default, not a cited legal threshold -- see reflow.policy.config module docstring); deferring the send rather than contacting the customer overnight. Final action: recovery_link_backoff. |
| no_action | card_number_invalid | error_reason='card_number_invalid' (tier=deterministic) resolved to remediation_class=customer_fix -> base_action=recovery_link_now. Escalation ladder selected candidate_action=recovery_link_now. amount_floor blocked (recovery_link_now -> no_action): amount 4900 paise is below the configured floor of 5000 paise; further recovery_link_now spend is not economically justified for this payment. Final action: no_action. |
| no_action | authentication_failed | error_reason='authentication_failed' (tier=deterministic) resolved to remediation_class=customer_fix -> base_action=recovery_link_now. Escalation ladder selected candidate_action=recovery_link_now. contact_cooldown blocked (recovery_link_now -> no_action): last contact to this customer was 0:12:07.654897 ago, inside the configured cooldown of 4:00:00; suppressing a further contact this round. Final action: no_action. |
| wait_bank_recovery | pin_not_set | error_reason='pin_not_set' (tier=deterministic) resolved to remediation_class=customer_fix -> base_action=recovery_link_now. Escalation ladder selected candidate_action=recovery_link_now. active_incident_suppression blocked (recovery_link_now -> wait_bank_recovery): poisson_surprise (docs/design.md ADR-0003) detected an active incident on this (method, bank) at this event's time; chasing the customer while the bank or rail itself is down is wrong -- deliberately waiting for bank-side recovery instead. Final action: wait_bank_recovery. |
| reconcile | duplicate_refund_id | error_reason='duplicate_refund_id' (tier=deterministic) resolved to remediation_class=merchant_action -> base_action=escalate_human. Escalation ladder selected candidate_action=escalate_human. terminal_reason_blocklist blocked (escalate_human -> reconcile): error_reason 'duplicate_refund_id' is a known duplicate/already-paid case (derived from the reason code's own taxonomy semantics); continuing toward escalate_human risks contacting the customer about a payment that does not need it, or a duplicate charge -- reconciliation is the correct action, not customer contact or human escalation. Final action: reconcile. |
| no_action | bank_technical_error | error_reason='bank_technical_error' (tier=deterministic) resolved to remediation_class=different_instrument_or_method -> base_action=switch_method. Escalation ladder selected candidate_action=escalate_human. attempt_cap blocked (escalate_human -> no_action): attempt 5 exceeds the configured cap of 4; the escalation ladder is exhausted and giving up is the correct terminal state, not silently retrying forever. Final action: no_action. |
| escalate_human | recurring_payment_not_enabled | error_reason='recurring_payment_not_enabled' (tier=deterministic) resolved to remediation_class=merchant_contact_razorpay -> base_action=escalate_human. Escalation ladder selected candidate_action=escalate_human. Every guardrail passed; no override was applied. Final action: escalate_human. |
