"""Tests for reflow.incident.correlate."""

from datetime import UTC, datetime

import pytest

from reflow.incident.aggregate import EntityKey
from reflow.incident.correlate import correlate_downtimes
from reflow.incident.downtime_api import Downtime, DowntimeMethod, DowntimeSeverity, DowntimeStatus
from reflow.incident.windows import DetectedIncident
from reflow.taxonomy.methods import PaymentMethod


def _downtime(
    method: DowntimeMethod,
    begin: datetime,
    end: datetime | None,
    bank: str | None = None,
    downtime_id: str = "down_1",
) -> Downtime:
    return Downtime(
        id=downtime_id,
        method=method,
        begin=begin.replace(tzinfo=UTC),
        end=end.replace(tzinfo=UTC) if end is not None else None,
        status=DowntimeStatus.STARTED if end is None else DowntimeStatus.RESOLVED,
        scheduled=False,
        severity=DowntimeSeverity.HIGH,
        instrument=({"bank": bank} if bank else {}),
        created_at=begin.replace(tzinfo=UTC),
        updated_at=(end or begin).replace(tzinfo=UTC),
    )


def _incident(entity: EntityKey, start: datetime, end: datetime) -> DetectedIncident:
    return DetectedIncident(
        entity=entity,
        detector="stub",
        start=start,
        end=end,
        bucket_starts=(start,),
        total_count=5,
        peak_score=1.0,
        event_indices=(),
    )


def test_correlate_matches_same_method_and_bank_overlapping_window() -> None:
    downtime = _downtime(
        DowntimeMethod.NETBANKING,
        datetime(2026, 1, 1, 10, 0),
        datetime(2026, 1, 1, 11, 0),
        "HDFC0001",
    )
    incident = _incident(
        (PaymentMethod.NETBANKING, "HDFC0001", None),
        datetime(2026, 1, 1, 10, 5),
        datetime(2026, 1, 1, 10, 20),
    )
    (correlation,) = correlate_downtimes([incident], [downtime])
    assert correlation.matched_downtime is downtime
    assert correlation.lead_time_minutes == 5.0


def test_correlate_detection_before_declared_downtime_is_negative_lead() -> None:
    downtime = _downtime(
        DowntimeMethod.UPI, datetime(2026, 1, 1, 10, 30), datetime(2026, 1, 1, 11, 0), "SBI0001"
    )
    incident = _incident(
        (PaymentMethod.UPI, "SBI0001", None),
        datetime(2026, 1, 1, 10, 15),
        datetime(2026, 1, 1, 10, 45),
    )
    (correlation,) = correlate_downtimes([incident], [downtime])
    assert correlation.matched_downtime is downtime
    assert correlation.lead_time_minutes == pytest.approx(-15.0)


def test_correlate_no_match_when_method_differs() -> None:
    downtime = _downtime(
        DowntimeMethod.CARD, datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0)
    )
    incident = _incident(
        (PaymentMethod.UPI, None, None),
        datetime(2026, 1, 1, 10, 5),
        datetime(2026, 1, 1, 10, 20),
    )
    (correlation,) = correlate_downtimes([incident], [downtime])
    assert correlation.matched_downtime is None
    assert correlation.lead_time_minutes is None


def test_correlate_no_match_when_bank_differs() -> None:
    downtime = _downtime(
        DowntimeMethod.CARD, datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0), "HDFC0001"
    )
    incident = _incident(
        (PaymentMethod.CARD, "ICIC0001", None),
        datetime(2026, 1, 1, 10, 5),
        datetime(2026, 1, 1, 10, 20),
    )
    (correlation,) = correlate_downtimes([incident], [downtime])
    assert correlation.matched_downtime is None


def test_correlate_open_ended_downtime_still_matches() -> None:
    downtime = _downtime(DowntimeMethod.UPI, datetime(2026, 1, 1, 10, 0), None, "SBI0001")
    incident = _incident(
        (PaymentMethod.UPI, "SBI0001", None),
        datetime(2026, 1, 5, 0, 0),
        datetime(2026, 1, 5, 1, 0),
    )
    (correlation,) = correlate_downtimes([incident], [downtime])
    assert correlation.matched_downtime is downtime


def test_correlate_picks_closest_candidate_by_begin_time() -> None:
    far = _downtime(
        DowntimeMethod.UPI,
        datetime(2026, 1, 1, 6, 0),
        datetime(2026, 1, 1, 12, 0),
        "SBI0001",
        downtime_id="down_far",
    )
    near = _downtime(
        DowntimeMethod.UPI,
        datetime(2026, 1, 1, 9, 55),
        datetime(2026, 1, 1, 10, 30),
        "SBI0001",
        downtime_id="down_near",
    )
    incident = _incident(
        (PaymentMethod.UPI, "SBI0001", None),
        datetime(2026, 1, 1, 10, 0),
        datetime(2026, 1, 1, 10, 15),
    )
    (correlation,) = correlate_downtimes([incident], [far, near])
    assert correlation.matched_downtime is near


def test_correlate_wallet_incidents_never_match_any_declared_downtime() -> None:
    downtime = _downtime(
        DowntimeMethod.CARD, datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0)
    )
    incident = _incident(
        (PaymentMethod.WALLET, None, None),
        datetime(2026, 1, 1, 10, 5),
        datetime(2026, 1, 1, 10, 20),
    )
    (correlation,) = correlate_downtimes([incident], [downtime])
    assert correlation.matched_downtime is None


def test_correlate_no_declared_downtimes_at_all() -> None:
    incident = _incident(
        (PaymentMethod.CARD, "HDFC0001", None),
        datetime(2026, 1, 1, 10, 5),
        datetime(2026, 1, 1, 10, 20),
    )
    (correlation,) = correlate_downtimes([incident], [])
    assert correlation.matched_downtime is None
    assert correlation.detected is incident
