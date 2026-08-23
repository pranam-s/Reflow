# Phase 6 bounded-execution benchmark results

- Generated at: 2026-08-23T00:34:21+00:00
- Command: `uv run python -m reflow.eval.execute`
- Seed: 20260822
- Corpus size: 50000
- Phase 4 report: `L:\projects\buildathon\Reflow\docs\reports\phase4_diagnosis.json`
- Library versions: pydantic=2.13.4, python=3.11.15, razorpay=2.0.1, reflow=0.1.0, rich=15.0.0
- Note: This benchmark always runs the bounded executor in dry-run mode: no Razorpay credentials are imported and no network call is ever made here. Every EXECUTED outcome anywhere in this project's test suite comes from a committed VCR cassette recorded once against the real API, never from this benchmark.
- Note: Diagnoses are loaded from Phase 4's already-committed report at zero marginal LLM cost, exactly as reflow.eval.policy does -- see reflow.policy.diagnosis_source module docstring.
- Note: reference_id collision-freedom is checked directly against every payment_id in the generated corpus, not merely asserted from the birthday-bound arithmetic.
- Note: The persisted audit trail is a bounded, representative sample (see this module's own docstring), not the full n_events run -- docs/design.md ADR-0005 anticipated persisting every decision, and run_benchmark's audit_sample_size=None option does exactly that for a caller who wants the complete trail; the committed report uses a bounded sample instead, stated here rather than silently shipping a partial trail under the full-trail label.
- Note: live_verification reports on cassettes already committed under tests/execute/cassettes/test_gateway_live/ -- it parses those files, it does not make any network call itself.

## Dry-run execution outcomes (this benchmark, $0 spend)

| outcome | count |
| --- | --- |
| dry_run | 35248 |
| no_op | 14752 |

## Idempotency key (reference_id) collision check

- Events checked: **50000**
- Distinct reference_id values: **50000**
- Collision-free: **True**
- Maximum reference_id length: **40** (cap: 40)

## Persisted audit trail (bounded, representative sample)

- Path: `L:\projects\buildathon\Reflow\docs\reports\phase6_audit_trail.jsonl`
- Records persisted: **503**
- Hash chain valid: **True**

Example `reflow replay <payment_id>` arguments:

| example | payment_id |
| --- | --- |
| active_incident_suppression_block | `pay_7g3rVMw8NZ8DwS` |
| amount_floor_block | `pay_YElq6ky2skTxjC` |
| attempt_cap_block | `pay_Wh5LAP7LJkxO5I` |
| contact_cooldown_block | `pay_1Q0bFcLELjzTHn` |
| final_action_escalate_human | `pay_IeXlD4tbUcOrLD` |
| final_action_no_action | `pay_YElq6ky2skTxjC` |
| final_action_reconcile | `pay_qtzV0yCV7oJ9OS` |
| final_action_recovery_link_backoff | `pay_w84MUvBpWpPESO` |
| final_action_recovery_link_now | `pay_AveIxliClLj06E` |
| final_action_switch_method | `pay_US08o19pHQB5Zf` |
| final_action_wait_bank_recovery | `pay_7g3rVMw8NZ8DwS` |
| quiet_hours_block | `pay_w84MUvBpWpPESO` |
| terminal_reason_blocklist_block | `pay_qtzV0yCV7oJ9OS` |

## Live test-mode verification (evidence, not re-executed here)

- Cassette directory: `L:\projects\buildathon\Reflow\tests\execute\cassettes\test_gateway_live`
- Cassette files: **5**
- Recorded HTTP interactions: **9**
- Real `short_url` values observed:
  - https://rzp.io/rzp/DKbJKo0I
  - https://rzp.io/rzp/TETxP8X
  - https://rzp.io/rzp/VLUNhhqi
  - https://rzp.io/rzp/ZZZwSUt
  - https://rzp.io/rzp/c6Q93h61
