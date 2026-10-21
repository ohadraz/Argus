"""What a postmortem says before any section: its title, and the rows a reader
asks about before reading any of it.

Which incident, when it was broken, how finished the document is, who wrote it
and when, and who ended the incident. The two times a reader most easily takes
for each other - when the service was broken, and when this was written about
it - are separate rows, each saying which it is.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Final

from argus_core.models import (
    ActionItemStatus,
    Alert,
    ChangeKind,
    ImpactExtent,
    OpenedPullRequest,
    Postmortem,
    PostmortemDocument,
    TimelineMarker,
)
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import as_revision, on_the_clock, on_the_day
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.resolution import Escalation, ReportedResolution
from postmortem_rendering.supporting import OPENED_AS_A_DRAFT

# What follows a moment's day, as the head says the start of the incident's window.
_AFTER_THE_DAY: Final = ", %Y, %H:%M"

# The end of a window that falls on the day it began, which says that day once.
_THE_TIME_OF_DAY: Final = "%H:%M"

_THE_AUTHOR: Final = "Argus Postmortem agent"


class Head(BaseModel):
    """The rows above the first section, each a line of the document, and
    `labels` - what each row is called, in the order the rows are read.

    `ended_by_whom` is whoever `ended_by` names, on its own, for a destination
    that marks the row with them; `None` where nobody is recorded.
    """

    model_config = ConfigDict(frozen=True)

    labels: tuple[str, ...] = ("Incident", "Date", "Status", "Written by", "Ended by")
    incident: Line
    date: Line
    status: Line
    written_by: Line
    ended_by: Line
    ended_by_whom: str | None


def a_title(postmortem: PostmortemDocument | None, alert: Alert) -> Line:
    """The document's title: the symptom in the model's words, and the change
    it began with in the record's.

    A suspected trigger stays out: the title is the one line read by everybody
    who reads nothing else, and there a change nothing tested would say the
    change did it. A document naming no symptom - one written before the model
    was asked for one, or none written at all - is titled by its alert.
    """
    if postmortem is None or not postmortem.symptom:
        return Line(runs=(Run(text=f"{alert.alert_name} on {alert.service}"),))

    trigger = postmortem.trigger
    if trigger is None or trigger.suspected or not trigger.to_state:
        return Line(runs=(Run(text=postmortem.symptom),))

    # A deployment's subject is the service and its state a revision, so it is
    # said as the service running that revision rather than as a flag's "was".
    if trigger.kind is ChangeKind.DEPLOY:
        return Line(runs=(Run(text=postmortem.symptom),
                          Run(text=" while "),
                          Run(text=alert.service, role=Role.CODE),
                          Run(text=" ran "),
                          Run(text=as_revision(trigger.to_state), role=Role.CODE)))

    return Line(runs=(Run(text=postmortem.symptom),
                      Run(text=" while "),
                      Run(text=trigger.subject, role=Role.CODE),
                      Run(text=" was "),
                      Run(text=trigger.to_state)))


def a_head(postmortem: Postmortem,
           alert: Alert,
           resolution: ReportedResolution | None,
           escalation: Escalation | None = None) -> Head:
    """The rows above the first section of a written postmortem.

    `resolution` is a person's and `escalation` Argus's handing it to one, each
    read off the record when the document is shown, since a resolution can
    arrive after the document was written.
    """
    ended_by, ended_by_whom = _who_ended_it(postmortem, resolution, escalation)

    return Head(incident=Line(runs=(Run(text=alert.alert_name, role=Role.CODE),
                                    Run(text=" on "),
                                    Run(text=alert.service, role=Role.CODE))),
                date=_the_incident_s_window(postmortem),
                status=_how_finished(postmortem),
                written_by=_who_wrote_it(postmortem),
                ended_by=ended_by,
                ended_by_whom=ended_by_whom)


def the_day_it_is_dated_by(postmortem: Postmortem) -> date | None:
    """The day the head names for the incident: its onset's, where the
    timeline places one, and its alert's where it does not - as the write-up
    dates it. `None` where there is neither.

    Public because every moment below the head of that day is said by its time
    alone (`rendering`), which leans on the head having said the day."""
    began = _when_it_began(postmortem)
    if began is not None:
        return began.astimezone(UTC).date()

    detection = postmortem.detection
    return detection.alerted_at.astimezone(UTC).date() if detection is not None else None


def _when_it_began(postmortem: Postmortem) -> datetime | None:
    """Where the metrics stopped, or else where the impact began."""
    return (_the_marker(postmortem, TimelineMarker.METRICS_STOP)
            or _the_marker(postmortem, TimelineMarker.IMPACT_BEGINS))


def _the_incident_s_window(postmortem: Postmortem) -> Line:
    """From onset to back to normal, the day said once where both fall on it -
    or, where the metrics stopped at the onset, from there with them missing:
    a service nobody measured from then on may never have left normal.

    With no onset, the alert's moment after it: every moment of that day is
    said below by its time alone, so the head is where the day is said."""
    stopped = _the_marker(postmortem, TimelineMarker.METRICS_STOP)
    began = _when_it_began(postmortem)
    if began is None:
        detection = postmortem.detection
        if detection is None:
            return Line(runs=(Run(text="onset unknown"),))

        return Line(runs=(Run(text="onset unknown, alerted "),
                          Run.a_moment(detection.alerted_at)))

    ended = _the_marker(postmortem, TimelineMarker.IMPACT_ENDS)
    if ended is not None:
        return Line(runs=(Run(text=f"{on_the_day(began, _AFTER_THE_DAY)} to "
                                   f"{_the_end_said(began, ended)} UTC",
                              role=Role.MOMENT, at=began, until=ended),))

    since = Run(text=f"{on_the_day(began, _AFTER_THE_DAY)} UTC", role=Role.MOMENT, at=began)
    if stopped is not None:
        return Line(runs=(since, Run(text=", metrics missing from then")))

    impact = postmortem.impact
    if impact is None or impact.extent is not ImpactExtent.AT_LEAST:
        return Line(runs=(since, Run(text=", not seen back to normal")))

    # A lower bound is measured to the last minute read, so that is the minute
    # the service was still not back by - a finding, not a recovery missed.
    still_not = began + impact.duration
    return Line(runs=(since,
                      Run(text=", not back to normal by "),
                      Run(text=f"{_the_end_said(began, still_not)} UTC",
                          role=Role.MOMENT, at=still_not)))


def _the_end_said(began: datetime, ended: datetime) -> str:
    """The end of a window: its time alone on the day it began."""
    if ended.date() == began.date():
        return on_the_clock(ended, _THE_TIME_OF_DAY)

    return on_the_day(ended, _AFTER_THE_DAY)


def _how_finished(postmortem: Postmortem) -> Line:
    """Final once a person has reviewed it, and a draft until then - Google's
    convention, and the only honest word for a document nobody who could
    disagree with it has read - with how many of its items are done."""
    items = postmortem.action_items
    if items:
        done = sum(1 for item in items if item.status is ActionItemStatus.DONE)
        counted = f"{done} of {len(items)} action items are done."
    else:
        counted = "No action items."

    return Line(runs=(Run(text=f"{'Final.' if _reviewed(postmortem) else 'Draft.'} {counted}"),))


def _who_wrote_it(postmortem: Postmortem) -> Line:
    """The agent that wrote it, when, and whether a person has reviewed it."""
    return Line(runs=(Run(text=f"{_THE_AUTHOR}, "),
                      Run.a_moment(postmortem.created_at),
                      Run(text=". Reviewed." if _reviewed(postmortem) else ". Not reviewed yet.")))


def _who_ended_it(postmortem: Postmortem,
                  resolution: ReportedResolution | None,
                  escalation: Escalation | None) -> tuple[Line, str | None]:
    """A person's resolution where there is one; else whichever came later of
    Argus's escalation and the last step taken - a walk that acted and then
    gave up ended by giving up, and one escalated and then walked again ended
    by what it did then; else that nothing is recorded - with whoever that
    names. A refusal to act is no step taken: nothing was done in it, so it
    ended nothing, and the step that did is the last action before it."""
    if resolution is not None:
        runs = [Run(text=resolution.by),
                Run(text=f" from {resolution.channel}, "),
                Run.a_moment(resolution.at)]
        if resolution.note:
            runs += [Run(text=" - "), Run(text=resolution.note, role=Role.QUOTE)]

        return Line(runs=tuple(runs)), resolution.by

    last = next((step for step in reversed(postmortem.resolution) if step.refused is None),
                None)
    if escalation is not None and (last is None or escalation.at > last.at):
        return _the_escalation(escalation, postmortem.pull_request), _ARGUS

    if last is not None:
        action = last.action[:1].lower() + last.action[1:]

        return Line(runs=(Run(text=last.by),
                          Run(text=f": {action} - {last.outcome}"))), last.by

    return Line(runs=(Run(text="Not recorded."),)), None


def _the_escalation(escalation: Escalation, fix: OpenedPullRequest | None) -> Line:
    """Argus handing the incident to a person, when, and what it left them: the
    fix it proposed, where there is one, else the reason it gave."""
    runs = [Run(text=_ARGUS), Run(text=": escalated to a person, "), Run.a_moment(escalation.at)]
    if fix is not None:
        runs += [Run(text=" - "),
                 Run.a_pull_request(fix.number).linked_to(fix.url),
                 Run(text=f", {OPENED_AS_A_DRAFT}")]
    elif escalation.detail:
        runs += [Run(text=f" - {escalation.detail}")]

    return Line(runs=tuple(runs))


# Who ends an incident by escalating it.
_ARGUS: Final = "Argus"


def _reviewed(postmortem: Postmortem) -> bool:
    """Whether every review check has been met or failed, leaving none for a
    person - and there is a review to have met."""
    return bool(postmortem.review) and all(check.met is not None for check in postmortem.review)


def _the_marker(postmortem: Postmortem, marker: TimelineMarker) -> datetime | None:
    """When the timeline places a marker, where it places one."""
    return next((entry.at for entry in postmortem.timeline if entry.marker is marker), None)
