import pytest

from reflow.policy.actions import Action
from reflow.policy.ladder import LADDER_ORDER, ladder_action


def test_ladder_order_is_the_four_escalating_rungs() -> None:
    assert LADDER_ORDER == (
        Action.RECOVERY_LINK_NOW,
        Action.RECOVERY_LINK_BACKOFF,
        Action.SWITCH_METHOD,
        Action.ESCALATE_HUMAN,
    )


@pytest.mark.parametrize(
    ("base_action", "attempt_number", "expected"),
    [
        (Action.RECOVERY_LINK_NOW, 1, Action.RECOVERY_LINK_NOW),
        (Action.RECOVERY_LINK_NOW, 2, Action.RECOVERY_LINK_BACKOFF),
        (Action.RECOVERY_LINK_NOW, 3, Action.SWITCH_METHOD),
        (Action.RECOVERY_LINK_NOW, 4, Action.ESCALATE_HUMAN),
        (Action.RECOVERY_LINK_NOW, 5, Action.ESCALATE_HUMAN),
        (Action.RECOVERY_LINK_NOW, 100, Action.ESCALATE_HUMAN),
        (Action.RECOVERY_LINK_BACKOFF, 1, Action.RECOVERY_LINK_BACKOFF),
        (Action.RECOVERY_LINK_BACKOFF, 2, Action.SWITCH_METHOD),
        (Action.RECOVERY_LINK_BACKOFF, 3, Action.ESCALATE_HUMAN),
        (Action.RECOVERY_LINK_BACKOFF, 4, Action.ESCALATE_HUMAN),
        (Action.SWITCH_METHOD, 1, Action.SWITCH_METHOD),
        (Action.SWITCH_METHOD, 2, Action.ESCALATE_HUMAN),
        (Action.SWITCH_METHOD, 3, Action.ESCALATE_HUMAN),
        (Action.ESCALATE_HUMAN, 1, Action.ESCALATE_HUMAN),
        (Action.ESCALATE_HUMAN, 5, Action.ESCALATE_HUMAN),
    ],
)
def test_ladder_action_climbs_and_clamps(
    base_action: Action, attempt_number: int, expected: Action
) -> None:
    assert ladder_action(base_action, attempt_number) == expected


@pytest.mark.parametrize(
    "base_action", [Action.NO_ACTION, Action.RECONCILE, Action.WAIT_BANK_RECOVERY]
)
def test_ladder_action_passes_through_non_ladder_actions(base_action: Action) -> None:
    for attempt_number in (1, 2, 5, 10):
        assert ladder_action(base_action, attempt_number) == base_action


def test_ladder_action_defensively_floors_attempt_number_below_one() -> None:
    assert ladder_action(Action.RECOVERY_LINK_NOW, 0) == Action.RECOVERY_LINK_NOW
    assert ladder_action(Action.RECOVERY_LINK_NOW, -5) == Action.RECOVERY_LINK_NOW
