"""The response's minutes, held by title.

Kept apart by title rather than summed, because a pay band prices a title:
whatever prices the response after the document is written prices these rows,
and a total that has added one title's minutes to another's cannot be priced.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.models import TitleMinutes

from postmortem_writing.sources import EngagedResponder


def minutes_by_title(engaged: Sequence[EngagedResponder]) -> list[TitleMinutes]:
    """One row per title, in the order each title first responded: how many
    held it and their minutes. Responders with no title recorded are a row of
    their own, so the rows still add up to everyone who responded."""
    by_title: dict[str | None, list[int]] = {}
    for responder in engaged:
        by_title.setdefault(responder.job_title, []).append(responder.minutes)

    return [TitleMinutes(title=title, responders=len(minutes), minutes=sum(minutes))
            for title, minutes in by_title.items()]
