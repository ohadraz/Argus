from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Lifespan(BaseModel, frozen=True):
    """When something was going on: from `began_at` to `ended_at`, or to now
    where it has not ended.

    What ties an on-call platform's incident to an Argus incident once a key
    no longer does. Every firing of an alert group pages under the group's
    one key, so a key held by several incidents names none of them; the two
    incidents an alert opened are the ones going on at the same time. Two
    doors ask that - a person's resolution arriving from the platform, and the
    postmortem reading who responded - and the rule is here so they give the
    same answer.
    """

    began_at: datetime
    # `None` while it is still going on.
    ended_at: datetime | None

    def overlaps(self, other: Lifespan) -> bool:
        """Whether the two were going on at any one moment.

        Ends included: one ending in the instant the other began overlaps it,
        because an incident and its page are stamped by two clocks, and two
        clocks cannot place those instants apart. One still going has not
        ended, and overlaps anything that had not ended before it began.
        """
        return (
            (other.ended_at is None or self.began_at <= other.ended_at)
            and (self.ended_at is None or other.began_at <= self.ended_at)
        )
