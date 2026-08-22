"""Tests for reflow.version."""

from reflow import __version__
from reflow.version import get_version


def test_get_version_returns_package_version() -> None:
    """get_version should return the value of reflow.__version__."""
    assert get_version() == __version__


def test_version_is_semver_like() -> None:
    """The package version string should look like a dotted semver triple."""
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
