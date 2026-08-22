from reflow.policy.actions import Action
from reflow.policy.decision import (
    Decision,
    LadderTerminalState,
    classify_ladder_terminal_state,
    to_dict,
)
from reflow.policy.guardrails import GuardrailEvaluation


def _evaluation(name: str, blocked: bool, before: Action, after: Action) -> GuardrailEvaluation:
    return GuardrailEvaluation(
        name=name, blocked=blocked, action_before=before, action_after=after, reason="test reason"
    )


def test_classify_direct_actions() -> None:
    assert classify_ladder_terminal_state(Action.RECOVERY_LINK_NOW, ()) == (
        LadderTerminalState.IN_PROGRESS_LINK_NOW
    )
    assert classify_ladder_terminal_state(Action.RECOVERY_LINK_BACKOFF, ()) == (
        LadderTerminalState.IN_PROGRESS_BACKOFF
    )
    assert classify_ladder_terminal_state(Action.SWITCH_METHOD, ()) == (
        LadderTerminalState.IN_PROGRESS_SWITCH_METHOD
    )
    assert classify_ladder_terminal_state(Action.ESCALATE_HUMAN, ()) == (
        LadderTerminalState.ESCALATED_TO_HUMAN
    )
    assert classify_ladder_terminal_state(Action.RECONCILE, ()) == LadderTerminalState.RECONCILED
    assert classify_ladder_terminal_state(Action.WAIT_BANK_RECOVERY, ()) == (
        LadderTerminalState.WAITING_ON_BANK
    )


def test_classify_no_action_gave_up_when_attempt_cap_blocked() -> None:
    evaluations = (
        _evaluation(
            "terminal_reason_blocklist", False, Action.ESCALATE_HUMAN, Action.ESCALATE_HUMAN
        ),
        _evaluation("attempt_cap", True, Action.ESCALATE_HUMAN, Action.NO_ACTION),
    )
    assert classify_ladder_terminal_state(Action.NO_ACTION, evaluations) == (
        LadderTerminalState.GAVE_UP
    )


def test_classify_no_action_other_for_non_attempt_cap_block() -> None:
    evaluations = (_evaluation("amount_floor", True, Action.RECOVERY_LINK_NOW, Action.NO_ACTION),)
    assert classify_ladder_terminal_state(Action.NO_ACTION, evaluations) == (
        LadderTerminalState.NO_ACTION_OTHER
    )


def test_classify_no_action_other_when_no_guardrail_blocked_at_all() -> None:
    assert (
        classify_ladder_terminal_state(Action.NO_ACTION, ()) == LadderTerminalState.NO_ACTION_OTHER
    )


def test_to_dict_is_json_safe_and_round_trips_key_fields() -> None:
    decision = Decision(
        payment_id="pay_x",
        order_id="order_x",
        customer_id="cust_x",
        method="upi",
        bank="State Bank of India",
        amount=100_000,
        created_at="2026-01-01T12:00:00",
        attempt_number=1,
        error_reason="payment_timed_out",
        remediation_class="retry_same",
        diagnosis_tier="deterministic",
        diagnosis_confidence="high",
        in_active_incident=False,
        base_action=Action.RECOVERY_LINK_NOW,
        candidate_action=Action.RECOVERY_LINK_NOW,
        guardrail_evaluations=(
            _evaluation(
                "terminal_reason_blocklist",
                False,
                Action.RECOVERY_LINK_NOW,
                Action.RECOVERY_LINK_NOW,
            ),
        ),
        final_action=Action.RECOVERY_LINK_NOW,
        ladder_terminal_state=LadderTerminalState.IN_PROGRESS_LINK_NOW,
        scheduled_delay_seconds=None,
        disallowed_method=None,
        justification="test justification",
    )
    payload = to_dict(decision)
    import json

    serialized = json.dumps(payload)
    reloaded = json.loads(serialized)
    assert reloaded["final_action"] == "recovery_link_now"
    assert reloaded["base_action"] == "recovery_link_now"
    assert reloaded["ladder_terminal_state"] == "in_progress_link_now"
    assert reloaded["guardrail_evaluations"][0]["name"] == "terminal_reason_blocklist"
    assert reloaded["guardrail_evaluations"][0]["blocked"] is False
