from __future__ import annotations

from typing import Any

import pytest
from agent_investigator import Findings
from argus_core.events import (
    ActionTaken,
    AgentInvoked,
    AlertAcknowledged,
    FlagChangesRetrieved,
    IncidentEvent,
    Publisher,
    VerdictReached,
    nobody,
)
from argus_core.models.action import Action, Outcome, Verdict
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.flag_change import FlagChange
from argus_core.models.incident_status import IncidentStatus
from orchestrator.graph import (
    investigator_node,
    mitigation_node,
    mitigation_proposal_node,
)
from orchestrator.publishing import acknowledge_alert

from ..framework.builders import (
    a_determined_hypothesis,
    a_high_enough_confidence,
    an_incident_state,
)

"""What the Orchestrator says about the work it hands out.

The agents narrate what they alone know - which window was read, what the
model answered. The Orchestrator narrates what it alone knows: that the alert
arrived at all, which agent it invoked, and what came back from an action it
had already gated. Between them the two accounts are one story.

Where the incident moved is published in one place, by the wrapper that derives
it - see `test_status_wrapper.py`. A node has no status to announce.
"""


@pytest.mark.unit
def test_receiving_the_alert_is_the_first_line_of_the_incidents_story() -> None:
    # The moment Argus has the alert and has looked at nothing yet. An account
    # that opens on the Investigator already working starts mid-sentence: the
    # reader never sees the thing that set it off.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    published: list[IncidentEvent] = []

    acknowledge_alert(_SOME_INCIDENT_ID, some_alert, published.append)

    assert len(published) == 1, f"Expected one event, got {len(published)}."
    acknowledged = published[0]
    assert isinstance(acknowledged, AlertAcknowledged), (
        f"Expected an AlertAcknowledged, got {type(acknowledged).__name__}."
    )
    assert acknowledged.incident_id == _SOME_INCIDENT_ID
    assert acknowledged.alert == some_alert


@pytest.mark.unit
def test_an_alert_nobody_is_listening_for_is_still_received() -> None:
    # The account is never part of the work. Acknowledging with no subscriber
    # has to be as ordinary as acknowledging with one, because the default
    # everywhere else in this system is that nobody is listening.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    acknowledge_alert(_SOME_INCIDENT_ID, dont_care_alert)


@pytest.mark.unit
def test_the_graph_says_when_it_invokes_the_investigator() -> None:
    # A narration that begins at the first retrieval starts mid-sentence: the
    # Orchestrator handing the incident over is the thing that caused it.
    published: list[IncidentEvent] = []

    _the_investigator_runs(publisher=published.append)

    invoked = [event for event in published if isinstance(event, AgentInvoked)]
    assert [event.agent for event in invoked] == [Actor.INVESTIGATOR]


@pytest.mark.unit
def test_the_investigation_publishes_to_the_same_place_the_graph_does() -> None:
    # The Investigator's own account and the graph's are one narration, and
    # they are only one if the node hands its publisher down rather than
    # letting the agent publish somewhere of its own.
    published: list[IncidentEvent] = []
    what_the_investigation_was_given: list[Any] = []

    _the_investigator_runs(
        publisher=published.append,
        remember_publisher=what_the_investigation_was_given.append,
    )

    assert what_the_investigation_was_given == [published.append]


@pytest.mark.unit
def test_the_graph_says_what_action_it_took_and_for_which_candidate() -> None:
    # The one moment production state changes. An account that omitted it
    # would describe an investigation rather than an intervention.
    published: list[IncidentEvent] = []
    some_candidate = a_determined_hypothesis(_SOME_INCIDENT_ID, a_high_enough_confidence())

    _an_action_is_taken(some_candidate, _CONFIRMED, publisher=published.append)

    taken = [event for event in published if isinstance(event, ActionTaken)]
    assert len(taken) == 1
    assert taken[0].hypothesis_id == some_candidate.id
    assert taken[0].action_type == _AN_ACTION.action_type


@pytest.mark.unit
def test_the_graph_says_which_way_it_moved_the_flag() -> None:
    # "A flag was changed" is the half of the sentence nobody can act on.
    # Whether the shop is now serving with the feature on or off is the whole
    # point of the change.
    published: list[IncidentEvent] = []
    some_candidate = a_determined_hypothesis(_SOME_INCIDENT_ID, a_high_enough_confidence())

    _an_action_is_taken(some_candidate, _CONFIRMED, publisher=published.append)

    taken = [event for event in published if isinstance(event, ActionTaken)]
    assert [event.enabled for event in taken] == [_AN_ACTION.enabled]


@pytest.mark.unit
def test_the_graph_says_what_verdict_came_back() -> None:
    # The verdict is what the action was for, and it arrives after it - two
    # lines in the narration, because they are two moments.
    published: list[IncidentEvent] = []
    some_candidate = a_determined_hypothesis(_SOME_INCIDENT_ID, a_high_enough_confidence())

    _an_action_is_taken(some_candidate, _REFUTED, publisher=published.append)

    reached = [event for event in published if isinstance(event, VerdictReached)]
    assert [event.outcome for event in reached] == [str(Verdict.REFUTED)]


@pytest.mark.unit
def test_the_graph_says_what_flag_history_it_chose_the_action_from() -> None:
    # The action rests on this and nothing else: which flag moved, which way,
    # and when. Unpublished, the page shows Argus reverting a flag with no
    # account of how it came to be that flag - the one step of the walk an
    # audience most wants to check.
    published: list[IncidentEvent] = []
    what_the_provider_recorded = [
        FlagChange(
            flag="monthly-spend-feature",
            enabled=True,
            occurred_at="2026-08-30T10:05:00Z",
            actor="a-human",
        )
    ]

    _an_action_is_proposed(what_the_provider_recorded, publisher=published.append)

    read = [event for event in published if isinstance(event, FlagChangesRetrieved)]
    assert len(read) == 1, f"Expected one FlagChangesRetrieved, got {len(read)}."
    assert read[0].changes == what_the_provider_recorded


@pytest.mark.unit
def test_a_flag_history_that_could_not_be_read_is_not_published_as_an_empty_one() -> None:
    # "Nothing changed" and "the provider did not answer" lead to the same
    # place - no action - and are not the same fact. A page showing an empty
    # history for the second would be stating that nothing had changed.
    published: list[IncidentEvent] = []

    def the_provider_is_unreachable() -> list[FlagChange]:
        raise ConnectionError("dont care")

    _an_action_is_proposed(the_provider_is_unreachable, publisher=published.append)

    assert [event for event in published if isinstance(event, FlagChangesRetrieved)] == []


@pytest.mark.unit
def test_a_node_nobody_is_listening_to_does_the_same_thing() -> None:
    # The account is never part of the work, at this level as at every other.
    some_candidate = a_determined_hypothesis(_SOME_INCIDENT_ID, a_high_enough_confidence())

    listened_to = _an_action_is_taken(
        some_candidate, _CONFIRMED, publisher=[].append
    )
    unheard = _an_action_is_taken(some_candidate, _CONFIRMED)

    assert listened_to == unheard


_SOME_INCIDENT_ID = "some-incident"
_AN_ACTION = Action(
    action_type="revert-feature-flag",
    flag="monthly-spend-feature",
    enabled=False,
    undo_descriptor={"flag": "monthly-spend-feature", "was_enabled": True},
)
_CONFIRMED = Outcome(verdict=Verdict.CONFIRMED, detail="dont care",
                     undo_descriptor={"was_enabled": True})
_REFUTED = Outcome(verdict=Verdict.REFUTED, detail="dont care",
                   undo_descriptor={"was_enabled": True})


def _the_investigator_runs(publisher: Any,
                           remember_publisher: Any = None) -> dict[str, Any]:
    """One turn of the investigator node, with everything it writes doubled."""
    state = an_incident_state(
        _AN_ALERT, IncidentStatus.INVESTIGATING, incident_id=_SOME_INCIDENT_ID
    )
    candidate = a_determined_hypothesis(_SOME_INCIDENT_ID, a_high_enough_confidence())

    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    resume_from: int = 0,
                    already_refuted: list[Attempt] | None = None,
                    publisher: Publisher = nobody) -> Findings:
        """The investigation the node calls, spelled to the shape it calls it
        in - so that what the node hands down is checkable rather than
        whatever a permissive double happened to accept."""
        if remember_publisher is not None:
            remember_publisher(publisher)

        return Findings(candidates=[candidate], can_widen=False, resumes_from=1)

    return investigator_node(
        state,
        investigate=investigate,
        record_hypothesis=lambda dont_care_hypothesis: None,
        publisher=publisher,
    )


def _an_action_is_proposed(flag_changes: Any, publisher: Any) -> dict[str, Any]:
    """One turn of the node that chooses an action, with the provider doubled.

    `flag_changes` is either the history the provider reports or a callable
    that fails like an unreachable one, because "what changed" and "nobody
    could say" are the two answers this node has to tell apart.
    """
    state = an_incident_state(
        _AN_ALERT, IncidentStatus.MITIGATING, incident_id=_SOME_INCIDENT_ID
    )
    state = state.model_copy(update={
        "hypothesis": a_determined_hypothesis(_SOME_INCIDENT_ID, a_high_enough_confidence())
    })
    fetch: Any = flag_changes if callable(flag_changes) else lambda: flag_changes

    return mitigation_proposal_node(state, fetch_flag_changes=fetch, publisher=publisher)


def _an_action_is_taken(candidate: Any,
                        outcome: Outcome,
                        publisher: Any = None) -> dict[str, Any]:
    """One turn of the mitigation node, with the action already gated."""
    state = an_incident_state(
        _AN_ALERT, IncidentStatus.MITIGATING, incident_id=_SOME_INCIDENT_ID
    )
    state = state.model_copy(
        update={"hypothesis": candidate, "proposed_action": _AN_ACTION}
    )
    keywords = {"publisher": publisher} if publisher is not None else {}

    return mitigation_node(
        state,
        take=lambda dont_care_action, **dont_care_keywords: outcome,
        record_action=lambda *dont_care_args, **dont_care_keywords: None,
        record_outcome=lambda *dont_care_args, **dont_care_keywords: None,
        **keywords,
    )


_AN_ALERT = Alert(service="io-shop", alert_name="HighErrorRate")
