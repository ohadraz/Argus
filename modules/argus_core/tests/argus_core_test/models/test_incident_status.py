"""Which statuses an incident can still move out of.

Asked by anything that waits on an incident - a page that polls, a report that
counts what is still open. It lives on the status rather than in the caller
because "is there more to come?" is a fact about the state machine (spec §10),
and a second copy of it in a template is a second copy that can be wrong.
"""

from __future__ import annotations

import pytest
from argus_core.models import Meaning
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario


@pytest.mark.unit
def test_a_resolved_incident_has_nowhere_left_to_go() -> None:
    Scenario() \
        .given(
            resolved := IncidentStatus.RESOLVED
        ) \
        .when(
            lambda: resolved.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
def test_an_escalated_incident_has_nowhere_left_to_go() -> None:
    # The walk hands over to a human here, and it does not come back.
    Scenario() \
        .given(
            escalated := IncidentStatus.ESCALATED
        ) \
        .when(
            lambda: escalated.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
def test_an_investigating_incident_is_still_going() -> None:
    Scenario() \
        .given(
            investigating := IncidentStatus.INVESTIGATING
        ) \
        .when(
            lambda: investigating.is_terminal()
        ) \
        .then(
            _there_is_more_to_come()
        )


@pytest.mark.unit
def test_a_mitigating_incident_is_still_going() -> None:
    Scenario() \
        .given(
            mitigating := IncidentStatus.MITIGATING
        ) \
        .when(
            lambda: mitigating.is_terminal()
        ) \
        .then(
            _there_is_more_to_come()
        )


@pytest.mark.unit
def test_a_fixing_incident_is_still_going() -> None:
    # `fixing` reads like an ending and is not one: it is where an incident
    # sits while Code-Fix looks for a permanent fix, so an incident in it is
    # one Argus is still working on.
    Scenario() \
        .given(
            fixing := IncidentStatus.FIXING
        ) \
        .when(
            lambda: fixing.is_terminal()
        ) \
        .then(
            _there_is_more_to_come()
        )


@pytest.mark.unit
def test_a_withdrawn_incident_has_nowhere_left_to_go() -> None:
    # A human took the incident back. Argus stops, and unlike `fixing` there is
    # nothing of Argus's still working on it.
    Scenario() \
        .given(
            withdrawn := IncidentStatus.WITHDRAWN
        ) \
        .when(
            lambda: withdrawn.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
def test_a_mitigated_incident_has_nowhere_left_to_go() -> None:
    # The service is well and the cause is still there, held back by a flag
    # somebody reverted. Terminal because it is as far as Argus can take it:
    # what would make it `resolved` is a human merging the fix, which is
    # outside Argus's autonomy entirely (spec §13) and nothing here can wait
    # for. An incident that sat here non-terminal would be one a page polls
    # forever.
    Scenario() \
        .given(
            mitigated := IncidentStatus.MITIGATED
        ) \
        .when(
            lambda: mitigated.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
def test_a_recommended_incident_has_nowhere_left_to_go() -> None:
    # Argus worked out what to do and declined to do it, because nothing could
    # tell it afterwards whether the action had worked. Terminal for the reason
    # `mitigated` is: it is as far as Argus can take the incident, and what
    # moves it on is a person taking the action Argus named. Non-terminal, it
    # would be an incident a page polls forever waiting for a walk that has
    # already stopped.
    Scenario() \
        .given(
            recommended := IncidentStatus.RECOMMENDED
        ) \
        .when(
            lambda: recommended.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
def test_a_disproven_incident_has_nowhere_left_to_go() -> None:
    # The metrics contradicted what the alarm claimed, so there was no incident
    # to work on. Terminal in the plainest sense of any status here: the others
    # are as far as Argus can take something, and this is as far as there was
    # anything to take.
    Scenario() \
        .given(
            disproven := IncidentStatus.DISPROVEN
        ) \
        .when(
            lambda: disproven.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
@pytest.mark.parametrize("resolvable", [
    IncidentStatus.ACKNOWLEDGED,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.MITIGATING,
    IncidentStatus.FIXING,
    IncidentStatus.MITIGATED,
    IncidentStatus.ESCALATED,
    IncidentStatus.RECOMMENDED
])
def test_a_person_may_report_the_incident_resolved(resolvable: IncidentStatus) -> None:
    # The three endings Argus reached by stopping are among them: mitigated,
    # escalated and recommended each leave something owed, and a person who
    # then finished the job is reporting exactly that.
    Scenario() \
        .given(
            resolvable
        ) \
        .when(
            lambda: resolvable.accepts_resolution()
        ) \
        .then(
            _a_person_may_resolve_it()
        )


@pytest.mark.unit
@pytest.mark.parametrize("unresolvable", [
    IncidentStatus.RESOLVED,
    IncidentStatus.WITHDRAWN,
    IncidentStatus.DISPROVEN
])
def test_a_person_may_not_report_the_incident_resolved(unresolvable: IncidentStatus) -> None:
    # Resolved already is; withdrawn was taken back, and resolving it would
    # rewrite why it ended; disproven had no incident to resolve.
    Scenario() \
        .given(
            unresolvable
        ) \
        .when(
            lambda: unresolvable.accepts_resolution()
        ) \
        .then(
            _nobody_may_resolve_it()
        )


@pytest.mark.unit
@pytest.mark.parametrize("withdrawable", [
    IncidentStatus.ACKNOWLEDGED,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.MITIGATING,
    IncidentStatus.FIXING
])
def test_a_person_may_withdraw_an_incident_still_being_worked_on(
        withdrawable: IncidentStatus) -> None:
    # Withdrawing is taking the work back, and there is work to take back
    # only until the incident ends - Code-Fix's `fixing` included.
    Scenario() \
        .given(
            withdrawable
        ) \
        .when(
            lambda: withdrawable.accepts_withdrawal()
        ) \
        .then(
            _a_person_may_withdraw_it(True)
        )


@pytest.mark.unit
@pytest.mark.parametrize("ended", [
    IncidentStatus.MITIGATED,
    IncidentStatus.RESOLVED,
    IncidentStatus.ESCALATED,
    IncidentStatus.RECOMMENDED,
    IncidentStatus.DISPROVEN,
    IncidentStatus.WITHDRAWN
])
def test_a_person_may_not_withdraw_an_incident_that_has_ended(ended: IncidentStatus) -> None:
    # Mitigated among them: its change is holding the service up, and the
    # unwind a withdrawal starts would put the failure back. Withdrawn among
    # them too: there is nothing left to confirm.
    Scenario() \
        .given(
            ended
        ) \
        .when(
            lambda: ended.accepts_withdrawal()
        ) \
        .then(
            _a_person_may_withdraw_it(False)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("meaning", "status", "accepted"), [
    (Meaning.RESOLVE, IncidentStatus.MITIGATED, True),
    (Meaning.RESOLVE, IncidentStatus.RESOLVED, False),
    (Meaning.WITHDRAW, IncidentStatus.FIXING, True),
    (Meaning.WITHDRAW, IncidentStatus.MITIGATED, False),
    (Meaning.QUESTION, IncidentStatus.INVESTIGATING, False),
    (Meaning.INFORMATION, IncidentStatus.INVESTIGATING, False),
    (Meaning.OTHER, IncidentStatus.INVESTIGATING, False)
])
def test_what_a_person_asked_for_is_accepted_only_where_its_ending_still_is(
        meaning: Meaning, status: IncidentStatus, accepted: bool) -> None:
    # A message that asks for an ending asks the question that ending asks of
    # the status - a resolution's of a mitigated incident gets a yes, a
    # withdrawal's a no - and one that asks for no ending is accepted nowhere,
    # so nothing is ever offered for it or waited on.
    Scenario() \
        .given(
            status
        ) \
        .when(
            lambda: status.accepts_what_was_asked(meaning)
        ) \
        .then(
            _it_is_accepted(accepted)
        )


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.WITHDRAWN, IncidentStatus.RESOLVED])
def test_a_person_writes_this_ending(ending: IncidentStatus) -> None:
    # The two endings written from outside the walk. Nothing the walk writes
    # afterwards may replace either, and the walk stops for both.
    Scenario() \
        .given(
            ending
        ) \
        .when(
            lambda: ending.is_a_persons_ending()
        ) \
        .then(
            _a_person_wrote_it(True)
        )


@pytest.mark.unit
@pytest.mark.parametrize("status", [status for status in IncidentStatus
                                    if status not in (IncidentStatus.WITHDRAWN,
                                                      IncidentStatus.RESOLVED)])
def test_the_walk_writes_every_other_status(status: IncidentStatus) -> None:
    # Argus's own endings among them. A mitigated incident read as ended by a
    # person would have the walk skip the Code-Fix it goes on to.
    Scenario() \
        .given(
            status
        ) \
        .when(
            lambda: status.is_a_persons_ending()
        ) \
        .then(
            _a_person_wrote_it(False)
        )


def _a_person_wrote_it(expected: bool) -> Assertion[bool]:
    def assertion(written_by_a_person: bool) -> bool:
        if written_by_a_person is not expected:
            raise AssertionError(
                f"Expected a status {"a person" if expected else "the walk"} writes, "
                f"got [{written_by_a_person!r}]."
            )

        return True

    return assertion


def _it_is_accepted(expected: bool) -> Assertion[bool]:
    def assertion(accepts: bool) -> bool:
        if accepts is not expected:
            raise AssertionError(
                f"Expected what was asked {'' if expected else 'not '}to be accepted, "
                f"got [{accepts!r}]."
            )

        return True

    return assertion


def _a_person_may_withdraw_it(expected: bool) -> Assertion[bool]:
    def assertion(accepts: bool) -> bool:
        if accepts is not expected:
            raise AssertionError(
                f"Expected a status {"a person" if expected else "nobody"} may withdraw, "
                f"got [{accepts!r}]."
            )

        return True

    return assertion


def _a_person_may_resolve_it() -> Assertion[bool]:
    def assertion(accepts: bool) -> bool:
        if accepts is not True:
            raise AssertionError(f"Expected a status a person may resolve, got [{accepts!r}].")

        return True

    return assertion


def _nobody_may_resolve_it() -> Assertion[bool]:
    def assertion(accepts: bool) -> bool:
        if accepts is not False:
            raise AssertionError(f"Expected a status nobody may resolve, got [{accepts!r}].")

        return True

    return assertion


def _nothing_more_is_coming() -> Assertion[bool]:
    """That the status is terminal, and says so as a real `bool`.

    Identity rather than truthiness, which is what the assertions this
    replaced were claiming too. Anything that polls this reads the answer
    directly, and a method that returned some truthy object instead would
    satisfy a looser check while serialising as something no page can read.
    """
    def assertion(terminal: bool) -> bool:
        if terminal is not True:
            raise AssertionError(f"Expected a status nothing follows, got [{terminal!r}].")

        return True

    return assertion


def _there_is_more_to_come() -> Assertion[bool]:
    """The other half, and the one whose failure is quieter: a status wrongly
    called terminal ends a walk early rather than leaving a page polling."""
    def assertion(terminal: bool) -> bool:
        if terminal is not False:
            raise AssertionError(f"Expected a status still to be worked on, got [{terminal!r}].")

        return True

    return assertion
