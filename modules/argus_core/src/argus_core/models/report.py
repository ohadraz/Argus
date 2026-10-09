"""A person telling Argus how an incident ended, and where they said it.

Here rather than beside the door that takes it, for the reason `Undone` is
here: the web endpoint builds one, the event that accounts for the ending
carries it, and the narration and the postmortem page read it back. A
vocabulary kept inside one of those parties is one the others read by
comparing spellings.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ReportChannel(StrEnum):
    """Where a person's report reached Argus.

    A channel rather than a free string, because what a reader does with a
    report differs by where it came from - a note typed into Argus's own page
    and a resolve pressed in a paging tool are answered in different places -
    and each door that takes a report is one more member here rather than one
    more spelling somebody has to recognise.
    """

    ARGUS_UI = "argus-ui"
    # The on-call platform that paged the person, resolved there. Named for the
    # vendor because the channel is where a reader goes to find the person, and
    # that place has a name; which platform it was stays a fact about the
    # report, not a word anything branches on.
    PAGERDUTY = "pagerduty"


class Report(BaseModel):
    """Who ended an incident from outside the walk, through which channel, and
    what they added.

    No time of its own: the event carrying it is stamped where it is built,
    and that is the moment the report was taken. A second time here would be a
    second answer to one question.

    `note` is `None` rather than empty where the person said nothing, so that a
    reader is never shown a blank where a sentence was expected.
    """

    by: str
    channel: ReportChannel
    note: str | None = None
