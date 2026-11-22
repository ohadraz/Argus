"""One change of Argus's open on a subject at a time, across incidents.

Two incidents blaming one flag would each change it, and the first one's
put-back would undo the second's change - or the second would overwrite the
first's confirmed mitigation, or move the flag inside the first's verification
wait, so that the first's verdict measured the second's change. The database
refuses the second claim, and the walk escalates, naming the incident whose
change it is.

Every part of that is pinned somewhere smaller: the refusal against a real row in
the actions repository's suite, the answer through `Records` in its own, the
escalation over a stand-in claim in the mitigating node's. What only this case
can say is that they are wired together: that the node, handed the claim the
graph is assembled with, escalates on a refusal the real index makes - and that
the subject is free again once the first change is put back.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Final, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of, calling
from core import utc_now
from core.events import ActionRefused, IncidentEvent, Publisher
from core.models import (
    Action,
    ActionProgress,
    Alert,
    ClaimAnswer,
    Claimed,
    FailureMode,
    FlagUndo,
    Hypothesis,
    IncidentStatus,
    Refusal,
    RevertFeatureFlag,
    Undone,
    Verdict,
    why_it_was_refused,
)
from incident_record import IsStillWanted
from incident_record.publishing import events_into_connection
from incident_record.repository import hypotheses, incidents, taken_actions
from orchestrator.records import Records
from orchestrator.walk import ports
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.mitigating import mitigation_node
from orchestrator.walk.state import IncidentState
from postgres import connect_from_env

# The flag both incidents blame.
THE_CONTESTED_FLAG: Final = "kuki-flag"
THE_WAY_BACK: Final = FlagUndo(flag=THE_CONTESTED_FLAG, was_enabled=True)

# How many characters of an incident's id a line names it by.
SHORT_INCIDENT_ID: Final = 8

DONT_CARE_ALERT: Final = Alert(service="io-shop", alert_name="HighErrorRate")
DONT_CARE_SUMMARY: Final = "dont care"
DONT_CARE_CONFIDENCE: Final = 0.9


@pytest.mark.integration
def test_a_change_to_a_flag_another_incident_s_change_holds_escalates_naming_it() -> None:
    records = Records(connect_from_env, publisher_for=events_into_connection)
    first_incident_id = _an_incident()
    _a_change_made_to_the_flag_in(first_incident_id, records)
    the_second_candidate = _a_candidate_blaming_the_flag(_an_incident())
    second = _an_incident_reverting_the_flag(the_second_candidate)
    take = cast(MagicMock, create_autospec(ports.TakeAction, instance=True))
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            second
        ) \
        .when(
            lambda: _mitigating(second, records, take, published.append)
        ) \
        .then(all_of(
            _it_escalated_because(_held_by_the_incident(first_incident_id)),
            _nothing_was_taken(take),
            _no_action_was_written_for(second.incident_id),
            _the_refusal_named(published, the_second_candidate, first_incident_id)
        ))


@pytest.mark.integration
def test_a_subject_whose_change_was_put_back_is_claimed_by_a_third_incident() -> None:
    records = Records(connect_from_env, publisher_for=events_into_connection)
    first_incident_id = _an_incident()
    the_first_change = _a_change_made_to_the_flag_in(first_incident_id, records)
    second = _an_incident_reverting_the_flag(_a_candidate_blaming_the_flag(_an_incident()))
    _mitigating(second, records, _nothing_is_taken(), _nobody_is_listening)
    third = _a_candidate_blaming_the_flag(_an_incident())

    Scenario() \
        .given(
            calling(lambda: _put_back(the_first_change))
        ) \
        .when(
            lambda: records.claim_action(third.incident_id,
                                         hypothesis_id=third.id,
                                         action_type=_the_revert().action_type,
                                         subject=THE_CONTESTED_FLAG,
                                         at=utc_now())
        ) \
        .then(
            _it_was_claimed()
        )


def _held_by_the_incident(open_in: str) -> str:
    """What the escalation says, where another incident holds the other change:
    the refusal's own sentence, then whose the other change is."""
    return (f"{why_it_was_refused(Refusal.SUBJECT_ALREADY_OPEN)} - incident "
            f"{open_in[:SHORT_INCIDENT_ID]}'s")


def _an_incident() -> str:
    with connect_from_env() as conn:
        return incidents.create(conn, DONT_CARE_ALERT, at=utc_now())


def _a_candidate_blaming_the_flag(incident_id: str) -> Hypothesis:
    """A candidate on file, as the claim's row refers to it."""
    candidate = Hypothesis(incident_id=incident_id, summary=DONT_CARE_SUMMARY,
                           failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                           confidence=DONT_CARE_CONFIDENCE,
                           supporting_evidence=[], subject=THE_CONTESTED_FLAG)

    with connect_from_env() as conn:
        hypotheses.record(conn, candidate)

    return candidate


def _the_revert() -> RevertFeatureFlag:
    return RevertFeatureFlag(flag=THE_CONTESTED_FLAG, enabled=False,
                             undo_descriptor=THE_WAY_BACK)


def _a_change_made_to_the_flag_in(incident_id: str, records: Records) -> str:
    """The flag switched off for the incident's candidate, and standing - the
    claim the first incident's walk writes, and the step it writes once the
    agent says the change was made. Answers the change's own id."""
    candidate = _a_candidate_blaming_the_flag(incident_id)
    answer = records.claim_action(incident_id, hypothesis_id=candidate.id,
                                  action_type=_the_revert().action_type,
                                  subject=THE_CONTESTED_FLAG, at=utc_now())
    assert isinstance(answer, Claimed)
    records.advance_action(incident_id, hypothesis_id=candidate.id,
                           to=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK,
                           performed_at=utc_now())

    return answer.action_id


def _an_incident_reverting_the_flag(candidate: Hypothesis) -> IncidentState:
    """`candidate`'s incident at mitigation, the candidate blaming the flag the
    gate admitted a revert of."""
    return IncidentState(incident_id=candidate.incident_id,
                         alert=DONT_CARE_ALERT,
                         status=IncidentStatus.MITIGATING,
                         hypothesis=candidate,
                         proposed_action=_the_revert())


def _mitigating(state: IncidentState,
                records: Records,
                take: ports.TakeAction,
                publisher: Publisher) -> StateDelta:
    """The node, writing through the `Records` the graph is assembled with, and
    with stand-ins for everything the claim decides is never reached."""
    still_wanted = cast(MagicMock, create_autospec(IsStillWanted, instance=True))
    still_wanted.return_value = True

    return mitigation_node(state,
                           record_action=records.claim_action,
                           complete_action=records.complete_action,
                           already_taken=records.claimed_action,
                           advance_action=records.advance_action,
                           owe_a_put_back=records.owe_a_put_back,
                           record_outcome=records.outcome,
                           still_wanted=still_wanted,
                           take=take,
                           plan_action=_no_plan,
                           resuming=cast(ports.Resuming,
                                         create_autospec(ports.Resuming, instance=True)),
                           acting_for=_acting_for_whichever,
                           publisher=publisher)


def _put_back(action_id: str) -> None:
    """What a withdrawal's cleanup writes once it has put the change back."""
    with connect_from_env() as conn:
        taken_actions.record_undone(conn, action_id, Undone.RESTORED)


def _nothing_is_taken() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.TakeAction, instance=True))


def _no_plan(dont_care_action: Action, /) -> None:
    """The write tier answering with no plan, which the claim never looks at."""


def _acting_for_whichever(dont_care_action_id: str) -> AbstractContextManager[None]:
    return nullcontext()


def _nobody_is_listening(_event: IncidentEvent) -> None:
    """A publisher for the part of a case that is not about publishing."""


def _it_escalated_because(expected: str) -> Assertion[StateDelta]:
    def assertion(delta: StateDelta) -> bool:
        if delta.action_outcome != Verdict.ESCALATED or delta.action_because != expected:
            raise AssertionError(
                f"Expected the walk to escalate because [{expected}], and it reported "
                f"[{delta.action_outcome}] because [{delta.action_because}]."
            )

        return True

    return assertion


def _nothing_was_taken(take: MagicMock) -> Assertion[StateDelta]:
    def assertion(_: StateDelta) -> bool:
        if take.called:
            raise AssertionError(
                f"Expected no action taken on a subject another incident's change "
                f"holds, and the agent was asked to take one: {take.call_args}."
            )

        return True

    return assertion


def _no_action_was_written_for(incident_id: str) -> Assertion[StateDelta]:
    def assertion(_: StateDelta) -> bool:
        with connect_from_env() as conn:
            written = taken_actions.get_by_incident(conn, incident_id)

        if written:
            raise AssertionError(
                f"Expected no action written for the refused incident, got {written}."
            )

        return True

    return assertion


def _the_refusal_named(published: list[IncidentEvent],
                       candidate: Hypothesis,
                       open_in: str) -> Assertion[StateDelta]:
    """One refusal published for an open subject, about `candidate` - by its id
    and the number a reader knows it by - naming `open_in`."""
    def assertion(_: StateDelta) -> bool:
        refusals = [(event.hypothesis_id, event.candidate_number, event.refusal, event.open_in)
                    for event in published if isinstance(event, ActionRefused)]
        wanted = [(candidate.id, candidate.number, Refusal.SUBJECT_ALREADY_OPEN, open_in)]

        if refusals != wanted:
            raise AssertionError(
                f"Expected one refusal saying the subject was open in incident "
                f"[{open_in}], as {wanted}, got {refusals}."
            )

        return True

    return assertion


def _it_was_claimed() -> Assertion[ClaimAnswer]:
    def assertion(answer: ClaimAnswer) -> bool:
        if not isinstance(answer, Claimed):
            raise AssertionError(
                f"Expected a subject whose change was put back to be claimed, got "
                f"[{answer}]."
            )

        return True

    return assertion
