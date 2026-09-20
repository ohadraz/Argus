"""Which explanation is worth an experiment next, and what would be done about it.

Shared by the two nodes that ask it: the investigation, choosing which of
the candidates it just formed to start on, and the walk, choosing which of
them to try after one was refuted. One question with one answer, so a
candidate the walk would skip is never the one the investigation begins
with.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_mitigation import propose_action
from argus_core.models import (
    Attempt,
    FlagChange,
    Hypothesis,
    WhatWouldBeTried,
    the_identity_of,
)


def what_each_would_do(candidates: Sequence[Hypothesis],
                       flag_changes: Sequence[FlagChange] | None,
                       service: str) -> list[WhatWouldBeTried]:
    """Every candidate, beside the action that answers it.

    Asked of Mitigation rather than guessed at here, because which action
    answers which cause is Mitigation's to say and asking it twice is how the
    two answers come to differ. It is the same question the proposal node asks
    a few nodes later, of the one candidate that got there - asked of all of
    them, and early, because both readers of the answer run before any
    proposal has been made.

    Free of I/O and free of a model, for the same reason `propose_action` is:
    the flag history arrives as a value.

    A history nobody could read is `None`, and then nothing would be done
    about anything. Not because every kind of action needs the history - a
    restart does not - but because this has to answer the same question the
    proposal node will, and that node proposes nothing at all while the
    provider cannot be read. An answer here that the node a few steps later
    contradicts would be the walk skipping a candidate on the strength of an
    action it then declines to take.
    """
    if flag_changes is None:
        return [
            WhatWouldBeTried(candidate=candidate, identity=None)
            for candidate in candidates
        ]

    proposals = (
        (candidate, propose_action(candidate, flag_changes, service))
        for candidate in candidates
    )

    return [
        WhatWouldBeTried(
            candidate=candidate,
            identity=the_identity_of(action) if action is not None else None
        )
        for candidate, action in proposals
    ]


def the_next_worth_trying(
    candidates: Sequence[WhatWouldBeTried], attempts: Sequence[Attempt], start: int
) -> tuple[int, Hypothesis] | None:
    """The first candidate from `start` onwards that is worth an experiment,
    with the index it sits at - or `None` when the list is spent.

    Every explanation that names a cause is worth one, however far down the list
    it sits: the list is ordered by confidence, so a later candidate is only
    ever reached once the ones the model believed more have been tried and
    refuted, and by then the ranking has already been proved wrong about the
    ones above it.

    Two things disqualify a candidate. One names no cause: there is nothing to
    change on its account, which is a different answer from being unsure. The
    other would do what has already been done - the same action on the same
    subject earlier in this incident, after which the service did not recover -
    and doing it again would be Argus running the same experiment expecting a
    different world. That can happen across rounds, where a later investigation
    is free to reach the same conclusion as the first: the refutation is offered
    to it as evidence, but nothing obliges it to change its mind, and nothing
    should oblige the walk to keep acting on it either.

    Matched on the action rather than on the candidate's own subject, which is
    what it used to be. The two are alike for a flag - what the model blames is
    the flag's name, and the action is addressed to that same name - and
    unalike for anything addressed to a service, where the candidate holds
    prose about the symptom. A restart already tried therefore disqualified
    nothing, and the gate's cap was the only thing standing between the walk
    and restarting the same service once per candidate.
    """
    already_tried = {attempt.identity for attempt in attempts}

    for index in range(start, len(candidates)):
        entry = candidates[index]

        if entry.candidate.is_actionable() and entry.identity not in already_tried:
            return index, entry.candidate

    return None
