"""Tests for reflow.outcome.oracle."""

from __future__ import annotations

import pytest

from reflow.outcome import oracle as oracle_module
from reflow.outcome.oracle import RecoveryOracle, SensitivityLevel, UnmodeledRemediationClassError
from reflow.policy.actions import Action, base_action_for
from reflow.taxonomy.remediation import RemediationClass


def test_every_remediation_class_has_a_strictly_positive_self_recovery_rate() -> None:
    central = RecoveryOracle(level=SensitivityLevel.CENTRAL)
    for remediation_class in RemediationClass:
        assert central.self_recovery_rate(remediation_class) > 0.0


def test_reconcile_never_recovers_regardless_of_class_or_level() -> None:
    for level in SensitivityLevel:
        oracle = RecoveryOracle(level=level)
        for remediation_class in RemediationClass:
            assert oracle.recovery_probability(remediation_class, Action.RECONCILE) == 0.0


def test_reconcile_sample_recovery_is_always_false() -> None:
    oracle = RecoveryOracle()
    for payment_id in ("pay_1", "pay_2", "pay_3", "pay_4", "pay_5"):
        assert (
            oracle.sample_recovery(payment_id, RemediationClass.RETRY_SAME, Action.RECONCILE)
            is False
        )


def test_wait_bank_recovery_probability_is_class_independent() -> None:
    oracle = RecoveryOracle(level=SensitivityLevel.CENTRAL)
    rates = {
        oracle.recovery_probability(remediation_class, Action.WAIT_BANK_RECOVERY)
        for remediation_class in RemediationClass
    }
    assert len(rates) == 1


def test_native_action_beats_non_native_action_for_every_class_with_headroom() -> None:
    oracle = RecoveryOracle(level=SensitivityLevel.CENTRAL)
    for remediation_class in RemediationClass:
        native_action = base_action_for(remediation_class)
        if native_action in (Action.RECONCILE, Action.WAIT_BANK_RECOVERY, Action.NO_ACTION):
            continue
        native_probability = oracle.recovery_probability(remediation_class, native_action)
        other_actions = [
            action
            for action in Action
            if action not in (native_action, Action.RECONCILE, Action.WAIT_BANK_RECOVERY)
        ]
        for action in other_actions:
            assert oracle.recovery_probability(remediation_class, action) <= native_probability


def test_no_action_matches_self_recovery_rate_exactly() -> None:
    oracle = RecoveryOracle(level=SensitivityLevel.OPTIMISTIC)
    for remediation_class in RemediationClass:
        assert oracle.recovery_probability(
            remediation_class, Action.NO_ACTION
        ) == oracle.self_recovery_rate(remediation_class)


def test_sensitivity_band_is_monotonic_in_uplift_bearing_actions() -> None:
    pessimistic = RecoveryOracle(level=SensitivityLevel.PESSIMISTIC)
    central = RecoveryOracle(level=SensitivityLevel.CENTRAL)
    optimistic = RecoveryOracle(level=SensitivityLevel.OPTIMISTIC)
    action = base_action_for(RemediationClass.RETRY_SAME)
    p_pess = pessimistic.recovery_probability(RemediationClass.RETRY_SAME, action)
    p_cent = central.recovery_probability(RemediationClass.RETRY_SAME, action)
    p_opt = optimistic.recovery_probability(RemediationClass.RETRY_SAME, action)
    assert p_pess <= p_cent <= p_opt


def test_sensitivity_band_moves_the_no_action_floor_monotonically_and_narrowly() -> None:
    for remediation_class in RemediationClass:
        pessimistic = RecoveryOracle(level=SensitivityLevel.PESSIMISTIC).recovery_probability(
            remediation_class, Action.NO_ACTION
        )
        central = RecoveryOracle(level=SensitivityLevel.CENTRAL).recovery_probability(
            remediation_class, Action.NO_ACTION
        )
        optimistic = RecoveryOracle(level=SensitivityLevel.OPTIMISTIC).recovery_probability(
            remediation_class, Action.NO_ACTION
        )
        assert pessimistic < central < optimistic
        assert pessimistic == pytest.approx(central * 0.8)
        assert optimistic == pytest.approx(central * 1.2)


def test_floor_band_is_narrower_than_the_action_uplift_band() -> None:
    remediation_class = RemediationClass.RETRY_SAME
    action = base_action_for(remediation_class)
    central = RecoveryOracle(level=SensitivityLevel.CENTRAL)
    optimistic = RecoveryOracle(level=SensitivityLevel.OPTIMISTIC)
    floor_ratio = optimistic.self_recovery_rate(remediation_class) / central.self_recovery_rate(
        remediation_class
    )
    action_ratio = optimistic.recovery_probability(
        remediation_class, action
    ) / central.recovery_probability(remediation_class, action)
    assert floor_ratio < action_ratio


def test_probabilities_are_always_within_the_unit_interval() -> None:
    for level in SensitivityLevel:
        oracle = RecoveryOracle(level=level)
        for remediation_class in RemediationClass:
            for action in Action:
                probability = oracle.recovery_probability(remediation_class, action)
                assert 0.0 <= probability <= 1.0


def test_sample_recovery_is_deterministic_across_repeated_calls() -> None:
    oracle = RecoveryOracle()
    args = ("pay_abc123", RemediationClass.RETRY_SAME, Action.RECOVERY_LINK_NOW)
    assert oracle.sample_recovery(*args) == oracle.sample_recovery(*args)


def test_sample_recovery_draw_is_shared_across_sensitivity_levels() -> None:
    payment_id = "pay_shared_draw"
    remediation_class = RemediationClass.CUSTOMER_FIX
    action = base_action_for(remediation_class)
    pessimistic_recovers = RecoveryOracle(level=SensitivityLevel.PESSIMISTIC).sample_recovery(
        payment_id, remediation_class, action
    )
    optimistic_recovers = RecoveryOracle(level=SensitivityLevel.OPTIMISTIC).sample_recovery(
        payment_id, remediation_class, action
    )
    if pessimistic_recovers:
        assert optimistic_recovers


def test_sample_recovery_distribution_is_plausible_over_many_payment_ids() -> None:
    oracle = RecoveryOracle(level=SensitivityLevel.CENTRAL)
    remediation_class = RemediationClass.RETRY_SAME
    action = base_action_for(remediation_class)
    expected = oracle.recovery_probability(remediation_class, action)
    n = 4000
    recovered = sum(
        1 for i in range(n) if oracle.sample_recovery(f"pay_dist_{i}", remediation_class, action)
    )
    observed = recovered / n
    assert abs(observed - expected) < 0.03


def test_recovery_probability_raises_for_an_unmodeled_remediation_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oracle_module, "_TAXONOMY_CLASSES", frozenset())
    oracle = RecoveryOracle()
    with pytest.raises(UnmodeledRemediationClassError):
        oracle.recovery_probability(RemediationClass.RETRY_SAME, Action.NO_ACTION)


def test_self_recovery_rate_raises_for_an_unmodeled_remediation_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oracle_module, "_TAXONOMY_CLASSES", frozenset())
    oracle = RecoveryOracle()
    with pytest.raises(UnmodeledRemediationClassError):
        oracle.self_recovery_rate(RemediationClass.TERMINAL)


def test_action_ceiling_is_reachable_from_native_fit_at_central_level() -> None:
    oracle = RecoveryOracle(level=SensitivityLevel.CENTRAL)
    remediation_class = RemediationClass.RETRY_SAME
    action = base_action_for(remediation_class)
    assert oracle.recovery_probability(remediation_class, action) == pytest.approx(
        oracle_module._ACTION_CEILING[remediation_class]
    )


def test_default_oracle_level_is_central() -> None:
    assert RecoveryOracle().level is SensitivityLevel.CENTRAL
