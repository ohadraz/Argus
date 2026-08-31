from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import agent_communicator
import agent_investigator
import pytest
from argus_core.config import get_settings
from argus_core.models.action import Action
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus, status_after
from orchestrator import graph
from orchestrator.graph import (
    communicator_node,
    investigator_node,
    next_candidate_node,
    recursion_limit,
    route_after_next_candidate,
)

from ..framework.builders import (
    a_below_threshold_confidence,
    a_determined_hypothesis,
    a_high_enough_confidence,
    a_random_id,
    an_undetermined_hypothesis,
)

"""Walking the candidates an investigation offered, one at a time.

Being wrong about a correlated change is the ordinary case in an incident, not
the exceptional one, so a refuted mitigation is not the end of what Argus can
do - it is the end of what Argus can do *about that candidate*. These cover the
decision made after each attempt: try the next explanation, buy a wider look,
or admit there are no moves left.

One node owns that decision. Both ways an attempt can fail to settle anything -
the gate refusing it, and the service refusing to recover - arrive at the same
place, because "what now" has one answer and splitting it across two nodes
would be two chances to get it wrong.

The node reports what it found and never a status. Where that leaves the
incident is derived from the state it produced, which is what `_the_route_taken`
does here and what the graph does in production.

A longer walk is a longer silence before a human hears anything, which is what
the war-room update is for: each attempt is posted as it happens, and the page
is kept for the moment autonomy is actually spent.
"""

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"


@pytest.fixture
def investigate() -> MagicMock:
    return cast(MagicMock, create_autospec(agent_investigator.investigate))


@pytest.fixture
def record_hypothesis() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.RecordHypothesis, instance=True))


@pytest.fixture
def post_update() -> MagicMock:
    return cast(MagicMock, create_autospec(agent_communicator.post_update))


@pytest.fixture
def raise_page() -> MagicMock:
    return cast(MagicMock, create_autospec(agent_communicator.raise_page))


@pytest.mark.unit
def test_every_candidate_the_investigation_offered_is_recorded(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # The incident's record should say what was considered, not only what was
    # acted on. A runner-up that never reached the table is a finding a human
    # picking the incident up cannot see Argus ever having had.
    incident_id = a_random_id()
    the_best_answer = a_determined_hypothesis(incident_id, a_high_enough_confidence())
    a_runner_up = a_determined_hypothesis(incident_id, a_below_threshold_confidence())
    investigate.return_value = _findings_of(the_best_answer, a_runner_up)

    investigator_node(
        _an_incident_being_investigated(incident_id),
        investigate=investigate,
        record_hypothesis=record_hypothesis,
    )

    assert record_hypothesis.call_count == 2


@pytest.mark.unit
def test_the_investigation_hands_the_walk_its_candidates(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    incident_id = a_random_id()
    the_best_answer = a_determined_hypothesis(incident_id, a_high_enough_confidence())
    a_runner_up = a_determined_hypothesis(incident_id, a_high_enough_confidence())
    investigate.return_value = _findings_of(the_best_answer, a_runner_up)

    updates = investigator_node(
        _an_incident_being_investigated(incident_id),
        investigate=investigate,
        record_hypothesis=record_hypothesis,
    )

    assert updates["candidates"] == [the_best_answer, a_runner_up]
    assert updates["candidate_index"] == 0
    assert updates["hypothesis"] == the_best_answer


@pytest.mark.unit
def test_a_resumed_investigation_is_told_where_to_pick_up_and_what_failed(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # Both halves of what makes a second round worth paying for. Without the
    # resume point it re-reads the window that has already been read; without
    # the attempts it re-answers the question that has already been answered.
    incident_id = a_random_id()
    investigate.return_value = _findings_of(
        a_determined_hypothesis(incident_id, a_high_enough_confidence())
    )
    a_refuted_attempt = _an_attempt_on(SOME_FLAG)
    a_second_round = _an_incident_being_investigated(incident_id).model_copy(
        update={"resume_from": 1, "attempts": [a_refuted_attempt]}
    )

    investigator_node(
        a_second_round,
        investigate=investigate,
        record_hypothesis=record_hypothesis,
    )

    assert investigate.call_args.kwargs["resume_from"] == 1
    assert investigate.call_args.kwargs["already_refuted"] == [a_refuted_attempt]


@pytest.mark.unit
def test_a_refuted_candidate_hands_over_to_the_next_one(post_update: MagicMock) -> None:
    incident_id = a_random_id()
    the_refuted_candidate = a_determined_hypothesis(
        incident_id, a_high_enough_confidence()
    )
    the_next_candidate = a_determined_hypothesis(incident_id, a_high_enough_confidence())
    a_walk = _a_walk_at(incident_id, [the_refuted_candidate, the_next_candidate], index=0)

    updates = next_candidate_node(a_walk, post_update=post_update)

    assert updates["candidate_index"] == 1
    assert updates["hypothesis"] == the_next_candidate
    assert _the_route_taken(a_walk, updates) == "mitigating"


@pytest.mark.unit
def test_what_was_tried_is_remembered_for_the_round_after(post_update: MagicMock) -> None:
    # A later investigation is only worth running because it can be told this.
    # Recorded here rather than in the investigator node, so the fact stays
    # attached to the attempt that produced it.
    incident_id = a_random_id()
    a_candidate = a_determined_hypothesis(incident_id, a_high_enough_confidence())

    updates = next_candidate_node(
        _a_walk_at(incident_id, [a_candidate], index=0, acted_on=SOME_FLAG),
        post_update=post_update,
    )

    assert [attempt.subject for attempt in updates["attempts"]] == [SOME_FLAG]


@pytest.mark.unit
def test_a_walk_with_a_candidate_left_carries_on(post_update: MagicMock) -> None:
    incident_id = a_random_id()
    candidates = [
        a_determined_hypothesis(incident_id, a_high_enough_confidence()),
        a_determined_hypothesis(incident_id, a_high_enough_confidence()),
    ]
    a_walk = _a_walk_at(incident_id, candidates, index=0)

    updates = next_candidate_node(a_walk, post_update=post_update)

    assert _the_route_taken(a_walk, updates) == "mitigating"


@pytest.mark.unit
def test_a_spent_list_buys_another_investigation(post_update: MagicMock) -> None:
    # Every explanation this round offered has been tried and failed, which is
    # the moment another round is worth paying for - and what pays for it is the
    # refutation rather than a wider window. Argus changed production and the
    # service did not answer; no amount of re-reading produces that fact, and
    # the model has never seen it. The state here has no widening budget left at
    # all, which is the ordinary shape of a hard incident by the time its first
    # answer comes back refuted.
    incident_id = a_random_id()
    the_only_candidate = a_determined_hypothesis(incident_id, a_high_enough_confidence())
    a_walk = _a_walk_at(incident_id, [the_only_candidate], index=0, rounds=1)

    updates = next_candidate_node(a_walk, post_update=post_update)

    assert _the_route_taken(a_walk, updates) == "investigating"


@pytest.mark.unit
def test_a_walk_that_has_used_every_round_ends(post_update: MagicMock) -> None:
    # The bound is a count of rounds rather than the walk's own judgement: each
    # round is a model call and another set of real changes to production, and
    # "keep going until something works" is not a stopping condition.
    #
    # It ends in `fixing`, not `escalated`: nothing reversible is left and what
    # remains is a permanent fix, which is what Code-Fix is for. `escalated`
    # comes later, once Code-Fix has nothing either.
    incident_id = a_random_id()
    the_only_candidate = a_determined_hypothesis(incident_id, a_high_enough_confidence())
    every_round_spent = get_settings().investigation_max_rounds
    a_walk = _a_walk_at(
        incident_id, [the_only_candidate], index=0, rounds=every_round_spent
    )

    updates = next_candidate_node(a_walk, post_update=post_update)

    assert _the_route_taken(a_walk, updates) == "fixing"


@pytest.mark.unit
def test_a_doubtful_candidate_is_tried_like_any_other(post_update: MagicMock) -> None:
    # Confidence orders the list; it does not decide who gets on it. By the time
    # the walk reaches a doubtful candidate, every explanation the model
    # believed more has been tried and refuted - so the ranking that made this
    # one doubtful has already been proved wrong about the ones above it, and
    # the cost of finding out is one reversible change and two minutes.
    incident_id = a_random_id()
    the_refuted_candidate = a_determined_hypothesis(incident_id, a_high_enough_confidence())
    a_doubtful_candidate = a_determined_hypothesis(
        incident_id, a_below_threshold_confidence()
    )
    a_walk = _a_walk_at(
        incident_id, [the_refuted_candidate, a_doubtful_candidate], index=0
    )

    updates = next_candidate_node(a_walk, post_update=post_update)

    assert _the_route_taken(a_walk, updates) == "mitigating"
    assert updates["hypothesis"] == a_doubtful_candidate


@pytest.mark.unit
def test_a_candidate_blaming_a_flag_already_tried_is_skipped(
    post_update: MagicMock
) -> None:
    # The same subject, twice on one list. Changing it again would be running
    # the experiment that has already been run and undone, against a world that
    # answered once - so the walk passes over it and reaches the first
    # explanation that is actually new.
    incident_id = a_random_id()
    the_refuted_candidate = _a_candidate_blaming(incident_id, SOME_FLAG)
    the_same_flag_again = _a_candidate_blaming(incident_id, SOME_FLAG)
    a_candidate_blaming_something_else = _a_candidate_blaming(incident_id, ANOTHER_FLAG)

    updates = next_candidate_node(
        _a_walk_at(
            incident_id,
            [the_refuted_candidate, the_same_flag_again, a_candidate_blaming_something_else],
            index=0,
            acted_on=SOME_FLAG,
        ),
        post_update=post_update,
    )

    assert updates["hypothesis"] == a_candidate_blaming_something_else
    assert updates["candidate_index"] == 2


@pytest.mark.unit
def test_a_later_round_does_not_act_on_an_explanation_already_refuted(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # A second investigation is told what was tried, and is free to conclude the
    # same thing anyway - being told does not oblige it to change its mind. What
    # it must not do is send the walk back to change the same flag a second
    # time, which would spend the round budget flipping one flag back and forth.
    #
    # The round reports that it found nothing worth trying, which is what ends
    # the incident. It is a fact about the investigation, not a status: the walk
    # leaves an identical candidate list behind when it runs out, and those two
    # do not end the same way.
    incident_id = a_random_id()
    the_same_explanation_again = _a_candidate_blaming(incident_id, SOME_FLAG)
    investigate.return_value = _findings_of(the_same_explanation_again)
    a_round_after_that_flag_was_tried = _an_incident_being_investigated(
        incident_id
    ).model_copy(update={"attempts": [_an_attempt_on(SOME_FLAG)]})

    updates = investigator_node(
        a_round_after_that_flag_was_tried,
        investigate=investigate,
        record_hypothesis=record_hypothesis,
    )

    assert updates["nothing_worth_trying"] is True


@pytest.mark.unit
def test_a_candidate_naming_no_cause_is_never_tried(post_update: MagicMock) -> None:
    # The one thing on the list that is not an experiment. "I found no cause"
    # names nothing to change, which is a different answer from "I am unsure
    # which of these it is" - and acting on it would mean changing production
    # with no hypothesis behind the change at all.
    incident_id = a_random_id()
    the_refuted_candidate = a_determined_hypothesis(incident_id, a_high_enough_confidence())
    a_candidate_naming_nothing = an_undetermined_hypothesis(incident_id)
    a_walk = _a_walk_at(
        incident_id,
        [the_refuted_candidate, a_candidate_naming_nothing],
        index=0,
        rounds=get_settings().investigation_max_rounds,
    )

    updates = next_candidate_node(a_walk, post_update=post_update)

    assert _the_route_taken(a_walk, updates) == "fixing"
    assert "hypothesis" not in updates


@pytest.mark.unit
def test_an_attempt_that_settled_nothing_is_posted_while_moves_remain(
    post_update: MagicMock
) -> None:
    # The war room is how a longer walk stays watchable. Without it a human
    # sees silence from the first attempt until the last, and an incident being
    # worked looks exactly like an incident nobody is on.
    incident_id = a_random_id()
    candidates = [
        a_determined_hypothesis(incident_id, a_high_enough_confidence()),
        a_determined_hypothesis(incident_id, a_high_enough_confidence()),
    ]

    next_candidate_node(
        _a_walk_at(incident_id, candidates, index=0), post_update=post_update
    )

    assert post_update.call_count == 1


@pytest.mark.unit
def test_an_update_names_what_was_tried(post_update: MagicMock) -> None:
    # "An attempt failed" is not something a watching human can act on. What
    # was changed is - it is the fact that tells them whether to step in.
    incident_id = a_random_id()
    candidates = [
        a_determined_hypothesis(incident_id, a_high_enough_confidence()),
        a_determined_hypothesis(incident_id, a_high_enough_confidence()),
    ]

    next_candidate_node(
        _a_walk_at(incident_id, candidates, index=0, acted_on=SOME_FLAG),
        post_update=post_update,
    )

    assert SOME_FLAG in post_update.call_args.args[1]


@pytest.mark.unit
def test_another_round_is_posted_too(post_update: MagicMock) -> None:
    # Buying another investigation is a move, not an ending - and the most
    # confusing moment to leave unannounced, because Argus goes quiet while it
    # thinks.
    incident_id = a_random_id()
    the_only_candidate = a_determined_hypothesis(incident_id, a_high_enough_confidence())

    next_candidate_node(
        _a_walk_at(incident_id, [the_only_candidate], index=0, rounds=1),
        post_update=post_update,
    )

    assert post_update.call_count == 1


@pytest.mark.unit
def test_a_walk_out_of_moves_posts_no_update(post_update: MagicMock) -> None:
    # The end of the walk is the page's to announce, and the page is the one
    # message that must not arrive in a crowd.
    incident_id = a_random_id()
    the_only_candidate = a_determined_hypothesis(incident_id, a_high_enough_confidence())

    next_candidate_node(
        _a_walk_at(
            incident_id,
            [the_only_candidate],
            index=0,
            rounds=get_settings().investigation_max_rounds,
        ),
        post_update=post_update,
    )

    assert post_update.call_count == 0


@pytest.mark.unit
def test_the_end_of_the_walk_raises_exactly_one_page(raise_page: MagicMock) -> None:
    # One page per incident, however many candidates were tried on the way.
    # A page per refuted attempt would teach its readers to ignore pages, which
    # costs more than the pages themselves are worth.
    incident_id = a_random_id()
    a_walk_with_nothing_left = _a_walk_at(
        incident_id,
        [a_determined_hypothesis(incident_id, a_high_enough_confidence())],
        index=0,
    ).model_copy(update={"status": IncidentStatus.ESCALATED})

    communicator_node(a_walk_with_nothing_left, raise_page=raise_page)

    assert raise_page.call_count == 1
    assert raise_page.call_args.args[0] == incident_id


@pytest.mark.unit
def test_the_shortest_possible_walk_costs_what_the_graph_says_it_costs() -> None:
    # Countable by hand off the graph, which is the point of asserting it: one
    # investigation, then the four nodes of a single attempt - proposal, gate,
    # mitigation, next_candidate - then the three that end an incident nobody
    # could fix: codefix, communicator, postmortem.
    assert recursion_limit(max_rounds=1, max_candidates=1) == 8


@pytest.mark.unit
def test_every_extra_candidate_buys_a_whole_attempt() -> None:
    # The loop's traversal budget has to grow with the list, or a verdict with
    # one more explanation than usual ends the incident on a recursion error
    # with production already changed and no postmortem written.
    a_walk_of_one = recursion_limit(max_rounds=1, max_candidates=1)
    a_walk_of_two = recursion_limit(max_rounds=1, max_candidates=2)

    assert a_walk_of_two - a_walk_of_one == 4


@pytest.mark.unit
def test_every_extra_round_pays_for_its_investigation_and_its_candidates() -> None:
    # A wider round is one more investigation plus a full list to walk again.
    some_candidates = 3
    one_round = recursion_limit(max_rounds=1, max_candidates=some_candidates)
    two_rounds = recursion_limit(max_rounds=2, max_candidates=some_candidates)

    assert two_rounds - one_round == 1 + 4 * some_candidates


def _findings_of(*candidates: Hypothesis) -> agent_investigator.Findings:
    return agent_investigator.Findings(
        candidates=list(candidates), can_widen=False, resumes_from=1
    )


def _an_incident_being_investigated(incident_id: str) -> IncidentState:
    return IncidentState(
        incident_id=incident_id,
        alert=an_alert(),
        status=IncidentStatus.INVESTIGATING,
    )


def _a_walk_at(
    incident_id: str,
    candidates: list[Hypothesis],
    index: int,
    acted_on: str = SOME_FLAG,
    rounds: int = 1,
) -> IncidentState:
    """An incident mid-walk: a candidate has just been tried and did not settle
    anything, and the state carries what it takes to decide what happens next.

    `can_widen` is deliberately left false throughout this file. The walk is
    bounded by how many times the incident may be investigated, not by how much
    log window is left unread - a hard incident has usually spent its whole
    widening schedule reaching the answer that just got refuted, and that is
    exactly when another round is worth buying.
    """
    return IncidentState(
        incident_id=incident_id,
        alert=an_alert(),
        status=IncidentStatus.MITIGATING,
        candidates=candidates,
        candidate_index=index,
        hypothesis=candidates[index],
        can_widen=False,
        rounds=rounds,
        proposed_action=Action(
            action_type="revert_feature_flag",
            flag=acted_on,
            enabled=False,
            undo_descriptor={
                "tool": "set_feature_flag",
                "flag": acted_on,
                "was_enabled": True,
            },
        ),
    )


def _the_route_taken(state: IncidentState, updates: dict[str, Any]) -> str:
    """The route the graph takes on the state this node produced.

    The status is derived rather than read off the updates, because the node no
    longer supplies one - so this asserts where the node's work actually leaves
    the incident, by exactly the path the graph takes. `narration` is dropped on
    the way, as the graph drops it: it is what the node said, not part of the
    state.
    """
    work = {key: value for key, value in updates.items() if key != "narration"}
    after = state.model_copy(update=work)

    return route_after_next_candidate(
        after.model_copy(
            update={
                "status": status_after(after, get_settings().investigation_max_rounds)
            }
        )
    )


def an_alert() -> Alert:
    return Alert(service="kuki", alert_name="HighErrorRate")


def _a_candidate_blaming(incident_id: str, flag: str) -> Hypothesis:
    """An explanation that names the flag it blames.

    Built here rather than through the shared builder because the subject is
    the whole point of these cases: what the walk refuses to try twice is a
    *subject*, not a hypothesis object, and two candidates blaming the same flag
    are different findings about the same thing.
    """
    return Hypothesis(
        incident_id=incident_id,
        summary="kukibuki hypothesis",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=a_high_enough_confidence(),
        supporting_evidence=["some log line"],
        subject=flag,
    )


def _an_attempt_on(subject: str) -> Attempt:
    return Attempt(subject=subject, enabled=False, occurred_at="2026-08-29T16:00:00Z")
