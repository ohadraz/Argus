"""Turning a finished incident's rows into the thing a later one can read.

Takes values and returns a value. The actions arrive already fetched, because
the walk that has just finished with them holds a repository already, and a
second module opening its own connection to the same rows would put the question
of whose actions these are in two places.

Almost all of the work is deciding what not to keep. An attempt nobody reached a
verdict on, and an attempt on a subject nobody recorded, are both rows about
something that happened - and neither is evidence about an action, which is the
only thing this record exists to carry.
"""

from __future__ import annotations

from collections.abc import Sequence

from argus_core.models import Alert, TakenAction, Verdict, the_identity_recorded

from incident_memory.records import RememberedIncident, WhatWasTried

# The two outcomes that say something about the action that was taken. The
# other two members of `Verdict` say only that nothing was learned: an action
# that could not be performed at all, and one abandoned while the service was
# still being watched.
VERDICTS_THAT_JUDGE_AN_ACTION: frozenset[Verdict] = frozenset(
    {Verdict.CONFIRMED, Verdict.REFUTED}
)


def a_memory_of(incident_id: str,
                alert: Alert,
                actions: Sequence[TakenAction],
                described_as: str) -> RememberedIncident | None:
    """What this incident is worth remembering as, or nothing.

    Nothing where no attempt reached a verdict on an action this version can
    identify. The record's whole content is what attempts were worth, so an
    incident that produced no such attempt would be stored as a description
    with an empty list - findable by a later search, and with nothing to tell
    it when found.

    A record is written for an escalated incident as readily as for a resolved
    one, and the escalated one is the more valuable of the two: it says three
    actions were taken and the service stayed broken, which is the part no
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
    """This row as evidence about the action it records, or nothing.

    Nothing where the row named no subject - there is then nothing for a later
    candidate to be matched against - and nothing where no verdict was reached
    on it.

    The outcome arrives as a value, so what is asked here is whether it is a
    verdict at all and, if it is, which. An outcome the row carries but this
    version cannot spell is neither of the two that judge an action, and is
    passed over with them: a row written by a version that knew an outcome this
    one does not is a row with nothing to say about the action, not a reason to
    fail at the close of an incident.

    The kind is read from the row the same way and passed over on the same
    terms. It is a column of text, so a version that has since dropped a kind
    of action can still be asked for one - and the answer is a record a later
    walk could never match, since matching it means proposing an action of a
    kind this Argus no longer has.
    """
    if not action.subject:
        return None

    outcome = action.outcome

    if not isinstance(outcome, Verdict) or outcome not in VERDICTS_THAT_JUDGE_AN_ACTION:
        return None

    identity = the_identity_recorded(action.type, action.subject)

    if identity is None:
        return None

    return WhatWasTried(identity=identity, verdict=outcome)
