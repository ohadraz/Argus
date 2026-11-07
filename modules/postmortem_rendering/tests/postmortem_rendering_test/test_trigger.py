"""What set it off: the change the confirmed cause blamed, the state it left,
the state it went to, when and by whom.

Each case is one postmortem and the sentence the section says it in.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.models import ChangeKind, ChannelReading, NoTrigger, Trigger, WhyNoTrigger
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
SOME_OTHER_REVISION = "4c810f2aa1e9a6f3b7c9d0e1f2a3b4c5d6e7f809"
SOME_THIRD_REVISION = "9a41c07be3d2f8165c0e7a92d4b8f3e6a1c5d720"
SOME_FILE = "deploy/values-production.yaml"


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
def test_a_file_a_deploy_carried_is_said_to_have_changed_in_that_deploy() -> None:
    # A file moves between no states, but a deploy changing it is still a
    # change: said as one, rather than as a name the time and the deploy hang
    # off.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                trigger=Trigger(subject="deploy/values-production.yaml",
                                from_state=None, to_state=None,
                                changed_at=None, carried_by="P1"),
                changes_read=[a_deploy_read("P1")])
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).line
        ) \
        .then(
            _it_reads(f"deploy/values-production.yaml changed, in the deploy of "
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
                                          absent="No trigger was established.",
                                          unestablished=None)))


@pytest.mark.unit
def test_a_confirmed_cause_with_no_trigger_says_why_in_place_of_none_established() -> None:
    # "No trigger was established" beside a confirmed cause reads as the cause
    # being in doubt. Said instead: what of the record left it without one.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=None, no_trigger=NoTrigger(
                why=WhyNoTrigger.ANOTHER_SERVICE_S_DEPLOYS_UNREAD, candidate="C1",
                service="io-pricing"))
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert())
        ) \
        .then(
            the_answer_was(TriggerSection(
                line=None, suspected=False, states_are_revisions=False, absent=None,
                unestablished=Line(runs=(Run(text="C1 was confirmed; it blames "),
                                         Run(text="io-pricing", role=Role.CODE),
                                         Run(text=", whose deploys Argus did not read."))))))


@pytest.mark.unit
def test_a_deploy_the_sentence_names_is_named_as_its_row_names_it_and_opens_its_commit() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                trigger=None,
                no_trigger=NoTrigger(why=WhyNoTrigger.CARRIED_BY_SEVERAL_BY_THE_ONSET,
                                     candidate="C1", subject=SOME_FILE, deploys=["P1", "P2"]),
                changes_read=[a_deploy_read("P1", SOME_OTHER_REVISION),
                              a_deploy_read("P2")])
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).unestablished
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="C1 was confirmed, and the deploys of "),
                Run(text=SOME_OTHER_REVISION[:7], role=Role.LINK,
                    address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_OTHER_REVISION}"),
                Run(text=" and "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK,
                    address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"),
                Run(text=" both changed "),
                Run(text=SOME_FILE, role=Role.CODE),
                Run(text=" by the time the incident began; which of them set it off "
                         "is not known.")))))


_THREE_DEPLOYS = [a_deploy_read("P1", SOME_OTHER_REVISION),
                  a_deploy_read("P2", SOME_THIRD_REVISION),
                  a_deploy_read("P3")]


@pytest.mark.unit
@pytest.mark.parametrize(("no_trigger", "expected"), [
    (NoTrigger(why=WhyNoTrigger.CARRIED_BY_SEVERAL_BY_THE_ONSET, candidate="C1",
               subject=SOME_FILE, deploys=["P1", "P2", "P3"]),
     f"C1 was confirmed, and the deploys of {SOME_OTHER_REVISION[:7]}, "
     f"{SOME_THIRD_REVISION[:7]} and {SOME_DEPLOYED_REVISION[:7]} all changed {SOME_FILE} by "
     f"the time the incident began; which of them set it off is not known."),
    (NoTrigger(why=WhyNoTrigger.CARRIED_BY_SEVERAL, candidate="C1",
               subject=SOME_FILE, deploys=["P1", "P2"]),
     f"C1 was confirmed, and the deploys of {SOME_OTHER_REVISION[:7]} and "
     f"{SOME_THIRD_REVISION[:7]} both changed {SOME_FILE}; which of them set it off is not "
     f"known."),
    (NoTrigger(why=WhyNoTrigger.CARRIED_AFTER_THE_ONSET, candidate="C1",
               subject=SOME_FILE, deploys=["P1"]),
     f"C1 was confirmed; the deploy of {SOME_OTHER_REVISION[:7]} changed {SOME_FILE}, but "
     f"after the incident began."),
    (NoTrigger(why=WhyNoTrigger.CARRIED_AFTER_THE_ONSET, candidate="C1",
               subject=SOME_FILE, deploys=["P1", "P2"]),
     f"C1 was confirmed; the deploys of {SOME_OTHER_REVISION[:7]} and "
     f"{SOME_THIRD_REVISION[:7]} changed {SOME_FILE}, but after the incident began."),
    (NoTrigger(why=WhyNoTrigger.ANOTHER_SERVICE_S_DEPLOYS_UNREAD, candidate="C1",
               service="io-pricing"),
     "C1 was confirmed; it blames io-pricing, whose deploys Argus did not read."),
    (NoTrigger(why=WhyNoTrigger.NAMES_NOTHING_SPECIFIC, candidate="C2"),
     "C2 was confirmed, but it names nothing specific, so no change could be matched to it."),
    (NoTrigger(why=WhyNoTrigger.THE_SERVICE_ITSELF, candidate="C1", service="io-shop"),
     "C1 was confirmed; it blames io-shop itself and names no change to it."),
    (NoTrigger(why=WhyNoTrigger.NO_DEPLOYS_READ, candidate="C1"),
     "C1 was confirmed, but Argus found no deploys in the window it read."),
    (NoTrigger(why=WhyNoTrigger.NO_DEPLOY_READ_CHANGED_IT, candidate="C1", subject=SOME_FILE),
     f"C1 was confirmed, but none of the deploys Argus read changed {SOME_FILE}."),
    (NoTrigger(why=WhyNoTrigger.NOT_EVERY_DEPLOY_READ_IN_FULL, candidate="C1",
               subject=SOME_FILE, deploys=["P2"]),
     f"C1 was confirmed; none of the deploys Argus read in full changed {SOME_FILE}, and "
     f"Argus did not read all of what {SOME_THIRD_REVISION[:7]} changed."),
    (NoTrigger(why=WhyNoTrigger.NO_DEPLOY_READ_IN_FULL, candidate="C1", deploys=["P1", "P2"]),
     f"C1 was confirmed, but Argus did not read all of what {SOME_OTHER_REVISION[:7]} and "
     f"{SOME_THIRD_REVISION[:7]} changed."),
    (NoTrigger(why=WhyNoTrigger.NOT_TIED, candidate="C1", subject="monthly-spend-feature"),
     "C1 was confirmed, but Argus could not tie monthly-spend-feature to any change it read.")
])
def test_each_reason_a_confirmed_cause_has_no_trigger_is_said_as_its_own_sentence(
    no_trigger: NoTrigger,
    expected: str
) -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(trigger=None, no_trigger=no_trigger,
                                            changes_read=_THREE_DEPLOYS)
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).unestablished
        ) \
        .then(
            _it_reads(expected))


@pytest.mark.unit
@pytest.mark.parametrize(("deploys", "flags", "expected"), [
    (ChannelReading.NOT_ASKED, ChannelReading.READ,
     "C1 was confirmed; no change Argus read was matched to it, and Argus did not read the "
     "deploys."),
    (ChannelReading.UNANSWERED, ChannelReading.READ,
     "C1 was confirmed; no change Argus read was matched to it, and Argus asked for the "
     "deploys and got no answer."),
    (ChannelReading.READ, ChannelReading.UNANSWERED,
     "C1 was confirmed; no change Argus read was matched to it, and Argus asked for the flag "
     "history and got no answer."),
    (ChannelReading.NOT_ASKED, ChannelReading.UNANSWERED,
     "C1 was confirmed; no change Argus read was matched to it. Argus did not read the "
     "deploys, and asked for the flag history and got no answer."),
    (None, None,
     "C1 was confirmed; no change Argus read was matched to it.")
])
def test_a_cause_with_changes_unread_says_which_and_how_beside_no_change_matched(
    deploys: ChannelReading | None,
    flags: ChannelReading | None,
    expected: str
) -> None:
    # Two facts and no "so": a flag cannot be in the deploys, and the unread
    # channel is not why nothing was tied to it. A document carrying no
    # readings says the first alone.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                trigger=None,
                no_trigger=NoTrigger(why=WhyNoTrigger.CHANGES_UNREAD, candidate="C1"),
                deploys_reading=deploys,
                flags_reading=flags)
        ) \
        .when(
            lambda: the_trigger(some_postmortem, an_alert()).unestablished
        ) \
        .then(
            _it_reads(expected))


def _it_reads(expected: str) -> Assertion[Line | None]:
    def assertion(line: Line | None) -> bool:
        said = line.said if line is not None else None

        if said != expected:
            raise AssertionError(f"Expected the trigger to read [{expected}], got [{said}].")

        return True

    return assertion
