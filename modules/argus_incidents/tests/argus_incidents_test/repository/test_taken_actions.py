from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import (
    ActionProgress,
    Alert,
    FailureMode,
    FlagUndo,
    Hypothesis,
    TakenAction,
    UndoDescriptor,
    UnreadVerdict,
    Verdict,
)
from argus_incidents.repository import hypotheses, taken_actions
from argus_testkit import Assertion, Scenario, all_of, calling

from argus_incidents_test.framework import no_column_is_empty
from argus_incidents_test.framework.builders import an_incident_created_for

SOME_INSTANT = datetime(2026, 10, 26, 18, 4, 49, 35000, tzinfo=UTC)
DONT_CARE_INSTANT = datetime(2026, 10, 11, 23, 38, tzinfo=UTC)


@pytest.mark.integration
def test_an_action_is_claimed_at_the_instant_its_claim_is_handed() -> None:
    # On the walk's clock, which dates everything else in the incident - a
    # replay's simulated one included - rather than on the database's, which
    # dates nothing else.
    some_alert = Alert(service="io-shop", alert_name="HighLatency")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_read_back_was_claimed_at = partial(_the_action_read_back_was_claimed_at, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=SOME_INSTANT
                )
            ) \
            .then(
                the_action_read_back_was_claimed_at(incident_id, SOME_INSTANT)
            )


@pytest.mark.integration
def test_record_writes_the_action_with_its_outcome_and_undo_descriptor() -> None:
    # The record of an incident has to say what was changed and what would put
    # it back. An outcome alone leaves a human reading the row afterwards
    # knowing a flag was touched and not which state it had been in.
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate")
    some_undo_descriptor = FlagUndo(
        flag="monthly-spend-feature",
        was_enabled=True,
        environment="production"
    )

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_says = partial(_the_action_row_says, conn)
        the_action_row_carries = partial(_the_action_row_carries, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="monthly-spend-feature",
                    outcome=Verdict.CONFIRMED,
                    undo_descriptor=some_undo_descriptor,
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
                )
            ) \
            .then(all_of(
                the_action_row_says(
                    incident_id, action_type="revert-feature-flag", outcome="confirmed"
                ),
                the_action_row_carries(incident_id, some_undo_descriptor)
            ))


@pytest.mark.integration
def test_an_action_with_nothing_to_undo_is_recorded_without_a_descriptor() -> None:
    # An action that never reached the provider changed nothing, so there is
    # nothing to put back - and a row claiming otherwise would send a human to
    # undo a change that was never made.
    some_service = "buki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_carries = partial(_the_action_row_carries, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    outcome=Verdict.ESCALATED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
                )
            ) \
            .then(
                the_action_row_carries(incident_id, None)
            )


@pytest.mark.integration
@pytest.mark.parametrize(("performed", "progress"),
                         [(True, ActionProgress.PERFORMED),
                          (False, ActionProgress.NOT_PERFORMED)],
                         ids=["performed", "never-performed"])
def test_a_completed_action_says_whether_it_was_performed(performed: bool,
                                                          progress: ActionProgress) -> None:
    # What says the candidate was tried where nothing was measured: a person's
    # ending stops a test before the write and during the wait alike, and no
    # verdict tells the two apart.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    outcome=Verdict.STOPPED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    performed=performed,
                    left_behind_known=True
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [progress])
            )


@pytest.mark.integration
@pytest.mark.parametrize("left_behind_known", [True, False], ids=["known", "not-known"])
def test_a_completed_action_says_whether_what_it_left_is_known(
        left_behind_known: bool) -> None:
    # Two refusals that changed nothing anybody recorded, and only one of them
    # may be written up as having changed nothing: the tier that said it asked
    # for no change, against the one whose change request's answer was lost.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    outcome=Verdict.ESCALATED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    performed=False,
                    left_behind_known=left_behind_known
                )
            ) \
            .then(
                _what_it_left_is_read_back_as_known(conn, incident_id, left_behind_known)
            )


@pytest.mark.integration
def test_an_action_only_claimed_is_not_known_to_have_left_nothing() -> None:
    # A worker that stopped after its claim may have made the change, so the
    # row says nothing is known until something more is written.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .then(
                _what_it_left_is_read_back_as_known(conn, incident_id, False)
            )


@pytest.mark.integration
@pytest.mark.parametrize(("performed", "progress"),
                         [(True, ActionProgress.PERFORMED),
                          (False, ActionProgress.NOT_PERFORMED)],
                         ids=["performed", "never-performed"])
def test_the_action_claimed_for_a_candidate_says_how_far_it_got(
        performed: bool, progress: ActionProgress) -> None:
    # The other read of the row - the one a resumed walk makes - maps the column
    # back too.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                some_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .given(
                calling(lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=some_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    outcome=Verdict.STOPPED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    performed=performed,
                    left_behind_known=True
                ))
            ) \
            .when(
                lambda: taken_actions.get_action_for_hypothesis(conn, incident_id,
                                                                some_hypothesis_id)
            ) \
            .then(
                _it_progressed_to(progress)
            )


@pytest.mark.integration
def test_an_action_only_claimed_is_known_as_claimed() -> None:
    # The state a row is in from the claim until anything else is known about
    # it - the action about to be taken, or taken by a worker that stopped
    # before saying so.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.CLAIMED])
            )


@pytest.mark.integration
def test_a_change_made_is_recorded_with_what_puts_it_back_before_any_verdict() -> None:
    # Written the moment the change is made, before the wait. A worker that
    # dies during the wait leaves a row saying the change was made and how to
    # put it back - which is what a withdrawal, or a failed run's unwinding,
    # reads through this same read.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    some_undo_descriptor = FlagUndo(flag="monthly-spend-feature", was_enabled=True)

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="monthly-spend-feature",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.PERFORMED,
                    undo_descriptor=some_undo_descriptor
                )
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.PERFORMED]),
                _the_undo_read_back_is(conn, incident_id, some_undo_descriptor),
                _the_outcome_read_back_is_absent(conn, incident_id)
            ))


@pytest.mark.integration
@pytest.mark.parametrize(("performed", "progress"),
                         [(True, ActionProgress.PERFORMED),
                          (False, ActionProgress.NOT_PERFORMED)],
                         ids=["performed", "never-performed"])
def test_an_action_already_completed_is_not_moved_back(performed: bool,
                                                       progress: ActionProgress) -> None:
    # Only a claim moves on. A completion is the whole account of the
    # attempt, and a later write about a claim - a resumed walk that could
    # not tell what happened - must not overwrite what the attempt itself
    # recorded.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    outcome=Verdict.STOPPED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    performed=performed,
                    left_behind_known=True
                ))
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.UNKNOWN,
                    undo_descriptor=None
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [progress])
            )


@pytest.mark.integration
def test_an_action_nobody_can_account_for_stays_unaccounted_for() -> None:
    # Unknown is final. A resumed walk that finds it escalates without asking
    # again, so nothing may later turn it into a claim's answer it never got.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)
        taken_actions.claim(conn, incident_id, hypothesis_id=hypothesis_id,
                            action_type="revert-feature-flag", subject="dont-care-flag",
                            at=DONT_CARE_INSTANT)

        Scenario() \
            .given(
                calling(lambda: taken_actions.advance(conn, incident_id,
                                                      hypothesis_id=hypothesis_id,
                                                      to=ActionProgress.UNKNOWN,
                                                      undo_descriptor=None))
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.PERFORMED,
                    undo_descriptor=FlagUndo(flag="dont-care-flag", was_enabled=True)
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.UNKNOWN])
            )


@pytest.mark.integration
def test_settling_an_incidents_claims_leaves_every_row_that_moved_on_alone() -> None:
    # Where no walk will write the incident's rows again. A claim still open
    # there will never be answered, so it becomes unknown; every row that
    # already says more keeps what it says - and another incident's claim is
    # that incident's.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        another_incident_id = an_incident_created_for(conn, some_alert)
        still_claimed = a_hypothesis_recorded_for(incident_id, subject="first", rank=1)
        performed = a_hypothesis_recorded_for(incident_id, subject="second", rank=2)
        never_performed = a_hypothesis_recorded_for(incident_id, subject="third", rank=3)
        anothers = a_hypothesis_recorded_for(another_incident_id)

        def four_actions_got_as_far_as_they_did() -> None:
            for candidate, at in ((still_claimed, SOME_INSTANT),
                                  (performed, SOME_INSTANT + timedelta(minutes=1))):
                taken_actions.claim(conn, incident_id, hypothesis_id=candidate,
                                    action_type="revert-feature-flag",
                                    subject="dont-care-flag", at=at)
            taken_actions.advance(conn, incident_id, hypothesis_id=performed,
                                  to=ActionProgress.PERFORMED, undo_descriptor=None)
            taken_actions.record(conn, incident_id, hypothesis_id=never_performed,
                                 action_type="revert-feature-flag", subject="dont-care-flag",
                                 outcome=Verdict.PLATFORM_UNREACHABLE, undo_descriptor=None,
                                 at=SOME_INSTANT + timedelta(minutes=2), performed=False,
                                 left_behind_known=True)
            taken_actions.claim(conn, another_incident_id, hypothesis_id=anothers,
                                action_type="revert-feature-flag", subject="dont-care-flag",
                                at=DONT_CARE_INSTANT)

        Scenario() \
            .given(
                calling(four_actions_got_as_far_as_they_did)
            ) \
            .when(
                lambda: taken_actions.settle_claims(conn, incident_id)
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id,
                                           [ActionProgress.UNKNOWN,
                                            ActionProgress.PERFORMED,
                                            ActionProgress.NOT_PERFORMED]),
                _the_progress_read_back_is(conn, another_incident_id,
                                           [ActionProgress.CLAIMED])
            ))


@pytest.mark.integration
def test_an_action_names_the_subject_it_changed() -> None:
    # The row has to say what was changed, not only that something was. Argus
    # holds the subject at the moment it claims the action - it is the candidate
    # it is acting on - and a column that is read back but never written is a
    # question every later reader has to answer by guessing.
    #
    # Two readers already depend on it and neither can recover it: the
    # postmortem's account of what was done renders the action and its subject
    # in one line, and long-term memory - whose whole content is which subjects
    # were tried and what each attempt was worth - keeps nothing at all for an
    # attempt that names none.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_flag_that_was_changed = "monthly-spend-feature"

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_changed = partial(_the_action_row_changed, conn)
        the_action_read_back_changed = partial(_the_action_read_back_changed, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject=the_flag_that_was_changed,
                    outcome=Verdict.CONFIRMED,
                    undo_descriptor=FlagUndo(
                        flag=the_flag_that_was_changed, was_enabled=True
                    ),
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
                )
            ) \
            .then(all_of(
                the_action_row_changed(incident_id, the_flag_that_was_changed),
                the_action_read_back_changed(incident_id, the_flag_that_was_changed)
            ))


@pytest.mark.integration
def test_an_action_claimed_and_not_yet_finished_already_names_its_subject() -> None:
    # The subject is written by the claim rather than by the verdict, because
    # the claim is the write that happens before anything is done - and the one
    # case this table exists to answer is a worker that stopped in between. A
    # row found with no outcome has to say what change is out there; recovering
    # that from the descriptor of an action that may never have reached the
    # provider is the reconstruction the column was added to avoid.
    some_alert = Alert(service="io-shop", alert_name="HighLatency")
    the_flag_that_was_changed = "checkout-v2"

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_changed = partial(_the_action_row_changed, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject=the_flag_that_was_changed,
                    at=DONT_CARE_INSTANT
                )
            ) \
            .then(
                the_action_row_changed(incident_id, the_flag_that_was_changed)
            )


@pytest.mark.integration
def test_an_action_names_the_candidate_it_was_taken_for() -> None:
    # The association is stored rather than inferred. Recovering it afterwards
    # means matching the flag the action and the hypothesis happen to share,
    # which is only ever right because the walk refuses to act on one subject
    # twice - a rule about not retrying a move, not about identity. Argus knows
    # which candidate it is acting on at the moment it writes the row, and this
    # is that knowledge surviving.
    some_alert = Alert(service="kukibuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_names = partial(_the_action_row_names, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="monthly-spend-feature",
                    outcome=Verdict.REFUTED,
                    undo_descriptor=FlagUndo(flag="monthly-spend-feature", was_enabled=False),
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
                )
            ) \
            .then(
                the_action_row_names(incident_id, hypothesis_id)
            )


@pytest.mark.integration
def test_two_candidates_naming_one_subject_keep_their_own_actions() -> None:
    # What the stored association buys that the subject match could not. Two
    # candidates about the same flag are indistinguishable to anything matching
    # on subject, so both actions would be attributed to whichever candidate was
    # found first. The walk forbids this today; the data model should not depend
    # on its continuing to.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_contested_flag = "monthly-spend-feature"

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        each_action_names_its_own_candidate = partial(
            _each_action_names_its_own_candidate, conn
        )

        incident_id = an_incident_created_for(conn, some_alert)
        first = a_hypothesis_recorded_for(incident_id, subject=the_contested_flag, rank=1)
        second = a_hypothesis_recorded_for(incident_id, subject=the_contested_flag, rank=2)

        def an_action_is_taken_for_each() -> None:
            for candidate, outcome in ((first, Verdict.REFUTED), (second, Verdict.CONFIRMED)):
                taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=candidate,
                    action_type="revert-feature-flag",
                    subject=the_contested_flag,
                    outcome=outcome,
                    undo_descriptor=FlagUndo(flag=the_contested_flag, was_enabled=True),
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
                )

        Scenario() \
            .when(
                an_action_is_taken_for_each
            ) \
            .then(
                each_action_names_its_own_candidate(incident_id, {first, second})
            )


@pytest.mark.integration
def test_the_actions_of_an_incident_come_back_in_the_order_they_were_taken() -> None:
    # A walk's actions are a sequence - tried, undone, tried again - and read
    # back in any other order they describe a different incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_actions_read_back_are = partial(_the_actions_read_back_are, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        first = a_hypothesis_recorded_for(incident_id, subject="first", rank=1)
        second = a_hypothesis_recorded_for(incident_id, subject="second", rank=2)

        def two_actions_are_taken() -> None:
            for candidate, outcome, at in ((first, Verdict.REFUTED, SOME_INSTANT),
                                           (second, Verdict.CONFIRMED,
                                            SOME_INSTANT + timedelta(minutes=4))):
                taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=candidate,
                    action_type="revert-feature-flag",
                    subject="dont-care",
                    outcome=outcome,
                    undo_descriptor=FlagUndo(flag="dont-care", was_enabled=True),
                    at=at,
                    left_behind_known=True
                )

        Scenario() \
            .when(
                two_actions_are_taken
            ) \
            .then(
                the_actions_read_back_are(incident_id, ["refuted", "confirmed"])
            )


@pytest.mark.integration
def test_an_outcome_no_verdict_spells_comes_back_unread_rather_than_absent() -> None:
    # The read every other reader comes through, asked about the row none of
    # them can spell. Absence is the state it must not collapse into: a claim
    # with no outcome means the worker died between acting and recording, and
    # it is the one row whose change may be out there unmeasured - so reading
    # a finished action as that one sends the walk to ask the provider about a
    # verdict that was already reached.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    a_verdict_this_version_cannot_spell = "dissolved"

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        an_older_versions_verdict_on = partial(_an_older_versions_verdict_on, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="monthly-spend-feature",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .given(
                an_older_versions_verdict_on(
                    incident_id, a_verdict_this_version_cannot_spell
                )
            ) \
            .when(
                lambda: taken_actions.get_action_for_hypothesis(
                    conn, incident_id, hypothesis_id
                )
            ) \
            .then(
                _the_outcome_read_back_is(
                    UnreadVerdict(a_verdict_this_version_cannot_spell)
                )
            )


@pytest.mark.integration
def test_a_completed_action_leaves_no_column_of_its_row_empty() -> None:
    # The other half of the written-columns guard, and the half that can see
    # what a static reading cannot: a writer that names a column and is never
    # called, and one that is called and puts NULL there, both satisfy a guard
    # that only asks whether a writer exists in the source.
    #
    # One action with everything an action can have: a claim, a candidate, a
    # subject, a verdict, and a change with a way back. A row legitimately
    # lacking one of those is a different case with its own test above; this
    # asks whether the complete case reaches the table complete.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_flag_that_was_changed = "monthly-spend-feature"

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject=the_flag_that_was_changed,
                    outcome=Verdict.CONFIRMED,
                    undo_descriptor=FlagUndo(
                        flag=the_flag_that_was_changed, was_enabled=True
                    ),
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
                )
            ) \
            .then(
                no_column_is_empty(conn, "action", "incident_id", incident_id)
            )


def _a_hypothesis_recorded_for(conn: psycopg.Connection,
                               incident_id: str,
                               subject: str | None = None,
                               rank: int = 1) -> str:
    """A candidate an action can point at.

    An action's hypothesis is a foreign key, so a row has to exist for it to
    name - which makes this the smallest hypothesis the column will accept
    rather than anything a test asserts on.
    """
    hypothesis = Hypothesis(
        incident_id=incident_id,
        summary="dont care",
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        supporting_evidence=[],
        subject=subject,
        rank=rank
    )
    hypotheses.record(conn, hypothesis)

    return hypothesis.id


def _the_action_row_says(conn: psycopg.Connection,
                         incident_id: str,
                         action_type: str,
                         outcome: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        recorded_type, recorded_outcome, _, _, _ = _the_only_action_row(conn, incident_id)

        assert recorded_type == action_type, (
            f"Expected type {action_type}, got {recorded_type}."
        )
        assert recorded_outcome == outcome, (
            f"Expected outcome {outcome}, got {recorded_outcome}."
        )

        return True

    return assertion


def _the_action_row_carries(conn: psycopg.Connection,
                            incident_id: str,
                            undo_descriptor: UndoDescriptor | None) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        _, _, recorded, _, _ = _the_only_action_row(conn, incident_id)
        expected = (
            undo_descriptor.model_dump(mode="json")
            if undo_descriptor is not None else None
        )

        assert recorded == expected, (
            f"Expected undo descriptor {expected}, got {recorded}."
        )

        return True

    return assertion


def _the_action_row_names(conn: psycopg.Connection,
                          incident_id: str,
                          hypothesis_id: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        _, _, _, recorded, _ = _the_only_action_row(conn, incident_id)

        assert str(recorded) == hypothesis_id, (
            f"Expected the action to name hypothesis {hypothesis_id}, got {recorded}."
        )

        return True

    return assertion


def _the_action_row_changed(conn: psycopg.Connection,
                            incident_id: str,
                            subject: str) -> Assertion[object]:
    """What the column holds, asked of the table directly.

    The column rather than the model, because the two failed differently and
    only one of them was visible: every read here selects `subject` and every
    write left it NULL, so a model populated from the row agreed with the row
    perfectly and both were empty.
    """
    def assertion(_result: object) -> bool:
        _, _, _, _, recorded = _the_only_action_row(conn, incident_id)

        assert recorded == subject, (
            f"Expected the action to have changed {subject}, got {recorded}."
        )

        return True

    return assertion


def _the_action_read_back_changed(conn: psycopg.Connection,
                                  incident_id: str,
                                  subject: str) -> Assertion[object]:
    """The same fact through the repository's own read.

    Both, because this is the one a caller sees. `composing.py` discards an
    attempt whose `subject` is empty, so a column written and not mapped back
    onto the model would leave long-term memory exactly as empty as a column
    never written at all.
    """
    def assertion(_result: object) -> bool:
        read_back = taken_actions.get_by_incident(conn, incident_id)

        assert len(read_back) == 1, (
            f"Expected exactly one action, got {len(read_back)}."
        )
        assert read_back[0].subject == subject, (
            f"Expected the action read back to name {subject}, "
            f"got {read_back[0].subject}."
        )

        return True

    return assertion


def _what_it_left_is_read_back_as_known(conn: psycopg.Connection,
                                        incident_id: str,
                                        expected: bool) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        read_back = [action.left_behind_known
                     for action in taken_actions.get_by_incident(conn, incident_id)]

        if read_back != [expected]:
            raise AssertionError(
                f"Expected one action whose left_behind_known reads [{expected}], "
                f"and the incident's actions read {read_back}."
            )

        return True

    return assertion


def _the_progress_read_back_is(conn: psycopg.Connection,
                               incident_id: str,
                               expected: list[ActionProgress]) -> Assertion[object]:
    """How far each of the incident's actions got, in the order they were taken."""
    def assertion(_result: object) -> bool:
        found = [action.progress for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != expected:
            raise AssertionError(f"Expected the actions read back as {expected}, got {found}.")

        return True

    return assertion


def _it_progressed_to(expected: ActionProgress) -> Assertion[TakenAction | None]:
    def assertion(action: TakenAction | None) -> bool:
        found = action.progress if action is not None else None
        if found is not expected:
            raise AssertionError(f"Expected the action read back as [{expected}], "
                                 f"got [{found}].")

        return True

    return assertion


def _the_undo_read_back_is(conn: psycopg.Connection,
                           incident_id: str,
                           expected: UndoDescriptor) -> Assertion[object]:
    """What would put the change back, through the read an unwinding makes."""
    def assertion(_result: object) -> bool:
        found = [action.undo_descriptor
                 for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != [expected]:
            raise AssertionError(f"Expected one action read back carrying [{expected}], "
                                 f"got {found}.")

        return True

    return assertion


def _the_outcome_read_back_is_absent(conn: psycopg.Connection,
                                     incident_id: str) -> Assertion[object]:
    """No verdict yet: the change being made is not what came of it."""
    def assertion(_result: object) -> bool:
        found = [action.outcome for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != [None]:
            raise AssertionError(f"Expected one action read back with no outcome, got {found}.")

        return True

    return assertion


def _the_action_read_back_was_claimed_at(conn: psycopg.Connection,
                                       incident_id: str,
                                       instant: datetime) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        read_back = taken_actions.get_by_incident(conn, incident_id)

        if [taken.taken_at for taken in read_back] != [instant]:
            raise AssertionError(f"Expected one action claimed at [{instant}], got "
                                 f"{[str(taken.taken_at) for taken in read_back]}.")

        return True

    return assertion


def _each_action_names_its_own_candidate(conn: psycopg.Connection,
                                         incident_id: str,
                                         candidates: set[str]) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT hypothesis_id FROM action WHERE incident_id = %s",
                (incident_id,)
            )
            named = {str(row[0]) for row in cursor.fetchall()}

        assert named == candidates, (
            f"Expected the two actions to name {candidates}, got {named}."
        )

        return True

    return assertion


def _the_only_action_row(conn: psycopg.Connection,
                         incident_id: str) -> tuple[Any, Any, Any, Any, Any]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT type, outcome, undo_descriptor, hypothesis_id, subject "
            "FROM action WHERE incident_id = %s",
            (incident_id,)
        )
        rows = cursor.fetchall()

    assert len(rows) == 1, f"Expected exactly one action row, got {len(rows)}."

    return rows[0]


def _the_actions_read_back_are(conn: psycopg.Connection,
                               incident_id: str,
                               outcomes: list[str]) -> Assertion[Any]:
    """The outcomes of an incident's actions, in the order they come back.

    Order is the claim: a walk's actions are a sequence - tried, undone, tried
    again - and read back in any other order they describe a different
    incident.
    """
    def assertion(_result: Any) -> bool:
        found = [taken.outcome for taken in taken_actions.get_by_incident(conn, incident_id)]

        if found != outcomes:
            raise AssertionError(f"Expected outcomes {outcomes}, got {found}.")

        return True

    return assertion


def _an_older_versions_verdict_on(conn: psycopg.Connection,
                                  incident_id: str,
                                  spelling: str) -> None:
    """One finished action whose outcome is spelled in a way this version does
    not know.

    Written in SQL, and the only thing here that is. Everything a writer can
    produce is produced by the real writer - the claim above this is
    `taken_actions.claim` for exactly that reason - because a test that seeds
    the store by hand proves the reader understands a shape the test itself
    invented, which is how a column read by two modules went its whole life
    unwritten.

    This row is the exception, and it is the exception because production
    cannot make one: `complete` takes a `Verdict`, so every spelling Argus
    writes is a spelling Argus reads. A row that disagrees comes from a version
    that is gone - a rename, an older deploy mid-migration - and the inability
    to write one is the behaviour under test, not a corner the seeding cuts.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET outcome = %s WHERE incident_id = %s",
            (spelling, incident_id)
        )
    conn.commit()


def _the_outcome_read_back_is(expected: Verdict | UnreadVerdict | None
                              ) -> Assertion[TakenAction | None]:
    """What the row's outcome is, as a value and as a type.

    Both, because `UnreadVerdict("refuted")` equals `Verdict.REFUTED` and is
    not one - and because the type is the whole distinction here: read back as
    `None`, an unreadable verdict is an action nobody finished, and the
    resuming walk goes and asks the provider whether a change it already has a
    verdict for ever landed.
    """
    def assertion(action: TakenAction | None) -> bool:
        if action is None:
            raise AssertionError(
                f"Expected an action whose outcome reads back as [{expected!r}], "
                f"got no row at all."
            )

        if action.outcome != expected or type(action.outcome) is not type(expected):
            raise AssertionError(
                f"Expected the outcome to read back as [{expected!r}], got "
                f"[{action.outcome!r}]."
            )

        return True

    return assertion
