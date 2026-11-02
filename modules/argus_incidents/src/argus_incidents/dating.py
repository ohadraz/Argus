"""When an action was taken, as every reader of an incident says it.

In this package because two readers say it - the postmortem and the incident's
pages - and `argus_web` may import nothing that walks a graph. Said by each in
its own way, the page dated an action by its row and the postmortem by its
announcement, and the one action stood in two different seconds.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from argus_core.events import ActionTaken, IncidentEvent, VerdictReached
from argus_core.models import TakenAction


def when_it_was_taken(taken_action: TakenAction, account: Sequence[IncidentEvent]) -> datetime:
    """The moment the incident's account says the action was taken, or its
    row's where the account says nothing of it.

    The announcement rather than the row, because the row is a claim written
    before anything happens - before even the agent taking the action is called
    in - and dated by it the action comes before the agent that took it. The
    last announcement, because a walk resumed after announcing an action and
    before taking it announces it again, and the second is the one it was taken
    by.

    An attempt that ended before its write is announced by nothing - the
    announcement is made only once a change is - so its verdict saying it was
    not performed is the line that dates it. Never a performed action's
    verdict, which comes once the service has been watched, minutes after the
    change. The row stands for an action an older walk never announced.
    """
    def for_it(hypothesis_id: str | None) -> bool:
        return hypothesis_id is not None and hypothesis_id == taken_action.hypothesis_id

    announced = [event.at for event in account
                 if isinstance(event, ActionTaken) and for_it(event.hypothesis_id)]
    not_performed = [event.at for event in account
                     if isinstance(event, VerdictReached) and not event.performed
                     and for_it(event.hypothesis_id)]

    return (announced or not_performed or [taken_action.taken_at])[-1]
