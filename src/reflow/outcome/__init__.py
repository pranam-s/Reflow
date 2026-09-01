"""The seeded recovery oracle: Phase 7's ground-truth world for scoring policy decisions.

Every other package under ``src/reflow`` builds the agent: it diagnoses a
failure, picks a bounded action, and executes it against Razorpay's
test-mode APIs. None of it knows, or is allowed to know, whether a given
action actually recovers a given payment -- Razorpay's test mode exposes
only a binary pass/fail toggle on demand, not a realistic, multi-reason
recovery-probability model, so there is nothing for the agent to observe
that would let it "know" this honestly (see :mod:`reflow.outcome.oracle`
module docstring for the full grounding and the sensitivity band this
package reports across).

:mod:`reflow.outcome.oracle` is a separate, seeded, deterministic world
built only to *score* decisions after the fact, in evaluation code under
:mod:`reflow.eval`. The policy and diagnosis layers never import from this
package, and this package never imports from :mod:`reflow.policy.engine`
or :mod:`reflow.diagnose` -- keeping the oracle a spectator, not a
participant, is what makes the resulting evaluation honest: a policy that
could see its own scoring function would not be evaluated, it would be
curve-fit.
"""

from __future__ import annotations

from reflow.outcome.oracle import RecoveryOracle, SensitivityLevel, UnmodeledRemediationClassError

__all__ = [
    "RecoveryOracle",
    "SensitivityLevel",
    "UnmodeledRemediationClassError",
]
