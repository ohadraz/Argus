"""How soon after the alert each moment that went well came, said by code.

Asked to set a span of time beside the thing it times, a write-up set it after
something else in the same sentence - "brought the service back from the
incident's level {T20.1 - alert_raised} after the alert was raised", which
reads as when the service came back - in two of nine write-ups of one
incident, after the description showed it how and how not. So the model says
what went well and which row it happened on, and says no span; code says the
span, first in the item, where it can time nothing but what follows.

Which moments went well, and whether when they came is part of why, is the
model's judgement. Only where it puts the time is taken from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from agent_postmortem.figures import Figure, a_span_from_the_alert, an_instant_of
from agent_postmortem.prompting import SubmittedPostmortem

# The words an item may open with that a sentence goes on to lower: what the
# description asks a timed item to begin with is who did it, and a name stays
# as it is written. Public because `checking` holds a timed item to opening
# with one of these or a name.
LOWERED_AFTER_A_SPAN: Final = frozenset({"The", "A", "An"})


def with_each_moment_timed(answer: SubmittedPostmortem,
                           figures: Mapping[str, Figure],
                           timeline_rows: frozenset[str]) -> SubmittedPostmortem:
    """The answer with each item of what went well that names its row said
    after how long from the alert that row's moment came - as a working of the
    row's instant and the alert's, which `with_figures_written` writes in.

    Only a row of the timeline (`timeline_rows`, the T and XW ones): another
    row's first figure is a claim's instant or a count, and timed by one an
    item says when nothing was done. An item naming any other row, or one the
    figures hold no instant for, is left as written: `checking` sends it back,
    and a time guessed here would be one nobody measured.
    """
    if answer.lessons is None or not any(answer.went_well_timed_by or []):
        return answer

    rows = answer.went_well_timed_by or []
    timed = [_timed(item, rows[position] if position < len(rows) else None, figures,
                    timeline_rows)
             for position, item in enumerate(answer.lessons.went_well)]

    return answer.model_copy(update={
        "lessons": answer.lessons.model_copy(update={"went_well": timed})})


def _timed(item: str, row: str | None, figures: Mapping[str, Figure],
           timeline_rows: frozenset[str]) -> str:
    if (row is None or row not in timeline_rows
            or (instant := an_instant_of(row)) not in figures):
        return item

    return f"{a_span_from_the_alert(instant, figures)}, {_as_it_goes_on(item)}"


def _as_it_goes_on(item: str) -> str:
    """The item as a sentence goes on with it after a span: its opening
    article lowered, and its own full stop kept as the sentence's."""
    opening, _, rest = item.partition(" ")
    said = f"{opening.lower()} {rest}" if opening in LOWERED_AFTER_A_SPAN else item

    return said if said.endswith(".") else f"{said}."
