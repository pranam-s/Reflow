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

Beat 5 renders 103 lines across intro, 5a-5f, and its continuation -- far
more than a terminal's 30-50 visible lines -- so it is split into three
screen-sized bursts, each followed by its own pause, rather than one
35-second pause after everything has already scrolled past. Splitting
happens entirely through ``render_replay``'s optional ``between_panels``
callback (see :func:`_pause_between_replay_panels`): this module still
calls :func:`~reflow.audit.replay.render_replay` exactly once, so the
embedded replay is never re-implemented or duplicated, only paused
part-way through.
"""

from __future__ import annotations

from collections.abc import Callable

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

_GUARDRAIL_CONTEXT_PANEL_INDEX = 2
"""``render_replay``'s panel index for 5c (diagnosis), the last panel of
burst 5-i (intro + 5a-5c)."""

_GUARDRAIL_CHAIN_PANEL_INDEX = 3
"""``render_replay``'s panel index for 5d (guardrail chain), which is
burst 5-ii on its own -- the demo's single most information-dense
screen."""


def _pause_between_replay_panels(pace: Pace) -> Callable[[int], None]:
    """Build the callback that splits Beat 5's pause into three bursts.

    Args:
        pace: The active :class:`~reflow.demo.pacing.Pace`, supplying the
            three guardrail sub-pauses to sleep for.

    Returns:
        A callback suitable for :func:`reflow.audit.replay.render_replay`'s
        ``between_panels`` argument: it pauses for
        ``pace.guardrail_context_seconds`` right after 5c and for
        ``pace.guardrail_chain_seconds`` right after 5d, and does nothing
        after any other panel (5a, 5b, 5e, 5f are not burst boundaries;
        the third pause, ``pace.guardrail_decision_seconds``, runs after
        this beat's continuation, outside the replay call, in
        :func:`run_demo`).
    """

    def _on_panel_rendered(panel_index: int) -> None:
        if panel_index == _GUARDRAIL_CONTEXT_PANEL_INDEX:
            pause(pace.guardrail_context_seconds)
        elif panel_index == _GUARDRAIL_CHAIN_PANEL_INDEX:
            pause(pace.guardrail_chain_seconds)

    return _on_panel_rendered


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
    render_replay(
        console,
        list(data.guardrail_records),
        section_numbers=_REPLAY_SECTION_NUMBERS,
        between_panels=_pause_between_replay_panels(pace),
    )
    console.print(narrative.build_guardrail_outro())
    pause(pace.guardrail_decision_seconds)

    console.print(narrative.build_results_beat(data.results))
    pause(pace.results_seconds)

    console.print(narrative.build_limitations_beat(data.limitations))
    pause(pace.limitations_seconds)

    console.print(narrative.build_outro_screen())
    pause(pace.outro_seconds)
