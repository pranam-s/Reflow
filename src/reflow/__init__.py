"""Reflow: an agent for recovering failed Razorpay payments.

Reflow clusters failed test-mode Razorpay payments into root causes,
selects a bounded recovery action for each cluster, executes that
action against the Razorpay test-mode APIs, and reports the measured
recovery rate against a baseline.

This phase (Phase 0) provides only the project skeleton: packaging,
tooling configuration, and a minimal module so the quality gates have
something real to check. Clustering, recovery, and reporting logic
land in later phases.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
