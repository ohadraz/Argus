"""The record's evidence as rows, each under the label a step of the cause
cites it by.

The model is shown these rows and the document lists them, under the same
labels: a label counted twice is two chances to disagree about which row it
names. Each kind is counted on its own, in the order the kinds are shown, so a
run reading one row more of one kind renames nothing in the others.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from argus_testkit import Assertion, Scenario, the_answer_was
from core import to_iso
from core.models import (
    ChangeEvent,
    ChangeKind,
    CitedChange,
    CitedEvidence,
    CodeUse,
    DeploymentComparison,
    FileAsItRan,
    RevisionSource,
)
from postmortem_writing import DeploymentChangesRecord
from postmortem_writing.citations import (
    the_cause_measured_labelled,
    the_changes_labelled,
    the_deployment_changes_labelled,
    the_evidence_labelled,
    the_files_as_they_ran_labelled,
)
from postmortem_writing.estimate import DemandLevels, LoadLevels
from postmortem_writing.log_groups import grouped

from postmortem_writing_test.framework.builders import (
    ONSET,
    a_candidate,
    a_measured_incident,
    a_timeline_entry,
    an_action,
    an_evidence_bundle,
)

# What a shop's integrity check reports, in its own words: two counts and an
# amount.
SOME_FINDING = ("240 of 240 shopper totals do not reconcile with the purchases behind "
                "them. The widest is short by 1,297.31.")

# A revision a file was read again at, as the brief names it: by its short form.
SOME_DEPLOYED_REVISION = "53f02e9f6cb774f7f5869637bcc879941dcbc82d"

A_MINUTE_BEFORE_THE_ONSET = to_iso(ONSET - timedelta(minutes=1))


@pytest.mark.unit
def test_what_the_alert_said_is_evidence_under_a_label_of_its_own() -> None:
    # The check that paged measured what it paged on, and that is the first
    # thing a chain's symptom rests on. Shown with no label, a model had nothing
    # to cite it by: it cited the finding's figures, which are no evidence, and
    # then a candidate cause, which is no fact.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(timeline=[a_timeline_entry("a line of the narration")],
                                           log_lines=[],
                                           candidates=[],
                                           actions=[]).model_copy(
                update={"alert_finding": SOME_FINDING})
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("AL1", SOME_FINDING), ("T1", "a line of the narration")])
        )


@pytest.mark.unit
def test_each_kind_of_evidence_is_labelled_on_its_own_in_the_order_it_is_shown() -> None:
    # The label is what a step of the cause cites, so every line the model can
    # rest a claim on has one, and no two share it: the narration, the changes,
    # the logs, the candidates, then the actions. Each kind counts on its own,
    # and the logs go by message, so a run reading one log line more renames
    # nothing.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(timeline=[a_timeline_entry("a line of the narration")],
                                           changes=[_a_change(reference="a change")],
                                           log_lines=["a log line"],
                                           candidates=[a_candidate("a candidate")],
                                           actions=[an_action("an action")])
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("T1", "a line of the narration"),
                                ("P1", "a change"),
                                (grouped(["a log line"], None, ONSET.date())[0].label,
                                 "a log line"),
                                ("C1", "a candidate"),
                                ("M1", "an action")])
        )


@pytest.mark.unit
def test_the_changes_are_shown_under_the_same_labels_with_each_revision_written_short() -> None:
    # The document lists them under the labels the prose cites them by, so it
    # takes them from here rather than counting them again: two countings are
    # two chances to disagree about which change P2 is. Each carries its
    # reference as the prose writes it - a revision short, a flag as named - so
    # a row and the sentence citing it name the change alike.
    some_revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_deploy = ChangeEvent(kind=ChangeKind.DEPLOY,
                              occurred_at=A_MINUTE_BEFORE_THE_ONSET,
                              reference=some_revision,
                              summary="dont care")
    some_toggle = _a_change(reference="a flag")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=[some_deploy, some_toggle])
        ) \
        .when(
            lambda: the_changes_labelled(evidence)
        ) \
        .then(
            the_answer_was([
                CitedChange(label="P1", change=some_deploy, short_reference=some_revision[:7]),
                CitedChange(label="P2", change=some_toggle, short_reference="a flag")
            ])
        )


@pytest.mark.unit
def test_two_revisions_alike_for_seven_characters_are_each_written_as_long_as_tells_them_apart(
) -> None:
    # As the prose writes them, which is what git does: a short form the two
    # share would name neither.
    some_deploys = [ChangeEvent(kind=ChangeKind.DEPLOY,
                                occurred_at=A_MINUTE_BEFORE_THE_ONSET,
                                reference=revision,
                                summary="dont care")
                    for revision in ("abcdef12" + "0" * 32, "abcdef13" + "0" * 32)]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=some_deploys)
        ) \
        .when(
            lambda: [cited.short_reference for cited in the_changes_labelled(evidence)]
        ) \
        .then(
            the_answer_was(["abcdef12", "abcdef13"])
        )


@pytest.mark.unit
def test_a_line_outside_the_walk_is_shown_under_a_label_of_its_own() -> None:
    # In the narration where it happened, and counted apart from the walk's
    # lines - so a recorded answer citing T2 names the same line of the walk
    # whether or not somebody wrote in the thread before it this time.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[a_timeline_entry("a line of the walk"),
                          a_timeline_entry("a line outside it", outside_the_walk=True),
                          a_timeline_entry("another line of the walk")],
                log_lines=[],
                candidates=[],
                actions=[])
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("T1", "a line of the walk"),
                                ("XW1", "a line outside it"),
                                ("T2", "another line of the walk")])
        )


@pytest.mark.unit
def test_what_each_deployment_changed_is_evidence_a_step_of_the_cause_may_cite() -> None:
    # Each deployment under a label of its own, in the order it was first
    # looked into, with every line it was read with.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], candidates=[], actions=[],
                deployment_changes=[
                    DeploymentChangesRecord(revision="some-revision",
                                            said=["some line", "another line"]),
                    DeploymentChangesRecord(revision="some-other-revision",
                                            said=["a third line"])])
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("D1", "another line"), ("D2", "a third line")])
        )


@pytest.mark.unit
@pytest.mark.parametrize(("comparison", "said"), [
    (DeploymentComparison.NOTHING_BEFORE_IT,
     "4c810f2 is the earliest deployment of io-shop the deployment history holds, so there "
     "was nothing before it to compare it against, and what it changed was not read."),
    (DeploymentComparison.NOT_DEPLOYED,
     "The deployment history holds no deployment of io-shop at revision 4c810f2, so nothing "
     "was compared.")
], ids=["nothing-before-it", "not-deployed"])
def test_a_deployment_with_no_comparison_behind_it_is_said_in_the_write_up_s_own_words(
        comparison: DeploymentComparison, said: str) -> None:
    # The read tier's answer is the Investigator's: bracketed for a model, and
    # with advice to one - "what it shipped can [be read], by reading the
    # repository at that revision" - which write-ups proposed as an item in 3
    # of 5. Only a comparison is a diff; the row of anything else says what
    # the history held.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(deployment_changes=[
                DeploymentChangesRecord(revision="4c810f2", said=["dont care"],
                                        comparison=comparison, service="io-shop")])
        ) \
        .when(
            lambda: the_deployment_changes_labelled(evidence)
        ) \
        .then(
            the_answer_was([CitedEvidence(label="D1", text=said)]))


@pytest.mark.unit
def test_a_file_as_it_ran_is_evidence_listed_directly_beneath_what_code_fix_read() -> None:
    # Six of six write-ups called the scrape config "Code-Fix's reading,
    # nothing ran" - right about where the text came from, since nothing in the
    # record held the file as it ran. Beneath F, where the model reaches for it
    # when it reasons about the file, and named by its path and the revision.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], candidates=[], actions=[],
                fix_explanation="some account of the code").model_copy(
                update={"files_as_they_ran": [FileAsItRan(
                    path="deploy/scrape.yaml", revision=SOME_DEPLOYED_REVISION,
                    as_read=False, content="selector:\n  port: metrics\n")]})
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("F1", "some account of the code"),
                                ("S1", "deploy/scrape.yaml at 53f02e9")])
        )


@pytest.mark.unit
def test_the_files_as_they_ran_are_labelled_in_the_order_of_their_paths() -> None:
    # Labelled in the order Code-Fix's reading named them, a reworded reading
    # swapped S1 and S2 under a write-up citing each for the other's claim. A
    # file's path holds whatever the reading says.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], candidates=[], actions=[],
                fix_explanation="some account of the code").model_copy(
                update={"files_as_they_ran": [
                    FileAsItRan(path="deploy/values-production.yaml",
                                revision=SOME_DEPLOYED_REVISION, as_read=False,
                                content="portName: http-metrics\n"),
                    FileAsItRan(path="deploy/scrape.yaml", revision=SOME_DEPLOYED_REVISION,
                                as_read=False, content="selector:\n  port: metrics\n")]})
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("F1", "some account of the code"),
                                ("S1", "deploy/scrape.yaml at 53f02e9"),
                                ("S2", "deploy/values-production.yaml at 53f02e9")])
        )


@pytest.mark.unit
def test_a_file_as_it_ran_opens_at_its_path_where_the_deploy_that_ran_it_can_be_opened() -> None:
    # The document names the file and leaves its text to the model's brief, so
    # a reader who wants the text needs somewhere to open it - at the revision
    # that ran, not on a branch that has moved on since.
    some_files_address = f"https://github.invalid/acme/shop/blob/{SOME_DEPLOYED_REVISION}"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"changes": [_a_deploy_of(SOME_DEPLOYED_REVISION, some_files_address)],
                        "files_as_they_ran": [FileAsItRan(
                            path="deploy/scrape.yaml", revision=SOME_DEPLOYED_REVISION,
                            as_read=False, content="selector:\n  port: metrics\n")]})
        ) \
        .when(
            lambda: [cited.address for cited in the_files_as_they_ran_labelled(evidence)]
        ) \
        .then(
            the_answer_was([f"{some_files_address}/deploy/scrape.yaml"])
        )


@pytest.mark.unit
def test_a_file_as_it_ran_whose_deploy_cannot_be_opened_opens_nowhere() -> None:
    # A deploy read before its files' address was carried, like one from a host
    # whose pages Argus does not know: an address made up for it would lead
    # nowhere.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"changes": [_a_deploy_of(SOME_DEPLOYED_REVISION, files_address=None)],
                        "files_as_they_ran": [FileAsItRan(
                            path="deploy/scrape.yaml", revision=SOME_DEPLOYED_REVISION,
                            as_read=False, content="selector:\n  port: metrics\n")]})
        ) \
        .when(
            lambda: [cited.address for cited in the_files_as_they_ran_labelled(evidence)]
        ) \
        .then(
            the_answer_was([None])
        )


@pytest.mark.unit
def test_the_uses_outside_the_patch_are_evidence_listed_beneath_what_code_fix_read() -> None:
    # A write-up wrote "nothing derived the month from history" from a reading
    # that listed the one reader adding it up to check it among those trusting
    # it. What each of those lines does is read off the code, and beneath F the
    # model has it where it reasons about the reading.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], candidates=[], actions=[],
                fix_explanation="some account of the code").model_copy(
                update={"uses_outside": [
                    CodeUse(name="total_this_month_cents", path="src/io_shop/spend_summary.py",
                            line=47, function="average_spend_per_item_this_month",
                            does="divides with it: account.total_this_month_cents // count"),
                    CodeUse(name="total_this_month_cents",
                            path="src/io_shop/spend_reconciliation.py", line=109,
                            function="reconcile_monthly_totals",
                            does="compares it with _bought_this_month(account)")]})
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([
                ("F1", "some account of the code"),
                ("U1", "total_this_month_cents at src/io_shop/spend_summary.py:47, in "
                       "average_spend_per_item_this_month: divides with it"),
                ("U2", "total_this_month_cents at src/io_shop/spend_reconciliation.py:109, in "
                       "reconcile_monthly_totals: compares it with _bought_this_month(account)")
            ])
        )


@pytest.mark.unit
def test_a_confirmed_demand_saturation_is_measured_in_rows_of_its_own() -> None:
    # The load and the CPU it asked for, which nothing else the write-up is
    # handed carries: a write-up told the volume only in the candidate's words,
    # which it may not cite, rested the root cause on Code-Fix's reading of a
    # slow default - the one deeper row it could cite. Measured by Argus, under
    # labels, so a step of the cause can rest on them.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", failure_mode="demand-saturation",
                                        tested=True, result="confirmed")]),
            measured := a_measured_incident(demand=DemandLevels(
                requests=LoadLevels(before=1200, while_broken=4200, at_its_highest=5400),
                cpu_share=LoadLevels(before=0.25, while_broken=0.8, at_its_highest=1.0)))
        ) \
        .when(
            lambda: the_cause_measured_labelled(evidence, measured)
        ) \
        .then(
            the_answer_was([
                CitedEvidence(label="R1",
                              text="Requests: 1200/min before it began, 4200/min on average "
                                   "while it was broken, 5400/min at its highest."),
                CitedEvidence(label="R2",
                              text="CPU in use, as a share of the service's CPU limit: 25.0% "
                                   "before it began, 80.0% on average while it was broken, "
                                   "100.0% at its highest.")
            ])
        )


@pytest.mark.unit
def test_a_confirmed_demand_saturation_s_rows_sit_after_the_actions_and_before_the_reading(
) -> None:
    # Beside what Argus did about it, and before Code-Fix's reading, whose
    # weight the line beneath the rows sets.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], fix_explanation="some account of the code",
                candidates=[a_candidate("some candidate", failure_mode="demand-saturation",
                                        tested=True, result="confirmed")],
                actions=[an_action("some action", verdict="confirmed")]),
            measured := a_measured_incident(demand=DemandLevels(
                requests=LoadLevels(before=1200, while_broken=4200, at_its_highest=5400),
                cpu_share=None))
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, measured)
        ) \
        .then(
            _labelled_in_order([
                ("C1", "some candidate"),
                ("M1", "some action"),
                ("R1", "Requests:"),
                ("F1", "some account of the code")
            ])
        )


@pytest.mark.unit
def test_what_code_fix_read_in_the_source_is_evidence_a_step_of_the_cause_may_cite() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(timeline=[], log_lines=[], candidates=[], actions=[],
                                           fix_explanation="some account of the code")
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("F1", "some account of the code")])
        )


def _a_change(reference: str = "dont care",
              summary: str = "dont care",
              actor: str | None = "dont care",
              occurred_at: str = A_MINUTE_BEFORE_THE_ONSET) -> ChangeEvent:
    """A flag toggled a minute before the onset, as the investigation read it."""
    return ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                       occurred_at=occurred_at,
                       reference=reference,
                       summary=summary,
                       actor=actor)


def _labelled_in_order(expected: list[tuple[str, str]]) -> Assertion[list[CitedEvidence]]:
    """Each label, and a piece of what it names - the rest of the line is the
    prompt's wording, and free to change."""
    def assertion(labelled: list[CitedEvidence]) -> bool:
        got = [(cited.label, cited.text) for cited in labelled]
        matching = (len(got) == len(expected)
                    and all(label == wanted_label and wanted_text in text
                            for (label, text), (wanted_label, wanted_text)
                            in zip(got, expected, strict=True)))

        if not matching:
            raise AssertionError(
                f"Expected the evidence labelled {expected}, in that order, got {got}.")

        return True

    return assertion


def _a_deploy_of(revision: str, files_address: str | None) -> ChangeEvent:
    """A deploy of `revision`, whose files open at `files_address` - nowhere,
    where it is `None`."""
    return ChangeEvent(kind=ChangeKind.DEPLOY,
                       occurred_at="2026-09-02T11:58:00Z",
                       reference=revision,
                       summary="dont care",
                       revision_source=RevisionSource(
                           repository="acme/shop",
                           repository_address="https://github.invalid/acme/shop",
                           revision_address=f"https://github.invalid/acme/shop/commit/{revision}",
                           files_address=files_address))
