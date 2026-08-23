"""Tests for reflow.execute.transport."""

import json

import responses

from reflow.execute.transport import build_capturing_session

_URL = "https://api.razorpay.com/v1/payment_links"


@responses.activate
def test_capturing_session_records_successful_response() -> None:
    responses.add(
        responses.POST,
        _URL,
        json={"id": "plink_test1", "short_url": "https://rzp.io/i/test1"},
        status=200,
    )
    session, capture = build_capturing_session()

    response = session.post(_URL, json={"amount": 100}, auth=("key", "secret"))

    assert response.status_code == 200
    assert capture.last_capture is not None
    assert capture.last_capture.status_code == 200
    assert capture.last_capture.json_body == {
        "id": "plink_test1",
        "short_url": "https://rzp.io/i/test1",
    }


@responses.activate
def test_capturing_session_redacts_authorization_header() -> None:
    responses.add(responses.POST, _URL, json={"id": "plink_test2"}, status=200)
    session, capture = build_capturing_session()

    session.post(_URL, json={"amount": 100}, auth=("key_id", "key_secret"))

    assert capture.last_capture is not None
    headers = capture.last_capture.request_headers
    assert "Authorization" in headers
    assert headers["Authorization"] == "[REDACTED]"
    assert "key_secret" not in json.dumps(headers)


@responses.activate
def test_capturing_session_records_error_status_and_body() -> None:
    error_body = {
        "error": {
            "code": "BAD_REQUEST_ERROR",
            "description": "reference_id already exists",
            "field": "reference_id",
            "source": "business",
            "step": "payment_initiation",
            "reason": "input_validation_failed",
            "metadata": {"foo": "bar"},
        }
    }
    responses.add(responses.POST, _URL, json=error_body, status=400)
    session, capture = build_capturing_session()

    response = session.post(_URL, json={"amount": 100}, auth=("key", "secret"))

    assert response.status_code == 400
    assert capture.last_capture is not None
    assert capture.last_capture.status_code == 400
    assert capture.last_capture.json_body == error_body
    assert capture.last_capture.json_body["error"]["field"] == "reference_id"
    assert capture.last_capture.json_body["error"]["metadata"] == {"foo": "bar"}


@responses.activate
def test_capturing_session_handles_empty_body() -> None:
    responses.add(responses.POST, _URL, body="", status=204)
    session, capture = build_capturing_session()

    session.post(_URL, json={}, auth=("key", "secret"))

    assert capture.last_capture is not None
    assert capture.last_capture.status_code == 204
    assert capture.last_capture.json_body is None


@responses.activate
def test_capturing_session_handles_non_json_body() -> None:
    responses.add(responses.GET, _URL, body="not json", status=200, content_type="text/plain")
    session, capture = build_capturing_session()

    session.get(_URL, auth=("key", "secret"))

    assert capture.last_capture is not None
    assert capture.last_capture.json_body is None


@responses.activate
def test_capturing_session_tracks_only_the_most_recent_call() -> None:
    responses.add(responses.GET, _URL, json={"call": 1}, status=200)
    responses.add(responses.GET, _URL, json={"call": 2}, status=201)
    session, capture = build_capturing_session()

    session.get(_URL, auth=("key", "secret"))
    session.get(_URL, auth=("key", "secret"))

    assert capture.last_capture is not None
    assert capture.last_capture.json_body == {"call": 2}
    assert capture.last_capture.status_code == 201
