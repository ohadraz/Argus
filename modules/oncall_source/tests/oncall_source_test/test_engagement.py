from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, all_of
from oncall_source import (
    Acknowledgement,
    OnCallUnavailable,
    ReportedIncident,
    engagement_with,
)

"""What human attention an incident took, as the on-call provider reports it.

What this suite injects is the incident the provider reports, in the vocabulary
the port is written in: one acknowledgement says when, who, and what that
person was called. Composing that out of the two resources a provider actually
publishes is the adapter's work, and is exercised where the adapter answers for
it - not here.

The minutes are person-minutes: each responder's own acknowledgement to the end
of the incident, summed. That is the whole reason this module exists - Argus
already knows how long its own incident lasted, and the one thing it cannot
know is when, or whether, a person picked it up. The incident's own start is
stated wherever the gap between it and an acknowledgement is the point, and
nothing computes from it.
"""

SOME_INCIDENT = "incident-1"
SOME_RESPONDER = "responder-1"
SOME_OTHER_RESPONDER = "responder-2"

# A title for a test that is about the minutes or the count. Every
# acknowledgement carries one, and this is the value for the ones that could
# have carried anything.
DONT_CARE_TITLE = "Software Engineer"

A_MINUTE = timedelta(minutes=1)


@pytest.mark.unit
def test_the_minutes_are_each_responders_own_span_from_when_they_acknowledged() -> None:
    # Two things at once, and neither survives the other's absence. The wait
    # before a responder acknowledged is time that responder did not spend, so
    # counting from the incident's start reports attention nobody paid; and two
    # people on an incident spent two people's time, so counting one span
    # reports half the attention it actually took. Two responders who
    # acknowledged at different times is the case that fails on either mistake.
    some_incident_began_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    some_incident_lasted = timedelta(hours=1)
    some_responder_took_it_after = timedelta(minutes=12)
    some_other_responder_took_it_after = timedelta(minutes=20)
    some_incident_ended_at = some_incident_began_at + some_incident_lasted
    some_acknowledged_at = {
        SOME_RESPONDER: some_incident_began_at + some_responder_took_it_after,
        SOME_OTHER_RESPONDER: some_incident_began_at + some_other_responder_took_it_after
    }

    Scenario() \
        .given(
            reported := _an_incident(
                began_at=some_incident_began_at,
                ended_at=some_incident_ended_at,
                acknowledged_at=some_acknowledged_at)
        ) \
        .when(
            lambda: engagement_with(SOME_INCIDENT,
                                    reported=_a_provider_reporting(reported))
        ) \
        .then(
            all_of(
                _the_minutes_were(
                    sum((some_incident_ended_at - at) // A_MINUTE
                        for at in some_acknowledged_at.values())),
                _the_responders_were(len(some_acknowledged_at))
            )
        )


@pytest.mark.unit
def test_a_responder_who_acknowledged_more_than_a_single_time_is_still_one_responder() -> None:
    # Acknowledging again is what a person does when they come back to an
    # incident, and it says nothing about how many people were on it. Counting
    # acknowledgements instead of people would report one engineer twice - and
    # would shorten their span to the later moment, understating the minutes
    # while overstating the headcount.
    some_began_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    some_incident_lasted = timedelta(hours=1)
    some_responder_took_it_after = timedelta(minutes=10)
    some_responder_came_back_after = timedelta(minutes=40)
    some_other_responder_took_it_after = timedelta(minutes=30)
    some_incident_ended_at = some_began_at + some_incident_lasted

    Scenario() \
        .given(
            reported := ReportedIncident(
                began_at=some_began_at,
                ended_at=some_incident_ended_at,
                acknowledgements=[
                    _acknowledged_at(
                        some_began_at + some_responder_took_it_after,
                        by=SOME_RESPONDER),
                    _acknowledged_at(
                        some_began_at + some_responder_came_back_after,
                        by=SOME_RESPONDER),
                    _acknowledged_at(
                        some_began_at + some_other_responder_took_it_after,
                        by=SOME_OTHER_RESPONDER)
                ]
            )
        ) \
        .when(
            lambda: engagement_with(SOME_INCIDENT,
                                    reported=_a_provider_reporting(reported))
        ) \
        .then(
            all_of(
                _the_responders_were(2),
                _the_minutes_were(
                    (some_incident_lasted - some_responder_took_it_after) // A_MINUTE
                    + (some_incident_lasted - some_other_responder_took_it_after) // A_MINUTE)
            )
        )


@pytest.mark.unit
def test_an_incident_nobody_acknowledged_is_answered_rather_than_left_unanswered() -> None:
    # An incident that resolved with nobody looking at it is a fact about the
    # response, and a true one: the alert fired, the service recovered, and no
    # human time was spent. Reported as an absent source instead, it would read
    # as a postmortem that failed to find out - and the one case Argus is best
    # placed to observe would be the one it says nothing about.
    some_began_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    some_length = timedelta(hours=1)

    Scenario() \
        .given(
            reported := ReportedIncident(
                began_at=some_began_at,
                ended_at=some_began_at + some_length,
                acknowledgements=[])
        ) \
        .when(
            lambda: engagement_with(SOME_INCIDENT,
                                    reported=_a_provider_reporting(reported))
        ) \
        .then(
            all_of(
                _the_minutes_were(0),
                _the_responders_were(0)
            )
        )


@pytest.mark.unit
def test_a_provider_that_cannot_be_reached_answers_that_it_could_not_say() -> None:
    # Not the vendor's error: the fetch that imports the SDK turns it into this
    # module's own, so nothing above the port has to know which library failed.
    # And not zero minutes either - a figure of nobody having responded is a
    # claim, and an unreadable provider has not earned it.
    Scenario() \
        .given(
            a_provider_that_is_down := _a_provider_that_cannot_be_read
        ) \
        .when(
            lambda: engagement_with(SOME_INCIDENT,
                                    reported=a_provider_that_is_down())
        ) \
        .then(
            _nobody_could_say()
        )


@pytest.mark.unit
def test_the_title_each_responder_held_is_reported_with_them() -> None:
    # A count says two people; a title says which two. The document that
    # follows reads better for it, and the change that comes to price these
    # minutes needs a title rather than a headcount - one senior engineer for
    # an hour and one intern for an hour are not the same hour.
    some_began_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    some_length = timedelta(hours=1)
    some_took_it_after = timedelta(minutes=10)
    some_title = "Senior Software Engineer"
    some_other_title = "Site Reliability Engineer"

    Scenario() \
        .given(
            reported := _an_incident(
                began_at=some_began_at,
                ended_at=some_began_at + some_length,
                acknowledged_at={
                    SOME_RESPONDER: some_began_at + some_took_it_after,
                    SOME_OTHER_RESPONDER: some_began_at + some_took_it_after
                },
                held={SOME_RESPONDER: some_title,
                      SOME_OTHER_RESPONDER: some_other_title})
        ) \
        .when(
            lambda: engagement_with(SOME_INCIDENT,
                                    reported=_a_provider_reporting(reported))
        ) \
        .then(
            _the_titles_were(some_title, some_other_title)
        )


@pytest.mark.unit
def test_a_responder_with_no_title_on_their_acknowledgement_is_still_a_responder() -> None:
    # A person the provider holds no title for is a person all the same: they
    # took the incident and spent the time, and the minutes and the count say
    # so. What is missing is the description - and whatever comes to price
    # these minutes will have nothing to match this responder against, which is
    # a fact worth arriving as a gap rather than as a title somebody invented.
    some_began_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    some_length = timedelta(hours=1)
    some_took_it_after = timedelta(minutes=10)
    some_title = "Senior Kukibuki"

    Scenario() \
        .given(
            reported := _an_incident(
                began_at=some_began_at,
                ended_at=some_began_at + some_length,
                acknowledged_at={
                    SOME_RESPONDER: some_began_at + some_took_it_after,
                    SOME_OTHER_RESPONDER: some_began_at + some_took_it_after
                },
                held={SOME_RESPONDER: some_title, SOME_OTHER_RESPONDER: None})
        ) \
        .when(
            lambda: engagement_with(SOME_INCIDENT,
                                    reported=_a_provider_reporting(reported))
        ) \
        .then(
            all_of(
                _the_titles_were(some_title),
                _the_responders_were(2)
            )
        )


def _an_incident(began_at: datetime,
                 ended_at: datetime,
                 acknowledged_at: Mapping[str, datetime],
                 held: Mapping[str, str | None] | None = None) -> ReportedIncident:
    """One incident as the provider reports it - when it began and ended, and
    who acknowledged it when, holding what title."""
    held = held or {}

    return ReportedIncident(
        began_at=began_at,
        ended_at=ended_at,
        acknowledgements=[
            _acknowledged_at(at,
                             by=responder,
                             holding=held.get(responder, DONT_CARE_TITLE))
            for responder, at in acknowledged_at.items()
        ]
    )


def _acknowledged_at(at: datetime,
                     by: str,
                     holding: str | None = DONT_CARE_TITLE) -> Acknowledgement:
    return Acknowledgement(at=at, responder_id=by, job_title=holding)


def _a_provider_reporting(
    incident: ReportedIncident
) -> Callable[[str], ReportedIncident]:
    def reported(dont_care_incident_id: str) -> ReportedIncident:
        return incident

    return reported


def _a_provider_that_cannot_be_read() -> Callable[[str], ReportedIncident]:
    def reported(dont_care_incident_id: str) -> ReportedIncident:
        raise OnCallUnavailable("the on-call provider could not be reached")

    return reported


def _the_minutes_were(minutes: int) -> Assertion[Any]:
    def assertion(engagement: Any) -> bool:
        if engagement is None:
            raise AssertionError(
                f"Expected [{minutes}] minutes of engagement, but the source "
                f"reported that it could not say at all."
            )

        if engagement.minutes != minutes:
            raise AssertionError(
                f"Expected [{minutes}] minutes of engagement, but what was "
                f"reported was [{engagement.minutes}]."
            )

        return True

    return assertion


def _the_responders_were(responders: int) -> Assertion[Any]:
    def assertion(engagement: Any) -> bool:
        if engagement is None:
            raise AssertionError(
                f"Expected [{responders}] responder(s), but the source reported "
                f"that it could not say at all."
            )

        if engagement.responders != responders:
            raise AssertionError(
                f"Expected [{responders}] responder(s), but what was reported "
                f"was [{engagement.responders}]."
            )

        return True

    return assertion


def _the_titles_were(*expected: str) -> Assertion[Any]:
    """Exactly these, once each.

    Sorted rather than ordered: the answer is who was on it, and the order two
    people acknowledged in is not something a document should imply.
    """
    def assertion(engagement: Any) -> bool:
        if engagement is None:
            raise AssertionError(
                f"Expected the titles {sorted(expected)}, but the source "
                f"reported that it could not say at all."
            )

        if sorted(engagement.titles) != sorted(expected):
            raise AssertionError(
                f"Expected the titles {sorted(expected)}, but what was reported "
                f"was {sorted(engagement.titles)}."
            )

        return True

    return assertion


def _nobody_could_say() -> Assertion[Any]:
    def assertion(engagement: Any) -> bool:
        if engagement is not None:
            raise AssertionError(
                f"Expected the source to report that it could not say, but it "
                f"answered {engagement}."
            )

        return True

    return assertion
