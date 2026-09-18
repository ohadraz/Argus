"""Turning a finished incident's rows into the thing a later one can read.

Takes values and returns a value. The actions arrive already fetched, because
the walk that has just finished with them holds a repository already, and a
second module opening its own connection to the same rows would put the question
of whose actions these are in two places.

Almost all of the work is deciding what not to keep. An attempt nobody reached a
verdict on, and an attempt on a subject nobody recorded, are both rows about
something that happened - and neither is evidence about a subject, which is the
only thing this record exists to carry.
"""

from __future__ import annotations

from collections.abc import Sequence

from argus_core.models import Alert, TakenAction, Verdict

from incident_memory.records import RememberedIncident, WhatWasTried

# The two outcomes that say something about the subject that was changed. The
# other two members of `Verdict` say only that nothing was learned: an action
# that could not be performed at all, and one abandoned while the service was
# still being watched.
VERDICTS_THAT_JUDGE_A_SUBJECT: frozenset[Verdict] = frozenset(
    {Verdict.CONFIRMED, Verdict.REFUTED}
)


def a_memory_of(incident_id: str,
                alert: Alert,
                actions: Sequence[TakenAction],
                described_as: str) -> RememberedIncident | None:
    """What this incident is worth remembering as, or nothing.

    Nothing where no action reached a verdict on a subject it named. The record's
    whole content is what attempts were worth, so an incident that produced no
    such attempt would be stored as a description with an empty list - findable
    by a later search, and with nothing to tell it when found.

    A record is written for an escalated incident as readily as for a resolved
    one, and the escalated one is the more valuable of the two: it says three
    subjects were changed and the service stayed broken, which is the part no
    later investigation can derive from its own evidence.
    """
    judged = (_what_the_attempt_was_worth(action) for action in actions)
    tried = [attempt for attempt in judged if attempt is not None]

    if not tried:
        return None

    return RememberedIncident(
        incident_id=incident_id,
        described_as=described_as,
        service=alert.service,
        alert_name=alert.alert_name,
        tried=tried
    )


def _what_the_attempt_was_worth(action: TakenAction) -> WhatWasTried | None:
    """This row as evidence about the subject it changed, or nothing.

    Nothing where the row named no subject - there is then nothing for a later
    candidate to be matched against - and nothing where no verdict was reached
    on it.

    The outcome is a column rather than an enum, so a value no `Verdict` spells
    is expressible and is read as the absence of one. A row written by a version
    that knew an outcome this one does not is a row to pass over, not a reason to
    fail at the close of an incident.
    """
    if not action.subject or action.outcome is None:
        return None

    judgements = {verdict.value: verdict for verdict in VERDICTS_THAT_JUDGE_A_SUBJECT}
    verdict = judgements.get(action.outcome)

    if verdict is None:
        return None

    return WhatWasTried(subject=action.subject, verdict=verdict)
