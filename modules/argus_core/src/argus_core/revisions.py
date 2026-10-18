"""A revision said short: as git abbreviates it, and as long as it takes to
name it alone among the revisions an incident read - and found in a sentence,
whole or by a start of it, as the one revision that start names.

One rule in one place, because the postmortem, the dashboard and the channel
each say a revision, and two shortenings are two chances to disagree.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

# How long a revision's short form is, as git abbreviates one - and longer only
# where two revisions the incident read start alike for that long.
_SHORT_FORM: Final = 7

# A revision as a deploy names it, short or whole: a run of hex with a digit and
# a letter in it, so that no English word reads as one, standing as a word of
# its own - the hash inside a pod's name is part of that name.
A_REVISION: Final = re.compile(
    r"(?<![\w-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w-])"
)


def the_revision_named(named: str, revisions: frozenset[str]) -> str | None:
    """The one revision among `revisions` that `named` is, whole, or is the
    start of - `None` where it starts several, since nothing here can say which
    was meant, or none.

    Nor a start shorter than a short form, which git abbreviates one to by
    default: that short, a start of a revision is any small number.

    A start a few characters off is no start of anything here: putting that
    right is a guess about what a writer meant, and belongs to whoever can ask
    the writer again."""
    if len(named) < _SHORT_FORM:
        return None

    starting = [revision for revision in revisions if revision.startswith(named)]

    return starting[0] if len(starting) == 1 else None


def said_short(text: str, shorts: Mapping[str, str]) -> str:
    """`text` with each revision in `shorts` it names - whole, or by a start
    only that one begins - said by its short form, the revision's value in
    `shorts`. A start several begin, and a revision `shorts` does not hold,
    are left as written."""
    if not shorts:
        return text

    whole = frozenset(shorts)

    def as_said(named: re.Match[str]) -> str:
        meant = the_revision_named(named.group(0), whole)
        return shorts[meant] if meant is not None else named.group(0)

    return A_REVISION.sub(as_said, text)


def short_form(revision: str, revisions: frozenset[str]) -> str:
    """The revision as short as git would write it, and as long as it takes to
    name it alone among `revisions`.

    A revision this one starts with, or that starts with this one, is another
    name for the same commit rather than a rival, and makes it no longer: a
    change's short form beside a candidate naming it whole is one revision.

    The length depends on what else was read, so a line said before a later,
    colliding read keeps fewer characters than one said after it - in seven
    hex characters within one incident, vanishingly rarely."""
    rivals = [other for other in revisions
              if not (other.startswith(revision) or revision.startswith(other))]
    length = _SHORT_FORM

    # Ends: a rival never starts with the whole revision, or it would be
    # another name for it.
    while any(other.startswith(revision[:length]) for other in rivals):
        length += 1

    return revision[:length]
