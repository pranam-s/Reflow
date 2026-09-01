# Phase 7 closed-loop simulation results

**Every number below is a simulated outcome scored by a seeded oracle, not an observed real-world recovery.** See `docs/reports/phase7_evaluation.md` for the full honesty statement.

- Generated at: 2026-09-01T08:23:46+00:00
- Command: `uv run python -m reflow.eval.simulate`
- Seed: 20260822
- Corpus size: 50000
- Phase 4 report: `docs/reports/phase4_diagnosis.json`
- Library versions: pydantic=2.12.5, python=3.11.15, reflow=0.1.0
- Note: Every recovery outcome in this report is scored by the seeded, deterministic reflow.outcome.oracle.RecoveryOracle, never observed from a real customer or a live Razorpay call -- see that module's docstring and docs/reports/phase7_evaluation.md for the full honesty statement this project makes about what these numbers do and do not mean.
- Note: Diagnoses are loaded from Phase 4's already-committed report at zero marginal LLM cost, exactly as reflow.eval.policy and reflow.eval.execute do -- this module's own spend is $0.
- Note: Active-incident detection reruns the ADR-0003-recommended poisson_surprise detector once per corpus, over the full, unmodified event sequence, shared identically across every policy and every sensitivity level compared here.
- Note: reflow's escalation-ladder attempt number and attempt-cap guardrail are driven by this order's own count of chase/escalate actions actually decided during this simulation, not by the corpus's ground-truth PaymentEvent.attempt_number -- see module docstring for how this closes the limitation ADR-0005 recorded without modifying reflow.policy itself.
- Note: Every policy is run against the same corpus and the same per-payment-id oracle draws, so a difference in a policy's outcome is attributable only to that policy's own decisions.

## Sensitivity level: central

| policy | money recovered (INR) | contacts sent | attempts made | guardrail-prevented contacts | contacts / rupee recovered | orders recovered |
| --- | --- | --- | --- | --- | --- | --- |
| do_nothing | 22584778.00 | 0 | 0 | 0 | 0.000000 | 6710/44674 |
| notify_all | 75677051.00 | 47192 | 47192 | 0 | 0.000624 | 22448/44674 |
| notify_all_once | 72722654.00 | 44674 | 44674 | 0 | 0.000614 | 21547/44674 |
| reflow | 71874179.00 | 33691 | 37484 | 9992 | 0.000469 | 20820/44674 |

## Sensitivity level: optimistic

| policy | money recovered (INR) | contacts sent | attempts made | guardrail-prevented contacts | contacts / rupee recovered | orders recovered |
| --- | --- | --- | --- | --- | --- | --- |
| do_nothing | 27327498.00 | 0 | 0 | 0 | 0.000000 | 8111/44674 |
| notify_all | 98088700.00 | 46353 | 46353 | 0 | 0.000473 | 29088/44674 |
| notify_all_once | 95306938.00 | 44674 | 44674 | 0 | 0.000469 | 28272/44674 |
| reflow | 95225149.00 | 33189 | 36861 | 9848 | 0.000349 | 27517/44674 |

## Sensitivity level: pessimistic

| policy | money recovered (INR) | contacts sent | attempts made | guardrail-prevented contacts | contacts / rupee recovered | orders recovered |
| --- | --- | --- | --- | --- | --- | --- |
| do_nothing | 18259548.00 | 0 | 0 | 0 | 0.000000 | 5420/44674 |
| notify_all | 50662109.00 | 48087 | 48087 | 0 | 0.000949 | 15018/44674 |
| notify_all_once | 48242292.00 | 44674 | 44674 | 0 | 0.000926 | 14292/44674 |
| reflow | 48701612.00 | 34195 | 38108 | 10148 | 0.000702 | 14035/44674 |

## Sensitivity-band findings

| level | reflow beats do_nothing | reflow >= notify_all money | reflow cheaper/rupee than notify_all | reflow cheaper/rupee than notify_all_once |
| --- | --- | --- | --- | --- |
| pessimistic | True | False | True | True |
| central | True | False | True | True |
| optimistic | True | False | True | True |
