"""Tests for reflow.execute.gateway.

``key_secret="fake_secret"`` below is a literal placeholder, never a real
credential -- every HTTP call in this module is intercepted by
``responses`` before it reaches the network, so no value passed here is
ever sent anywhere. Ruff's hardcoded-password heuristic (S106) cannot
distinguish that from a real leaked secret by pattern alone, hence the
narrow, named suppression.
"""

import pytest
import requests
import responses

from reflow.execute.errors import ApiCallFailedError
from reflow.execute.gateway import RazorpayGateway

_BASE = "https://api.razorpay.com/v1/payment_links"


def _gateway(*, max_retries: int = 5) -> RazorpayGateway:
    return RazorpayGateway(
        key_id="rzp_test_fake",
        key_secret="fake_secret",  # noqa: S106
        max_retries=max_retries,
        base_delay_seconds=0.0,
        max_delay_seconds=0.0,
    )


def test_gateway_repr_never_exposes_the_key_secret() -> None:
    gateway = RazorpayGateway(key_id="rzp_test_fake", key_secret="super-secret-value")  # noqa: S106
    assert "super-secret-value" not in repr(gateway)
    assert "rzp_test_fake" in repr(gateway)


def _bad_request_body(description: str) -> dict[str, object]:
    return {"error": {"code": "BAD_REQUEST_ERROR", "description": description}}


def _server_error_body(description: str = "internal server error") -> dict[str, object]:
    return {"error": {"code": "SERVER_ERROR", "description": description}}


@responses.activate
def test_create_payment_link_success_on_first_attempt() -> None:
    responses.add(
        responses.POST,
        _BASE,
        json={"id": "plink_ok1", "short_url": "https://rzp.io/i/ok1", "reference_id": "ref1"},
        status=200,
    )
    gateway = _gateway()

    result = gateway.create_payment_link({"amount": 100, "reference_id": "ref1"})

    assert result.response["id"] == "plink_ok1"
    assert result.http_status == 200
    assert result.retry_count == 0
    assert result.recovered_existing is False
    assert "Authorization" in result.request_headers
    assert result.request_headers["Authorization"] == "[REDACTED]"


@responses.activate
def test_create_payment_link_retries_on_429_then_succeeds() -> None:
    responses.add(responses.POST, _BASE, json=_bad_request_body("Too many requests"), status=429)
    responses.add(responses.POST, _BASE, json={"id": "plink_ok2"}, status=200)
    gateway = _gateway(max_retries=3)

    result = gateway.create_payment_link({"amount": 100, "reference_id": "ref2"})

    assert result.response["id"] == "plink_ok2"
    assert result.retry_count == 1


@responses.activate
def test_create_payment_link_retries_on_502_then_succeeds() -> None:
    responses.add(responses.POST, _BASE, json=_server_error_body(), status=502)
    responses.add(responses.POST, _BASE, json={"id": "plink_ok3"}, status=200)
    gateway = _gateway(max_retries=3)

    result = gateway.create_payment_link({"amount": 100, "reference_id": "ref3"})

    assert result.response["id"] == "plink_ok3"
    assert result.retry_count == 1


@responses.activate
def test_create_payment_link_non_retryable_400_raises_immediately() -> None:
    responses.add(responses.POST, _BASE, json=_bad_request_body("amount is required"), status=400)
    gateway = _gateway(max_retries=5)

    with pytest.raises(ApiCallFailedError) as excinfo:
        gateway.create_payment_link({"reference_id": "ref4"})

    assert excinfo.value.status_code == 400
    assert excinfo.value.retry_count == 0
    assert excinfo.value.error_body == _bad_request_body("amount is required")
    assert len(responses.calls) == 1


@responses.activate
def test_create_payment_link_exhausts_retries_on_persistent_5xx() -> None:
    for _ in range(3):
        responses.add(responses.POST, _BASE, json=_server_error_body(), status=500)
    gateway = _gateway(max_retries=2)

    with pytest.raises(ApiCallFailedError) as excinfo:
        gateway.create_payment_link({"reference_id": "ref5"})

    assert excinfo.value.status_code == 500
    assert excinfo.value.retry_count == 2
    assert len(responses.calls) == 3


@responses.activate
def test_create_payment_link_retries_on_connection_error() -> None:
    responses.add(responses.POST, _BASE, body=requests.exceptions.ConnectionError("boom"))
    responses.add(responses.POST, _BASE, json={"id": "plink_ok6"}, status=200)
    gateway = _gateway(max_retries=2)

    result = gateway.create_payment_link({"reference_id": "ref6"})

    assert result.response["id"] == "plink_ok6"
    assert result.retry_count == 1


@responses.activate
def test_create_payment_link_recovers_from_duplicate_reference_id() -> None:
    reference_id = "reflow_dup"
    responses.add(
        responses.POST,
        _BASE,
        json=_bad_request_body(
            f"payment link with given reference_id: {reference_id} already exists. Please "
            "create a payment link with a different reference_id"
        ),
        status=400,
    )
    existing_link = {"id": "plink_existing", "reference_id": reference_id, "status": "created"}
    responses.add(responses.GET, _BASE, json={"payment_links": [existing_link]}, status=200)
    gateway = _gateway()

    result = gateway.create_payment_link({"amount": 100, "reference_id": reference_id})

    assert result.recovered_existing is True
    assert result.response == existing_link


@responses.activate
def test_create_payment_link_duplicate_but_no_existing_link_found_raises() -> None:
    reference_id = "reflow_dup_missing"
    responses.add(
        responses.POST,
        _BASE,
        json=_bad_request_body(
            f"payment link with given reference_id: {reference_id} already exists. Please "
            "create a payment link with a different reference_id"
        ),
        status=400,
    )
    responses.add(responses.GET, _BASE, json={"payment_links": []}, status=200)
    gateway = _gateway()

    with pytest.raises(ApiCallFailedError, match="no existing Payment Link could be recovered"):
        gateway.create_payment_link({"amount": 100, "reference_id": reference_id})


@responses.activate
def test_fetch_payment_link_success() -> None:
    responses.add(responses.GET, f"{_BASE}/plink_abc", json={"id": "plink_abc"}, status=200)
    gateway = _gateway()

    result = gateway.fetch_payment_link("plink_abc")

    assert result.response["id"] == "plink_abc"


@responses.activate
def test_notify_payment_link_success() -> None:
    responses.add(
        responses.POST, f"{_BASE}/plink_abc/notify_by/sms", json={"success": True}, status=200
    )
    gateway = _gateway()

    result = gateway.notify_payment_link("plink_abc", "sms")

    assert result.response == {"success": True}
