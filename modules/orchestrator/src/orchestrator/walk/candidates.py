"""Which explanation is worth an experiment next, and what would be done about it.

Shared by the two nodes that ask it: the investigation, choosing which of
the candidates it just formed to start on, and the walk, choosing which of
them to try after one was refuted. One question with one answer, so a
candidate the walk would skip is never the one the investigation begins
with.

What an action is worked out from is built here too, for those two and for the
proposal node, so that all three reason from the same circumstances.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_mitigation import propose_action
from argus_core.models import (
    Alert,
    Attempt,
    ChangeEvent,
    Circumstances,
    FlagChange,
    Hypothesis,
    Platform,
    WhatWouldBeTried,
    the_identity_of,
    the_platform_of,
)


def the_circumstances(alert: Alert,
                      flag_changes: Sequence[FlagChange] | None,
                      deployments: Sequence[ChangeEvent] | None
                      ) -> Circumstances | None:
    """What every candidate in a round is answered from, or `None` where the
    flag history could not be read.

    Built here, once, for the three nodes that ask what a candidate would be
    answered with - the investigation ordering its candidates, the walk choosing
    the next one, and the proposal node answering the one chosen. Built by each
    of them, they could come to disagree, and the walk would skip a candidate on
    the strength of an action the proposal node then declines to take.

    The alert's service, because an action addressed to a service is addressed
    to the one the incident is about. The alert's keys for the same reason and
    one more: an entry in a store is addressed by a key nothing in Argus may
    compose, so the addresses the evidence carried are the only thing a discard
    can be worked out from. Both histories are what the round read.

    `None` where the provider could not be read, and then nothing is done about
    anything. Not because every kind of action needs the history - a restart
    does not - but because "I could not find out what changed" and "nothing
    changed" lead to the same place, no action and a human, and acting on the
    one as though it were the other is not something to do in production.

    The alert's keys and an unread platform history are both carried as empty.
    An alert that mentions no cache says nothing about entries rather than
    claiming none is stale, and the one mode that reads deployments proposes a
    rollback only where one was recorded - so neither absence has anything to
    tell a strategy that an empty sequence does not.
    """
    if flag_changes is None:
        return None

    return Circumstances(
        service=alert.service,
        flag_changes=flag_changes,
        stale_entry_keys=alert.stale_entry_keys or (),
        deployments=deployments or ()
    )


def what_each_would_do(candidates: Sequence[Hypothesis],
                       circumstances: Circumstances | None
                       ) -> list[WhatWouldBeTried]:
    """Every candidate, beside the action that answers it.

    Asked of Mitigation rather than guessed at here, because which action
    answers which cause is Mitigation's to say and asking it twice is how the
    two answers come to differ. It is the same question the proposal node asks
    a few nodes later, of the one candidate that got there - asked of all of
    them, and early, because both readers of the answer run before any
    proposal has been made.

    Free of I/O and free of a model, for the same reason `propose_action` is:
    the circumstances arrive as a value.

    No circumstances - a flag history nobody could read - and nothing would be
    done about anything, because this has to answer the same question the
    proposal node will, and that node proposes nothing at all then.
    """
    if circumstances is None:
        return [
            WhatWouldBeTried(candidate=candidate, identity=None)
            for candidate in candidates
        ]

    proposals = (
        (candidate, propose_action(candidate, circumstances))
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
    candidates: Sequence[WhatWouldBeTried],
    attempts: Sequence[Attempt],
    start: int,
    unreachable_platforms: Sequence[Platform] = ()
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

    A third thing disqualifies one, and it is the only one that is not about the
    candidate at all: the platform its action would act through is not answering.
    Four of the five generic mitigations reach the estate through the deployment
    platform, so a platform that failed one of them has failed every candidate
    that needs it - and trying the next of them buys a second failure and a
    verification window. What it does not do is end the walk: the flag revert
    acts through something else, and an incident whose next candidate is one is
    still an incident Argus can mitigate.

    `unreachable_platforms` is empty until something has actually failed, which is
    the only way it can be right. Nothing asks a platform in advance whether it is
    up, because the answer would be about a moment other than the one an action is
    taken in.

    A candidate nothing would be done about is passed over here as it always was,
    by `is_actionable`, and never asked which platform it acts through - there is
    no action to ask about, and asking anyway is the crash this ordering avoids.
    """
    already_tried = {attempt.identity for attempt in attempts}
    unreachable = set(unreachable_platforms)

    for index in range(start, len(candidates)):
        entry = candidates[index]

        if not entry.candidate.is_actionable() or entry.identity in already_tried:
            continue

        if entry.identity is not None and \
                the_platform_of(entry.identity.action_type) in unreachable:
            continue

        return index, entry.candidate

    return None
