"""One incident's whole account of itself, arranged for one screen.

The narration is what happened; the metrics, the logs and the changes are what
it read - gathered into a table each rather than repeated under every retrieval
that returned them. A widening investigation reads overlapping windows, so the
same minute comes back several times, and three tables that each say a thing
once are readable where a dozen inline fragments saying it again are not.

Deduplicated by the identity the evidence already has: a bucket is its minute
and a log line is its text. Where a minute comes back twice the later read
wins, because it is the later read that Argus acted on.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from hashlib import sha256

from argus_core.events import ChangesRetrieved, IncidentEvent, StatusChanged
from argus_core.ids import UuidStr
from argus_core.models.alert import Alert
from argus_core.models.change_event import ChangeEvent
from argus_core.models.flag_change import FlagChange
from argus_core.models.incident import Incident
from argus_core.models.incident_status import IncidentStatus
from argus_narration import (
    BucketRow,
    FlagToggleRow,
    LogLine,
    NarrationLine,
    a_flag_history,
    build_narration,
    pointed_at,
    the_minutes_logged,
)
from pydantic import BaseModel

from argus_web.views.decorating import DecoratedLine, decorated


class Story(BaseModel):
    """One incident's account of itself, arranged for one screen.

    The narration is what happened; the metrics and the logs are what it read,
    gathered into a table each rather than repeated under every retrieval that
    returned them. A widening investigation reads overlapping windows, so the
    same minute comes back several times - and three tables that each say a
    thing once are readable where a dozen inline fragments saying it again are
    not.
    """

    # Dressed for this page rather than as the renderer handed them over: the
    # class on a marked word and the link beside a line exist because this is a
    # web page, and are worked out here for that reason.
    narration: list[DecoratedLine]
    metrics: list[BucketRow]
    logs: list[LogLine]
    changes: list[ChangeEvent]
    flag_changes: list[FlagToggleRow]
    # Whether the change channel was read at all. An empty answer from it is a
    # finding - it is what rules a deploy out - and a table that simply did not
    # appear would leave that finding unsaid.
    read_changes: bool


class LiveIncident(BaseModel):
    """The incident somebody watching Argus is looking at.

    Header and story together, because they are one screen and answering "what
    is happening" in two calls invites the two halves to disagree about which
    incident they are describing.
    """

    id: UuidStr
    alert: Alert
    status: IncidentStatus
    created_at: datetime
    # When it stopped, or `None` while it runs. The page counts the elapsed
    # time itself from these two, so that the seconds advance smoothly between
    # polls rather than in the two-second steps the server can supply.
    finished_at: datetime | None
    elapsed_seconds: int
    story: Story
    # What this incident's page currently says, as one value. The page polls
    # every two seconds and almost every poll returns exactly what is already
    # on screen; re-rendering it anyway destroys everything the reader is doing
    # inside it - a scrolled table jumps to its first row, a minute they
    # followed a link to scrolls away, and the status badge's pulse restarts
    # mid-breath. Comparing this says whether there is anything to swap.
    version: str


def build_story(events: Sequence[IncidentEvent]) -> Story:
    """One incident's whole account: what happened, and what it read.

    The evidence is gathered here rather than left under the retrievals that
    returned it, because an investigation that widens reads the same minutes
    several times - and a reader scanning for the minute the errors started
    should find one table with that minute in it, not the fourth of six
    fragments that each contain a copy.

    Deduplicated by the identity the evidence already has: a bucket is its
    minute and a log line is its text. Where a minute comes back twice the
    later read wins, because it is the later read that Argus acted on.
    """
    narration = build_narration(events)

    minutes: dict[str, BucketRow] = {}
    lines: dict[str, LogLine] = {}
    changed: dict[str, ChangeEvent] = {}
    toggled: dict[tuple[str, str], FlagChange] = {}

    for line in narration:
        minutes.update({bucket.bucket_id: bucket for bucket in line.buckets})
        lines.update({log.text: log for log in line.log_lines})
        changed.update({change.reference: change for change in line.changes})
        # Keyed by flag and moment together: one flag moving twice is two
        # changes, and it is exactly the flag that moved twice - tried, then
        # put back - whose second move a reader must not lose.
        toggled.update({(toggle.flag, toggle.occurred_at): toggle
                        for toggle in line.flag_changes})

    return Story(
        narration=[
            decorated(_pointed_at(line, list(minutes), the_minutes_logged(lines.values())))
            for line in narration
        ],
        metrics=sorted(minutes.values(), key=lambda bucket: bucket.bucket_id),
        logs=sorted(lines.values(), key=lambda log: log.stamp or ""),
        changes=sorted(changed.values(), key=lambda change: change.occurred_at),
        flag_changes=a_flag_history(
            sorted(toggled.values(), key=lambda toggle: toggle.occurred_at)
        ),
        read_changes=any(isinstance(event, ChangesRetrieved) for event in events)
    )


def _utc_now() -> datetime:
    """The clock `build_live_incident` reads when an incident is still running.

    Its own function so that it is an argument with a default rather than a
    call buried in the builder - which is the difference between a test that
    can hold the elapsed time still and one that cannot.
    """
    return datetime.now(UTC)


def build_live_incident(incident: Incident,
                        events: Sequence[IncidentEvent],
                        now: Callable[[], datetime] = _utc_now) -> LiveIncident:
    """Arranges one incident into the screen somebody watches it on.

    `now` is injected because the elapsed time is the one value here that does
    not come out of the rows, and a clock reached for internally is a clock no
    test can hold still.
    """
    finished_at = _when_it_finished(incident, events)
    story = build_story(events)

    return LiveIncident(
        id=incident.id,
        alert=Alert.model_validate(incident.alert_payload),
        status=incident.status,
        created_at=incident.created_at,
        finished_at=finished_at,
        elapsed_seconds=int(((finished_at or now()) - incident.created_at).total_seconds()),
        story=story,
        version=_a_version_of(incident, finished_at, story)
    )


def _pointed_at(line: NarrationLine,
                minutes: Sequence[str],
                logged: Sequence[str]) -> NarrationLine:
    """One line, with its findings pointed at the minutes the page holds.

    Done here rather than while the line is built, because a finding cited at
    10:14 can only link to 10:14 once it is known that 10:14 is on the page -
    and that is not known until every metrics retrieval has been read.
    """
    if not line.candidates:
        return line

    return line.model_copy(update={"candidates": [
        candidate.model_copy(update={"evidence": [
            pointed_at(cited, minutes, logged) for cited in candidate.evidence
        ]})
        for candidate in line.candidates
    ]})


def _a_version_of(incident: Incident,
                  finished_at: datetime | None,
                  story: Story) -> str:
    """A short value that changes exactly when the page's content does.

    Everything the page renders goes in except the elapsed time, which is a
    clock rather than a fact about the incident and is counted by the browser
    for that reason. Including it would make every poll a change, which is the
    same as having no version at all.

    A hash rather than a counter: there is no writer to keep a counter, and the
    question being asked - "is this the same page I am already showing?" - is
    answered by the content itself.
    """
    said = f"{incident.id}|{incident.status}|{finished_at}|{story.model_dump_json()}"

    return sha256(said.encode()).hexdigest()[:16]


def _when_it_finished(incident: Incident,
                      events: Sequence[IncidentEvent]) -> datetime | None:
    """The moment a finished incident stopped, or `None` while it is running.

    An elapsed time that kept climbing after the incident ended would report
    the age of the record rather than the length of the incident.

    Taken from the status change that ended it, falling back to the last thing
    recorded at all: an incident can reach a terminal status without that
    change appearing in its stream - it was resolved before the stream existed,
    or by a path that publishes nothing - and a header that answered "still
    going" for one of those would be wrong in the one way this field exists to
    prevent.
    """
    if not incident.status.is_terminal():
        return None

    ended = [
        event.at
        for event in events
        if isinstance(event, StatusChanged) and event.to_status.is_terminal()
    ]

    if ended:
        return ended[-1]

    return events[-1].at if events else incident.created_at
