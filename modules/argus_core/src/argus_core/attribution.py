from __future__ import annotations

from collections.abc import Sequence

from argus_core.models.flag_change import FlagChange

"""Telling Argus's own changes from everybody else's.

Argus identifies a culprit partly by asking the provider what changed recently.
The moment Argus can act more than once, it becomes one of the parties making
those changes: it sets a flag, the provider records it, and the next look at
"what changed recently" finds Argus's own action sitting among the candidates.
An agent that then blames it is investigating itself.

The provider answers this by recording an author on every change, which is only
useful if Argus writes under a name of its own - see `Settings.unleash_actor`
and the credential the Target Environment seeds for it.
"""


def changes_not_made_by(actor: str, changes: Sequence[FlagChange]) -> list[FlagChange]:
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


def change_by_actor_to(flag: str,
                       actor: str,
                       changes: Sequence[FlagChange]) -> bool | None:
    """Whether `actor` is recorded as having changed `flag`, or `None` if that
    cannot be known.

    The question asked about Argus itself, which is the opposite of what the
    rest of this module is for: not "what did somebody else do" but "did what I
    was doing actually happen". A walk resumed after its worker died asks it,
    because the provider's log is the only record of an action taken by a
    process that is gone.

    `None` where no actor is configured. That deployment cannot attribute
    anything to Argus, so the honest answer is that the question is
    unanswerable - and a caller told `False` there would go and act again on
    something that may already have been done.
    """
    if not actor:
        return None

    return any(change.flag == flag for change in changes_made_by(actor, changes))


def changes_made_by(actor: str, changes: Sequence[FlagChange]) -> list[FlagChange]:
    """`changes` that `actor` made, in the order they arrived.

    The mirror of the rule above and not its complement: a change with no
    recorded author is left out of both. "The provider did not say" is not
    "Argus did it" in either direction, and the question this answers - did the
    change Argus was making actually land - has to be answered from what the
    provider attributed, never from what it left blank.

    An empty `actor` therefore answers nothing rather than everything. Where
    Argus and its operators share one credential the provider cannot tell the
    two apart, and a caller asking "did I do this" must be told that it cannot
    be known.
    """
    if not actor:
        return []

    return [
        change
        for change in changes
        if change.actor is not None and change.actor.casefold() == actor.casefold()
    ]
