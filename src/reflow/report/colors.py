"""A fixed, WCAG-AA-verified colour palette, plus the contrast-ratio maths.

Every colour the HTML report (:mod:`reflow.report.html`) uses for text is
declared here, once, alongside the exact background it is always paired
with, so :mod:`reflow.report.validate` can recompute a real WCAG 2.1
contrast ratio for every pair independently of any browser -- the
report's colours are fixed constants, so this is exact maths on the
values actually shipped, not a guess about how a renderer might display
them.

**WCAG 2.1 success criterion 1.4.3 (contrast, minimum)** requires a ratio
of at least 4.5:1 for normal text and 3:1 for large-scale text (at least
18pt, or 14pt bold) and for graphical/UI-component boundaries (1.4.11).
Every pair in :data:`TEXT_CONTRAST_PAIRS` is checked against 4.5:1;
:data:`GRAPHICAL_CONTRAST_PAIRS` (purely decorative bar-chart fills, which
carry no text and are marked ``aria-hidden`` in the generated HTML, so
they are not strictly required to meet even the lower bound) are checked
against 3:1 anyway, as a stricter bar than the specification demands.
"""

from __future__ import annotations

COLOR_BACKGROUND: str = "#ffffff"
COLOR_TEXT: str = "#1a1a1a"
COLOR_HEADING: str = "#10243e"
COLOR_LINK: str = "#0b4f9e"
COLOR_DANGER: str = "#a3241c"
COLOR_SUCCESS: str = "#146c2e"
COLOR_MUTED: str = "#3f3f3f"
COLOR_BORDER: str = "#8a8a8a"
COLOR_TABLE_HEADER_BG: str = "#dbe4f0"
COLOR_TABLE_HEADER_TEXT: str = "#0a1a2e"
COLOR_FOOTER_BG: str = "#f2f2f2"
COLOR_FOOTER_TEXT: str = "#3f3f3f"
COLOR_BAR_TRACK: str = "#e2e8f0"
COLOR_BAR_FILL: str = "#0b4f9e"

TEXT_CONTRAST_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("body text on page background", COLOR_TEXT, COLOR_BACKGROUND),
    ("headings on page background", COLOR_HEADING, COLOR_BACKGROUND),
    ("links on page background", COLOR_LINK, COLOR_BACKGROUND),
    ("danger/verdict text on page background", COLOR_DANGER, COLOR_BACKGROUND),
    ("success/verdict text on page background", COLOR_SUCCESS, COLOR_BACKGROUND),
    ("muted/caption text on page background", COLOR_MUTED, COLOR_BACKGROUND),
    (
        "table header text on table header background",
        COLOR_TABLE_HEADER_TEXT,
        COLOR_TABLE_HEADER_BG,
    ),
    ("footer text on footer background", COLOR_FOOTER_TEXT, COLOR_FOOTER_BG),
)
"""Every (label, foreground, background) pair the report uses for actual
text, each required to meet WCAG AA's 4.5:1 minimum for normal text."""

GRAPHICAL_CONTRAST_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("decorative bar fill on bar track", COLOR_BAR_FILL, COLOR_BAR_TRACK),
)
"""Purely decorative, ``aria-hidden`` bar-chart fills against their track
background -- not required by WCAG to meet any text contrast minimum
(they carry no text and are hidden from assistive technology), checked
here anyway against the stricter 3:1 bound as a deliberate margin of
safety for sighted low-vision readers who do not use a screen reader."""

_MIN_TEXT_CONTRAST: float = 4.5
_MIN_GRAPHICAL_CONTRAST: float = 3.0


def _srgb_channel_to_linear(channel: float) -> float:
    """Convert one sRGB channel value (0-1) to its linear-light equivalent.

    Args:
        channel: The channel value, in ``[0, 1]``.

    Returns:
        The linearised channel value, per the WCAG 2.1 formula.
    """
    if channel <= 0.03928:
        return channel / 12.92
    return float(((channel + 0.055) / 1.055) ** 2.4)


def relative_luminance(hex_color: str) -> float:
    """Compute a colour's relative luminance, per WCAG 2.1.

    Args:
        hex_color: A ``"#rrggbb"`` colour string.

    Returns:
        The relative luminance, in ``[0, 1]``.
    """
    stripped = hex_color.lstrip("#")
    red = int(stripped[0:2], 16) / 255.0
    green = int(stripped[2:4], 16) / 255.0
    blue = int(stripped[4:6], 16) / 255.0
    linear_red = _srgb_channel_to_linear(red)
    linear_green = _srgb_channel_to_linear(green)
    linear_blue = _srgb_channel_to_linear(blue)
    return 0.2126 * linear_red + 0.7152 * linear_green + 0.0722 * linear_blue


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """Compute the WCAG 2.1 contrast ratio between two colours.

    Args:
        hex_a: The first ``"#rrggbb"`` colour.
        hex_b: The second ``"#rrggbb"`` colour.

    Returns:
        The contrast ratio, in ``[1, 21]`` (``1`` is identical colours,
        ``21`` is black against white).
    """
    luminance_a = relative_luminance(hex_a)
    luminance_b = relative_luminance(hex_b)
    lighter = max(luminance_a, luminance_b)
    darker = min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def meets_text_contrast_minimum(hex_a: str, hex_b: str) -> bool:
    """Check whether a colour pair meets WCAG AA's normal-text minimum.

    Args:
        hex_a: The first ``"#rrggbb"`` colour.
        hex_b: The second ``"#rrggbb"`` colour.

    Returns:
        ``True`` if :func:`contrast_ratio` is at least 4.5:1.
    """
    return contrast_ratio(hex_a, hex_b) >= _MIN_TEXT_CONTRAST


def meets_graphical_contrast_minimum(hex_a: str, hex_b: str) -> bool:
    """Check whether a colour pair meets WCAG AA's graphical-object minimum.

    Args:
        hex_a: The first ``"#rrggbb"`` colour.
        hex_b: The second ``"#rrggbb"`` colour.

    Returns:
        ``True`` if :func:`contrast_ratio` is at least 3:1.
    """
    return contrast_ratio(hex_a, hex_b) >= _MIN_GRAPHICAL_CONTRAST
