"""Which explanation is worth an experiment next.

Shared by the two nodes that ask it: the investigation, choosing which of
the candidates it just formed to start on, and the walk, choosing which of
them to try after one was refuted. One question with one answer, so a
candidate the walk would skip is never the one the investigation begins
with.
"""

from __future__ import annotations

from argus_core.models.attempt import Attempt
from argus_core.models.hypothesis import Hypothesis


def the_next_worth_trying(
    candidates: list[Hypothesis], attempts: list[Attempt], start: int
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
    other has already been tried - the same subject was changed earlier in this
    incident and the service did not recover - and doing it again would be
    Argus running the same experiment expecting a different world. That can
    happen across rounds, where a later investigation is free to reach the same
    conclusion as the first: the refutation is offered to it as evidence, but
    nothing obliges it to change its mind, and nothing should oblige the walk to
    keep acting on it either.
    """
    already_tried = {attempt.subject for attempt in attempts}

    for index in range(start, len(candidates)):
        candidate = candidates[index]

        if candidate.is_actionable() and candidate.subject not in already_tried:
            return index, candidate

    return None
