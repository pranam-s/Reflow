from datetime import datetime, timedelta

import pytest

from reflow.policy.actions import Action
from reflow.policy.config import PolicyConfig
from reflow.policy.guardrails import (
    ActiveIncidentGuardrail,
    AmountFloorGuardrail,
    AttemptCapGuardrail,
    ContactCapGuardrail,
    CooldownGuardrail,
    GuardrailContext,
    QuietHoursGuardrail,
    TerminalReasonGuardrail,
    _in_quiet_hours,
    default_guardrail_chain,
)
from reflow.taxonomy.remediation import RemediationClass
from tests.policy.factories import make_event

_CONFIG = PolicyConfig()


def _context(
    *,
    reason: str = "payment_timed_out",
    remediation_class: RemediationClass = RemediationClass.RETRY_SAME,
    in_active_incident: bool = False,
    contacts_in_window: int = 0,
    time_since_last_contact: timedelta | None = None,
    amount: int = 100_000,
    attempt_number: int = 1,
    created_at: datetime = datetime(2026, 1, 1, 12, 0, 0),
    config: PolicyConfig = _CONFIG,
) -> GuardrailContext:
    event = make_event(
        error_reason=reason, amount=amount, attempt_number=attempt_number, created_at=created_at
    )
    return GuardrailContext(
        event=event,
        remediation_class=remediation_class,
        in_active_incident=in_active_incident,
        contacts_in_window=contacts_in_window,
        time_since_last_contact=time_since_last_contact,
        config=config,
    )


class TestTerminalReasonGuardrail:
    def test_passes_unblocklisted_reason(self) -> None:
        guardrail = TerminalReasonGuardrail()
        context = _context(reason="payment_timed_out")
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert not result.blocked
        assert result.action_after == Action.RECOVERY_LINK_NOW

    def test_blocks_duplicate_reason_to_reconcile(self) -> None:
        guardrail = TerminalReasonGuardrail()
        context = _context(reason="order_already_paid")
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert result.blocked
        assert result.action_after == Action.RECONCILE

    def test_blocks_duplicate_reason_from_escalate_human(self) -> None:
        guardrail = TerminalReasonGuardrail()
        context = _context(reason="duplicate_request")
        result = guardrail.evaluate(context, Action.ESCALATE_HUMAN)
        assert result.blocked
        assert result.action_after == Action.RECONCILE

    def test_passes_duplicate_reason_already_reconcile(self) -> None:
        guardrail = TerminalReasonGuardrail()
        context = _context(reason="duplicate_refund_id")
        result = guardrail.evaluate(context, Action.RECONCILE)
        assert not result.blocked

    def test_passes_duplicate_reason_when_action_is_not_chase_or_escalate(self) -> None:
        guardrail = TerminalReasonGuardrail()
        context = _context(reason="order_already_paid")
        result = guardrail.evaluate(context, Action.NO_ACTION)
        assert not result.blocked
        assert result.action_after == Action.NO_ACTION

    def test_blocks_terminal_remediation_class_to_no_action(self) -> None:
        guardrail = TerminalReasonGuardrail()
        context = _context(reason="some_future_reason", remediation_class=RemediationClass.TERMINAL)
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert result.blocked
        assert result.action_after == Action.NO_ACTION

    def test_passes_terminal_remediation_class_already_no_action(self) -> None:
        guardrail = TerminalReasonGuardrail()
        context = _context(reason="some_future_reason", remediation_class=RemediationClass.TERMINAL)
        result = guardrail.evaluate(context, Action.NO_ACTION)
        assert not result.blocked


class TestActiveIncidentGuardrail:
    def test_passes_when_no_active_incident(self) -> None:
        guardrail = ActiveIncidentGuardrail()
        context = _context(in_active_incident=False)
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert not result.blocked

    @pytest.mark.parametrize(
        "action", [Action.RECOVERY_LINK_NOW, Action.RECOVERY_LINK_BACKOFF, Action.SWITCH_METHOD]
    )
    def test_blocks_chase_actions_to_wait_bank_recovery(self, action: Action) -> None:
        guardrail = ActiveIncidentGuardrail()
        context = _context(in_active_incident=True)
        result = guardrail.evaluate(context, action)
        assert result.blocked
        assert result.action_after == Action.WAIT_BANK_RECOVERY

    def test_does_not_suppress_escalate_human(self) -> None:
        guardrail = ActiveIncidentGuardrail()
        context = _context(in_active_incident=True)
        result = guardrail.evaluate(context, Action.ESCALATE_HUMAN)
        assert not result.blocked
        assert result.action_after == Action.ESCALATE_HUMAN


class TestAmountFloorGuardrail:
    def test_passes_amount_above_floor(self) -> None:
        guardrail = AmountFloorGuardrail()
        context = _context(amount=_CONFIG.amount_floor_paise + 1)
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert not result.blocked

    def test_blocks_amount_below_floor_for_chase_action(self) -> None:
        guardrail = AmountFloorGuardrail()
        context = _context(amount=_CONFIG.amount_floor_paise - 1)
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert result.blocked
        assert result.action_after == Action.NO_ACTION

    def test_blocks_amount_below_floor_for_escalate_human(self) -> None:
        guardrail = AmountFloorGuardrail()
        context = _context(amount=1)
        result = guardrail.evaluate(context, Action.ESCALATE_HUMAN)
        assert result.blocked
        assert result.action_after == Action.NO_ACTION

    def test_passes_non_investment_action_regardless_of_amount(self) -> None:
        guardrail = AmountFloorGuardrail()
        context = _context(amount=1)
        result = guardrail.evaluate(context, Action.WAIT_BANK_RECOVERY)
        assert not result.blocked


class TestAttemptCapGuardrail:
    def test_passes_within_cap(self) -> None:
        guardrail = AttemptCapGuardrail()
        context = _context(attempt_number=_CONFIG.attempt_cap)
        result = guardrail.evaluate(context, Action.ESCALATE_HUMAN)
        assert not result.blocked

    def test_blocks_beyond_cap_for_escalate_human(self) -> None:
        guardrail = AttemptCapGuardrail()
        context = _context(attempt_number=_CONFIG.attempt_cap + 1)
        result = guardrail.evaluate(context, Action.ESCALATE_HUMAN)
        assert result.blocked
        assert result.action_after == Action.NO_ACTION

    def test_passes_non_investment_action_beyond_cap(self) -> None:
        guardrail = AttemptCapGuardrail()
        context = _context(attempt_number=_CONFIG.attempt_cap + 5)
        result = guardrail.evaluate(context, Action.RECONCILE)
        assert not result.blocked


class TestContactCapGuardrail:
    def test_passes_under_cap(self) -> None:
        guardrail = ContactCapGuardrail()
        context = _context(contacts_in_window=_CONFIG.contact_cap - 1)
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert not result.blocked

    def test_blocks_at_cap(self) -> None:
        guardrail = ContactCapGuardrail()
        context = _context(contacts_in_window=_CONFIG.contact_cap)
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert result.blocked
        assert result.action_after == Action.NO_ACTION

    def test_passes_non_chase_action_regardless_of_contacts(self) -> None:
        guardrail = ContactCapGuardrail()
        context = _context(contacts_in_window=999)
        result = guardrail.evaluate(context, Action.ESCALATE_HUMAN)
        assert not result.blocked


class TestCooldownGuardrail:
    def test_passes_when_never_contacted(self) -> None:
        guardrail = CooldownGuardrail()
        context = _context(time_since_last_contact=None)
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert not result.blocked

    def test_passes_when_cooldown_elapsed(self) -> None:
        guardrail = CooldownGuardrail()
        context = _context(time_since_last_contact=_CONFIG.cooldown)
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert not result.blocked

    def test_blocks_within_cooldown(self) -> None:
        guardrail = CooldownGuardrail()
        context = _context(time_since_last_contact=_CONFIG.cooldown - timedelta(minutes=1))
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert result.blocked
        assert result.action_after == Action.NO_ACTION

    def test_passes_non_chase_action_regardless_of_cooldown(self) -> None:
        guardrail = CooldownGuardrail()
        context = _context(time_since_last_contact=timedelta(seconds=1))
        result = guardrail.evaluate(context, Action.ESCALATE_HUMAN)
        assert not result.blocked


class TestQuietHoursGuardrail:
    def test_passes_outside_quiet_hours(self) -> None:
        guardrail = QuietHoursGuardrail()
        context = _context(created_at=datetime(2026, 1, 1, 12, 0, 0))
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert not result.blocked

    def test_blocks_inside_quiet_hours_for_recovery_link_now(self) -> None:
        guardrail = QuietHoursGuardrail()
        context = _context(created_at=datetime(2026, 1, 1, 23, 0, 0))
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_NOW)
        assert result.blocked
        assert result.action_after == Action.RECOVERY_LINK_BACKOFF

    def test_blocks_inside_quiet_hours_for_switch_method(self) -> None:
        guardrail = QuietHoursGuardrail()
        context = _context(created_at=datetime(2026, 1, 1, 4, 0, 0))
        result = guardrail.evaluate(context, Action.SWITCH_METHOD)
        assert result.blocked
        assert result.action_after == Action.RECOVERY_LINK_BACKOFF

    def test_passes_already_backoff_action(self) -> None:
        guardrail = QuietHoursGuardrail()
        context = _context(created_at=datetime(2026, 1, 1, 23, 0, 0))
        result = guardrail.evaluate(context, Action.RECOVERY_LINK_BACKOFF)
        assert not result.blocked

    def test_passes_escalate_human_regardless_of_hour(self) -> None:
        guardrail = QuietHoursGuardrail()
        context = _context(created_at=datetime(2026, 1, 1, 23, 0, 0))
        result = guardrail.evaluate(context, Action.ESCALATE_HUMAN)
        assert not result.blocked


@pytest.mark.parametrize(
    ("hour", "start", "end", "expected"),
    [
        (21, 21, 9, True),
        (20, 21, 9, False),
        (8, 21, 9, True),
        (9, 21, 9, False),
        (0, 21, 9, True),
        (23, 21, 9, True),
        (10, 9, 17, True),
        (8, 9, 17, False),
        (17, 9, 17, False),
    ],
)
def test_in_quiet_hours(hour: int, start: int, end: int, expected: bool) -> None:
    assert _in_quiet_hours(hour, start, end) is expected


def test_default_guardrail_chain_order_and_names() -> None:
    chain = default_guardrail_chain()
    assert [guardrail.name for guardrail in chain] == [
        "terminal_reason_blocklist",
        "active_incident_suppression",
        "amount_floor",
        "attempt_cap",
        "per_customer_contact_cap",
        "contact_cooldown",
        "quiet_hours",
    ]
