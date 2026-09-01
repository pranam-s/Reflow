"""Orchestrating ``reflow demo``'s eight beats: print, then pause, in order.

This is the only module in :mod:`reflow.demo` that ever calls
:func:`reflow.demo.pacing.pause` or prints anything -- every beat's content
comes from :mod:`reflow.demo.narrative`, unmodified, regardless of
``pace``. Beat 5 additionally calls
:func:`reflow.audit.replay.render_replay` directly, reusing the exact
rendering Deliverable 3's ``reflow replay <payment_id>`` already uses, so
the demo's centrepiece beat is not a re-implementation of the replay view
but a literal invocation of it. It passes ``section_numbers=_REPLAY_SECTION_NUMBERS``
so the replay's own six internal sections read as ``5a`` through ``5f`` --
clearly subordinate to this demo's outer beat 5 -- instead of restarting
at ``1`` and colliding, on screen, with this demo's own 1-7 numbering.
"""

from __future__ import annotations

from rich.console import Console

from reflow.audit.replay import render_replay
from reflow.demo import narrative
from reflow.demo.data import DemoData
from reflow.demo.pacing import Pace, pause

_REPLAY_SECTION_NUMBERS: tuple[str, ...] = ("5a", "5b", "5c", "5d", "5e", "5f")
"""Sub-letters the embedded replay's six sections under this demo's own
beat 5, so the on-screen sequence reads ``5.`` then ``5a.``-``5f.`` then
``5. (continued)`` then ``6.`` -- never a second, independent ``1.``-``6.``
run nested inside the outer ``1``-``7`` flow."""


def run_demo(*, console: Console, data: DemoData, pace: Pace) -> None:
    """Print every beat of ``reflow demo`` to ``console``, paced by ``pace``.

    Args:
        console: Where to print. Colour, if any, follows this console's own
            terminal detection (see :mod:`rich.console`); this function
            never overrides it, and every visual cue printed is paired
            with explicit text so the same information survives whether or
            not colour renders.
        data: Every fact the demo needs, from
            :func:`reflow.demo.data.load_demo_data`.
        pace: How long to pause between beats. Never changes what is
            printed -- see :mod:`reflow.demo.pacing`.
    """
    console.print(narrative.build_title_screen())
    pause(pace.intro_seconds)

    console.print(narrative.build_corpus_beat(data.corpus))
    pause(pace.corpus_seconds)

    console.print(narrative.build_root_cause_beat(data.root_cause))
    pause(pace.root_cause_seconds)

    console.print(narrative.build_incident_beat(data.incident))
    pause(pace.incident_seconds)

    console.print(narrative.build_routing_beat(data.routing))
    pause(pace.routing_seconds)

    console.print(narrative.build_guardrail_intro(data))
    render_replay(console, list(data.guardrail_records), section_numbers=_REPLAY_SECTION_NUMBERS)
    console.print(narrative.build_guardrail_outro())
    pause(pace.guardrail_seconds)

    console.print(narrative.build_results_beat(data.results))
    pause(pace.results_seconds)

    console.print(narrative.build_limitations_beat(data.limitations))
    pause(pace.limitations_seconds)

    console.print(narrative.build_outro_screen())
    pause(pace.outro_seconds)
