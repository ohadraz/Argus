"""One thing a candidate rests on, pointed at the row it names.

A finding links to a minute where the Investigator said which minute it cited,
and nowhere else. The instant is a field on the evidence rather than something
read back out of the sentence: the model is quoting a line it retrieved, so it
knows the moment, and a link built by matching text against log lines would
point confidently at the wrong evidence - worse than no link, because a reader
would believe it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from argus_core.models.evidence import Evidence
from argus_core.timestamps import parse_iso
from pydantic import BaseModel

from argus_narration.prose import said_plainly


class Finding(BaseModel):
    """One thing a candidate rests on, as the Investigator cited it.

    `links_to_minute` is set only where the finding names a moment that is one
    of the minutes on the page. A finding about a minute nobody retrieved gets
    no link rather than a link into an empty table.
    """

    text: str
    # The moment the Investigator cited, carried through so the finding can be
    # pointed at a row later. A candidate is rendered before the page knows
    # which minutes it holds - that is only settled once every retrieval has
    # been read - so the link is computed twice, and the second time needs the
    # datum rather than the sentence.
    at: datetime | None = None
    links_to_minute: str = ""
    # The lines of that same minute. Its own link because the two answer
    # different questions - what the numbers did, and what the service said -
    # and a reader checking a claim usually wants the second.
    links_to_lines: str = ""


def a_finding(cited: Evidence,
              minutes: Sequence[str] = (),
              logged: Sequence[str] = ()) -> Finding:
    """One cited fact, pointed at the minute it names where it names one.

    Pointed at rows that exist and nothing else: the minute has to be one the
    metrics window covers, and the lines have to be lines the page holds. A
    finding whose moment nobody retrieved gets no link rather than a link into
    an empty table.
    """
    return Finding(
        text=said_plainly(cited.claim),
        at=cited.at,
        links_to_minute=_the_minute_of(cited.at, minutes),
        links_to_lines=_the_minute_of(cited.at, logged)
    )


def pointed_at(finding: Finding,
               minutes: Sequence[str],
               logged: Sequence[str]) -> Finding:
    """The same finding, now that it is known which rows the page holds.

    A candidate is rendered before that is settled - it is only settled once
    every metrics retrieval has been read - so the link is worked out a second
    time here. From the moment the finding carries, never from its sentence:
    the sentence has already been arranged for a reader by then.
    """
    return finding.model_copy(update={
        "links_to_minute": _the_minute_of(finding.at, minutes),
        "links_to_lines": _the_minute_of(finding.at, logged)
    })


def _the_minute_of(said: datetime | None, minutes: Sequence[str]) -> str:
    """The row a finding refers to, or nothing.

    Compared minute against minute, never as text inside text. `21:00` is a
    substring of `2026-08-30T20:21:00Z` - it lands in that minute's *seconds* -
    so a link built by searching for one inside the other points confidently at
    a minute half an hour away from the one the finding named.

    Matched against the minutes actually on the page: a link has to land on a
    row that exists, and a moment nothing retrieved names no row here however
    well it parses.
    """
    if said is None:
        return ""

    for minute in minutes:
        if _the_same_minute(said, minute):
            return minute

    return ""


def _the_same_minute(said: datetime, minute: str) -> bool:
    """Whether the moment a finding named is this minute.

    Truncated to the minute on both sides: a claim cited at 12:30:42 rests on
    the 12:30 bucket, and a comparison to the second would match none of the
    rows the page holds.
    """
    try:
        return said.replace(second=0, microsecond=0) == parse_iso(minute).replace(
            second=0, microsecond=0
        )
    except ValueError:
        return False
