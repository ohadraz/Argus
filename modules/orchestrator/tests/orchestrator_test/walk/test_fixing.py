"""Looking for a permanent fix, and reporting what came back.

Code-Fix now proposes a real draft pull request, so what the node carries is an
address rather than a sentence: this is the one step in the walk that ends with
somebody else's turn, and an incident that could not say where to go would have
proposed nothing anybody can find.

Three outcomes, not two. A fix was proposed; no fix was found, which is a real
conclusion and the one every flag scenario reaches; or the proposal could not be
made at all - the repository refused, or was unreachable. The third must not
take the walk down with it: an incident that failed here would never reach the
human it was on its way to, and the investigation behind it would be lost.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent_codefix.proposing import FixNotAnswered
from argus_core.events import FixAttempted, IncidentEvent
from argus_core.models import Alert, FixOutcome, Hypothesis, IncidentStatus, OpenedPullRequest
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.fixing import codefix_node, route_after_codefix
from orchestrator.walk.ports import ProposeFix
from orchestrator.walk.routes import POSTMORTEM_ROUTE
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.builders import a_determined_hypothesis

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"


@pytest.mark.unit
def test_an_agent_with_no_fix_to_offer_is_reported_as_finding_none() -> None:
    # A real conclusion, not a failure. Every flag scenario reaches it: the code
    # is working as written and the fault was in what somebody switched on.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_with_nothing := _an_agent_offering(None)
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_with_nothing)
        ) \
        .then(all_of(
            _the_updates_carry("fix_found", False),
            _the_work_was_narrated()
        ))


@pytest.mark.unit
def test_a_fix_the_agent_proposed_is_reported_as_found() -> None:
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_with_a_fix := _an_agent_offering(a_pull_request())
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_with_a_fix)
        ) \
        .then(all_of(
            _the_updates_carry("fix_found", True),
            _the_work_was_narrated()
        ))


@pytest.mark.unit
def test_what_is_narrated_is_where_the_proposal_can_be_read() -> None:
    # THE POINT OF THE WHOLE STEP. What reaches a human - on the page, in Slack,
    # in the postmortem - is this line, and a line that described the fix
    # without saying where it is would leave everyone hunting for a branch.
    some_url = "https://github.invalid/io-shop/target/pull/41"

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_with_a_fix := _an_agent_offering(a_pull_request(url=some_url))
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_with_a_fix)
        ) \
        .then(
            _the_narration_mentions(some_url)
        )


@pytest.mark.unit
def test_a_proposal_that_could_not_be_made_does_not_fail_the_walk() -> None:
    # An unreachable repository is a bad afternoon, not a lost incident. If this
    # raised, the walk would fail here and the incident would never reach the
    # human it was on its way to - along with everything the investigation
    # learned on the way.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_that_could_not := _an_agent_that_fails(
                RuntimeError("the repository refused the pull request")
            )
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_that_could_not)
        ) \
        .then(all_of(
            _the_updates_carry("fix_found", False),
            _the_work_was_narrated()
        ))


@pytest.mark.unit
def test_a_proposal_that_could_not_be_made_says_so_rather_than_saying_none_was_found() -> None:
    # The two are different things to the person who reads them. "No fix was
    # found" is a verdict on the code; "the fix could not be pushed" is a thing
    # somebody can go and repair, and then ask again.
    some_failure = "the repository refused the pull request"

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_that_could_not := _an_agent_that_fails(RuntimeError(some_failure))
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_that_could_not)
        ) \
        .then(
            _the_narration_mentions(some_failure)
        )


@pytest.mark.unit
def test_what_code_fix_found_is_published_as_an_event_of_its_own() -> None:
    # The node narrates, and on the path that matters nobody writes it down: a
    # mitigated incident is mitigated whether a fix was proposed or not, so the
    # status never changes here and the narration handed up is discarded
    # unwritten. This step would then be the one step in the walk that leaves
    # no account of itself - which is exactly what happened, and it took the
    # checkpoint tables to find out why.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_with_a_fix := _an_agent_offering(the_proposal := a_pull_request())
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_with_a_fix,
                                 publisher=published.append)
        ) \
        .then(_exactly_one_attempt_was_announced(
            FixOutcome.PROPOSED, the_proposal, published
        ))


@pytest.mark.unit
def test_a_fix_that_was_not_warranted_is_published_as_the_finding_it_is() -> None:
    # "I read the code and there is nothing here to change" is a conclusion a
    # human acts on. Published with no pull request, because there is none -
    # and distinguishable from the failure below, because the outcome says so
    # rather than the absence.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_with_nothing := _an_agent_offering(None)
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_with_nothing,
                                 publisher=published.append)
        ) \
        .then(_exactly_one_attempt_was_announced(
            FixOutcome.NOT_WARRANTED, None, published
        ))


@pytest.mark.unit
def test_a_proposal_that_could_not_be_made_is_published_as_a_failure() -> None:
    # The outcome somebody can go and repair, and the one this whole event
    # exists for: a repository that refused reached the timeline looking
    # identical to a model that had read the code and found it clean. What
    # stopped it travels on the event, because the next question is always why.
    published: list[IncidentEvent] = []
    what_stopped_it = "could not create branch: 403 Forbidden"

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_that_could_not := _an_agent_raising(RuntimeError(what_stopped_it))
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_that_could_not,
                                 publisher=published.append)
        ) \
        .then(all_of(
            _exactly_one_attempt_was_announced(
                FixOutcome.NOT_POSSIBLE, None, published
            ),
            _the_attempt_says_why(what_stopped_it, published)
        ))


@pytest.mark.unit
def test_an_agent_that_never_answered_is_not_reported_as_having_found_nothing() -> None:
    # The distinction a live incident cost us. Code-Fix spent every turn it had
    # reading, never submitted, and the incident recorded "no code-level fix
    # found" - which reads as a verdict on the service and was a statement
    # about the budget. One of those is somebody's cue to widen the bound; the
    # other closes the question.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_that_never_answered := _an_agent_raising(
                FixNotAnswered("read for 12 turns without submitting a fix")
            )
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_that_never_answered,
                                 publisher=published.append)
        ) \
        .then(all_of(
            _exactly_one_attempt_was_announced(
                FixOutcome.NOT_ANSWERED, None, published
            ),
            _the_updates_carry("fix_found", False)
        ))


@pytest.mark.unit
def test_a_node_nobody_is_listening_to_still_does_its_work() -> None:
    # Publishing is an account, never a participant (spec §4 principle 6). A
    # node that behaved differently with no subscriber would make every test
    # above a test of a different code path than production runs.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_with_a_fix := _an_agent_offering(a_pull_request())
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_with_a_fix)
        ) \
        .then(_the_updates_carry("fix_found", True))


@pytest.mark.unit
def test_the_agent_is_asked_about_the_hypothesis_the_walk_reached() -> None:
    # The one thing Code-Fix is told, and the only reason it can do anything at
    # all. An incident asked about the wrong thing would answer honestly about
    # something that never happened.
    a_hypothesis = a_determined_hypothesis(DONT_CARE_INCIDENT_ID)

    Scenario() \
        .given(
            an_incident_with_a_hypothesis := _an_incident_in(
                IncidentStatus.FIXING, hypothesis=a_hypothesis
            ),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_with_a_hypothesis, the_agent.propose)
        ) \
        .then(
            _the_agent_was_asked_about(the_agent, a_hypothesis)
        )


@pytest.mark.unit
def test_the_agent_is_told_which_incident_it_is_fixing() -> None:
    # It names the branch after it, so two incidents patching the same file do
    # not write over each other's proposal - and a branch found weeks later says
    # which incident produced it.
    some_incident = "buki-123"

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, the_agent.propose)
        ) \
        .then(
            _the_agent_was_asked_for_incident(the_agent, some_incident)
        )


@pytest.mark.unit
def test_an_incident_with_no_hypothesis_is_still_asked_about() -> None:
    # A walk can reach here having concluded nothing. Code-Fix is asked anyway,
    # about nothing, because "I looked and found nothing" and "I never looked"
    # reach the same human and only one of them would be true.
    Scenario() \
        .given(
            an_incident_that_concluded_nothing := _an_incident_in(IncidentStatus.FIXING),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_that_concluded_nothing, the_agent.propose)
        ) \
        .then(
            _the_agent_was_asked_about(the_agent, None)
        )


@pytest.mark.unit
def test_every_incident_that_reaches_code_fix_goes_on_to_the_postmortem() -> None:
    # One route, because there is one destination. This used to branch on
    # `resolved` versus everything else, and both arms led to the postmortem
    # anyway - a distinction the graph could not act on and nothing set. How the
    # incident ended is the status's to say; where it goes next is not in doubt.
    Scenario() \
        .given(a_mitigated_incident := _an_incident_in(IncidentStatus.MITIGATED)) \
        .when(lambda: route_after_codefix(a_mitigated_incident)) \
        .then(_the_route_is(POSTMORTEM_ROUTE))


@pytest.mark.unit
def test_an_incident_nothing_could_be_done_for_also_goes_to_the_postmortem() -> None:
    # The other road in. An incident that reached Code-Fix having stopped
    # nothing still gets written up - a human reading it afterwards needs the
    # account most, not least.
    Scenario() \
        .given(an_unfixed_incident := _an_incident_in(IncidentStatus.FIXING)) \
        .when(lambda: route_after_codefix(an_unfixed_incident)) \
        .then(_the_route_is(POSTMORTEM_ROUTE))


class _AnAgentRememberingWhatItWasAsked:
    """Code-Fix as a seam, holding on to what it was told.

    A small class rather than `create_autospec`, because the test reads the
    question back afterwards and a named attribute says what is being read more
    plainly than a call record does.
    """

    def __init__(self) -> None:
        self.hypothesis: Hypothesis | None = None
        self.incident_id: str | None = None

    def propose(self,
                hypothesis: Hypothesis | None,
                incident_id: str) -> OpenedPullRequest | None:
        self.hypothesis = hypothesis
        self.incident_id = incident_id

        return None


def _an_agent_offering(proposal: OpenedPullRequest | None) -> ProposeFix:
    """Code-Fix, answering the same thing however it is asked."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str) -> OpenedPullRequest | None:
        return proposal

    return propose


def _an_agent_that_fails(failure: Exception) -> ProposeFix:
    """Code-Fix, unable to propose at all.

    The failure is an arbitrary exception rather than a named type: what opens a
    pull request in production is a tool on another process, so what arrives
    here is whatever the transport raised - and a node catching one specific
    class would let every other way that call fails take the walk down.
    """
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str) -> OpenedPullRequest | None:
        raise failure

    return propose


def a_pull_request(url: str = "https://github.invalid/dont-care/dont-care/pull/1"
                   ) -> OpenedPullRequest:
    return OpenedPullRequest(number=1, url=url, branch="argus/fix-buki-123")


def _an_incident_in(status: IncidentStatus,
                    hypothesis: Hypothesis | None = None) -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=status,
                         hypothesis=hypothesis)


def _the_agent_was_asked_about(
    agent: _AnAgentRememberingWhatItWasAsked, hypothesis: Hypothesis | None
) -> Assertion[StateDelta]:
    def assertion(_updates: StateDelta) -> bool:
        if agent.hypothesis != hypothesis:
            raise AssertionError(
                f"Expected Code-Fix to be asked about [{hypothesis}], "
                f"it was asked about [{agent.hypothesis}]."
            )

        return True

    return assertion


def _the_agent_was_asked_for_incident(
    agent: _AnAgentRememberingWhatItWasAsked, incident_id: str
) -> Assertion[StateDelta]:
    def assertion(_updates: StateDelta) -> bool:
        if agent.incident_id != incident_id:
            raise AssertionError(
                f"Expected Code-Fix to be told incident [{incident_id}], "
                f"it was told [{agent.incident_id}]."
            )

        return True

    return assertion


def _the_updates_carry(field: str, expected: Any) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if field not in updates.model_fields_set:
            raise AssertionError(
                f"Expected the updates to carry [{field}], they carry "
                f"{sorted(updates.model_fields_set)}."
            )

        if getattr(updates, field) != expected:
            raise AssertionError(
                f"Expected [{field}] to be [{expected}], it was "
                f"[{getattr(updates, field)}]."
            )

        return True

    return assertion


def _the_work_was_narrated() -> Assertion[StateDelta]:
    """Something was said, not what. A node that moves the incident and says
    nothing raises in `with_status`, and the words themselves are not a promise
    to anybody."""
    def assertion(updates: StateDelta) -> bool:
        if not isinstance(updates.narration, Narration):
            raise AssertionError(
                f"Expected the node to narrate what it did, it returned "
                f"{updates.narration!r}."
            )

        return True

    return assertion


def _the_narration_mentions(said: str) -> Assertion[StateDelta]:
    """What the narration says, where saying it is the node's whole output.

    The exception to `_the_work_was_narrated` above: an address and a failure
    are both things a human acts on, so here the words are a promise.
    """
    def assertion(updates: StateDelta) -> bool:
        narration = updates.narration

        if not isinstance(narration, Narration):
            raise AssertionError(
                f"Expected the node to narrate, it returned {narration!r}."
            )

        if said not in f"{narration.action} {narration.detail}":
            raise AssertionError(
                f"Expected the narration to mention [{said!r}], it said "
                f"[{narration.action!r} / {narration.detail!r}]."
            )

        return True

    return assertion


def _the_route_is(expected: str) -> Assertion[str]:
    def assertion(route: str) -> bool:
        if route != expected:
            raise AssertionError(f"Expected the route [{expected}], got [{route}].")

        return True

    return assertion


def _an_agent_raising(error: Exception) -> ProposeFix:
    """A repository that refused, said as the agent raising what it raised."""
    def refuse(dont_care_hypothesis: Hypothesis | None, dont_care_incident_id: str) -> Any:
        raise error

    return refuse


def _exactly_one_attempt_was_announced(
    outcome: FixOutcome,
    proposal: OpenedPullRequest | None,
    published: list[IncidentEvent]
) -> Assertion[StateDelta]:
    """One account of the step, saying which of the three things happened."""
    def assertion(dont_care_result: StateDelta) -> bool:
        attempts = [
            event for event in published if isinstance(event, FixAttempted)
        ]
        if len(attempts) != 1:
            raise AssertionError(
                f"Expected one fix attempt announced, got {len(attempts)}."
            )

        announced = attempts[0]
        if (announced.outcome, announced.pull_request) != (outcome, proposal):
            raise AssertionError(
                f"Expected [{outcome}] carrying [{proposal}], got "
                f"[{announced.outcome}] carrying [{announced.pull_request}]."
            )

        return True

    return assertion


def _the_attempt_says_why(reason: str,
                          published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """The failure's own words, because the next question is always why."""
    def assertion(dont_care_result: StateDelta) -> bool:
        said = [
            event.detail for event in published if isinstance(event, FixAttempted)
        ]
        if not any(reason in detail for detail in said):
            raise AssertionError(
                f"Expected an attempt mentioning [{reason}], got {said}."
            )

        return True

    return assertion
