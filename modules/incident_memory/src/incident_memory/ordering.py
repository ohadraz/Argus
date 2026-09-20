"""What memory is allowed to do to a walk, which is to change an order.

An action that was taken on a similar incident and did not help sends the
candidate that would take it again to the back of the list. Everything else
keeps the order confidence gave it, so a walk with no matching record behaves
exactly as a walk with no memory at all - which is what lets the benchmark
(§21) compare the two.

**Demoted, never removed.** A past incident is evidence about a past incident,
the same flag can break the service twice, and a walk that refused to try the
only candidate it had - on the strength of a different incident's result - would
end in an escalation it had the means to avoid. The set of candidates tried is
identical with memory and without it; only the order differs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from argus_core.models import ActionIdentity, Verdict, WhatWouldBeTried

from incident_memory.records import RememberedIncident


@dataclass(frozen=True)
class Reordering:
    """The candidates in the order to try them, and what moved them.

    `on_the_strength_of` is the past incident whose record demoted something,
    and `None` where nothing moved - which is the ordinary case and the one that
    must stay silent. A walk that tried its second-best candidate first with
    nothing saying why is a walk a human reading the incident back cannot
    account for; a walk that says so on every incident is a timeline nobody
    reads.
    """

    # Handed back in the shape they arrived in, still paired with what each
    # would be answered with. The caller asked that question to put it here,
    # and asking it a second time to recover the candidates alone would be the
    # walk holding two answers it has to keep in step.
    candidates: list[WhatWouldBeTried]
    # The action that moved a candidate, beside the record that moved it. Both
    # or neither: a line saying an order changed without saying what changed
    # places is a line a reader cannot check against the list in front of them.
    #
    # The identity rather than its subject, because the subject is what the
    # reader cannot check. "Moved checkout down the list" is true of a service
    # somebody restarted and of a flag somebody put back, and the two are not
    # the same evidence.
    moved: ActionIdentity | None
    on_the_strength_of: str | None


def demoting_what_was_refuted(candidates: Sequence[WhatWouldBeTried],
                              recalled: Sequence[RememberedIncident]) -> Reordering:
    """The candidates again, with anything refuted before moved to the back.

    Each candidate arrives beside the action that answers it, and it is the
    action that is matched. Asked of the candidates themselves the question was
    unanswerable: what a model calls a leak is prose, and no two incidents
    write the same prose, so a service restarted on both of them looked like
    two unrelated subjects. Asked of the action, "restarting checkout did not
    help last time" is evidence the walk can act on.

    Stable on both sides of the split: candidates memory says nothing about keep
    their order among themselves, and so do the demoted ones. Demotion is
    relative, so demoting every candidate demotes none of them - and the walk
    still tries them all, which is the point.

    A candidate nothing would be done about is left where it is. There is no
    action for a record to match it against, and moving it would be moving it
    for a reason nobody could read back.
    """
    refuted_by = _what_refuted_each_action(recalled)
    kept: list[WhatWouldBeTried] = []
    demoted: list[WhatWouldBeTried] = []
    # The first candidate that actually moved, and below it the record that
    # moved it. One of each rather than all of them: the line this becomes is
    # read during an incident, and "because of these four" is a list a person
    # scanning a timeline does not follow. Taken as the split is made, because
    # that is where the identity is known to be one.
    moved: ActionIdentity | None = None

    for entry in candidates:
        if entry.identity is not None and entry.identity in refuted_by:
            demoted.append(entry)
            moved = moved if moved is not None else entry.identity
        else:
            kept.append(entry)

    reordered = [*kept, *demoted]

    if moved is None or reordered == list(candidates):
        return Reordering(
            candidates=list(candidates), moved=None, on_the_strength_of=None
        )

    return Reordering(
        candidates=reordered, moved=moved, on_the_strength_of=refuted_by[moved]
    )


def _what_refuted_each_action(
    recalled: Sequence[RememberedIncident]
) -> dict[ActionIdentity, str]:
    """Each action a recalled incident took and was refuted by, and which one.

    Only a refutation. A confirmation says taking that action once fixed an
    incident, which is no reason at all to demote it later - and the two
    verdicts are the only ones a record can carry, because nothing else was
    ever a judgement about the action.

    The nearest record wins an action two of them name, since `recalled`
    arrives ordered by similarity and the more alike incident is the better
    evidence.
    """
    refuted_by: dict[ActionIdentity, str] = {}

    for incident in recalled:
        for attempt in incident.tried:
            if attempt.verdict is Verdict.REFUTED:
                refuted_by.setdefault(attempt.identity, incident.incident_id)

    return refuted_by
