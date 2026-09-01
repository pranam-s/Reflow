"""Webhook-adjacent primitives that have no live HTTP consumer in this project.

See :mod:`reflow.webhook.dedup` for the one primitive that lives here today
and the production-readiness gap it closes.
"""

from reflow.webhook.dedup import DEFAULT_MAX_TRACKED_EVENTS, DEFAULT_TTL, WebhookEventDeduplicator

__all__ = [
    "DEFAULT_MAX_TRACKED_EVENTS",
    "DEFAULT_TTL",
    "WebhookEventDeduplicator",
]
