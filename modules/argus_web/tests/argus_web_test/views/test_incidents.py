"""Shaping an incident's rows into what a reader is shown.

No database here: the rows these take are what the repositories already return,
and every question below is about the arrangement rather than the retrieval -
which attempt belongs to which candidate, what an untried candidate looks like,
and what happens to an attempt that names no candidate at all.

The order everything arrives in is kept rather than re-imposed. Ranking
candidates and sequencing actions are decisions the investigation made, and a
view that sorted them again would be a second opinion about them - so the
assertions read the lists as lists, in the order they came.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core import new_id
from argus_core.events import ActionTaken, IncidentEvent
from argus_core.models import (
    Alert,
    Evidence,
    FailureMode,
    FlagUndo,
    Hypothesis,
    Incident,
    IncidentStatus,
    TakenAction,
    Verdict,
)
from argus_narration import ShownRevision
from argus_testkit import Assertion, Scenario, all_of
from argus_web.views.incidents import (
    Candidate,
    IncidentDetail,
    IncidentSummary,
    build_incident_detail,
    build_incident_summary,
)

_OPENED_AT = datetime(2026, 8, 30, 10, 15, tzinfo=UTC)

NOTHING_WAS_TRIED: list[TakenAction] = []
NOTHING_WAS_SAID: list[IncidentEvent] = []
NOTHING_WAS_FORMED: list[Hypothesis] = []

REFUTED = Verdict.REFUTED
CONFIRMED = Verdict.CONFIRMED


@pytest.mark.unit
def test_an_attempt_is_shown_against_the_candidate_it_was_taken_for() -> None:
    # Attached to the candidate, because "what did we try for this
    # explanation?" is the question a reader has while looking at one.
    an_incident = _an_incident()
    the_first_candidate = _a_candidate(an_incident.id, subject="first", rank=1)
    the_second_candidate = _a_candidate(an_incident.id, subject="second", rank=2)

    Scenario() \
        .given(
            each_candidate_was_tried_once := [
                _an_attempt(an_incident.id, the_first_candidate.id, outcome=REFUTED),
                _an_attempt(an_incident.id, the_second_candidate.id, outcome=CONFIRMED)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[the_first_candidate, the_second_candidate],
            attempts=each_candidate_was_tried_once,
            account=NOTHING_WAS_SAID
        )) \
        .then(_the_attempts_shown_per_candidate_are(
            [("first", [REFUTED]), ("second", [CONFIRMED])]
        ))


@pytest.mark.unit
def test_an_attempt_is_dated_by_its_announcement_as_the_postmortem_dates_it() -> None:
    # The row is a claim written before the agent taking the action is called
    # in. Dated by it, the page put a roll-back at 18:04:48 and the postmortem,
    # dated by the announcement, at 18:04:49.
    an_incident = _an_incident()
    some_candidate = _a_candidate(an_incident.id, subject="io-shop", rank=1)
    an_attempt = _an_attempt(an_incident.id, some_candidate.id, outcome=CONFIRMED)
    announced_at = an_attempt.taken_at + timedelta(milliseconds=438)

    Scenario() \
        .given(
            its_announcement := [ActionTaken(incident_id=an_incident.id,
                                             hypothesis_id=some_candidate.id,
                                             action_type="revert-feature-flag",
                                             subject="dont-care",
                                             at=announced_at)]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[some_candidate],
            attempts=[an_attempt],
            account=its_announcement
        )) \
        .then(_the_first_attempt_was_taken_at(announced_at))


@pytest.mark.unit
def test_a_candidate_the_walk_never_reached_is_shown_as_untried() -> None:
    # "Never reached" and "tried and refuted" are the difference between a walk
    # that ran out of options and one that stopped because it was right.
    an_incident = _an_incident()

    Scenario() \
        .given(
            a_candidate_never_reached := _a_candidate(
                an_incident.id, subject="never reached", rank=2
            )
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_never_reached],
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID
        )) \
        .then(all_of(_the_first_candidate_was_tested(False),
                     _the_first_candidate_resulted_in(None),
                     _the_attempts_shown_per_candidate_are([("never reached", [])])))


@pytest.mark.unit
def test_a_refuted_attempt_is_shown_as_having_been_put_back() -> None:
    # A reversible action that did not help is undone before its verdict is
    # returned. A page showing the attempt without that would leave a reader
    # believing the flag is still flipped.
    an_incident = _an_incident()
    the_refuted_candidate = _a_candidate(an_incident.id, subject="refuted", rank=1)
    the_confirmed_candidate = _a_candidate(an_incident.id, subject="confirmed", rank=2)

    Scenario() \
        .given(
            one_of_each_verdict := [
                _an_attempt(an_incident.id, the_refuted_candidate.id, outcome=REFUTED),
                _an_attempt(an_incident.id, the_confirmed_candidate.id, outcome=CONFIRMED)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[the_refuted_candidate, the_confirmed_candidate],
            attempts=one_of_each_verdict,
            account=NOTHING_WAS_SAID
        )) \
        .then(_the_attempts_were_undone([True, False]))


@pytest.mark.unit
def test_an_attempt_with_no_verdict_yet_is_shown_as_undecided_rather_than_undone() -> None:
    # An action taken a second ago has no answer yet, and calling that "not
    # undone" is right while calling it "refuted" or "confirmed" would not be.
    an_incident = _an_incident()
    a_candidate_being_acted_on = _a_candidate(an_incident.id, subject="in flight", rank=1)

    Scenario() \
        .given(
            an_attempt_the_service_has_not_answered := [
                _an_attempt(an_incident.id, a_candidate_being_acted_on.id, outcome=None)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_being_acted_on],
            attempts=an_attempt_the_service_has_not_answered,
            account=NOTHING_WAS_SAID
        )) \
        .then(all_of(_the_attempts_shown_per_candidate_are([("in flight", [None])]),
                     _the_attempts_were_undone([False]),
                     _the_attempts_await_a_verdict([True])))


@pytest.mark.unit
@pytest.mark.parametrize("status", [IncidentStatus.ESCALATED, IncidentStatus.WITHDRAWN,
                                    IncidentStatus.RESOLVED],
                         ids=lambda status: status.value)
def test_an_attempt_with_no_verdict_on_an_incident_that_is_over_awaits_none(
        status: IncidentStatus) -> None:
    # The worker taking it stopped, and nothing is coming to answer it - so it
    # is shown as a verdict never recorded rather than one still to come.
    an_incident = _an_incident().model_copy(update={"status": status})
    a_candidate_acted_on = _a_candidate(an_incident.id, subject="dont care", rank=1)

    Scenario() \
        .given(
            an_attempt_nobody_will_answer := [
                _an_attempt(an_incident.id, a_candidate_acted_on.id, outcome=None)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_acted_on],
            attempts=an_attempt_nobody_will_answer,
            account=NOTHING_WAS_SAID
        )) \
        .then(
            _the_attempts_await_a_verdict([False])
        )


@pytest.mark.unit
def test_an_attempt_naming_no_candidate_is_still_shown() -> None:
    # `action.hypothesis_id` is nullable, so an action can arrive attributed to
    # nothing. Dropping it would delete a change Argus made to the service from
    # the only account of what it did.
    an_incident = _an_incident()
    some_candidate = _a_candidate(an_incident.id, subject="a-flag", rank=1)

    Scenario() \
        .given(
            an_attempt_attributed_to_nothing := [
                _an_attempt(an_incident.id, None, outcome=CONFIRMED)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[some_candidate],
            attempts=an_attempt_attributed_to_nothing,
            account=NOTHING_WAS_SAID
        )) \
        .then(all_of(_the_attempts_shown_per_candidate_are([("a-flag", [])]),
                     _the_unattributed_attempts_are([CONFIRMED])))


@pytest.mark.unit
def test_a_candidate_is_shown_with_the_move_it_blamed() -> None:
    # Said the way the flag table says it, because this is the same page. The
    # states arrive as the model wrote them - `off` and `on` - and which of
    # those two words the page shouts is not the model's to decide.
    an_incident = _an_incident()

    Scenario() \
        .given(
            a_candidate_blaming_a_toggle := _a_candidate(
                an_incident.id, subject="a-flag", rank=1, from_state="off", to_state="on"
            )
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_blaming_a_toggle],
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID
        )) \
        .then(_the_only_candidate_moved(was="OFF", now="ON"))


@pytest.mark.unit
def test_a_candidate_carries_the_evidence_it_was_formed_from() -> None:
    # Evidence in a collection of its own makes a reader correlate claims to
    # timestamps, which is the reader investigating the incident again. Each in
    # the words the timeline says it in, never as the record it is kept in.
    an_incident = _an_incident()
    what_it_was_formed_from = [
        Evidence(claim="error rate rose at 10:14", at=None),
        Evidence(claim="a-flag was enabled at 10:13", at=None)
    ]

    Scenario() \
        .given(
            a_candidate_that_cited_two_things := _a_candidate(
                an_incident.id, subject="a-flag", rank=1, evidence=what_it_was_formed_from
            )
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_that_cited_two_things],
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID
        )) \
        .then(_the_first_candidate_cites(["error rate rose at 10:14",
                                          "a-flag was enabled at 10:13"]))


@pytest.mark.unit
def test_a_finding_naming_a_minute_the_page_holds_leads_to_it() -> None:
    # As the same finding does in the timeline above it. Said in words and
    # leading nowhere, the moment the finding rests on was lost.
    an_incident = _an_incident()
    the_minute_read = "2026-08-30T10:14:00Z"
    the_minute_logged = "2026-08-30T10:14"

    Scenario() \
        .given(
            a_candidate_citing_that_minute := _a_candidate(
                an_incident.id, subject="a-flag", rank=1,
                evidence=[Evidence(claim="error rate rose",
                                   at=datetime(2026, 8, 30, 10, 14, 30, tzinfo=UTC))])
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_citing_that_minute],
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID,
            minutes=[the_minute_read],
            logged=[the_minute_logged]
        )) \
        .then(_the_first_finding_leads_to(the_minute_read, the_minute_logged))


@pytest.mark.unit
@pytest.mark.parametrize(("named", "said"), [("2026-08-30T10:13Z", "10:13"),
                                             ("2026-08-29T10:13Z", "Aug 29 10:13")],
                         ids=["the-day-it-opened", "another-day"])
def test_an_instant_a_candidate_names_is_said_as_the_timeline_says_it(named: str,
                                                                     said: str) -> None:
    # The candidate says it as the Investigator wrote it, in the wire format
    # its tools speak, and the timeline above says the same words on a clock.
    # Left so, one page says one instant two ways. A clock time is read as
    # the day the incident opened, so an instant on any other keeps its date.
    an_incident = _an_incident()

    Scenario() \
        .given(
            a_candidate_naming_an_instant := _a_candidate(
                an_incident.id, subject="a-flag", rank=1, summary=f"the deploy at {named} broke it")
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_naming_an_instant],
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID
        )) \
        .then(_the_first_candidate_says(f"the deploy at {said} broke it"))


@pytest.mark.unit
@pytest.mark.parametrize(("named", "said"), [("2026-08-30T10:13Z", "10:13"),
                                             ("2026-08-29T10:13Z", "Aug 29 10:13")],
                         ids=["the-day-it-opened", "another-day"])
def test_an_instant_a_finding_names_is_said_as_its_candidate_says_one(named: str,
                                                                    said: str) -> None:
    # Read beside the day the incident opened, as the candidate's summary is.
    # Said beside nothing, a deploy a week before it read as one that morning,
    # under a summary that dated the same deploy.
    an_incident = _an_incident()

    Scenario() \
        .given(
            a_candidate_citing_an_instant := _a_candidate(
                an_incident.id, subject="a-flag", rank=1,
                evidence=[Evidence(claim=f"the deploy at {named} broke it", at=None)])
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_citing_an_instant],
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID
        )) \
        .then(_the_first_candidate_cites([f"the deploy at {said} broke it"]))


@pytest.mark.unit
def test_a_revision_a_candidate_names_is_said_short_and_leads_to_its_commit() -> None:
    # As the changes table above it names it, and the timeline beside it:
    # named whole here, one page named one revision two ways, and only one of
    # them opened.
    an_incident = _an_incident()
    some_revision = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
    some_commit = f"https://github.invalid/acme/shop/commit/{some_revision}"

    Scenario() \
        .given(
            a_candidate_naming_it := _a_candidate(
                an_incident.id, subject=some_revision, rank=1,
                summary=f"The deploy of [{some_revision}] broke it",
                evidence=[Evidence(claim=f"{some_revision} rewrote it", at=None)])
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_naming_it],
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID,
            revisions={some_revision: ShownRevision(short=some_revision[:7],
                                                    address=some_commit)}
        )) \
        .then(_the_first_candidate_names(
            summary=f"The deploy of {some_revision[:7]} broke it",
            subject=some_revision[:7],
            evidence=[f"{some_revision[:7]} rewrote it"],
            links={some_revision[:7]: some_commit}))


@pytest.mark.unit
def test_a_revision_a_candidate_moved_from_or_to_is_said_short_and_leads_to_its_commit() -> None:
    # As its subject is: whole and leading nowhere beside the subject named
    # short, one candidate named one revision two ways.
    an_incident = _an_incident()
    some_revision = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
    some_earlier_revision = "4c810f22894e612ced87f5ee3f3062dfeb785050"
    some_commit = f"https://github.invalid/acme/shop/commit/{some_revision}"
    some_earlier_commit = f"https://github.invalid/acme/shop/commit/{some_earlier_revision}"

    Scenario() \
        .given(
            a_candidate_blaming_the_deploy := _a_candidate(
                an_incident.id, subject="dont care", rank=1,
                from_state=some_earlier_revision, to_state=some_revision)
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_blaming_the_deploy],
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID,
            revisions={
                some_revision: ShownRevision(short=some_revision[:7], address=some_commit),
                some_earlier_revision: ShownRevision(short=some_earlier_revision[:7],
                                                     address=some_earlier_commit)}
        )) \
        .then(_the_first_candidate_moved(
            was=some_earlier_revision[:7], now=some_revision[:7],
            links={some_earlier_revision[:7]: some_earlier_commit,
                   some_revision[:7]: some_commit}))


@pytest.mark.unit
def test_an_incident_is_shown_with_the_alert_it_opened_on() -> None:
    # The row stores the alert as the JSON it was normalized into. A reader
    # gets the alert back, not the payload it was stored as.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate", severity="critical")

    Scenario() \
        .given(an_incident_opened_on_it := _an_incident(alert=some_alert)) \
        .when(lambda: build_incident_summary(an_incident_opened_on_it)) \
        .then(_it_opened_on(some_alert))


@pytest.mark.unit
def test_an_incident_that_formed_no_candidate_is_shown_as_empty() -> None:
    # An incident that escalated before forming a hypothesis is a real incident
    # with nothing to show, which is not the same as an unknown one.
    Scenario() \
        .given(an_incident_that_explained_nothing := _an_incident()) \
        .when(lambda: build_incident_detail(
            an_incident_that_explained_nothing,
            candidates=NOTHING_WAS_FORMED,
            attempts=NOTHING_WAS_TRIED,
            account=NOTHING_WAS_SAID
        )) \
        .then(_the_attempts_shown_per_candidate_are([]))


def _an_incident(alert: Alert | None = None) -> Incident:
    return Incident(
        id=new_id(),
        alert_payload=(alert or Alert(service="io-shop", alert_name="HighErrorRate"))
        .model_dump(mode="json"),
        status=IncidentStatus.INVESTIGATING,
        created_at=_OPENED_AT,
        ended_at=None
    )


def _a_candidate(incident_id: str,
                 subject: str,
                 rank: int,
                 evidence: list[Evidence] | None = None,
                 from_state: str | None = None,
                 to_state: str | None = None,
                 summary: str | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=incident_id,
        summary=summary or f"dont care - {subject}",
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        supporting_evidence=evidence or [],
        subject=subject,
        rank=rank,
        from_state=from_state,
        to_state=to_state
    )


def _an_attempt(incident_id: str,
                hypothesis_id: str | None,
                outcome: Verdict | None) -> TakenAction:
    return TakenAction(
        id=new_id(),
        incident_id=incident_id,
        hypothesis_id=hypothesis_id,
        type="revert-feature-flag",
        subject=None,
        has_a_way_back=True,
        undo_descriptor=FlagUndo(flag="dont-care", was_enabled=True),
        outcome=outcome,
        taken_at=_OPENED_AT + timedelta(minutes=1)
    )


def _the_first_attempt_was_taken_at(expected: datetime) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        shown = [attempt.taken_at for candidate in detail.candidates
                 for attempt in candidate.attempts]

        if shown[:1] != [expected]:
            raise AssertionError(f"Expected the attempt dated [{expected}], got {shown}.")

        return True

    return assertion


def _the_attempts_shown_per_candidate_are(
    expected: list[tuple[str | None, list[str | None]]]
) -> Assertion[IncidentDetail]:
    """Every candidate with what was tried for it, in order, as one value.

    Asserted whole because the arrangement is the subject: a candidate carrying
    somebody else's attempt is as wrong as one carrying none, and a check that
    named only the candidate it expected could not see the first kind.
    """
    def assertion(detail: IncidentDetail) -> bool:
        shown = [
            (candidate.subject, [attempt.outcome for attempt in candidate.attempts])
            for candidate in detail.candidates
        ]

        if shown != expected:
            raise AssertionError(f"Expected {expected}, got {shown}.")

        return True

    return assertion


def _the_attempts_await_a_verdict(expected: list[bool]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        awaiting = [attempt.awaiting_a_verdict
                    for candidate in detail.candidates
                    for attempt in candidate.attempts]

        if awaiting != expected:
            raise AssertionError(f"Expected {expected} awaiting a verdict, got {awaiting}.")

        return True

    return assertion


def _the_attempts_were_undone(expected: list[bool]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        undone = [
            attempt.undone
            for candidate in detail.candidates
            for attempt in candidate.attempts
        ]

        if undone != expected:
            raise AssertionError(f"Expected {expected} undone, got {undone}.")

        return True

    return assertion


def _the_unattributed_attempts_are(expected: list[str | None]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        shown = [attempt.outcome for attempt in detail.unattributed_attempts]

        if shown != expected:
            raise AssertionError(
                f"Expected {expected} attributed to nothing, got {shown}."
            )

        return True

    return assertion


def _the_first_candidate_was_tested(expected: bool) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        tested = _the_first(detail).tested

        if tested is not expected:
            raise AssertionError(f"Expected tested [{expected}], got [{tested}].")

        return True

    return assertion


def _the_first_candidate_resulted_in(expected: str | None) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        result = _the_first(detail).result

        if result != expected:
            raise AssertionError(f"Expected the result [{expected}], got [{result}].")

        return True

    return assertion


def _the_first_finding_leads_to(minute: str, lines: str) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        finding = _the_first(detail).evidence[0]
        led_to = (finding.links_to_minute, finding.links_to_lines)

        if led_to != (minute, lines):
            raise AssertionError(
                f"Expected the finding to lead to the minute [{minute}] and its lines "
                f"[{lines}], it led to {led_to}."
            )

        return True

    return assertion


def _the_first_candidate_cites(expected: list[str]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        cited = [finding.text for finding in _the_first(detail).evidence]

        if cited != expected:
            raise AssertionError(f"Expected the evidence {expected}, got {cited}.")

        return True

    return assertion


def _it_opened_on(expected: Alert) -> Assertion[IncidentSummary]:
    def assertion(summary: IncidentSummary) -> bool:
        if summary.alert != expected:
            raise AssertionError(f"Expected the alert [{expected}], got [{summary.alert}].")

        return True

    return assertion


def _the_first(detail: IncidentDetail) -> Candidate:
    """The single candidate a one-candidate incident was shaped into.

    Checked here rather than by indexing inside each assertion, so a detail
    that came back with two fails saying so instead of quietly asserting on
    whichever landed first.
    """
    if len(detail.candidates) != 1:
        raise AssertionError(f"Expected one candidate, got {len(detail.candidates)}.")

    return detail.candidates[0]


def _the_only_candidate_moved(was: str, now: str) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        candidate = detail.candidates[0]

        if (candidate.moved_from, candidate.moved_to) != (was, now):
            raise AssertionError(
                f"Expected the candidate to have moved [{was}] to [{now}], "
                f"got [{candidate.moved_from}] to [{candidate.moved_to}]."
            )

        return True

    return assertion


def _the_first_candidate_says(expected: str) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        said = _the_first(detail).summary

        if said != expected:
            raise AssertionError(f"Expected the candidate to say [{expected}], got [{said}].")

        return True

    return assertion


def _the_first_candidate_moved(was: str, now: str,
                               links: dict[str, str]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        candidate = _the_first(detail)
        moved = (candidate.moved_from, candidate.moved_to, candidate.links)
        expected = (was, now, links)

        if moved != expected:
            raise AssertionError(f"Expected the candidate's move and links {expected}, "
                                 f"got {moved}.")

        return True

    return assertion


def _the_first_candidate_names(summary: str, subject: str, evidence: list[str],
                               links: dict[str, str]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        candidate = _the_first(detail)
        named = (candidate.summary, candidate.subject,
                 [finding.text for finding in candidate.evidence], candidate.links)
        expected = (summary, subject, evidence, links)

        if named != expected:
            raise AssertionError(f"Expected the candidate's claim, subject, findings and "
                                 f"links {expected}, got {named}.")

        return True

    return assertion
