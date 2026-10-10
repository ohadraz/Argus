"""What Argus says about its own work, and the one rule that says on it.

An event is an account of something that happened - it names the incident, the
moment, and enough of the values involved that somebody reading it months later
needs nothing but the event. The rule is that publishing one can never change
what Argus decides, which here means it cannot fail a caller either.

Where an event carries a word from a vocabulary this system already names, it
carries the value rather than the spelling: a reader that has to know which of
four words means "it worked" is a reader that will one day match none of them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from argus_core.events import (
    ActionRefused,
    AgentInvoked,
    CandidateSelected,
    ChangeUndone,
    FixAttempted,
    IncidentEvent,
    LogsRetrieved,
    MessageUnderstood,
    MitigationResumed,
    OfferExpired,
    PersonWrote,
    PlacementRecorded,
    PlatformUnavailable,
    Publisher,
    ResolutionOffered,
    RetrievalRequested,
    SimilarIncidentsRecalled,
    StatusChanged,
    VerdictReached,
    WithdrawalOffered,
    parse_event,
    publish,
)
from argus_core.ids import new_id
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    PIN_AUTOSCALER,
    PIN_TO_ACCELERATOR,
    RESTART_SERVICE,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    IncidentStatus,
    Meaning,
    PodPlacement,
    RecordedPlacement,
    Reference,
    Report,
    ReportChannel,
    the_actions_through,
)
from argus_core.models.action import Verdict
from argus_core.models.actor import Actor
from argus_core.models.fix import FixOutcome
from argus_core.models.pull_request import OpenedPullRequest
from argus_core.models.reading import RetrievalChannel
from argus_core.models.refusal import Refusal
from argus_core.models.undone import Undone
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_testkit import Assertion, Scenario, all_of, attempting, one_record_was_logged
from pydantic import ValidationError

SOME_WINDOW_START = "2026-08-30T10:02:00Z"
SOME_WINDOW_END = "2026-08-30T10:12:00Z"
# A spelling no `ActionType` has. Named rather than written inline so the case
# reads as being about the vocabulary rather than about one typo.
SOME_KIND_NOBODY_DECLARED = "drain-node"


@pytest.mark.unit
def test_an_event_names_the_incident_it_belongs_to() -> None:
    # An event that cannot be attributed to an incident is a line in a log
    # file, which is what the system already had and could not read.
    some_incident_id = new_id()

    Scenario() \
        .given(some_incident_id) \
        .when(lambda: AgentInvoked(incident_id=some_incident_id,
                                   agent=Actor.INVESTIGATOR)) \
        .then(_it_belongs_to(some_incident_id))


@pytest.mark.unit
def test_an_event_knows_when_it_happened_without_being_told() -> None:
    # The moment is the event's own, taken where it is built - a caller that
    # had to supply it could supply the wrong one, and a narration ordered by
    # when rows were written is a narration of the database's day.
    Scenario() \
        .given(dont_care_incident := new_id()) \
        .when(lambda: AgentInvoked(incident_id=dont_care_incident,
                                   agent=Actor.INVESTIGATOR)) \
        .then(_it_is_stamped())


@pytest.mark.unit
def test_a_retrieval_names_its_channel_and_both_bounds_of_its_window() -> None:
    # "Argus looked at the logs" is not readable; "Argus looked at the logs
    # between 10:02 and 10:12" is. A window with one bound is a window nobody
    # can check the answer against.
    Scenario() \
        .given(dont_care_incident := new_id()) \
        .when(lambda: RetrievalRequested(
            incident_id=dont_care_incident,
            channel=RetrievalChannel.LOGS,
            window_start=SOME_WINDOW_START,
            window_end=SOME_WINDOW_END
        )) \
        .then(all_of(_it_asked_about(RetrievalChannel.LOGS),
                     _it_asked_between(SOME_WINDOW_START, SOME_WINDOW_END)))


@pytest.mark.unit
def test_a_retrieval_that_returned_carries_what_came_back() -> None:
    # The whole point of storing the payload: the page shows what Argus read,
    # not what the log store happens to hold when somebody opens the page.
    the_lines_it_read = [
        "2026-08-30T10:03:00Z ERROR io-shop: division by zero",
        "2026-08-30T10:03:00Z INFO io-shop: monthly-spend-feature=on"
    ]

    Scenario() \
        .given(the_lines_it_read) \
        .when(lambda: LogsRetrieved(
            incident_id=new_id(),
            window_start=SOME_WINDOW_START,
            window_end=SOME_WINDOW_END,
            lines=the_lines_it_read
        )) \
        .then(_it_carries(the_lines_it_read))


@pytest.mark.unit
def test_an_event_read_back_is_the_event_that_was_published() -> None:
    # It is written to a table and read out again, and what comes back has to
    # be the same kind of thing it went in as - otherwise every reader is left
    # matching on strings to work out what it is holding.
    Scenario() \
        .given(
            published := LogsRetrieved(
                incident_id=new_id(),
                window_start=SOME_WINDOW_START,
                window_end=SOME_WINDOW_END,
                lines=["some log line"]
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(_it_is(published))


@pytest.mark.unit
def test_an_unavailable_platform_carries_what_it_took_away() -> None:
    # Self-describing, which is what every event here is for: an incident read
    # months later is read without the code that published it, so a platform's
    # name alone would leave the reader to work out which of Argus's actions
    # went with it - from a mapping that may have changed since.
    #
    # Carried rather than derived, even though the mapping is right there. The
    # two are the same answer today and the event is the one that has to stay
    # true: a sixth mitigation added next year changes what the platform carries
    # *now*, and must not change what an incident from last year says it carried
    # then.
    Scenario() \
        .given(
            published := PlatformUnavailable(
                incident_id=new_id(),
                platform=DEPLOYMENT_PLATFORM,
                actions_unavailable=the_actions_through(DEPLOYMENT_PLATFORM)
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(all_of(
            _it_is(published),
            _it_took_away([
                RESTART_SERVICE, ROLL_BACK_DEPLOYMENT, SCALE_OUT, PIN_AUTOSCALER,
                PIN_TO_ACCELERATOR
            ])
        ))


@pytest.mark.unit
def test_an_unavailable_platform_refuses_an_action_kind_nobody_declared() -> None:
    # The vocabulary already has a name in this codebase, so the event carries
    # the value rather than the spelling - and a kind nobody declared is refused
    # where it is read rather than reaching a renderer that cannot match it.
    #
    # Read back rather than built, because a row is where such a value comes
    # from: nothing in Python can hand this field an undeclared kind without the
    # type checker objecting first, and the case worth holding is the one where a
    # spelling that was legal when it was written no longer is.
    Scenario() \
        .given(SOME_KIND_NOBODY_DECLARED) \
        .when(attempting(lambda: parse_event({
            "kind": "platform-unavailable",
            "id": new_id(),
            "incident_id": new_id(),
            "at": "2026-08-30T10:02:00Z",
            "platform": DEPLOYMENT_PLATFORM,
            "actions_unavailable": [SOME_KIND_NOBODY_DECLARED]
        }))) \
        .then(_it_was_refused())


@pytest.mark.unit
def test_a_verdict_is_one_of_the_answers_mitigation_gives() -> None:
    # The vocabulary already has a name in this codebase. Carried as the value,
    # an outcome nobody defined is refused where it is published rather than
    # reaching a page that compares spellings and quietly matches none of them.
    some_word_that_is_not_a_verdict = "probably"

    Scenario() \
        .given(some_word_that_is_not_a_verdict) \
        .when(attempting(lambda: VerdictReached.model_validate({
            "incident_id": new_id(),
            "hypothesis_id": None,
            "outcome": some_word_that_is_not_a_verdict
        }))) \
        .then(_it_was_refused())


@pytest.mark.unit
def test_a_verdict_read_back_is_the_answer_it_was_published_as() -> None:
    # Written as its own spelling and read back as the value, so what a reader
    # holds can be compared rather than recognised.
    Scenario() \
        .given(
            published := VerdictReached(incident_id=new_id(),
                                        hypothesis_id=None,
                                        outcome=Verdict.CONFIRMED)
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(all_of(_it_is(published), _its_verdict_is(Verdict.CONFIRMED)))


@pytest.mark.unit
def test_a_refusal_is_one_of_the_reasons_the_gate_gives() -> None:
    # Two rejections reach the same status for different reasons - nothing to
    # do at all, or something to do that could not be undone - and a reader has
    # to know which. Carried as the value, a third reason nobody defined is
    # refused here rather than reaching a page that matches no case.
    some_word_that_is_not_a_refusal = "vibes"

    Scenario() \
        .given(some_word_that_is_not_a_refusal) \
        .when(attempting(lambda: ActionRefused.model_validate({
            "incident_id": new_id(),
            "hypothesis_id": new_id(),
            "refusal": some_word_that_is_not_a_refusal
        }))) \
        .then(_it_was_refused())


@pytest.mark.unit
def test_a_recall_that_names_no_incident_is_refused() -> None:
    # The event exists to say memory found something, so a recall naming nothing
    # is not a quieter version of it - it is the case the publisher stays silent
    # on. Refused in the type rather than left to that one caller's guard,
    # because the narrator reads the nearest incident off the front of the list:
    # a row read back through `parse_event` with an empty one raises on the
    # incident page and in the postmortem, a long way from whoever wrote it.
    no_incidents_at_all: list[str] = []

    Scenario() \
        .given(no_incidents_at_all) \
        .when(attempting(lambda: SimilarIncidentsRecalled.model_validate({
            "incident_id": new_id(),
            "incident_ids": no_incidents_at_all
        }))) \
        .then(_it_was_refused())


@pytest.mark.unit
def test_a_refusal_read_back_names_the_candidate_it_refused() -> None:
    # The autonomy boundary holding is the single most important line Argus
    # publishes, and a refusal loose of the candidate it refused cannot be read
    # against the explanation it belonged to.
    some_candidate = new_id()

    Scenario() \
        .given(
            published := ActionRefused(
                incident_id=new_id(),
                hypothesis_id=some_candidate,
                refusal=Refusal.NOT_A_GENERIC_MITIGATION
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(_it_is(published))


@pytest.mark.unit
def test_a_change_put_back_reads_back_as_what_became_of_it() -> None:
    # Three answers, not two: restored, left as somebody else found it, or a
    # flag nobody could read. A withdrawal is only honest while the account can
    # tell them apart, so the outcome travels as the value.
    Scenario() \
        .given(
            published := ChangeUndone(
                incident_id=new_id(),
                subject="some-flag",
                outcome=Undone.LEFT_AS_FOUND,
                detail="somebody else has changed it since"
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(_it_is(published))


@pytest.mark.unit
def test_a_resumed_attempt_reads_back_as_the_verdict_it_caught_up_with() -> None:
    # A walk restarted after the verdict was written, reading it off the row.
    # The account says so, because an incident whose story simply skips from a
    # taken action to a conclusion reads as one that lost a step.
    Scenario() \
        .given(
            published := MitigationResumed(
                incident_id=new_id(),
                hypothesis_id=new_id(),
                outcome=Verdict.REFUTED
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(all_of(_it_is(published), _its_verdict_is(Verdict.REFUTED)))


@pytest.mark.unit
def test_a_candidate_selected_reads_back_as_the_one_now_under_test() -> None:
    # Which explanation is being tested now is not derivable from the ranked
    # list: the walk skips candidates it cannot act on, so a reader following
    # along has no way to guess which one this attempt is about.
    Scenario() \
        .given(
            published := CandidateSelected(
                incident_id=new_id(),
                hypothesis_id=new_id(),
                summary="the checkout flag was toggled on",
                confidence=0.72
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(_it_is(published))


@pytest.mark.unit
def test_a_recorded_placement_reads_back_with_the_onset_it_was_recorded_against() -> None:
    # The placement means nothing without the minute it was read against: which
    # pods started at the onset is the whole of what it is published for, and a
    # reader months later has the event and not the walk.
    Scenario() \
        .given(
            published := PlacementRecorded(
                incident_id=new_id(),
                placement=RecordedPlacement(
                    onset=datetime(2026, 10, 8, 9, 30, tzinfo=UTC),
                    pods=(
                        PodPlacement(
                            pod="io-shop-7d9c4f8b6-x2k9p",
                            node="gpu-a100-0",
                            accelerator="NVIDIA-A100-SXM4-40GB",
                            started_at=datetime(2026, 10, 8, 9, 29, 30, tzinfo=UTC)
                        ),
                    )
                )
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(_it_is(published))


@pytest.mark.unit
def test_a_status_change_a_person_reported_reads_back_with_who_how_and_what_they_said() -> None:
    # A person's ending is the one status change Argus did not decide, so who
    # made it, where they said it and what they added travel with the change
    # itself - the account is where a reader looks, months later, without the
    # page that took the report.
    the_report = Report(
        by="some person",
        channel=ReportChannel.ARGUS_UI,
        note="rolled the flag back by hand"
    )

    Scenario() \
        .given(
            published := StatusChanged(
                incident_id=new_id(),
                to_status=IncidentStatus.RESOLVED,
                reported=the_report
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(all_of(_it_is(published), _it_was_reported_as(the_report)))


@pytest.mark.unit
@pytest.mark.parametrize("published", [
    PersonWrote(
        incident_id=new_id(),
        message=Reference(source="some-chat", kind="some-kind", value="some-message"),
        person_id="some-person-id",
        text="rolled the flag back by hand, we're fine"
    ),
    MessageUnderstood(
        incident_id=new_id(),
        message=Reference(source="some-chat", kind="some-kind", value="some-message"),
        meaning=Meaning.RESOLVE
    ),
    ResolutionOffered(
        incident_id=new_id(),
        message=Reference(source="some-chat", kind="some-kind", value="some-message"),
        person_id="some-person-id",
        person_name="some person",
        said="rolled the flag back by hand, we're fine"
    ),
    ResolutionOffered(
        incident_id=new_id(),
        message=Reference(source="some-chat", kind="some-kind", value="some-message"),
        person_id="some-person-id",
        person_name=None,
        said="rolled the flag back by hand, we're fine"
    ),
    WithdrawalOffered(
        incident_id=new_id(),
        message=Reference(source="some-chat", kind="some-kind", value="some-message"),
        person_id="some-person-id",
        person_name="some person",
        said="stop, I've got this one"
    ),
    WithdrawalOffered(
        incident_id=new_id(),
        message=Reference(source="some-chat", kind="some-kind", value="some-message"),
        person_id="some-person-id",
        person_name=None,
        said="stop, I've got this one"
    ),
    OfferExpired(
        incident_id=new_id(),
        message=Reference(source="some-chat", kind="some-kind", value="some-message")
    )
], ids=["person-wrote", "message-understood", "resolution-offered", "offered-to-nobody-named",
        "withdrawal-offered", "withdrawal-offered-to-nobody-named", "offer-expired"])


def test_what_a_person_wrote_and_what_argus_made_of_it_read_back_as_published(
        published: IncidentEvent) -> None:
    # A person's words are the one input to an incident Argus did not produce,
    # so they travel whole - who, where, and exactly what - as does what Argus
    # took them to mean and what it offered to do about it. The offer is read
    # back by whoever presses its button, and a field lost on the way is a
    # press checked against nobody.
    Scenario() \
        .given(published) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(_it_is(published))


@pytest.mark.unit
def test_a_status_change_stored_before_anybody_reported_one_reads_back_naming_nobody() -> None:
    # Every row written before a person could be named has no such field. It
    # must still read, and read as Argus's own move rather than as a report
    # from somebody whose name was lost.
    stored_without_a_reporter = StatusChanged(
        incident_id=new_id(),
        to_status=IncidentStatus.ESCALATED
    ).model_dump(mode="json", exclude={"reported"})

    Scenario() \
        .given(stored_without_a_reporter) \
        .when(lambda: parse_event(stored_without_a_reporter)) \
        .then(_nobody_reported_it())


@pytest.mark.unit
def test_an_event_reaches_the_publisher_it_was_given() -> None:
    everything_published: list[IncidentEvent] = []
    an_event = AgentInvoked(incident_id=new_id(), agent=Actor.MITIGATION)

    Scenario() \
        .given(everything_published) \
        .when(lambda: publish(an_event, publisher=everything_published.append)) \
        .then(_what_was_published(everything_published, [an_event]))


@pytest.mark.unit
def test_a_publisher_that_fails_does_not_fail_the_work_it_was_describing() -> None:
    # The account of the work is never part of the work. An incident that
    # would have resolved must resolve even when nobody could write down that
    # it was resolving.
    Scenario() \
        .given(a_failing_publisher := _a_publisher_having_a_bad_day()) \
        .when(attempting(lambda: publish(
            AgentInvoked(incident_id=new_id(), agent=Actor.INVESTIGATOR),
            publisher=a_failing_publisher
        ))) \
        .then(_nothing_was_raised())


@pytest.mark.unit
def test_publishing_reaches_nobody_by_default() -> None:
    # A component publishes whether or not anything is listening, and nothing
    # about its behaviour changes either way. The default is where that is
    # true by construction.
    Scenario() \
        .given(dont_care_incident := new_id()) \
        .when(attempting(lambda: publish(
            AgentInvoked(incident_id=dont_care_incident, agent=Actor.INVESTIGATOR)
        ))) \
        .then(_nothing_was_raised())


@pytest.mark.unit
def test_the_fix_argus_looked_for_is_said_however_it_turned_out() -> None:
    # Code-Fix is the one step whose whole outcome is invisible in the status:
    # a mitigated incident is mitigated whether a fix was proposed, was not
    # warranted, or could not be proposed at all. Nothing else in the log
    # distinguishes those, so without this event "Argus looked at the code and
    # found nothing" and "Argus could not reach the repository" reach a reader
    # looking identical - and one of them is somebody's to go and fix.
    #
    # The outcome travels as the value rather than as a sentence, for the
    # reason a verdict does: three answers this system already names, and a
    # reader matching on prose is a reader who will one day match none of them.
    some_incident_id = new_id()
    the_proposal = OpenedPullRequest(number=7, url="https://example.invalid/pull/7",
                                     branch="argus/fix-abc")

    Scenario() \
        .given(some_incident_id) \
        .when(
            lambda: FixAttempted(incident_id=some_incident_id,
                                 outcome=FixOutcome.PROPOSED,
                                 pull_request=the_proposal,
                                 detail="dont care what it said")
        ) \
        .then(
            all_of(
                _it_belongs_to(some_incident_id),
                _it_reports(FixOutcome.PROPOSED),
                _it_carries_the_proposal(the_proposal)
            )
        )


@pytest.mark.unit
def test_a_fix_that_was_not_possible_is_not_a_fix_that_was_not_warranted() -> None:
    # Two outcomes with no pull request between them, and they mean opposite
    # things: one is a verdict on the code, the other is a repository somebody
    # can go and repair before asking again. A reader told only that there is
    # no proposal cannot tell which happened.
    Scenario() \
        .given(some_incident_id := new_id()) \
        .when(
            lambda: FixAttempted(incident_id=some_incident_id,
                                 outcome=FixOutcome.NOT_POSSIBLE,
                                 pull_request=None,
                                 detail="the repository refused the branch")
        ) \
        .then(
            all_of(
                _it_reports(FixOutcome.NOT_POSSIBLE),
                _it_carries_the_proposal(None)
            )
        )


@pytest.mark.unit
def test_a_fix_attempt_is_read_back_as_what_it_was_published_as() -> None:
    # The log is read by a page, a relay and a postmortem, none of which
    # published it. A row that came back as a dictionary would have every one
    # of them matching on strings to work out what happened.
    an_attempt = FixAttempted(incident_id=new_id(),
                              outcome=FixOutcome.NOT_WARRANTED,
                              pull_request=None,
                              detail="no code-level fix was warranted")

    Scenario() \
        .given(an_attempt) \
        .when(lambda: parse_event(an_attempt.model_dump(mode="json"))) \
        .then(_it_reports(FixOutcome.NOT_WARRANTED))


@pytest.mark.unit
def test_a_publisher_that_fails_is_logged_as_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    # Swallowed so the work goes on, and said so the gap in the account is
    # found from the log rather than by somebody noticing a page with a line
    # missing. It names the incident itself: an alert being acknowledged is
    # published before any work on the incident has put it in the baggage.
    some_incident = new_id()

    Scenario() \
        .when(attempting(lambda: publish(
            AgentInvoked(incident_id=some_incident, agent=Actor.INVESTIGATOR),
            publisher=_a_publisher_having_a_bad_day()
        ))) \
        .then(
            one_record_was_logged(caplog, "argus_core.events", logging.WARNING,
                                  "event could not be published",
                                  values={"event": "AgentInvoked",
                                          ARGUS_INCIDENT_ID: some_incident},
                                  failure=RuntimeError)
        )


def _a_publisher_having_a_bad_day() -> Publisher:
    """A subscriber that throws on everything it is handed."""
    def raise_on_everything(dont_care_event: IncidentEvent) -> None:
        raise RuntimeError("the subscriber is having a bad day")

    return raise_on_everything


def _a_verdict_in(read_back: object) -> VerdictReached | MitigationResumed:
    """What came back, as the type it was published as - or the failure to be.

    Read here rather than asserted in three places: every claim below about a
    verdict starts by holding one, and a reader that got something else has
    already learned the only thing worth reporting.

    Two kinds carry one. A verdict is reached once and a resumed walk reads the
    same answer back off the row, so an assertion about the answer is the same
    assertion either way.
    """
    if not isinstance(read_back, VerdictReached | MitigationResumed):
        raise AssertionError(f"Expected a verdict, got [{type(read_back).__name__}].")

    return read_back


def _it_belongs_to(incident_id: str) -> Assertion[IncidentEvent]:
    def assertion(event: IncidentEvent) -> bool:
        if event.incident_id != incident_id:
            raise AssertionError(
                f"Expected it about [{incident_id}], it is about [{event.incident_id}]."
            )

        return True

    return assertion


def _it_is_stamped() -> Assertion[IncidentEvent]:
    def assertion(event: IncidentEvent) -> bool:
        if event.at is None:
            raise AssertionError("Expected the event to know when it happened, it has no moment.")

        return True

    return assertion


def _it_asked_about(channel: RetrievalChannel) -> Assertion[RetrievalRequested]:
    def assertion(requested: RetrievalRequested) -> bool:
        if requested.channel is not channel:
            raise AssertionError(
                f"Expected it to ask about [{channel}], it asked about [{requested.channel}]."
            )

        return True

    return assertion


def _it_asked_between(start: str, end: str) -> Assertion[RetrievalRequested]:
    def assertion(requested: RetrievalRequested) -> bool:
        asked = (requested.window_start, requested.window_end)
        if asked != (start, end):
            raise AssertionError(f"Expected the window {(start, end)}, got {asked}.")

        return True

    return assertion


def _it_carries(lines: list[str]) -> Assertion[LogsRetrieved]:
    def assertion(retrieved: LogsRetrieved) -> bool:
        if retrieved.lines != lines:
            raise AssertionError(f"Expected it to carry {lines}, it carries {retrieved.lines}.")

        return True

    return assertion


def _it_is(published: IncidentEvent) -> Assertion[object]:
    def assertion(read_back: object) -> bool:
        if read_back != published:
            raise AssertionError(f"Expected [{published}], got [{read_back}].")

        return True

    return assertion


def _it_was_reported_as(expected: Report) -> Assertion[object]:
    def assertion(read_back: object) -> bool:
        reported = getattr(read_back, "reported", None)

        if reported != expected:
            raise AssertionError(
                f"Expected the status change to carry the report [{expected}], "
                f"it carries [{reported}]."
            )

        return True

    return assertion


def _nobody_reported_it() -> Assertion[object]:
    def assertion(read_back: object) -> bool:
        if not isinstance(read_back, StatusChanged) or read_back.reported is not None:
            raise AssertionError(
                f"Expected a status change naming nobody as having reported it, "
                f"got [{read_back}]."
            )

        return True

    return assertion


def _its_verdict_is(expected: Verdict) -> Assertion[object]:
    def assertion(read_back: object) -> bool:
        outcome = _a_verdict_in(read_back).outcome
        if outcome is not expected:
            raise AssertionError(f"Expected [{expected!r}], got [{outcome!r}].")

        return True

    return assertion


def _it_was_refused() -> Assertion[Exception | None]:
    """A value the event cannot carry does not become an event.

    Said of the event rather than of any one field, because four cases ask it: a
    verdict nothing defines, a refusal nothing defines, a recall naming no
    incident, and an action kind nothing declares. A message naming one of those
    and a reader chasing the failure would start at the wrong field.

    Refused where it is built rather than where it is read: an event that reached
    the log carrying something nothing recognises is one every reader afterwards
    has to decide what to do about.
    """
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ValidationError):
            raise AssertionError(
                f"Expected the event refused where it was built, got [{raised}]."
            )

        return True

    return assertion


def _what_was_published(published: list[IncidentEvent],
                        expected: list[IncidentEvent]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if published != expected:
            raise AssertionError(f"Expected {expected} published, got {published}.")

        return True

    return assertion


def _nothing_was_raised() -> Assertion[Exception | None]:
    """Publishing answers rather than throwing, whatever the subscriber does."""
    def assertion(raised: Exception | None) -> bool:
        if raised is not None:
            raise AssertionError(
                f"Expected the work to survive, got [{type(raised).__name__}]: {raised}."
            )

        return True

    return assertion


def _it_reports(outcome: FixOutcome) -> Assertion[IncidentEvent]:
    """Which of the three things happened, as the value rather than the word."""
    def assertion(event: IncidentEvent) -> bool:
        reported = getattr(event, "outcome", None)
        if reported != outcome:
            raise AssertionError(
                f"Expected the attempt to report [{outcome}], got [{reported}]."
            )

        return True

    return assertion


def _it_carries_the_proposal(
    proposal: OpenedPullRequest | None
) -> Assertion[IncidentEvent]:
    """The address a person goes to, or nothing where there is nowhere to go."""
    def assertion(event: IncidentEvent) -> bool:
        carried = getattr(event, "pull_request", None)
        if carried != proposal:
            raise AssertionError(
                f"Expected the attempt to carry [{proposal}], got [{carried}]."
            )

        return True

    return assertion


def _it_took_away(expected: list[str]) -> Assertion[IncidentEvent]:
    def assertion(event: IncidentEvent) -> bool:
        took_away = getattr(event, "actions_unavailable", None)

        if took_away != expected:
            raise AssertionError(
                f"Expected the event to say {expected} went with the platform, "
                f"it says {took_away}."
            )

        return True

    return assertion
