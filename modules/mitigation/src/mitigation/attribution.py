"""Telling Argus's own changes from everybody else's.

Argus identifies a culprit partly by asking the provider what changed recently.
The moment Argus can act more than once, it becomes one of the parties making
those changes: it sets a flag, the provider records it, and the next look at
"what changed recently" finds Argus's own action sitting among the candidates.
An agent that then blames it is investigating itself.

The provider answers this by recording an author on every change, which is only
useful if Argus writes under a name of its own - the provider's adapter compares
the two and says so on each change (`FlagChange.made_by_argus`), which is what
Mitigation's window of flag changes reads.

The platform's deploy history is the same problem a second time: a rollback is
recorded as a deployment, attributed to the account that asked for it - see
`Settings.argocd_actor`. No adapter says so on a deployment yet, so this filter
is asked of the deployment history here, by the author it records.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Attributed(Protocol):
    """Anything its source records an author on - a deployment, today."""

    @property
    def actor(self) -> str | None: ...


def changes_not_made_by[C: Attributed](actor: str, changes: Sequence[C]) -> list[C]:
    """`changes`, less the ones `actor` made, in the order they arrived.

    Order is preserved because callers read the last mention of a flag as its
    current state, and reordering would change which state gets put back.

    Three rules, and each is a decision about what to do when the answer is not
    clean:

    An empty `actor` filters nothing. That is the honest behaviour where Argus
    and its operators share one credential: the distinction cannot be made, and
    dropping every unattributed change would be acting on a guess.

    A change with no recorded author is kept. "The provider did not say" is not
    "Argus did it", and the costly mistake here is discarding a human's change -
    the real evidence - rather than keeping one of Argus's.

    The comparison ignores case. The name is seeded in the Target Environment's
    repository and compared in this one, and case drifting between the two would
    silently switch the filtering off - which is precisely the failure this
    exists to prevent, arriving quietly.
    """
    if not actor:
        return list(changes)

    return [
        change
        for change in changes
        if change.actor is None or change.actor.casefold() != actor.casefold()
    ]

