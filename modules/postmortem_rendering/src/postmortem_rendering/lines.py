"""A line of the postmortem: its words, in pieces, each with the part it plays.

Every word a reader is told is in a run, joining words included - "went from",
"later", "by" - so no destination adds one of its own and the page and the PDF
cannot come to say different things. What a destination may add is how a part
looks: a subject set in code on the page and in a fixed-width face in the PDF,
a state struck through, a moment said again on the reader's own clock where
there is a reader's clock to say it on.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import in_utc

# How a moment is said in the body of the document: its date spelled once, in
# UTC, which every destination can print and none has to work out.
_A_MOMENT: Final = "%b %d, %Y, %H:%M"


class Role(StrEnum):
    """The part a run plays, which is all a destination may style it by.

    `PROSE` is the model's words, which may cite a label - a destination with
    rows to link to links them - where everything else is the record's.
    `CITATION` is one such label, cut out of the prose by `Run.with_citations`;
    a name in it that opens somewhere is cut out as a `LINK`.
    `NARRATION` is a line of Argus's own account, which writes the statuses
    and verdicts it names in capitals, so a destination may mark them.
    """

    PLAIN = "plain"
    PROSE = "prose"
    CITATION = "citation"
    NARRATION = "narration"
    CODE = "code"
    STRONG = "strong"
    FROM_STATE = "from-state"
    TO_STATE = "to-state"
    STATUS = "status"
    LINK = "link"
    QUOTE = "quote"
    MOMENT = "moment"


class Run(BaseModel):
    """A piece of a line: its words and the part they play.

    `address` is where a link goes - for a citation, the label of the row it
    names - and `at` the instant a moment names - each set on the roles that
    have one. `until` is the other end, for a moment
    that is a window: said as one run, because "14:03 to 14:12 UTC" names its
    zone once and a reader's own clock says the two ends together.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    role: Role = Role.PLAIN
    address: str | None = None
    at: datetime | None = None
    until: datetime | None = None

    @classmethod
    def a_moment(cls, at: datetime) -> Run:
        """A moment said in UTC, carrying the instant for a destination that
        can say it again on a reader's own clock."""
        return cls(text=in_utc(at, _A_MOMENT), role=Role.MOMENT, at=at)

    @classmethod
    def an_address(cls, address: str) -> Run:
        """An address said whole: read away from the screen it came from, one
        relative to nothing leads nowhere."""
        return cls(text=address, role=Role.LINK, address=address)

    def with_citations(self, labels: Collection[str]) -> tuple[Run, ...]:
        """The run cut at every label it cites, each label a citation of the
        row it names and the words between them left as they were.

        Only `labels` are cited - the ones with a row in the document - so a
        label with nothing to lead to stays in the words. A label is matched
        whole, so `AI-1` is never cut out of `AI-12`.
        """
        return tuple(Run(text=piece, role=Role.CITATION, address=piece) if named
                     else self.model_copy(update={"text": piece})
                     for piece, named in self._cut_at(labels))

    def with_links(self, addresses: Mapping[str, str]) -> tuple[Run, ...]:
        """The run cut at every name in `addresses`, each name a link to where
        it opens and the words between them left as they were.

        A name is matched whole, as a label is, so the directory `deploy` is
        never cut out of `deployed`.
        """
        return tuple(Run(text=piece, role=Role.LINK, address=addresses[piece]) if named
                     else self.model_copy(update={"text": piece})
                     for piece, named in self._cut_at(addresses))

    def with_references(self, labels: Collection[str],
                        addresses: Mapping[str, str]) -> tuple[Run, ...]:
        """The run cut at every label it cites, as `with_citations` cuts it,
        and the words between them at every name in `addresses`, as
        `with_links` does - "the deploy of revision 7c3ca00 (P2)" leading to
        the row P2 names and to where the revision opens."""
        return tuple(linked for piece in self.with_citations(labels)
                     for linked in (piece.with_links(addresses)
                                    if piece.role is not Role.CITATION else (piece,)))

    def _cut_at(self, names: Collection[str]) -> Iterator[tuple[str, bool]]:
        """The run's words in pieces, each with whether it is one of `names` -
        matched whole, the longer of two names that start alike first."""
        if not names:
            yield self.text, False
            return

        alternatives = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        pieces = re.split(rf"(?<!\w)({alternatives})(?!\w)", self.text)
        # `split` puts what the group matched at every odd place.
        yield from ((piece, bool(place % 2)) for place, piece in enumerate(pieces) if piece)


class Line(BaseModel):
    """A line of the document, as the runs it is said in."""

    model_config = ConfigDict(frozen=True)

    runs: tuple[Run, ...]

    @property
    def said(self) -> str:
        """The line's words, every run's in order, with nothing wrapped round
        them."""
        return "".join(run.text for run in self.runs)
