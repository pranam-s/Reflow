"""Narration pacing for ``reflow demo``, kept strictly separate from content.

The phase brief requires the demo to run roughly 2.5-3 minutes of wall
clock by default, with deliberate pauses a live narrator can talk over,
and a ``--fast`` mode for CI/testing that must never change what is
printed -- only how long the process waits between printing it.
:class:`Pace` is the single seam that separates those two concerns: every
narrative-building function in :mod:`reflow.demo.narrative` takes no pace
argument at all and always returns the same renderables, and
:mod:`reflow.demo.runner` is the only place :func:`pause` is ever called.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pace:
    """How long ``reflow demo`` pauses after each beat, in seconds.

    Attributes:
        intro_seconds: Pause after the title/introduction.
        corpus_seconds: Pause after Beat 1 (the corpus).
        root_cause_seconds: Pause after Beat 2 (``GROUP BY`` vs.
            clustering).
        incident_seconds: Pause after Beat 3 (incident detection).
        routing_seconds: Pause after Beat 4 (the routing split).
        guardrail_seconds: Pause after Beat 5 (the guardrail refusing to
            act, plus the full replay) -- the longest pause, since this
            beat carries the most content to narrate over.
        results_seconds: Pause after Beat 6 (the results table).
        limitations_seconds: Pause after Beat 7 (honest limitations).
        outro_seconds: Pause after the closing summary.
    """

    intro_seconds: float
    corpus_seconds: float
    root_cause_seconds: float
    incident_seconds: float
    routing_seconds: float
    guardrail_seconds: float
    results_seconds: float
    limitations_seconds: float
    outro_seconds: float

    @property
    def total_seconds(self) -> float:
        """Sum of every pause this pace defines, i.e. the demo's floor wall-clock time.

        Returns:
            The total number of seconds :func:`pause` will sleep for across
            one full run at this pace, excluding the negligible time spent
            actually printing content.
        """
        return (
            self.intro_seconds
            + self.corpus_seconds
            + self.root_cause_seconds
            + self.incident_seconds
            + self.routing_seconds
            + self.guardrail_seconds
            + self.results_seconds
            + self.limitations_seconds
            + self.outro_seconds
        )


PACED: Pace = Pace(
    intro_seconds=8.0,
    corpus_seconds=18.0,
    root_cause_seconds=24.0,
    incident_seconds=22.0,
    routing_seconds=20.0,
    guardrail_seconds=35.0,
    results_seconds=22.0,
    limitations_seconds=15.0,
    outro_seconds=8.0,
)
"""The default pace: roughly 172 seconds (~2 minutes 52 seconds) of
deliberate pauses, within the phase brief's 2.5-3 minute target, spread so
the single most consequential beat (the guardrail refusing to act) gets
the most room."""

FAST: Pace = Pace(
    intro_seconds=0.0,
    corpus_seconds=0.0,
    root_cause_seconds=0.0,
    incident_seconds=0.0,
    routing_seconds=0.0,
    guardrail_seconds=0.0,
    results_seconds=0.0,
    limitations_seconds=0.0,
    outro_seconds=0.0,
)
"""Zero pauses, for CI and automated verification (``reflow demo --fast``).
Prints exactly the same content as :data:`PACED`, in the same order --
only the pauses between sections are removed."""


def pause(seconds: float) -> None:
    """Sleep for ``seconds``, the only place ``reflow demo`` blocks on time.

    Args:
        seconds: How long to sleep. ``0`` (as every :data:`FAST` field is)
            returns immediately without calling :func:`time.sleep` at all.
    """
    if seconds > 0:
        time.sleep(seconds)
