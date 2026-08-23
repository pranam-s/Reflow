"""VCR-cassette-recorded tests against the real Razorpay test-mode API.

Every cassette under ``cassettes/test_gateway_live/`` was recorded once,
for real, against Razorpay's live test-mode API::

    uv run --env-file .env pytest tests/execute/test_gateway_live.py --record-mode=once

and is replayed thereafter with ``pytest-recording``'s default
``--record-mode=none``, so this module costs $0, needs no network or
credentials, and moves no real money in ordinary test runs -- test mode
never touches live money regardless (this phase's brief). See
``conftest.py`` for the ``Authorization``-header redaction and gzip
-decoding applied before a cassette is ever written, and
``docs/reports/phase6_execution.md`` for confirmation every committed
cassette here was read by hand and contains no credential.

This is the phase's genuine, live-verified evidence, deliberately kept to
a small, fixed number of real calls (see each test's docstring for what it
proves): Payment Link creation, the verified duplicate-``reference_id``
rejection-and-recovery path (``reflow.execute.gateway`` module docstring),
a method-restricted creation, and both notification media.
"""

from __future__ import annotations

import os

import pytest

from reflow.execute.gateway import RazorpayGateway

_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_recorded_cassette_placeholder")
_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "recorded_cassette_placeholder")
"""Read from ``os.environ`` only, never from ``.env`` directly. A real
credential pair is only needed the one time a cassette is (re-)recorded;
every ordinary test run replays a cassette and never sends this value
anywhere."""


def _gateway() -> RazorpayGateway:
    return RazorpayGateway(key_id=_KEY_ID, key_secret=_KEY_SECRET, max_retries=3)


@pytest.mark.vcr
def test_create_payment_link_live_returns_a_real_short_url() -> None:
    """A plain Payment Link creation succeeds against the real API.

    Proves the base mechanism every :attr:`~reflow.policy.actions.Action.RECOVERY_LINK_NOW`
    /:attr:`~reflow.policy.actions.Action.RECOVERY_LINK_BACKOFF` decision resolves to: this
    is not mocked anywhere else in the suite.
    """
    gateway = _gateway()

    result = gateway.create_payment_link(
        {
            "amount": 19900,
            "currency": "INR",
            "description": "reflow phase6 live verification -- plain payment link",
            "reference_id": "reflow_live_create_0001",
            "customer": {
                "name": "Reflow Live Test Customer",
                "contact": "+919876500001",
                "email": "reflow.live.create@example.com",
            },
            "notify": {"sms": False, "email": False},
        }
    )

    assert result.http_status == 200
    assert result.response["id"].startswith("plink_")
    assert result.response["short_url"].startswith("https://rzp.io/")
    assert result.response["reference_id"] == "reflow_live_create_0001"
    assert result.recovered_existing is False


@pytest.mark.vcr
def test_duplicate_reference_id_is_recovered_not_duplicated() -> None:
    """A second creation with the same reference_id recovers the original link.

    Verified live, 2026-08-23 (``reflow.execute.gateway`` module
    docstring): Razorpay rejects a duplicate ``reference_id`` outright
    rather than silently returning the original link, so this test drives
    :meth:`~reflow.execute.gateway.RazorpayGateway.create_payment_link`
    through its full recovery path -- create, duplicate rejection, and the
    ``reference_id``-filtered lookup that recovers the pre-existing link
    -- against the real API, not a mock of the rejection message.
    """
    gateway = _gateway()
    data = {
        "amount": 29900,
        "currency": "INR",
        "description": "reflow phase6 live verification -- idempotency probe",
        "reference_id": "reflow_live_idempotent_0001",
        "customer": {
            "name": "Reflow Live Test Customer",
            "contact": "+919876500002",
            "email": "reflow.live.idempotent@example.com",
        },
        "notify": {"sms": False, "email": False},
    }

    first = gateway.create_payment_link(data)
    second = gateway.create_payment_link(data)

    assert first.recovered_existing is False
    assert second.recovered_existing is True
    assert second.response["id"] == first.response["id"]
    assert second.response["short_url"] == first.response["short_url"]


@pytest.mark.vcr
def test_create_method_restricted_payment_link_live() -> None:
    """A SWITCH_METHOD-style, method-restricted creation succeeds live.

    Sends the ``options.checkout.method`` shape verified live 2026-08-23
    against Razorpay's "Customise Payment Methods" documentation (see
    ``reflow.execute.gateway.RESTRICTABLE_METHODS`` and
    ``reflow.policy.actions`` module docstrings), disabling UPI on a real
    test-mode Payment Link.
    """
    gateway = _gateway()

    result = gateway.create_payment_link(
        {
            "amount": 39900,
            "currency": "INR",
            "description": "reflow phase6 live verification -- method-restricted (upi off)",
            "reference_id": "reflow_live_switch_method_0001",
            "customer": {
                "name": "Reflow Live Test Customer",
                "contact": "+919876500003",
                "email": "reflow.live.switch@example.com",
            },
            "notify": {"sms": False, "email": False},
            "options": {
                "checkout": {
                    "method": {"card": True, "netbanking": True, "upi": False, "wallet": True}
                }
            },
        }
    )

    assert result.http_status == 200
    assert result.response["short_url"].startswith("https://rzp.io/")


@pytest.mark.vcr
def test_notify_payment_link_sms_live() -> None:
    """Resending a Payment Link notification by SMS succeeds against the real API."""
    gateway = _gateway()
    created = gateway.create_payment_link(
        {
            "amount": 9900,
            "currency": "INR",
            "description": "reflow phase6 live verification -- notify sms",
            "reference_id": "reflow_live_notify_sms_0001",
            "customer": {
                "name": "Reflow Live Test Customer",
                "contact": "+919876500004",
                "email": "reflow.live.notify.sms@example.com",
            },
            "notify": {"sms": False, "email": False},
        }
    )

    result = gateway.notify_payment_link(created.response["id"], "sms")

    assert result.response == {"success": True}


@pytest.mark.vcr
def test_notify_payment_link_email_live() -> None:
    """Resending a Payment Link notification by email succeeds against the real API."""
    gateway = _gateway()
    created = gateway.create_payment_link(
        {
            "amount": 9900,
            "currency": "INR",
            "description": "reflow phase6 live verification -- notify email",
            "reference_id": "reflow_live_notify_email_0001",
            "customer": {
                "name": "Reflow Live Test Customer",
                "contact": "+919876500005",
                "email": "reflow.live.notify.email@example.com",
            },
            "notify": {"sms": False, "email": False},
        }
    )

    result = gateway.notify_payment_link(created.response["id"], "email")

    assert result.response == {"success": True}
