"""One thing a candidate rests on, pointed at the row it names.

A finding links to a minute only where it quotes a time that parses into one of
the minutes the page actually holds. Prose is never matched to log lines: the
model writes *about* the lines rather than quoting them, and a link built by
guessing which line it meant would point confidently at the wrong evidence -
worse than no link, because a reader would believe it.
"""

from __future__ import annotations

from collections.abc import Sequence

from argus_core.timestamps import parse_iso
from pydantic import BaseModel

from argus_web.views.clock import a_minute
from argus_web.views.prose import a_time_named_in, said_plainly


class Finding(BaseModel):
    """One thing a candidate rests on, as the Investigator cited it.

    `links_to_minute` is set only where the finding quotes a time that can be
    parsed into one of the minutes on the page. Prose is not matched to log
    lines: the model writes about the lines rather than quoting them, and a
    link built by guessing which line it meant would point confidently at the
    wrong evidence - worse than no link, because a reader would believe it.
    """

    text: str
    links_to_minute: str = ""
    # The lines of that same minute. Its own link because the two answer
    # different questions - what the numbers did, and what the service said -
    # and a reader checking a claim usually wants the second.
    links_to_lines: str = ""


def a_finding(cited: str,
              minutes: Sequence[str] = (),
              logged: Sequence[str] = ()) -> Finding:
    """One cited fact, pointed at the minute it names where it names one.

    Pointed at rows that exist and nothing else: the minute has to be one the
    metrics window covers, and the lines have to be lines the page holds. A
    finding about a minute nobody retrieved gets no link rather than a link
    into an empty table.
    """
    return Finding(
        text=said_plainly(cited),
        links_to_minute=_the_minute_named_in(cited, minutes),
        links_to_lines=_the_minute_named_in(cited, logged),
    )


def _the_minute_named_in(cited: str, minutes: Sequence[str]) -> str:
    """The row a finding refers to, or nothing.

    Compared minute against minute, never as text inside text. `21:00` is a
    substring of `2026-08-30T20:21:00Z` - it lands in that minute's *seconds* -
    so a link built by searching for one inside the other points confidently at
    a minute half an hour away from the one the finding named.

    Matched against the minutes actually on the page: a link has to land on a
    row that exists, and a time nothing retrieved names no row here however
    well it parses.
    """
    said = a_time_named_in(cited)

    if said is None:
        return ""

    for minute in minutes:
        if _the_same_minute(said, minute):
            return minute

    return ""


def _the_same_minute(said: str, minute: str) -> bool:
    """Whether a time quoted in prose is this minute.

    Prose writes a time either as the wire format the tools speak or as the
    clock time a person reads, so both are compared as what they are: an
    instant truncated to its minute, or the minute's own rendering.
    """
    try:
        return parse_iso(said).replace(second=0, microsecond=0) == parse_iso(
            minute
        ).replace(second=0, microsecond=0)
    except ValueError:
        return a_minute(minute) == said.rstrip("Z")[:5]
