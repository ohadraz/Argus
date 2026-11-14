"""How soon after the alert each moment that went well came, and what it was,
said by code.

Asked to set a span of time beside the thing it times, a write-up set it after
something else in the same sentence - "brought the service back from the
incident's level {T20.1 - alert_raised} after the alert was raised", which
reads as when the service came back - in two of nine write-ups of one
incident, after the description showed it how and how not. So the model says
what went well and which row it happened on, and says no span; code says the
span, first in the item, where it can time nothing but what follows.

And what follows is the row itself, as the record says it: an item timed by a
restart went on to the confirmation three minutes later, and the span dated
both to the restart. Said as its row, a timed item says exactly what happened
at the moment it is dated to - and what else the model wrote of it goes.

All of the row but one kind: a refuted action's verdict and its undo share a
row, and every write-up timing an item by one credited the put-back, never the
verdict. Said whole, the item credited the verdict too - beside a went_wrong
item faulting that very verdict, so the page praised and faulted one thing. So
an item timed by such a row says the undo alone, in the undo's own words.

And they come in the order they happened. Said in the order the model listed
them, the spans ran 48 seconds, 2 minutes 32 seconds, 45 seconds, 2 minutes 43
seconds down the page - each one true, and the list reading as though the
response went back in time. An item the model left as a sentence keeps its
place; the timed ones take the places the timed ones held, earliest first.

Which moments went well is the model's judgement. Only where it puts the time,
how it says the moment, and the order the timed ones come in are taken from it.
"""

from __future__ import annotations

from collections.abc import Mapping

from argus_core.models import TimelineEntry

from agent_postmortem.figures import Figure, a_span_from_the_alert, an_instant_of
from agent_postmortem.prompting import SubmittedPostmortem
from agent_postmortem.sections import said_as_a_clause


def with_each_moment_timed(answer: SubmittedPostmortem,
                           figures: Mapping[str, Figure],
                           rows: Mapping[str, TimelineEntry]) -> SubmittedPostmortem:
    """The answer with each item of what went well that names its row said
    as that row says it, after how long from the alert its moment came - as a
    working of the row's instant and the alert's, which `with_figures_written`
    writes in - and those items in the order their rows happened, the row each
    is timed by moving with it.

    Only a row of the timeline (`rows`, the T and XW ones by label): another
    row's first figure is a claim's instant or a count, and timed by one an
    item says when nothing was done. An item naming any other row, or one the
    figures hold no instant for, is left as written: `checking` sends it back,
    and a time guessed here would be one nobody measured.
    """
    if answer.lessons is None or not any(answer.went_well_timed_by or []):
        return answer

    timed_by = answer.went_well_timed_by or []
    rows_of = [timed_by[position] if position < len(timed_by) else None
               for position in range(len(answer.lessons.went_well))]
    timed = [_timed(item, row, figures, rows)
             for item, row in zip(answer.lessons.went_well, rows_of, strict=True)]

    said_as_rows = [(position, row) for position, row in enumerate(rows_of)
                    if row is not None and is_said_as_its_row(row, figures, rows)]
    in_time = sorted(said_as_rows, key=lambda said: rows[said[1]].at)
    went_well, by = list(timed), list(rows_of)
    for (place, _), (moved, row) in zip(said_as_rows, in_time, strict=True):
        went_well[place], by[place] = timed[moved], row

    return answer.model_copy(update={
        "lessons": answer.lessons.model_copy(update={"went_well": went_well}),
        "went_well_timed_by": by})


def is_said_as_its_row(row: str | None, figures: Mapping[str, Figure],
                       rows: Mapping[str, TimelineEntry]) -> bool:
    """Whether an item timed by `row` is said as that row - and so none of its
    own words are kept for anyone to judge."""
    return row is not None and row in rows and an_instant_of(row) in figures


def _timed(item: str, row: str | None, figures: Mapping[str, Figure],
           rows: Mapping[str, TimelineEntry]) -> str:
    if row is None or not is_said_as_its_row(row, figures, rows):
        return item

    entry = rows[row]
    said = entry.put_back or said_as_a_clause(entry)

    return f"{a_span_from_the_alert(an_instant_of(row), figures)}, {said}."
