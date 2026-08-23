"""Tests for reflow.execute.executor."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from reflow.execute.errors import (
    ApiCallFailedError,
    GatewayNotConfiguredError,
    LiveCallBudgetExceededError,
)
from reflow.execute.executor import (
    BoundedExecutor,
    build_payment_link_request,
    payment_link_request_to_wire,
)
from reflow.execute.gateway import GatewayCallResult
from reflow.execute.models import ExecutionOutcome
from reflow.policy.actions import Action
from tests.execute.factories import make_decision, make_event


@dataclass
class _FakeGateway:
    responses_queue: list[GatewayCallResult | Exception] = field(default_factory=list)
    calls: list[dict[str, object]] = field(default_factory=list)

    def create_payment_link(self, data: dict[str, object]) -> GatewayCallResult:
        self.calls.append(data)
        outcome = self.responses_queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _success_result(*, recovered_existing: bool = False, retry_count: int = 0) -> GatewayCallResult:
    return GatewayCallResult(
        response={"id": "plink_x", "short_url": "https://rzp.io/i/x"},
        http_status=200,
        latency_ms=12.3,
        retry_count=retry_count,
        request_headers={"Authorization": "[REDACTED]"},
        recovered_existing=recovered_existing,
    )


@pytest.mark.parametrize(
    "action",
    [Action.NO_ACTION, Action.WAIT_BANK_RECOVERY, Action.ESCALATE_HUMAN, Action.RECONCILE],
)
def test_non_chase_actions_are_no_ops_and_never_touch_the_gateway(action: Action) -> None:
    executor = BoundedExecutor(dry_run=False, gateway=None)
    decision = make_decision(final_action=action)
    event = make_event()

    record = executor.execute(decision, event)

    assert record.outcome is ExecutionOutcome.NO_OP
    assert record.dry_run is True
    assert record.reference_id is None
    assert executor.live_calls_made == 0


def test_dry_run_is_the_default_and_makes_no_gateway_call() -> None:
    executor = BoundedExecutor()
    decision = make_decision(final_action=Action.RECOVERY_LINK_NOW)
    event = make_event()

    record = executor.execute(decision, event)

    assert executor.dry_run is True
    assert record.outcome is ExecutionOutcome.DRY_RUN
    assert record.request is not None
    assert record.request["reference_id"] == record.reference_id
    assert record.response is None


def test_live_without_gateway_raises() -> None:
    executor = BoundedExecutor(dry_run=False, gateway=None)
    decision = make_decision(final_action=Action.RECOVERY_LINK_NOW)

    with pytest.raises(GatewayNotConfiguredError):
        executor.execute(decision, make_event())


def test_live_call_budget_exceeded_raises_on_second_call() -> None:
    gateway = _FakeGateway(responses_queue=[_success_result(), _success_result()])
    executor = BoundedExecutor(dry_run=False, gateway=gateway, live_call_budget=1)
    decision = make_decision(final_action=Action.RECOVERY_LINK_NOW)

    first = executor.execute(decision, make_event(payment_id="pay_a"))
    assert first.outcome is ExecutionOutcome.EXECUTED
    assert executor.live_calls_made == 1

    with pytest.raises(LiveCallBudgetExceededError):
        executor.execute(decision, make_event(payment_id="pay_b"))


def test_live_execution_populates_short_url_and_payment_link_id() -> None:
    gateway = _FakeGateway(responses_queue=[_success_result()])
    executor = BoundedExecutor(dry_run=False, gateway=gateway)
    decision = make_decision(final_action=Action.RECOVERY_LINK_NOW)

    record = executor.execute(decision, make_event())

    assert record.outcome is ExecutionOutcome.EXECUTED
    assert record.short_url == "https://rzp.io/i/x"
    assert record.payment_link_id == "plink_x"
    assert record.retry_count == 0
    assert record.idempotent_replay is False


def test_live_execution_reports_idempotent_replay() -> None:
    gateway = _FakeGateway(
        responses_queue=[_success_result(recovered_existing=True, retry_count=2)]
    )
    executor = BoundedExecutor(dry_run=False, gateway=gateway)
    decision = make_decision(final_action=Action.RECOVERY_LINK_NOW)

    record = executor.execute(decision, make_event())

    assert record.idempotent_replay is True
    assert "already existed" in (record.note or "")


def test_live_execution_failure_captures_full_error_detail() -> None:
    rich_error_body = {
        "error": {
            "code": "BAD_REQUEST_ERROR",
            "description": "some field is invalid",
            "field": "customer.contact",
            "source": "business",
            "step": "payment_initiation",
            "reason": "input_validation_failed",
            "metadata": {"attempt": 1},
        }
    }
    error = ApiCallFailedError(
        "some field is invalid", status_code=400, error_body=rich_error_body, retry_count=0
    )
    gateway = _FakeGateway(responses_queue=[error])
    executor = BoundedExecutor(dry_run=False, gateway=gateway)
    decision = make_decision(final_action=Action.RECOVERY_LINK_NOW)

    record = executor.execute(decision, make_event())

    assert record.outcome is ExecutionOutcome.FAILED
    assert record.error_detail == rich_error_body
    assert record.error_detail["error"]["field"] == "customer.contact"
    assert record.http_status == 400


def test_switch_method_disables_only_the_failed_method() -> None:
    decision = make_decision(final_action=Action.SWITCH_METHOD, disallowed_method="upi")
    event = make_event()

    request = build_payment_link_request(decision, event)
    wire = payment_link_request_to_wire(request)

    assert wire["options"]["checkout"]["method"] == {
        "card": True,
        "netbanking": True,
        "upi": False,
        "wallet": True,
    }
    assert request.unrestrictable_note is None


@pytest.mark.parametrize("method", ["cardless_emi", "emandate"])
def test_switch_method_leaves_unrestrictable_methods_unrestricted(method: str) -> None:
    decision = make_decision(final_action=Action.SWITCH_METHOD, disallowed_method=method)
    event = make_event()

    request = build_payment_link_request(decision, event)
    wire = payment_link_request_to_wire(request)

    assert "options" not in wire
    assert request.unrestrictable_note is not None
    assert method in request.unrestrictable_note


def test_recovery_link_now_has_no_method_restriction() -> None:
    decision = make_decision(final_action=Action.RECOVERY_LINK_NOW, disallowed_method=None)
    event = make_event()

    wire = payment_link_request_to_wire(build_payment_link_request(decision, event))

    assert "options" not in wire


def test_synthetic_customer_contact_is_deterministic_and_format_valid() -> None:
    decision = make_decision(final_action=Action.RECOVERY_LINK_NOW)
    event = make_event(customer_id="cust_stable_0001")

    request_a = build_payment_link_request(decision, event)
    request_b = build_payment_link_request(decision, event)

    assert request_a.customer_contact == request_b.customer_contact
    assert request_a.customer_email == request_b.customer_email
    assert request_a.customer_contact.startswith("+919")
    assert len(request_a.customer_contact) == len("+919") + 9
    assert request_a.customer_email.endswith("@example.com")
