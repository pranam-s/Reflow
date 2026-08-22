"""Deterministic train/test split assignment.

The split is designed around one hazard: **downtime-window leakage**. If
events from the same outage incident could land on both sides of the
split, a model could partly memorise that specific incident's exact
characteristics (its precise reason mixture, its bank, its time window)
from the train half and get credit for "generalizing" to the test half of
the very same incident. That would overstate how well clustering
generalizes to genuinely unseen outages.

The policy implemented here is therefore:

- **Every event belonging to a given downtime window goes to the same
  split.** The decision is made once per window (a single weighted coin
  flip per :class:`~reflow.corpus.downtime.DowntimeWindow`), not per event.
  This guarantees no single incident straddles the boundary.
- **Background (non-downtime) events are split independently per event.**
  They carry no window identity to leak, so there is nothing to protect
  by grouping them.

One consequence, chosen deliberately: because whole windows move together,
some *distinct* outage incidents land in train and others in test. That is
the correct property for evaluation -- it lets a later phase ask "does
this generalize to an outage it has not seen the specifics of," which is a
meaningfully harder and more honest question than "does it remember this
exact outage." A naive per-event random split would have answered the
easier, less honest question instead.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Iterator
from dataclasses import replace

from reflow.corpus.downtime import DowntimeWindow
from reflow.corpus.events import PaymentEvent

TRAIN = "train"
TEST = "test"


def assign_splits(
    rng: random.Random,
    events: Iterable[PaymentEvent],
    windows: list[DowntimeWindow],
    test_fraction: float = 0.2,
) -> Iterator[PaymentEvent]:
    """Assign each event to the train or test split.

    Args:
        rng: Deterministic random source. Consumed once per window (to
            decide that window's split) up front, then once per
            background event as they are streamed through.
        events: The generated event stream, with ``split`` left as the
            ``"unassigned"`` placeholder set by
            :func:`reflow.corpus.events.build_event`.
        windows: Every downtime window used to generate ``events``, so a
            split can be pre-assigned to each one.
        test_fraction: Target fraction of independent split decisions
            (windows and background events alike) assigned to the test
            split.

    Yields:
        Each input event with ``split`` set to ``"train"`` or ``"test"``.
    """
    window_split = {
        window.window_id: (TEST if rng.random() < test_fraction else TRAIN) for window in windows
    }
    for event in events:
        if event.downtime_window_id is not None:
            split = window_split[event.downtime_window_id]
        else:
            split = TEST if rng.random() < test_fraction else TRAIN
        yield replace(event, split=split)
