"""Tests for reflow.incident.downtime_api."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from reflow.incident.downtime_api import (
    Downtime,
    DowntimeEventType,
    DowntimeMethod,
    DowntimeSeverity,
    DowntimeStatus,
    DowntimeWebhookEvent,
)

_RAW_DOWNTIME = {
    "id": "down_F1cxDoHWD4fkQt",
    "method": "netbanking",
    "begin": 1591946222,
    "end": None,
    "status": "started",
    "scheduled": False,
    "severity": "high",
    "instrument": {"bank": "COSB"},
    "created_at": 1591946223,
    "updated_at": 1591946297,
}


def test_downtime_parses_documented_sample_response() -> None:
    downtime = Downtime.model_validate(_RAW_DOWNTIME)
    assert downtime.id == "down_F1cxDoHWD4fkQt"
    assert downtime.entity == "payment.downtime"
    assert downtime.method is DowntimeMethod.NETBANKING
    assert downtime.status is DowntimeStatus.STARTED
    assert downtime.severity is DowntimeSeverity.HIGH
    assert downtime.scheduled is False
    assert downtime.end is None
    assert downtime.bank == "COSB"
    assert downtime.begin == datetime(2020, 6, 12, 7, 17, 2, tzinfo=UTC)


def test_downtime_bank_property_is_none_when_absent() -> None:
    downtime = Downtime.model_validate({**_RAW_DOWNTIME, "instrument": {}})
    assert downtime.bank is None


def test_downtime_rejects_wallet_method() -> None:
    with pytest.raises(ValidationError):
        Downtime.model_validate({**_RAW_DOWNTIME, "method": "wallet"})


def test_downtime_rejects_cardless_emi_method() -> None:
    with pytest.raises(ValidationError):
        Downtime.model_validate({**_RAW_DOWNTIME, "method": "cardless_emi"})


def test_downtime_is_frozen() -> None:
    downtime = Downtime.model_validate(_RAW_DOWNTIME)
    with pytest.raises(ValidationError):
        downtime.severity = DowntimeSeverity.LOW


def test_downtime_upi_flow_field() -> None:
    downtime = Downtime.model_validate(
        {**_RAW_DOWNTIME, "method": "upi", "flow": "collect", "instrument": {}}
    )
    assert downtime.flow is not None
    assert downtime.flow.value == "collect"


def test_downtime_webhook_event_parses_nested_dotted_key() -> None:
    raw_webhook = {
        "entity": "event",
        "account_id": "acc_ABC123",
        "event": "payment.downtime.started",
        "contains": ["payment.downtime"],
        "payload": {"payment.downtime": {"entity": _RAW_DOWNTIME}},
        "created_at": 1591946223,
    }
    webhook = DowntimeWebhookEvent.model_validate(raw_webhook)
    assert webhook.event is DowntimeEventType.STARTED
    assert webhook.downtime.id == "down_F1cxDoHWD4fkQt"
    assert webhook.contains == ("payment.downtime",)


def test_downtime_webhook_event_resolved_populates_end() -> None:
    resolved_downtime = {
        **_RAW_DOWNTIME,
        "status": "resolved",
        "end": 1591949822,
    }
    raw_webhook = {
        "entity": "event",
        "account_id": "acc_ABC123",
        "event": "payment.downtime.resolved",
        "contains": ["payment.downtime"],
        "payload": {"payment.downtime": {"entity": resolved_downtime}},
        "created_at": 1591949823,
    }
    webhook = DowntimeWebhookEvent.model_validate(raw_webhook)
    assert webhook.event is DowntimeEventType.RESOLVED
    assert webhook.downtime.end is not None
    assert webhook.downtime.status is DowntimeStatus.RESOLVED


def test_downtime_webhook_event_rejects_unknown_event_name() -> None:
    raw_webhook = {
        "entity": "event",
        "account_id": "acc_ABC123",
        "event": "payment.downtime.exploded",
        "contains": ["payment.downtime"],
        "payload": {"payment.downtime": {"entity": _RAW_DOWNTIME}},
        "created_at": 1591946223,
    }
    with pytest.raises(ValidationError):
        DowntimeWebhookEvent.model_validate(raw_webhook)


def test_downtime_webhook_payload_can_be_validated_standalone() -> None:
    from reflow.incident.downtime_api import DowntimeWebhookPayload

    payload = DowntimeWebhookPayload.model_validate({"payment.downtime": {"entity": _RAW_DOWNTIME}})
    assert payload.payment_downtime.entity.id == "down_F1cxDoHWD4fkQt"

    webhook = DowntimeWebhookEvent(
        account_id="acc_ABC123",
        event=DowntimeEventType.STARTED,
        contains=("payment.downtime",),
        payload=payload,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert webhook.downtime.id == "down_F1cxDoHWD4fkQt"
