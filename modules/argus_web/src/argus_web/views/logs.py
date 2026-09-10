"""One log line as the service wrote it, read off into the columns a table shows.

The line itself travels alongside whatever is made of it, because the line is
the evidence: `when` and `message` are an arrangement for reading and never a
substitute for what came back. A line announcing no level Argus recognises is
still shown, at no level - the log store belongs to the service, and a line it
never labelled is still a line Argus read.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from argus_web.views.clock import a_moment, is_a_moment

# What a log line's level token means, as the Target Service writes them. The
# page distinguishes warnings and errors from the rest; anything it cannot read
# a level from is the rest.
_LEVELS = {"ERROR": "error", "WARN": "warn", "WARNING": "warn", "INFO": "info"}

# How far into a line to look for that token. The service writes the minute
# first and the level second; a level word appearing later is prose - a line
# that mentions an error is not a line at error level.
_LEVEL_IS_WITHIN_THE_FIRST = 2

_PLAIN = "plain"


class LogLine(BaseModel):
    """One log line as it was read, split into the columns a table shows.

    `text` is the line exactly as the service wrote it - stamp and level
    included - because the line is the evidence. `when` and `message` are that
    same line arranged for reading, never a substitute for it: the page shows
    the arrangement and carries the original with it.
    """

    level: str
    text: str
    stamp: str | None
    when: str
    message: str


def a_log_line(text: str) -> LogLine:
    """One log line, read off into the columns a table shows.

    A line announcing no level it recognises is still shown, at no level, and
    with its whole text as the message: the log store belongs to the service
    rather than to Argus, and a line it never labelled is still a line Argus
    read. The original travels alongside whatever is made of it, so what the
    page shows can always be checked against what came back.
    """
    tokens = text.split()
    stamp = tokens[0] if tokens and is_a_moment(tokens[0]) else None
    level = _PLAIN
    rest = tokens[1:] if stamp else tokens

    for index, token in enumerate(rest[:_LEVEL_IS_WITHIN_THE_FIRST]):
        found = _LEVELS.get(token.strip(":").upper())

        if found is not None:
            level = found
            rest = rest[:index] + rest[index + 1:]
            break

    return LogLine(
        level=level,
        text=text,
        stamp=stamp,
        when=a_moment(stamp) if stamp else "",
        message=" ".join(rest),
    )


def the_minutes_logged(logs: Iterable[LogLine]) -> list[str]:
    """Every minute the page holds log lines for, so a link lands on a row.

    A log line's stamp is to the second; the anchor is the minute, because that
    is the granularity a finding cites and the granularity a reader reads at.
    """
    return sorted({log.stamp[:16] for log in logs if log.stamp})
