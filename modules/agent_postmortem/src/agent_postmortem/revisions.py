"""The revisions an answer names, held to the ones the incident read.

A revision is a name, and the answer writes it as given - it is what a reader
searches for. What code holds it to is being one. A real revision, short or
whole, stands. One a few characters off is the revision it starts like, and is
written as that: code knows which one it was, and asking the model again would
pay twice to put back a character. One that starts like none of them, or like
more than one, is left as written for the check to put back to the model
(`checking`), because nothing here can know what it meant.
"""

from __future__ import annotations

import os
import re
from typing import Final

from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.prompting import SubmittedPostmortem

# A revision as a deploy names it, short or whole: a run of hex with a digit and
# a letter in it, so that no English word reads as one, standing as a word of
# its own - the hash inside a pod's name is part of that name.
A_REVISION: Final = re.compile(
    r"(?<![\w-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w-])"
)

# How many leading characters a misremembered revision has to share with a real
# one to be read as it: one chance in sixty-five thousand by accident.
ENOUGH_TO_BE_THE_SAME: Final = 4


def revisions_of(evidence: IncidentEvidence) -> frozenset[str]:
    """Every revision the incident read: what its changes name, and what its
    candidates blame. A flag is named in both places too, and is no revision."""
    named = [change.reference for change in evidence.changes]
    named += [candidate.subject for candidate in evidence.candidates
              if candidate.subject is not None]

    return frozenset(each for each in named if A_REVISION.fullmatch(each))


def with_revisions_corrected(answer: SubmittedPostmortem,
                             revisions: frozenset[str]) -> SubmittedPostmortem:
    """The answer with every misremembered revision written as the real one,
    as long as the model wrote it."""
    def corrected(prose: str) -> str:
        return A_REVISION.sub(lambda named: _as_meant(named.group(0), revisions), prose)

    return answer.with_each_sentence(corrected)


def unknown_revisions_in(prose: str, revisions: frozenset[str]) -> list[str]:
    """The revisions a sentence names that are none the incident read."""
    return [named for named in A_REVISION.findall(prose) if not _is_one_of(named, revisions)]


def _is_one_of(named: str, revisions: frozenset[str]) -> bool:
    return any(revision.startswith(named) for revision in revisions)


def _as_meant(named: str, revisions: frozenset[str]) -> str:
    """The revision as written where it is real, as the one it starts like
    where exactly one starts like it, and as written otherwise."""
    if _is_one_of(named, revisions):
        return named

    meant = _the_one_it_starts_like(named, revisions)

    return meant[:len(named)] if meant is not None else named


def _the_one_it_starts_like(named: str, revisions: frozenset[str]) -> str | None:
    shared = {revision: len(os.path.commonprefix([named, revision])) for revision in revisions}
    longest = max(shared.values(), default=0)
    closest = [revision for revision, length in shared.items() if length == longest]

    if longest < ENOUGH_TO_BE_THE_SAME or len(closest) != 1:
        return None

    return closest[0]
