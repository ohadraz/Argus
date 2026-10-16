"""What set it off: the change the confirmed cause blamed, the state it left,
the state it went to, when and by whom.

Each case is one postmortem and the sentence the section says it in.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.models import ChangeKind, Trigger
from argus_testkit import Assertion, Scenario, the_answer_was
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.trigger import TriggerSection, the_trigger

from postmortem_rendering_test.framework.builders import (
    SOME_DEPLOYED_REVISION,
    SOME_REPOSITORY_ADDRESS,
    a_deploy_read,
    a_postmortem,
    an_alert,
)

SOME_CHANGE = datetime(2026, 10, 11, 14, 2, tzinfo=UTC)


@pytest.mark.unit
def test_a_flag_change_is_the_flag_going_from_one_state_to_the_other_when_and_by_whom() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=Trigger(
                subject="monthly-spend-feature", from_state="off", to_state="on",
                changed_at=SOME_CHANGE, kind=ChangeKind.FLAG_TOGGLE, actor="kuki"))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).line
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="monthly-spend-feature", role=Role.CODE),
                                      Run(text=" flag went from "),
                                      Run(text="OFF", role=Role.FROM_STATE),
                                      Run(text=" to "),
                                      Run(text="ON", role=Role.TO_STATE),
                                      Run(text=" at "),
                                      Run.a_moment(SOME_CHANGE),
                                      Run(text=", by kuki"),
                                      Run(text=".")))))


@pytest.mark.unit
def test_a_deployment_is_the_service_deployed_from_one_revision_to_another() -> None:
    # A revision is an identifier, not a word: shown as written and cut as git
    # cuts one, never in capitals.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=Trigger(
                subject="dont care",
                from_state="4c810f2aa1e9a6f3b7c9d0e1f2a3b4c5d6e7f809",
                to_state="26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2",
                changed_at=None, kind=ChangeKind.DEPLOY))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert(service="io-shop")).line
        ) \
        .then(
            _it_reads("io-shop was deployed from 4c810f2 to 26f1d7e."))


@pytest.mark.unit
def test_a_deployment_s_revision_read_is_named_as_its_row_names_it_and_opens_its_commit() -> None:
    # Short as the prose and the change's own row write it, and leading where
    # it opens. A revision no change read names has nowhere to lead, and is
    # cut as git cuts one.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                trigger=Trigger(subject="dont care",
                                from_state="4c810f2aa1e9a6f3b7c9d0e1f2a3b4c5d6e7f809",
                                to_state=SOME_DEPLOYED_REVISION,
                                changed_at=None, kind=ChangeKind.DEPLOY),
                changes_read=[a_deploy_read("P1")])
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert(service="io-shop")).line
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="io-shop", role=Role.CODE),
                Run(text=" was deployed from "),
                Run(text="4c810f2", role=Role.FROM_STATE),
                Run(text=" to "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.TO_STATE,
                    address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"),
                Run(text=".")))))


@pytest.mark.unit
def test_a_deployment_s_states_are_revisions() -> None:
    # For a destination that sets a revision as code: the page does.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=Trigger(
                subject="dont care", from_state="v1", to_state="v2",
                changed_at=None, kind=ChangeKind.DEPLOY))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).states_are_revisions
        ) \
        .then(
            the_answer_was(True))


@pytest.mark.unit
def test_a_state_nobody_recorded_is_unknown() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=Trigger(
                subject="monthly-spend-feature", from_state=None, to_state="on",
                changed_at=None, kind=ChangeKind.FLAG_TOGGLE))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).line
        ) \
        .then(
            _it_reads("monthly-spend-feature flag went from UNKNOWN to ON."))


@pytest.mark.unit
def test_a_change_of_no_known_kind_says_its_states_as_written() -> None:
    # Only a flag's states are words said in capitals. A change nothing said
    # the kind of - a setting a deploy carried - may be named by its version,
    # and v2 is not V2.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=Trigger(
                subject="categoriser.model", from_state="v1", to_state="v2",
                changed_at=None, kind=None))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).line
        ) \
        .then(
            _it_reads("categoriser.model went from v1 to v2."))


@pytest.mark.unit
def test_a_change_with_no_states_is_named_alone() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=Trigger(
                subject="pricing-config", from_state=None, to_state=None,
                changed_at=None, kind=None))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).line
        ) \
        .then(
            _it_reads("pricing-config."))


@pytest.mark.unit
def test_a_setting_a_deploy_carried_names_the_deploy_and_who_started_it() -> None:
    # The setting is what moved, and the deploy is how: its revision short, as
    # the prose and the deploy's own row name it, leading where it opens.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                trigger=Trigger(subject="categoriser.model", from_state="v1", to_state="v2",
                                changed_at=SOME_CHANGE, actor="kuki", carried_by="P2"),
                changes_read=[a_deploy_read("P1"), a_deploy_read("P2")])
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).line
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="categoriser.model", role=Role.CODE),
                Run(text=" went from "),
                Run(text="v1", role=Role.FROM_STATE),
                Run(text=" to "),
                Run(text="v2", role=Role.TO_STATE),
                Run(text=" at "),
                Run.a_moment(SOME_CHANGE),
                Run(text=", in the deploy of "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK,
                    address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"),
                Run(text=" that kuki started"),
                Run(text=".")))))


@pytest.mark.unit
def test_a_setting_a_deploy_nobody_is_named_for_carried_names_the_deploy_alone() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                trigger=Trigger(subject="categoriser.model", from_state="v1", to_state="v2",
                                changed_at=None, carried_by="P1"),
                changes_read=[a_deploy_read("P1")])
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).line
        ) \
        .then(
            _it_reads(f"categoriser.model went from v1 to v2, in the deploy of "
                      f"{SOME_DEPLOYED_REVISION[:7]}."))


@pytest.mark.unit
def test_a_suspected_trigger_says_so_before_the_change_is_named() -> None:
    # Said first, so it is read before the change is.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=Trigger(
                subject="monthly-spend-feature", from_state="off", to_state="on",
                changed_at=None, kind=ChangeKind.FLAG_TOGGLE, suspected=True))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).line
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="Suspected, not confirmed:", role=Role.STRONG),
                                      Run(text=" "),
                                      Run(text="monthly-spend-feature", role=Role.CODE),
                                      Run(text=" flag went from "),
                                      Run(text="OFF", role=Role.FROM_STATE),
                                      Run(text=" to "),
                                      Run(text="ON", role=Role.TO_STATE),
                                      Run(text=".")))))


@pytest.mark.unit
def test_whether_the_trigger_is_suspected_is_said_on_its_own() -> None:
    # For a destination that marks which: the page tags the sentence.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=Trigger(
                subject="dont care", from_state=None, to_state=None,
                changed_at=None, suspected=True))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).suspected
        ) \
        .then(
            the_answer_was(True))


@pytest.mark.unit
def test_no_trigger_established_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=None)
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert())
        ) \
        .then(
            the_answer_was(TriggerSection(line=None, suspected=False, states_are_revisions=False,
                                          absent="No trigger was established.")))


def _it_reads(expected: str) -> Assertion[Line | None]:
    def assertion(line: Line | None) -> bool:
        said = line.said if line is not None else None

        if said != expected:
            raise AssertionError(f"Expected the trigger to read [{expected}], got [{said}].")

        return True

    return assertion
