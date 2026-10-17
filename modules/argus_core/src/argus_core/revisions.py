"""A revision said short: as git abbreviates it, and as long as it takes to
name it alone among the revisions an incident read.

One rule in one place, because the postmortem, the dashboard and the channel
each say a revision, and two shortenings are two chances to disagree.
"""

from __future__ import annotations

from typing import Final

# How long a revision's short form is, as git abbreviates one - and longer only
# where two revisions the incident read start alike for that long.
_SHORT_FORM: Final = 7


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
