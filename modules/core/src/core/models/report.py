"""A person telling Argus how an incident ended, and where they said it.

Here rather than beside the door that takes it, for the reason `Undone` is
here: the web endpoint builds one, the event that accounts for the ending
carries it, and the narration and the postmortem page read it back. A
vocabulary kept inside one of those parties is one the others read by
comparing spellings.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, model_validator


class ReportChannel(StrEnum):
    """Where a person's report reached Argus, by the part the door plays.

    A channel rather than a free string, because what a reader does with a
    report differs by where it came from - a note typed into Argus's own page
    and a resolve pressed in a paging tool are answered in different places.
    By role rather than by vendor: which platform it was is the report's
    `platform`, supplied by that platform's adapter, so a deployment paging
    through another vendor adds an adapter and nothing here.
    """

    ARGUS_UI = "argus-ui"
    # The on-call platform that paged the person, resolved there.
    ON_CALL_PLATFORM = "on-call-platform"
    # The incident's own thread, where the person said it was over and then
    # confirmed it.
    CHAT_PLATFORM = "chat-platform"


class Report(BaseModel):
    """Who ended an incident from outside the walk, through which channel, and
    what they added.

    No time of its own: the event carrying it is stamped where it is built,
    and that is the moment the report was taken. A second time here would be a
    second answer to one question.

    `platform` is the platform's own name, as its adapter gives it - the place a
    reader goes to find the person - and `None` for Argus's own page, which is
    no platform's. `note` is `None` rather than empty where the person said
    nothing, so that a reader is never shown a blank where a sentence was
    expected.
    """

    by: str
    channel: ReportChannel
    platform: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _a_platform_exactly_where_one_was_used(self) -> Self:
        """A platform named for every report that came through one, and none
        for a report typed into Argus's own page - so a reader is never told
        a report came from nowhere, or from a platform it never passed through.
        An empty name is no name, and would be said as one."""
        if self.platform == "" or (self.platform is None) != (
                self.channel is ReportChannel.ARGUS_UI):
            raise ValueError(
                f"a report through [{self.channel}] names the platform "
                f"[{self.platform}]: only one through Argus's own page names none"
            )

        return self
