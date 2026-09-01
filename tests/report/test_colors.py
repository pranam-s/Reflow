"""Tests for reflow.report.colors."""

from __future__ import annotations

import pytest

from reflow.report import colors


def test_relative_luminance_of_black_is_zero() -> None:
    assert colors.relative_luminance("#000000") == pytest.approx(0.0)


def test_relative_luminance_of_white_is_one() -> None:
    assert colors.relative_luminance("#ffffff") == pytest.approx(1.0)


def test_contrast_ratio_of_black_on_white_is_maximal() -> None:
    assert colors.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)


def test_contrast_ratio_is_symmetric() -> None:
    assert colors.contrast_ratio("#000000", "#ffffff") == colors.contrast_ratio(
        "#ffffff", "#000000"
    )


def test_contrast_ratio_of_identical_colors_is_one() -> None:
    assert colors.contrast_ratio("#123456", "#123456") == pytest.approx(1.0)


def test_meets_text_contrast_minimum_rejects_low_contrast_pair() -> None:
    assert colors.meets_text_contrast_minimum("#777777", "#888888") is False


def test_meets_text_contrast_minimum_accepts_black_on_white() -> None:
    assert colors.meets_text_contrast_minimum("#000000", "#ffffff") is True


def test_meets_graphical_contrast_minimum_rejects_low_contrast_pair() -> None:
    assert colors.meets_graphical_contrast_minimum("#777777", "#888888") is False


def test_meets_graphical_contrast_minimum_accepts_black_on_white() -> None:
    assert colors.meets_graphical_contrast_minimum("#000000", "#ffffff") is True


def test_every_declared_text_pair_meets_aa() -> None:
    for label, foreground, background in colors.TEXT_CONTRAST_PAIRS:
        assert colors.meets_text_contrast_minimum(foreground, background), label


def test_every_declared_graphical_pair_meets_its_minimum() -> None:
    for label, foreground, background in colors.GRAPHICAL_CONTRAST_PAIRS:
        assert colors.meets_graphical_contrast_minimum(foreground, background), label
