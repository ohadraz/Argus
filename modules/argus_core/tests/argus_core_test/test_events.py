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

import pytest
from argus_core.events import (
    ActionRefused,
    AgentInvoked,
    CandidateSelected,
    ChangeUndone,
    FixAttempted,
    IncidentEvent,
    LogsRetrieved,
    MitigationResumed,
    Publisher,
    RetrievalRequested,
    VerdictReached,
    parse_event,
    publish,
)
from argus_core.ids import new_id
from argus_core.models.action import Verdict
from argus_core.models.actor import Actor
from argus_core.models.fix import FixOutcome
from argus_core.models.pull_request import OpenedPullRequest
from argus_core.models.reading import RetrievalChannel
from argus_core.models.refusal import Refusal
from argus_core.models.undone import Undone
from argus_testkit import Assertion, Scenario, all_of, attempting
from pydantic import ValidationError

SOME_WINDOW_START = "2026-08-30T10:02:00Z"
SOME_WINDOW_END = "2026-08-30T10:12:00Z"


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
                refusal=Refusal.NOT_REVERSIBLE
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
                flag="some-flag",
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


def _its_verdict_is(expected: Verdict) -> Assertion[object]:
    def assertion(read_back: object) -> bool:
        outcome = _a_verdict_in(read_back).outcome
        if outcome is not expected:
            raise AssertionError(f"Expected [{expected!r}], got [{outcome!r}].")

        return True

    return assertion


def _it_was_refused() -> Assertion[Exception | None]:
    """An unknown verdict does not become an event.

    Refused where it is built rather than where it is read: an event that
    reached the log carrying a word nothing recognises is one every reader
    afterwards has to decide what to do about.
    """
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ValidationError):
            raise AssertionError(f"Expected the verdict refused, got [{raised}].")

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
