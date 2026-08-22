import pytest

from reflow.policy.actions import (
    CHASE_ACTIONS,
    RECONCILE_REASONS,
    Action,
    UnmappedRemediationClassError,
    base_action_for,
)
from reflow.taxonomy.remediation import RemediationClass


def test_base_action_for_covers_every_remediation_class() -> None:
    for remediation_class in RemediationClass:
        action = base_action_for(remediation_class)
        assert isinstance(action, Action)


@pytest.mark.parametrize(
    ("remediation_class", "expected"),
    [
        (RemediationClass.RETRY_SAME, Action.RECOVERY_LINK_NOW),
        (RemediationClass.WAIT, Action.RECOVERY_LINK_BACKOFF),
        (RemediationClass.CUSTOMER_FIX, Action.RECOVERY_LINK_NOW),
        (RemediationClass.DIFFERENT_INSTRUMENT, Action.RECOVERY_LINK_NOW),
        (RemediationClass.DIFFERENT_METHOD, Action.SWITCH_METHOD),
        (RemediationClass.DIFFERENT_INSTRUMENT_OR_METHOD, Action.SWITCH_METHOD),
        (RemediationClass.CUSTOMER_CONTACT_ISSUER_BANK, Action.RECOVERY_LINK_NOW),
        (RemediationClass.MERCHANT_ACTION, Action.ESCALATE_HUMAN),
        (RemediationClass.MERCHANT_CONTACT_RAZORPAY, Action.ESCALATE_HUMAN),
        (RemediationClass.TERMINAL, Action.NO_ACTION),
    ],
)
def test_base_action_for_exact_mapping(
    remediation_class: RemediationClass, expected: Action
) -> None:
    assert base_action_for(remediation_class) == expected


def test_base_action_for_raises_on_unmapped_class(monkeypatch: pytest.MonkeyPatch) -> None:
    import reflow.policy.actions as actions_module

    fake_map: dict[RemediationClass, Action] = {}
    monkeypatch.setattr(actions_module, "_BASE_ACTION_BY_CLASS", fake_map)
    with pytest.raises(UnmappedRemediationClassError):
        base_action_for(RemediationClass.RETRY_SAME)


def test_chase_actions_is_exactly_the_three_customer_facing_sends() -> None:
    assert (
        frozenset({Action.RECOVERY_LINK_NOW, Action.RECOVERY_LINK_BACKOFF, Action.SWITCH_METHOD})
        == CHASE_ACTIONS
    )


def test_reconcile_reasons_excludes_duplicate_rrn_found() -> None:
    assert "duplicate_rrn_found" not in RECONCILE_REASONS
    assert (
        frozenset({"order_already_paid", "duplicate_request", "duplicate_refund_id"})
        == RECONCILE_REASONS
    )


def test_action_enum_is_exactly_the_seven_closed_members() -> None:
    assert {member.value for member in Action} == {
        "no_action",
        "wait_bank_recovery",
        "recovery_link_now",
        "recovery_link_backoff",
        "switch_method",
        "escalate_human",
        "reconcile",
    }
