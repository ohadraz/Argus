"""How soon after the alert Argus did what went well, said by code.

Asked to set a span of time beside the thing it times, a write-up set it after
something else in the same sentence - "brought the service back from the
incident's level {T20.1 - alert_raised} after the alert was raised", which
reads as when the service came back - in two of nine write-ups of one
incident, after the description showed it how and how not. A span is a figure,
and the document writes its figures: so code says each of these moments with
its span first in its sentence, where it can time nothing but what follows, and
the model is asked to say no span of its own there.

Each from the record's own line for the moment - its instant as the row shows
it, to the second, so the span agrees with the rows beside it - and only where
the record holds the moment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from argus_core import parse_iso, said_as_a_span, to_iso
from argus_core.models import TimelineEntry

from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.sections import CANDIDATE_PREFIX, inside_a_sentence, label_of

# What every span here is measured from, as the rest of the document says it.
_AFTER_THE_ALERT: Final = "after the alert was raised"


def how_soon_argus_moved(evidence: IncidentEvidence) -> list[str]:
    """Each moment of the response that went well, timed from the alert, in
    the order they came: the cause the walk acted on formed, the action that
    ended the incident taken, the service confirmed no longer at the incident's
    level, and the fix proposed.

    The first three only where an action was confirmed - one refuted did not go
    well, and an incident a person ended before Argus judged confirmed nothing.
    Confirmed in the record's words, "no longer at the incident's level": that
    is what the verdict measured, and "back" is a claim about normal it did not
    make.
    """
    moments = [*_how_soon_it_was_ended(evidence), *_how_soon_a_fix_was_proposed(evidence)]

    return [_said(evidence.alerted_at, at, what)
            for at, what in sorted(moments, key=lambda moment: moment[0])]


def _how_soon_it_was_ended(evidence: IncidentEvidence) -> list[tuple[datetime, str]]:
    """When the cause the confirmed action was for was formed, when that action
    was taken, and when it was confirmed - the first two by whoever said their
    line, and only where it is in the record; the confirmation by whoever took
    the action, wherever the record dates the verdict."""
    credited = evidence.credited_action
    if credited is None or credited.line is None:
        return []

    taken = evidence.timeline[credited.line]
    moments = [(taken.at, f"{_who(taken)} {inside_a_sentence(credited.action)}")]

    if credited.candidate is not None:
        formed = _the_line_that_formed(evidence.timeline, credited.candidate - 1)
        if formed is not None:
            moments.append((formed.at, f"{_who(formed)} formed the cause that was acted on, "
                                       f"{label_of(CANDIDATE_PREFIX, credited.candidate)}"))

    # By whoever took it: the verdict's own line names no candidate, so nothing
    # on it says which action it judged, while the record dates the verdict.
    if credited.judged_at is not None:
        moments.append((credited.judged_at, f"{_who(taken)} confirmed the service was no "
                                            f"longer at the incident's level"))

    return moments


def _who(entry: TimelineEntry) -> str:
    """Whoever said the line, as a sentence names an agent - Argus, where the
    line names nobody."""
    return f"the {entry.who}" if entry.who is not None else "Argus"


def _the_line_that_formed(timeline: list[TimelineEntry], place: int) -> TimelineEntry | None:
    """The first line that formed the candidate at `place` - a later one can
    list it again, and it was formed when it was first said."""
    return next((entry for entry in timeline if place in entry.candidates), None)


def _how_soon_a_fix_was_proposed(evidence: IncidentEvidence) -> list[tuple[datetime, str]]:
    """When Code-Fix opened the draft fix that stands, where it opened one."""
    if evidence.pull_request is None or evidence.pull_request_opened_at is None:
        return []

    return [(evidence.pull_request_opened_at,
             f"Code-Fix proposed a draft fix, {evidence.pull_request.name}")]


def _said(alerted_at: datetime, at: datetime, what: str) -> str:
    """A moment with its span from the alert first: worked out from both as
    the rows show them, to the second, and opening the sentence as one -
    "Less than a second after", where a span says no figure."""
    span = said_as_a_span(_to_the_second(at) - _to_the_second(alerted_at))

    return f"{span[:1].upper()}{span[1:]} {_AFTER_THE_ALERT}, {what}."


def _to_the_second(instant: datetime) -> datetime:
    return parse_iso(to_iso(instant))
