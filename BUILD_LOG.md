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
