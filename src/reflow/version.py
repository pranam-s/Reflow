"""Version reporting utilities for the reflow package."""

from reflow import __version__


def get_version() -> str:
    """Return the currently installed reflow package version.

    Returns:
        The semantic version string of the installed reflow package, as
        declared in ``reflow.__version__``.
    """
    return __version__
