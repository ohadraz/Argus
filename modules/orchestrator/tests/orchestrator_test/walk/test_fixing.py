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

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from agent_codefix.proposing import FixDeclined, FixNotAnswered, FixNotProposed, FixStopped
from argus_core import RunLost
from argus_core.budget import StillWanted, wanted_throughout
from argus_core.events import FixAttempted, IncidentEvent
from argus_core.models import (
    Alert,
    ChangeEvent,
    ChangeKind,
    CodeUse,
    FileAsItRan,
    FixOutcome,
    Hypothesis,
    IncidentStatus,
    Leads,
    OpenedPullRequest,
    ProposedFix,
    ThreadMessage,
    no_leads,
)
from argus_incidents import IsStillWanted
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.fixing import codefix_node, route_after_codefix
from orchestrator.walk.ports import LeadsOf, ProposeFix
from orchestrator.walk.routes import POSTMORTEM_ROUTE
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.assertions import (
    the_result_is,
    the_route_is,
    the_updates_carry,
)
from orchestrator_test.framework.builders import a_determined_hypothesis, a_lead

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"

THE_ALERT_FIRED_AT = datetime(2026, 9, 27, 9, 20, tzinfo=UTC)
AN_EARLIER_REVISION = "65279ee05d2cfae49802712847428bc55e794bb3"
THE_REVISION_THAT_RAN = "383534e9bb182bb778e01fd22ba63f88885362e3"
A_LATER_REVISION = "4c810f22894e612ced87f5ee3f3062dfeb785050"


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
            the_updates_carry("fix_found", False),
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
            the_updates_carry("fix_found", True),
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
            the_updates_carry("fix_found", False),
            _the_work_was_narrated()
        ))


@pytest.mark.unit
def test_a_proposal_stopped_because_the_run_was_lost_is_not_said_as_a_failed_fix() -> None:
    # Not a bad afternoon either: the run is another claim's, and whatever this
    # walk said of the fix would be said for an incident somebody else is
    # walking. The worker is the one that answers it, by writing nothing more.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_told_the_run_was_lost := _an_agent_that_fails(
                RunLost("a newer claim holds this run")
            )
        ) \
        .when(attempting(
            lambda: codefix_node(an_incident_being_fixed, an_agent_told_the_run_was_lost)
        )) \
        .then(
            an_error_was_raised(RunLost)
        )


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
@pytest.mark.parametrize("proposed", [True, False], ids=["proposed", "not-warranted"])
def test_what_code_fix_said_of_the_code_is_published_with_what_came_of_it(
        proposed: bool) -> None:
    # Its account of the code - why this change, or why no change - is the one
    # thing the walk learns of the mechanism, and a write-up never told it
    # hedges a cause Code-Fix read off the source.
    published: list[IncidentEvent] = []
    the_explanation = "v2's vocabulary is lowercase, and the categoriser does not lowercase"

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent := _an_agent_offering(a_pull_request() if proposed else None,
                                           explaining=the_explanation)
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent,
                                 publisher=published.append)
        ) \
        .then(
            _the_attempt_explains(the_explanation, published)
        )


@pytest.mark.unit
@pytest.mark.parametrize("holds_what_ran", [True, False, None],
                         ids=["holds-it", "does-not", "not-established"])
def test_the_attempt_keeps_which_branch_code_fix_read_and_whether_it_holds_what_ran(
        holds_what_ran: bool | None) -> None:
    # The write-up reads the attempt, not the agent. A fix written against a
    # branch that does not hold what ran changes nothing that runs once merged -
    # not until a deploy carries it - and only Code-Fix's opening ever knew.
    published: list[IncidentEvent] = []
    some_branch = "main"

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent := _an_agent_that_read(some_branch, holds_what_ran)
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent,
                                 publisher=published.append)
        ) \
        .then(
            _the_attempt_says_it_read(some_branch, holds_what_ran, published)
        )


@pytest.mark.unit
def test_the_attempt_keeps_the_files_code_fix_s_reading_names_as_they_ran() -> None:
    # The write-up reads the attempt: what ran is what settles a reading made
    # on a branch that is other text.
    published: list[IncidentEvent] = []
    some_file = FileAsItRan(path="deploy/scrape.yaml", revision=THE_REVISION_THAT_RAN,
                            as_read=False, content="selector:\n  port: metrics\n")

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent := _an_agent_finding([some_file])
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent,
                                 publisher=published.append)
        ) \
        .then(
            _the_attempt_found_as_they_ran([some_file], published)
        )


@pytest.mark.unit
def test_the_attempt_keeps_how_the_code_outside_the_patch_uses_what_it_changes() -> None:
    # The write-up reads the attempt: what the code outside the patch does with
    # what it changes is said there by the code, which a survey of readers in
    # Code-Fix's words was not.
    published: list[IncidentEvent] = []
    some_use = CodeUse(name="total_this_month_cents", path="src/io_shop/spend_reconciliation.py",
                       line=109, function="reconcile_monthly_totals",
                       does="compares it with _bought_this_month(account)")

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent := _an_agent_finding_the_uses([some_use])
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent,
                                 publisher=published.append)
        ) \
        .then(
            _the_attempt_found_the_uses_outside([some_use], published)
        )


@pytest.mark.unit
def test_a_fix_that_needs_code_outside_is_published_as_written_and_not_opened() -> None:
    # Neither a proposal nor "nothing to change": the model wrote a fix and
    # said it helps nobody until code outside the repository changes too. A
    # reader told "no fix found" would close the question the fix answers.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_holding_back := _an_agent_holding_back()
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_holding_back,
                                 publisher=published.append)
        ) \
        .then(all_of(
            _exactly_one_attempt_was_announced(FixOutcome.NOT_OPENED, None, published),
            the_updates_carry("fix_found", False)
        ))


@pytest.mark.unit
def test_a_fix_that_needs_code_outside_publishes_what_would_have_to_change_there() -> None:
    # What the postmortem reads of the code, and what the person taking it to
    # whoever owns that code needs.
    published: list[IncidentEvent] = []
    what_has_to_change_outside = "the cache writer has to write under the new key too"

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_holding_back := _an_agent_holding_back(
                explaining=what_has_to_change_outside
            )
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_holding_back,
                                 publisher=published.append)
        ) \
        .then(
            _the_attempt_explains(what_has_to_change_outside, published)
        )


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
@pytest.mark.parametrize("left_on", ["argus/fix-abc", None], ids=["a-branch", "no-branch"])
def test_a_proposal_that_could_not_be_made_keeps_the_fix_code_fix_wrote(
        left_on: str | None) -> None:
    # GitHub answered 500 to a pull request, and the reading of the code that
    # came with the fix went nowhere: the write-up had no account of the
    # mechanism, and its action items lost the fix to review. The reading is a
    # finding whether or not the proposal could be opened - and the fix itself
    # is still on the branch it was written to, where that write landed.
    published: list[IncidentEvent] = []
    some_reading = "spend_summary divides by the month's purchase count, 0 for a new shopper"
    what_stopped_it = "could not open a pull request: GitHub answered 500 Internal Server Error"

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_that_could_not := _an_agent_raising(FixNotProposed(
                what_stopped_it,
                reading=ProposedFix(pull_request=None, explanation=some_reading),
                branch=left_on
            ))
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
            _the_attempt_says_why(what_stopped_it, published),
            _the_attempt_explains(some_reading, published),
            _the_attempt_left_a_fix_unproposed_on(left_on, published)
        ))


@pytest.mark.unit
def test_a_failure_with_nothing_to_say_is_still_named_by_its_type() -> None:
    # An exception carrying no message reached the timeline as "the fix could
    # not be proposed: " - a sentence that stops at its own colon. A recording
    # run of eleven real incidents came back with no fix in any of them and
    # this as the whole account of why, so the failure had to be re-derived
    # from the shape of what was missing. A type is never empty, and naming it
    # costs nothing on the failures that do carry words.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_that_failed_without_a_word := _an_agent_raising(TimeoutError())
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_that_failed_without_a_word,
                                 publisher=published.append)
        ) \
        .then(all_of(
            _exactly_one_attempt_was_announced(
                FixOutcome.NOT_POSSIBLE, None, published
            ),
            _the_attempt_says_why("TimeoutError", published)
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
            the_updates_carry("fix_found", False)
        ))


@pytest.mark.unit
def test_a_model_that_declined_is_not_reported_as_a_repository_that_refused() -> None:
    # Three different afternoons reached the same sentence. "Could not
    # propose a fix" is what a reader sees when GitHub is down, when the
    # branch could not be pushed - and, until now, when the model simply
    # said no. The first two send somebody to go and repair something; the
    # third has nothing to repair and no wider budget that would help,
    # because the same question over the same code is declined again.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            a_model_that_declined := _an_agent_raising(
                FixDeclined("the model declined to write a fix")
            )
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 a_model_that_declined,
                                 publisher=published.append)
        ) \
        .then(all_of(
            _exactly_one_attempt_was_announced(
                FixOutcome.DECLINED, None, published
            ),
            the_updates_carry("fix_found", False)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("error", "reason"), [
    (RuntimeError("could not create branch: 403 Forbidden"),
     "could not create branch: 403 Forbidden"),
    (FixNotAnswered("read for 12 turns without submitting a fix"),
     "read for 12 turns without submitting a fix"),
    (FixDeclined("the model declined to write a fix"), "")
], ids=["not-possible", "not-answered", "declined"])
def test_a_fix_that_failed_says_why_once_on_its_own_line(error: Exception,
                                                         reason: str) -> None:
    # The attempt's own line opens by saying what happened - "Could not propose
    # a fix" - so the attempt carries the reason alone. Handed the move's words
    # as well, it read "Could not propose a fix - the fix could not be proposed:
    # ...", saying the one thing twice. A refusal has no reason to carry: the
    # sentence that the model declined is all there is.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_that_failed := _an_agent_raising(error)
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_that_failed,
                                 publisher=published.append)
        ) \
        .then(
            _the_attempt_says_only(reason, published)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("error", "the_move_says"), [
    (RuntimeError("could not create branch: 403 Forbidden"),
     "the fix could not be proposed: could not create branch: 403 Forbidden"),
    (FixNotAnswered("read for 12 turns without submitting a fix"),
     "the agent did not finish looking: read for 12 turns without submitting a fix"),
    (FixDeclined("the model declined to write a fix"), "the model declined to write one")
], ids=["not-possible", "not-answered", "declined"])
def test_the_move_after_a_failed_fix_says_what_failed_and_why(error: Exception,
                                                              the_move_says: str) -> None:
    # The move's line has no sentence of its own about the fix - "Moved the
    # incident to ESCALATED" - so it carries both: what failed, and why, where
    # there is a why.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_that_failed := _an_agent_raising(error)
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_that_failed)
        ) \
        .then(
            _the_move_says(the_move_says)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("holds_back", "the_move_says"), [
    (False, "no code-level fix found"),
    (True, "the fix Code-Fix wrote helps only once code outside the repository changes as well")
], ids=["not-warranted", "not-opened"])
def test_the_move_after_a_fix_left_unopened_says_why_and_not_that_a_person_has_it(
        holds_back: bool, the_move_says: str) -> None:
    # The move is the hand-over, and wherever it is read - its own line, the
    # postmortem's "Ended by" after "escalated to a person" - that is said
    # already. The reason says only why, in words that stand without the
    # attempt's own line before them.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent := _an_agent_holding_back() if holds_back else _an_agent_offering(None)
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent)
        ) \
        .then(
            _the_move_says(the_move_says)
        )


@pytest.mark.unit
def test_a_fix_stopped_because_nobody_wants_it_any_more_says_nothing() -> None:
    # Not an attempt that ended in any of its outcomes - somebody said stop.
    # Announcing one would put a line on the timeline about a fix nobody asked
    # to have finished, and `fix_found` would route an incident nobody wants
    # onwards. The node hands back nothing and the walk's own check routes out.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_that_was_stopped := _an_agent_raising(
                FixStopped("the incident is no longer wanted")
            )
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 an_agent_that_was_stopped,
                                 publisher=published.append)
        ) \
        .then(all_of(
            the_result_is(StateDelta()),
            _no_attempt_was_announced(published)
        ))


@pytest.mark.unit
def test_the_agent_asks_whether_this_incident_is_still_wanted() -> None:
    # The agent asks without knowing which incident it is fixing, so the node
    # binds it: a question handed down about any other incident would stop the
    # wrong walk, or none.
    asked: list[str] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 the_agent.propose,
                                 still_wanted=_a_question_recording_who_it_asks_about(asked))
        ) \
        .then(
            _the_question_handed_down_asks_about(the_agent, asked, DONT_CARE_INCIDENT_ID)
        )


@pytest.mark.unit
def test_the_agent_is_handed_what_people_told_this_incident() -> None:
    # Handed as a question rather than an answer, because a person can write
    # while the fix is worked out - and bound here, because the agent asks it
    # without knowing which incident it is fixing.
    some_leads = [a_lead("the kuki flag was flipped at noon")]
    asked: list[str] = []

    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed,
                                 the_agent.propose,
                                 leads_of=_a_thread_noting_who_it_is_asked_about(
                                     asked, some_leads))
        ) \
        .then(
            _the_leads_handed_down_are(some_leads, the_agent, asked, DONT_CARE_INCIDENT_ID)
        )


@pytest.mark.unit
def test_a_node_nobody_is_listening_to_still_does_its_work() -> None:
    # Publishing is an account, never a participant (spec §4 principle 8). A
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
        .then(the_updates_carry("fix_found", True))


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
def test_the_agent_is_told_the_revision_running_when_the_alert_fired() -> None:
    # Code-Fix reads one branch, and is told when that branch does not hold
    # what ran. What ran is the newest deploy the alert came after - not one
    # made since, which a rollback or anybody else may have put out, and not
    # the newest before the onset: a deploy that stopped a series' rows lands
    # after its last row, and is still the one that ran.
    Scenario() \
        .given(
            an_incident_after_three_deploys := _an_incident_in(
                IncidentStatus.FIXING,
                alert=Alert(service="kuki", alert_name="HighErrorRate",
                            started_at=THE_ALERT_FIRED_AT),
                deployments=[
                    _a_deploy(AN_EARLIER_REVISION, "2026-09-27T09:00:00Z"),
                    _a_deploy(THE_REVISION_THAT_RAN, "2026-09-27T09:14:00Z"),
                    _a_deploy(A_LATER_REVISION, "2026-09-27T09:30:00Z")
                ]
            ),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_after_three_deploys, the_agent.propose)
        ) \
        .then(
            _the_agent_was_told_what_ran(the_agent, THE_REVISION_THAT_RAN)
        )


@pytest.mark.unit
def test_an_incident_with_no_deploy_recorded_tells_the_agent_of_none() -> None:
    # Nothing known to have run is nothing to ask the branch about - and a
    # history nobody could read is not one in which something was deployed.
    Scenario() \
        .given(
            an_incident_with_no_deploys_read := _an_incident_in(
                IncidentStatus.FIXING, deployments=None
            ),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_with_no_deploys_read, the_agent.propose)
        ) \
        .then(
            _the_agent_was_told_what_ran(the_agent, None)
        )


@pytest.mark.unit
def test_an_alert_that_dated_nothing_tells_the_agent_of_none() -> None:
    # With no instant to bound it, the newest deploy could be the walk's own
    # rollback - and Code-Fix would be told of a revision that never caused
    # anything. Silence loses a caveat; the guess could state something false.
    Scenario() \
        .given(
            an_incident_whose_alert_dated_nothing := _an_incident_in(
                IncidentStatus.FIXING,
                alert=Alert(service="kuki", alert_name="HighErrorRate", started_at=None),
                deployments=[_a_deploy(THE_REVISION_THAT_RAN, "2026-09-27T09:14:00Z")]
            ),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_whose_alert_dated_nothing, the_agent.propose)
        ) \
        .then(
            _the_agent_was_told_what_ran(the_agent, None)
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
        .then(the_route_is(POSTMORTEM_ROUTE))


@pytest.mark.unit
def test_an_incident_nothing_could_be_done_for_also_goes_to_the_postmortem() -> None:
    # The other road in. An incident that reached Code-Fix having stopped
    # nothing still gets written up - a human reading it afterwards needs the
    # account most, not least.
    Scenario() \
        .given(an_unfixed_incident := _an_incident_in(IncidentStatus.FIXING)) \
        .when(lambda: route_after_codefix(an_unfixed_incident)) \
        .then(the_route_is(POSTMORTEM_ROUTE))


@pytest.mark.unit
def test_what_code_fix_found_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # The one step that ends with somebody else's turn, and it usually moves no
    # status - so no line from the walk's narration says it happened, and this
    # is the line saying where the proposal can be read.
    some_url = "https://github.invalid/io-shop/target/pull/41"

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_with_a_fix := _an_agent_offering(a_pull_request(url=some_url))
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_with_a_fix)
        ) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.fixing", logging.INFO,
                                  "fix attempted",
                                  values={"outcome": FixOutcome.PROPOSED,
                                          "pull_request": some_url})
        )


@pytest.mark.unit
def test_a_proposal_that_could_not_be_made_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The outcome somebody can go and repair, so its line carries the traceback
    # the timeline's one sentence leaves out.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.MITIGATED),
            an_agent_that_could_not := _an_agent_raising(
                RuntimeError("could not create branch: 403 Forbidden")
            )
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_that_could_not)
        ) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.fixing", logging.WARNING,
                                  "fix could not be proposed", failure=RuntimeError)
        )


class _AnAgentRememberingWhatItWasAsked:
    """Code-Fix as a seam, holding on to what it was told.

    A small class rather than `create_autospec`, because the test reads the
    question back afterwards and a named attribute says what is being read more
    plainly than a call record does.
    """

    def __init__(self) -> None:
        self.hypothesis: Hypothesis | None = None
        self.incident_id: str | None = None
        self.still_wanted: StillWanted | None = None
        self.leads: Leads | None = None
        self.deployed: str | None = None

    def propose(self,
                hypothesis: Hypothesis | None,
                incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                deployed: str | None = None) -> ProposedFix:
        self.hypothesis = hypothesis
        self.incident_id = incident_id
        self.still_wanted = still_wanted
        self.leads = leads
        self.deployed = deployed

        return ProposedFix(pull_request=None, explanation=None)


def _an_agent_offering(proposal: OpenedPullRequest | None,
                       explaining: str | None = None) -> ProposeFix:
    """Code-Fix, answering the same thing however it is asked."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                deployed: str | None = None) -> ProposedFix:
        return ProposedFix(pull_request=proposal, explanation=explaining)

    return propose


def _an_agent_that_read(branch: str, holds_what_ran: bool | None) -> ProposeFix:
    """Code-Fix, having proposed a fix from `branch`, which held what ran or not."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                deployed: str | None = None) -> ProposedFix:
        return ProposedFix(pull_request=a_pull_request(), explanation="dont care",
                           branch_read=branch, holds_what_ran=holds_what_ran)

    return propose


def _an_agent_finding(as_it_ran: list[FileAsItRan]) -> ProposeFix:
    """Code-Fix, having proposed a fix whose reading names files read again
    at the revision that ran."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                deployed: str | None = None) -> ProposedFix:
        return ProposedFix(pull_request=a_pull_request(), explanation="dont care",
                           as_it_ran=as_it_ran)

    return propose


def _an_agent_finding_the_uses(uses_outside: list[CodeUse]) -> ProposeFix:
    """Code-Fix, having proposed a fix whose patch changes what the code
    outside it uses."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                deployed: str | None = None) -> ProposedFix:
        return ProposedFix(pull_request=a_pull_request(), explanation="dont care",
                           uses_outside=uses_outside)

    return propose


def _an_agent_holding_back(explaining: str = "an explanation") -> ProposeFix:
    """Code-Fix, having written a fix it says helps nobody until code outside
    the repository changes too."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                deployed: str | None = None) -> ProposedFix:
        return ProposedFix(pull_request=None, explanation=explaining,
                           needs_code_outside=True)

    return propose


def _an_agent_that_fails(failure: Exception) -> ProposeFix:
    """Code-Fix, unable to propose at all.

    The failure is an arbitrary exception rather than a named type: what opens a
    pull request in production is a tool on another process, so what arrives
    here is whatever the transport raised - and a node catching one specific
    class would let every other way that call fails take the walk down.
    """
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                deployed: str | None = None) -> ProposedFix:
        raise failure

    return propose


def a_pull_request(url: str = "https://github.invalid/dont-care/dont-care/pull/1"
                   ) -> OpenedPullRequest:
    return OpenedPullRequest(number=1, url=url, branch="argus/fix-buki-123")


def _an_incident_in(status: IncidentStatus,
                    hypothesis: Hypothesis | None = None,
                    alert: Alert = DONT_CARE_ALERT,
                    deployments: list[ChangeEvent] | None = None) -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=alert,
                         status=status,
                         hypothesis=hypothesis,
                         deployments=deployments)


def _a_deploy(revision: str, at: str) -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.DEPLOY,
                       occurred_at=at,
                       reference=revision,
                       summary="dont-care-summary")


def _the_agent_was_told_what_ran(
    agent: _AnAgentRememberingWhatItWasAsked, revision: str | None
) -> Assertion[StateDelta]:
    def assertion(_updates: StateDelta) -> bool:
        if agent.deployed != revision:
            raise AssertionError(
                f"Expected Code-Fix to be told [{revision}] was running, it was "
                f"told [{agent.deployed}]."
            )

        return True

    return assertion


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


def _an_agent_raising(error: Exception) -> ProposeFix:
    """A repository that refused, said as the agent raising what it raised."""
    def refuse(dont_care_hypothesis: Hypothesis | None,
               dont_care_incident_id: str,
               *,
               still_wanted: StillWanted = wanted_throughout,
               leads: Leads = no_leads,
               deployed: str | None = None) -> Any:
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


def _the_attempt_left_a_fix_unproposed_on(branch: str | None,
                                          published: list[IncidentEvent]
                                          ) -> Assertion[StateDelta]:
    """A fix Code-Fix wrote and nothing proposes, and the branch it is on -
    `None` where it is on none."""
    def assertion(dont_care_result: StateDelta) -> bool:
        attempt = next(event for event in published if isinstance(event, FixAttempted))

        if not attempt.unproposed or attempt.branch_written != branch:
            raise AssertionError(
                f"Expected the attempt to leave a fix unproposed on [{branch}], got "
                f"unproposed [{attempt.unproposed}] on [{attempt.branch_written}]."
            )

        return True

    return assertion


def _the_attempt_explains(explanation: str,
                          published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """What Code-Fix said of the code, on the one account of the step."""
    def assertion(dont_care_result: StateDelta) -> bool:
        explained = [event.explanation for event in published
                     if isinstance(event, FixAttempted)]
        if explained != [explanation]:
            raise AssertionError(
                f"Expected the attempt to carry Code-Fix's account of the code, "
                f"[{explanation}], got {explained}."
            )

        return True

    return assertion


def _the_attempt_says_it_read(branch: str,
                              holds_what_ran: bool | None,
                              published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """Which branch Code-Fix read, and whether it held what ran, on the attempt."""
    def assertion(dont_care_result: StateDelta) -> bool:
        said = [(event.branch_read, event.holds_what_ran) for event in published
                if isinstance(event, FixAttempted)]
        if said != [(branch, holds_what_ran)]:
            raise AssertionError(
                f"Expected the attempt to say Code-Fix read [{branch}], holding what "
                f"ran [{holds_what_ran}], got {said}."
            )

        return True

    return assertion


def _the_attempt_found_as_they_ran(expected: list[FileAsItRan],
                                   published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """The files Code-Fix's reading names, as they ran, on the attempt."""
    def assertion(dont_care_result: StateDelta) -> bool:
        found = [event.as_it_ran for event in published if isinstance(event, FixAttempted)]
        if found != [expected]:
            raise AssertionError(
                f"Expected the attempt to carry the files as they ran, {expected}, "
                f"got {found}."
            )

        return True

    return assertion


def _the_attempt_found_the_uses_outside(expected: list[CodeUse],
                                        published: list[IncidentEvent]
                                        ) -> Assertion[StateDelta]:
    """How the code outside Code-Fix's patch uses what it changes, on the
    attempt."""
    def assertion(dont_care_result: StateDelta) -> bool:
        found = [event.uses_outside for event in published if isinstance(event, FixAttempted)]
        if found != [expected]:
            raise AssertionError(
                f"Expected the attempt to carry how the code outside the patch uses "
                f"what it changes, {expected}, got {found}."
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


def _the_move_says(expected: str) -> Assertion[StateDelta]:
    """What the move after this step says of it, whole: a reason after the
    words saying what failed is the reason, and anything more is noise."""
    def assertion(updates: StateDelta) -> bool:
        said = updates.narration.detail if updates.narration is not None else None

        if said != expected:
            raise AssertionError(f"Expected the move to say [{expected}], it said [{said}].")

        return True

    return assertion


def _the_attempt_says_only(reason: str,
                           published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """The reason and nothing before it: the attempt's line says the rest."""
    def assertion(dont_care_result: StateDelta) -> bool:
        said = [event.detail for event in published if isinstance(event, FixAttempted)]

        if said != [reason]:
            raise AssertionError(
                f"Expected the one attempt to say [{reason}] and nothing more, got {said}."
            )

        return True

    return assertion


def _no_attempt_was_announced(published: list[IncidentEvent]) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        attempts = [event for event in published if isinstance(event, FixAttempted)]

        if attempts:
            raise AssertionError(
                f"Expected no fix attempt announced for a fix somebody stopped, "
                f"got {[attempt.outcome for attempt in attempts]}."
            )

        return True

    return assertion


def _a_question_recording_who_it_asks_about(asked: list[str]) -> IsStillWanted:
    def still_wanted(incident_id: str, /) -> bool:
        asked.append(incident_id)
        return True

    return still_wanted


def _the_question_handed_down_asks_about(agent: _AnAgentRememberingWhatItWasAsked,
                                         asked: list[str],
                                         incident_id: str) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if agent.still_wanted is None:
            raise AssertionError(
                "Expected Code-Fix to be handed a way to ask whether it is still "
                "wanted, and it was handed none."
            )

        agent.still_wanted()

        if asked != [incident_id]:
            raise AssertionError(
                f"Expected the question handed down to ask about incident "
                f"[{incident_id}], and it asked about {asked}."
            )

        return True

    return assertion


def _a_thread_noting_who_it_is_asked_about(asked: list[str],
                                           leads: list[ThreadMessage]) -> LeadsOf:
    def leads_of(incident_id: str, /) -> list[ThreadMessage]:
        asked.append(incident_id)
        return leads

    return leads_of


def _the_leads_handed_down_are(expected: list[ThreadMessage],
                               agent: _AnAgentRememberingWhatItWasAsked,
                               asked: list[str],
                               incident_id: str) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if agent.leads is None:
            raise AssertionError(
                "Expected Code-Fix to be handed a way to ask what people told the "
                "incident, and it was handed none."
            )

        told = agent.leads()

        if asked != [incident_id]:
            raise AssertionError(
                f"Expected the question handed down to ask about incident "
                f"[{incident_id}], and it asked about {asked}."
            )

        if told != expected:
            raise AssertionError(
                f"Expected the question handed down to answer with the "
                f"{len(expected)} lead(s) the thread holds, and it answered {told}."
            )

        return True

    return assertion
