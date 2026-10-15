"""The revisions an answer names, held to the ones the incident read.

A revision is a name, and the answer writes it the way a reader meets one: in
its short form, as git abbreviates it and a pull request or a log shows it.
Forty characters in a sentence read as noise, and a document writing one
revision two ways reads as naming two. The one place it is also written whole
is a change's own row, beside its short form, for a reader to copy.

What code holds it to is being one. A real revision, short or whole, is written
short. One a few characters off is the revision it starts like, and is written
as that: code knows which one it was, and asking the model again would pay
twice to put back a character. One that starts like none of them, or like more
than one, is left as written for the check to put back to the model
(`checking`), because nothing here can know what it meant.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Final

from agent_postmortem.evidence import IncidentEvidence

# For the annotations alone: the prompt labels each change with its revision's
# short form for the document's rows, so it imports this module, and the
# answer's type is the prompt's.
if TYPE_CHECKING:
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

# How long a revision's short form is, as git abbreviates one - and longer only
# where two revisions the incident read start alike for that long.
_SHORT_FORM: Final = 7


def revisions_of(evidence: IncidentEvidence) -> frozenset[str]:
    """Every revision the incident read: what its changes name, and what its
    candidates blame. A flag is named in both places too, and is no revision."""
    named = [change.reference for change in evidence.changes]
    named += [candidate.subject for candidate in evidence.candidates
              if candidate.subject is not None]

    return frozenset(each for each in named if A_REVISION.fullmatch(each))


def with_revisions_corrected(answer: SubmittedPostmortem,
                             revisions: frozenset[str]) -> SubmittedPostmortem:
    """The answer with every revision it names written as the real one, in
    its short form."""
    def corrected(prose: str) -> str:
        return A_REVISION.sub(lambda named: _as_meant(named.group(0), revisions), prose)

    return answer.with_each_sentence(corrected)


def unknown_revisions_in(prose: str, revisions: frozenset[str]) -> list[str]:
    """The revisions a sentence names that are none the incident read."""
    return [named for named in A_REVISION.findall(prose) if not _is_one_of(named, revisions)]


def _is_one_of(named: str, revisions: frozenset[str]) -> bool:
    return any(revision.startswith(named) for revision in revisions)


def _as_meant(named: str, revisions: frozenset[str]) -> str:
    """The short form of the revision it names, or of the one it starts like
    where exactly one starts like it - and as written where it names no one
    revision."""
    meant = _the_revision_named(named, revisions)

    return short_form(meant, revisions) if meant is not None else named


def _the_revision_named(named: str, revisions: frozenset[str]) -> str | None:
    """The one revision `named` is the start of, or is a few characters off -
    `None` where it is the start of several, or like none."""
    starting = [revision for revision in revisions if revision.startswith(named)]

    if starting:
        return starting[0] if len(starting) == 1 else None

    return _the_one_it_starts_like(named, revisions)


def short_form(revision: str, revisions: frozenset[str]) -> str:
    """The revision as short as git would write it, and as long as it takes to
    name it alone among the revisions the incident read.

    A revision this one starts with, or that starts with this one, is another
    name for the same commit rather than a rival, and makes it no longer: a
    change's short form beside a candidate naming it whole is one revision.

    Public because the document's rows name each change's revision as the
    prose does, and a second shortening is a second chance to disagree."""
    rivals = [other for other in revisions
              if not (other.startswith(revision) or revision.startswith(other))]
    length = _SHORT_FORM

    # Ends: a rival never starts with the whole revision, or it would be
    # another name for it.
    while any(other.startswith(revision[:length]) for other in rivals):
        length += 1

    return revision[:length]


def _the_one_it_starts_like(named: str, revisions: frozenset[str]) -> str | None:
    shared = {revision: len(os.path.commonprefix([named, revision])) for revision in revisions}
    longest = max(shared.values(), default=0)
    closest = [revision for revision, length in shared.items() if length == longest]

    if longest < ENOUGH_TO_BE_THE_SAME or len(closest) != 1:
        return None

    return closest[0]
