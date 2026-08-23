"""Bounded execution of the Phase 5 action set against Razorpay test mode.

This package is Deliverable 1 of Phase 6: it turns a
:class:`~reflow.policy.decision.Decision` (Phase 5's output) into either a
simulated ("dry run") or a real Razorpay Payment Link API call, never a
retry of the original failed payment -- verified in ``BUILD_LOG.md``
(2026-08-22) and again in :mod:`reflow.policy.actions`'s module docstring,
the Payments API has no endpoint that re-attempts a failed authorisation,
so every customer-facing recovery action in this project's closed
:class:`~reflow.policy.actions.Action` set goes through a fresh Payment
Link instead.

**Dry run is the default.** :class:`~reflow.execute.executor.BoundedExecutor`
never calls a live API unless both ``dry_run=False`` is set explicitly and a
:class:`~reflow.execute.gateway.RazorpayGateway` (constructed from
``RAZORPAY_KEY_ID``/``RAZORPAY_KEY_SECRET`` read from ``os.environ``, never
from ``.env`` directly -- see :mod:`reflow.execute.config`) is supplied.

Module map:

- :mod:`reflow.execute.reference` -- the deterministic, collision-resistant
  Payment Link ``reference_id`` derivation used as this project's
  idempotency key, since Razorpay documents idempotency headers only for
  transfers, refunds, and payouts, never for Payment Link creation
  (``BUILD_LOG.md``, 2026-08-22).
- :mod:`reflow.execute.transport` -- transport-level capture of the raw
  HTTP status code and JSON error body the installed ``razorpay`` SDK
  (2.0.1) parses and then discards (verified by reading
  ``razorpay/client.py`` and ``razorpay/errors.py`` directly).
- :mod:`reflow.execute.gateway` -- a retrying wrapper around
  ``razorpay.Client`` with adaptive backoff-with-jitter for HTTP 429/5xx
  (the SDK's own ``enable_retry`` covers only ``ConnectionError``/
  ``Timeout``, never an HTTP error status -- ``BUILD_LOG.md``,
  2026-08-22), plus a verified-live recovery path for the one case a naive
  idempotency design would treat as a hard failure: Razorpay rejects a
  second Payment Link creation carrying an already-used ``reference_id``
  outright, rather than silently returning the original link (see that
  module's docstring for the live evidence).
- :mod:`reflow.execute.models` -- the request/response/outcome shapes the
  audit trail (:mod:`reflow.audit`) persists.
- :mod:`reflow.execute.executor` -- :class:`~reflow.execute.executor.BoundedExecutor`,
  the orchestrator this package exists to provide.
"""

from __future__ import annotations
