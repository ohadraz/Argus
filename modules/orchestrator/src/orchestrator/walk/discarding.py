"""Where a step about to run discards what its interrupted attempt wrote.

A step's writes stand or fall with its checkpoint. LangGraph checkpoints a step
once it has returned, so a worker that dies inside one - or a step that lets an
unavailable model requeue the run - leaves a checkpoint from before it, and the
step runs again from its start. Everything it wrote the first time it writes
again: the agent invoked, every line of its findings, a second set of
candidates under the same numbers. So the step takes the first attempt's back
before it starts, found by the step every one of those rows carries.

Just before the node runs, and only where it is about to: a step stopped by a
person's ending runs nothing, so it keeps its interrupted attempt's account -
the change the attempt made, or the postmortem's line beside its row. For a
node wrapped in `with_status`, that is inside it, after the ending is asked;
for the two that are not, it is around the node itself (`discarding_first`).

Inside the step's binding (`incident_record.within_step`), which is where the
key is read from. Reading it there rather than being handed it is what makes
a discard outside a step - one wrapped in the wrong order - fail where it is
made, instead of writing the line it publishes with no step on it, which a
second attempt would then never take back.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from core.events import StepRunAgain
from incident_record import the_current_step

from orchestrator.walk.ports import DiscardTheInterruptedAttempt
from orchestrator.walk.state import IncidentState


class Discard(Protocol):
    """What a node is handed to run just before it: the discard of its own
    interrupted attempt, or the decision not to make one."""

    def __call__(self, state: IncidentState, /) -> None: ...


def discarding_the_interrupted_attempt(step: str,
                                       discard: DiscardTheInterruptedAttempt) -> Discard:
    """The discard for the node registered as `step`, taking back what its
    interrupted attempt wrote and saying so where it wrote anything.

    Refuses outside a step of the walk: there is no step to discard, and the
    line saying the step was run again would be written as nobody's.
    """
    def run(state: IncidentState, /) -> None:
        at_step = the_current_step()

        if at_step is None:
            raise RuntimeError(
                f"the {step} step of incident {state.incident_id} discarded its "
                f"interrupted attempt outside any step of the walk"
            )

        discard(state.incident_id, at_step,
                StepRunAgain(incident_id=state.incident_id, step=step))

    return run


def discards_nothing(dont_care_state: IncidentState, /) -> None:
    """The discard a node with nothing to take back is handed: every case
    about something else."""


def discarding_first[R](discard: Discard,
                        node: Callable[[IncidentState], R]) -> Callable[[IncidentState], R]:
    """`node`, run after `discard` - for a node not wrapped in `with_status`,
    which runs the discard for the nodes that are."""
    def run(state: IncidentState) -> R:
        discard(state)

        return node(state)

    return run
