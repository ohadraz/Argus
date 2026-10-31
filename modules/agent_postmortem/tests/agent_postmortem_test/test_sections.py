"""The sections code writes from the record, never asking the model.

Detection, trigger, resolution, the hypotheses considered, the action items the
record implies and the timeline are each a fact the incident left behind,
arranged. A section here that disagreed with the
record would be a postmortem describing a different incident from the page
beside it, so each case names a record and the section it must come out as.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from agent_postmortem import CandidateRecord, DeploymentChangesRecord, RefusalRecord
from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels, RuleSeriesSpan, Unmeasured
from agent_postmortem.log_groups import labels_reaching_into
from agent_postmortem.sections import (
    detection_of,
    hypotheses_of,
    impact_of,
    logs_in_the_gap_of,
    record_action_items_of,
    resolution_of,
    timeline_of,
    trigger_of,
)
from argus_core import parse_iso, to_iso
from argus_core.events import PATCH_LINE_INDENT, a_changed_file_line
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ActionProgress,
    CandidateConsidered,
    ChangeEvent,
    ChangeKind,
    CitedEvidence,
    Detection,
    ErrorRateLevels,
    FirstTold,
    ForCandidate,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    LogsInTheGap,
    OpenedPullRequest,
    Refusal,
    ReportChannel,
    ResolutionStep,
    RuleSeriesBeforeTheAlert,
    RuleSeriesHarm,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Verdict,
)
from argus_testkit import Scenario, the_answer_was

from agent_postmortem_test.framework.builders import (
    ONSET,
    RECOVERED_AT,
    STARTED_AT,
    a_candidate,
    a_measured_incident,
    a_resolution,
    a_timeline_entry,
    an_action,
    an_evidence_bundle,
)

SOME_FLAG = "monthly-spend-feature"
SOME_RULE = "kuki-rule"
SOME_REVISION = "5e07d73148d0a704b8fefe5f379bc652bb773655"
SOME_EARLIER_REVISION = "70dbcfde2b549d110a3817d92d60b6dd9786e78b"


@pytest.mark.unit
def test_detection_states_how_long_the_alert_took_after_the_onset() -> None:
    # The gap is carried rather than left to the reader: the page and the file
    # sent onwards would otherwise each subtract, and two subtractions are two
    # chances to disagree.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=ONSET, started_at=STARTED_AT,
                                           rule=SOME_RULE)
        ) \
        .when(
            lambda: detection_of(evidence)
        ) \
        .then(
            the_answer_was(Detection(alerted_at=STARTED_AT,
                                     rule=SOME_RULE,
                                     onset_at=ONSET,
                                     gap=STARTED_AT - ONSET))
        )


@pytest.mark.unit
def test_detection_without_an_onset_states_no_gap() -> None:
    # The alert's own time is not the onset, and a gap of nothing measured from
    # it would read as an alert that fired the moment the service broke.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, rule=SOME_RULE)
        ) \
        .when(
            lambda: detection_of(evidence)
        ) \
        .then(
            the_answer_was(Detection(alerted_at=STARTED_AT,
                                     rule=SOME_RULE,
                                     onset_at=None,
                                     gap=None))
        )


@pytest.mark.unit
def test_detection_is_dated_by_when_the_alert_fired_not_when_argus_heard() -> None:
    # A sender holds an alert back before sending it - Grafana groups and
    # waits - so the incident opens after the alert fired, and a gap measured
    # to the opening would count the delivery as detection.
    some_firing = STARTED_AT - timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=ONSET, started_at=STARTED_AT,
                                           alerted_at=some_firing, rule=SOME_RULE)
        ) \
        .when(
            lambda: detection_of(evidence)
        ) \
        .then(
            the_answer_was(Detection(alerted_at=some_firing,
                                     rule=SOME_RULE,
                                     onset_at=ONSET,
                                     gap=some_firing - ONSET))
        )


@pytest.mark.unit
def test_detection_carries_what_the_alert_said_under_the_label_it_is_cited_by() -> None:
    # The check that paged measured what it paged on, and a chain's symptom
    # rests on it - so it has a row to lead to, like everything else cited.
    some_finding = "240 of 240 shopper totals do not reconcile with the purchases behind them"

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"alert_finding": some_finding})
        ) \
        .when(
            lambda: detection_of(evidence).said
        ) \
        .then(
            the_answer_was(CitedEvidence(label="AL1", text=some_finding))
        )


@pytest.mark.unit
def test_detection_carries_when_argus_first_posted_about_the_incident() -> None:
    # Written by code rather than left to the model: a write-up told only that
    # nobody was paged said nobody was told at all, of an incident Argus had
    # announced in its thread.
    some_post = FirstTold(channel=ReportChannel.SLACK, at=STARTED_AT + timedelta(seconds=2))

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"first_told": some_post})
        ) \
        .when(
            lambda: detection_of(evidence).first_told
        ) \
        .then(
            the_answer_was(some_post)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("rule_waits", "rule_wait_unread"), [
    (timedelta(minutes=5), False),
    (None, True)
], ids=["read", "unread"])
def test_detection_carries_how_long_the_rule_waits_as_it_was_measured(
        rule_waits: timedelta | None, rule_wait_unread: bool) -> None:
    # The wait is part of what a reader weighs the gap against, and a rule
    # nobody could read is carried as unread rather than as one that fires at
    # once.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=ONSET, started_at=STARTED_AT,
                                           rule=SOME_RULE)
        ) \
        .when(
            lambda: detection_of(evidence, rule_waits=rule_waits,
                                 rule_wait_unread=rule_wait_unread)
        ) \
        .then(
            the_answer_was(Detection(alerted_at=STARTED_AT,
                                     rule=SOME_RULE,
                                     onset_at=ONSET,
                                     gap=STARTED_AT - ONSET,
                                     rule_waits=rule_waits,
                                     rule_wait_unread=rule_wait_unread))
        )


@pytest.mark.unit
@pytest.mark.parametrize("held", [True, False, None], ids=["held", "did-not-hold", "unknown"])
def test_detection_carries_whether_the_rule_held_before_the_onset_as_measured(
        held: bool | None) -> None:
    # The writer has the series and the page does not, so what the minutes
    # before the onset said travels on the detection.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=ONSET, started_at=STARTED_AT,
                                           rule=SOME_RULE)
        ) \
        .when(
            lambda: detection_of(evidence, held_before_the_onset=held).held_before_the_onset
        ) \
        .then(
            the_answer_was(held)
        )


@pytest.mark.unit
def test_the_trigger_is_the_change_the_confirmed_candidate_blamed() -> None:
    # Dated by the change the investigation read, the latest one to that
    # subject - an earlier toggle of the same flag is history, not the trigger.
    the_change = "2026-09-02T11:59:52Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[
                    a_candidate("dont care", subject="some-other-flag",
                                tested=True, result=Verdict.REFUTED),
                    a_candidate("dont care", subject=SOME_FLAG,
                                from_state="off", to_state="on",
                                tested=True, result=Verdict.CONFIRMED)
                ],
                changes=[
                    _a_change_to(SOME_FLAG, at="2026-09-01T09:00:00Z"),
                    _a_change_to(SOME_FLAG, at=the_change),
                    _a_change_to("some-other-flag", at="2026-09-02T11:59:59Z")
                ])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject=SOME_FLAG,
                                   from_state="off",
                                   to_state="on",
                                   changed_at=parse_iso(the_change),
                                   kind=ChangeKind.FLAG_TOGGLE,
                                   dated_by="P2"))
        )


@pytest.mark.unit
def test_the_trigger_names_who_made_the_change() -> None:
    # A change is somebody's - the reader's next question after what changed
    # is who to ask about it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_FLAG,
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                     occurred_at="2026-09-02T11:59:52Z",
                                     reference=SOME_FLAG,
                                     summary="dont care",
                                     actor="kuki")])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "actor", None)
        ) \
        .then(
            the_answer_was("kuki")
        )


@pytest.mark.unit
def test_a_trigger_no_change_dates_is_undated() -> None:
    # The candidate was confirmed and says what moved, and the change itself
    # was never read - a trigger with its moment unknown, rather than one dated
    # by a guess.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_FLAG,
                                        from_state="off", to_state="on",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject=SOME_FLAG,
                                   from_state="off",
                                   to_state="on",
                                   changed_at=None))
        )


@pytest.mark.unit
def test_a_confirmed_candidate_that_names_no_change_is_no_trigger() -> None:
    # Confirmed, but with no state it moved between and no change read to its
    # subject - a dependency that slowed has no change behind it. The subject
    # alone is the candidate again, already in the hypotheses, and under
    # "Trigger" it would read as a change somebody made.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="some-dependency",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_revision_is_dated_by_the_deploy_that_put_it_out() -> None:
    # A deployment's subject is the investigation's own words about it, and the
    # revision it blames is the state it moved to - so that state, not the
    # wording around it, is what the deploy is found by.
    the_deploy = "2026-10-12T02:07:00Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject=f"revision {SOME_REVISION} (dont care)",
                                        from_state=SOME_EARLIER_REVISION,
                                        to_state=SOME_REVISION,
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_EARLIER_REVISION, at="2026-10-11T22:07:00Z"),
                         _a_deploy_of(SOME_REVISION, at=the_deploy)])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "changed_at", None)
        ) \
        .then(
            the_answer_was(parse_iso(the_deploy))
        )


@pytest.mark.unit
def test_a_revision_is_found_among_the_words_of_the_state_it_moved_to() -> None:
    # The state is the investigation's wording too, and can carry the revision
    # among other words. The revision moved *from* is named in the subject as
    # well, and deployed later here, so a match on the subject would date the
    # wrong one.
    the_deploy = "2026-10-12T02:33:00Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject=f"rollout from {SOME_EARLIER_REVISION} "
                                                f"to {SOME_REVISION}",
                                        from_state=SOME_EARLIER_REVISION,
                                        to_state=f"{SOME_REVISION} (dont care)",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at=the_deploy),
                         _a_deploy_of(SOME_EARLIER_REVISION, at="2026-10-12T02:35:00Z")])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "changed_at", None)
        ) \
        .then(
            the_answer_was(parse_iso(the_deploy))
        )


@pytest.mark.unit
def test_a_revision_blamed_by_name_moved_from_the_one_deployed_before_it() -> None:
    # The investigation named the revision as its subject and gave no states,
    # so the trigger said a deploy happened and not what it put out. What it
    # replaced is the deploy just before it - the one its diff is compared
    # against - not an older one, and not one that came after.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_REVISION)],
                changes=[_a_deploy_of("some-older-revision", at="2026-10-15T11:41:00Z"),
                         _a_deploy_of(SOME_EARLIER_REVISION, at="2026-10-15T15:41:00Z"),
                         _a_deploy_of(SOME_REVISION, at="2026-10-15T19:41:00Z"),
                         _a_deploy_of("some-later-revision", at="2026-10-15T23:41:00Z")])
        ) \
        .when(
            lambda: _the_move(trigger_of(evidence))
        ) \
        .then(
            the_answer_was((SOME_EARLIER_REVISION, SOME_REVISION))
        )


@pytest.mark.unit
def test_a_revision_blamed_by_name_with_no_deploy_read_before_it_moved_from_unknown() -> None:
    # What it put out is its own; what it replaced is only known where that
    # deploy was read, and is not guessed.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_REVISION)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-10-15T19:41:00Z")])
        ) \
        .when(
            lambda: _the_move(trigger_of(evidence))
        ) \
        .then(
            the_answer_was((None, SOME_REVISION))
        )


@pytest.mark.unit
def test_a_revision_blamed_by_name_did_not_replace_itself() -> None:
    # Deployed again with nothing changed - a re-sync - it is still the
    # revision it replaced that the trigger names, not itself.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_REVISION)],
                changes=[_a_deploy_of(SOME_EARLIER_REVISION, at="2026-10-15T15:41:00Z"),
                         _a_deploy_of(SOME_REVISION, at="2026-10-15T19:41:00Z"),
                         _a_deploy_of(SOME_REVISION, at="2026-10-15T19:51:00Z")])
        ) \
        .when(
            lambda: _the_move(trigger_of(evidence))
        ) \
        .then(
            the_answer_was((SOME_EARLIER_REVISION, SOME_REVISION))
        )


@pytest.mark.unit
def test_a_reference_that_is_only_part_of_a_word_dates_nothing() -> None:
    # A whole word of the state or nothing: a short reference found inside a
    # longer one is a coincidence of spelling, not the same change.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject="dont care",
                                        to_state=SOME_REVISION,
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION[:7], at="2026-10-12T02:07:00Z")])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "changed_at", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_change_that_names_nothing_dates_nothing() -> None:
    # A deploy whose revision came back empty is a change to no revision in
    # particular - not a word of every state there is.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject="dont care",
                                        to_state=f"{SOME_REVISION} (dont care)",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of("", at="2026-10-12T02:07:00Z")])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "changed_at", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_no_confirmed_candidate_establishes_no_trigger() -> None:
    # A refuted candidate is not a weaker trigger. It is not one.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_FLAG,
                                        tested=True, result=Verdict.REFUTED),
                            a_candidate("dont care", subject="some-other-flag")],
                changes=[_a_change_to(SOME_FLAG, at="2026-09-02T11:59:52Z")])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_leading_candidate_never_tested_names_a_suspected_trigger() -> None:
    # Nothing confirmed it, because the action that would have was only
    # recommended - and nothing refuted it either. Not a trigger, and not
    # nothing: the change it blames, said as suspected.
    the_change = "2026-09-02T11:59:52Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_FLAG,
                                        from_state="off", to_state="on"),
                            a_candidate("dont care", subject="some-other-flag")],
                changes=[_a_change_to(SOME_FLAG, at=the_change)])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject=SOME_FLAG,
                                   from_state="off",
                                   to_state="on",
                                   changed_at=parse_iso(the_change),
                                   kind=ChangeKind.FLAG_TOGGLE,
                                   suspected=True,
                                   dated_by="P1"))
        )


@pytest.mark.unit
def test_a_trigger_names_its_own_change_where_another_shares_its_instant() -> None:
    # A decoy flag moved at the same instant. Found again by its instant, the
    # trigger's change was whichever of the two was listed first - so the
    # change chosen is carried out under its row's label.
    the_instant = "2026-09-02T11:59:52Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_FLAG,
                                        from_state="off", to_state="on",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_change_to("some-decoy-flag", at=the_instant),
                         _a_change_to(SOME_FLAG, at=the_instant)])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "dated_by", None)
        ) \
        .then(
            the_answer_was("P2")
        )


@pytest.mark.unit
def test_a_suspect_whose_change_was_never_read_is_no_trigger() -> None:
    # Suspected on the investigation's word alone, with no change read to
    # point at: that is the candidate, already in the hypotheses, and a
    # trigger section repeating it would add nothing but the word "trigger".
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_FLAG)],
                changes=[])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_suspect_named_in_words_is_carried_by_the_deploy_that_moved_its_value() -> None:
    # The investigation names a setting in its own words - "metrics port name"
    # - which no line of a diff spells, and nothing recommended would have
    # tested it. What the diff does spell is the value: a key that shares a
    # word with the setting's name losing the one state and gaining the other
    # in one hunk, in the one deploy made by the onset.
    the_deploy = "2026-09-02T11:58:00Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="metrics port name",
                                        from_state="metrics", to_state="http-metrics")],
                changes=[_a_deploy_of(SOME_REVISION, at=the_deploy, actor="kuki")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,10 +1,10 @@ ports:",
                    "   web:",
                    "-    portName: web",
                    "+    portName: http",
                    "   metrics:",
                    "-    portName: metrics",
                    "+    portName: http-metrics"])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject="metrics port name",
                                   from_state="metrics",
                                   to_state="http-metrics",
                                   changed_at=parse_iso(the_deploy),
                                   actor="kuki",
                                   suspected=True,
                                   carried_by="P1"))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("subject", "from_state", "to_state", "moved"), [
    ("metrics port name", "metrics", "http-metrics",
     [" monitoring:", "-  scrapeTarget: metrics", "+  scrapeTarget: http-metrics"]),
    ("the categoriser model version", "1", "2",
     [" fraudScorer:", "-  replicas: 1", "+  replicas: 2"]),
    ("the categoriser model version", "1", "2",
     [" fraudScorer:", "-  version: 1", "+  version: 2"]),
    ("metrics port name", "metrics", "http-metrics",
     [" metrics:", "-  portName: metrics", " web:", "+  portName: http-metrics"])],
    ids=["a-key-sharing-no-word-with-it", "generic-states-on-another-key",
         "one-generic-word-shared", "lost-under-one-parent-gained-under-another"])
def test_a_value_moving_on_a_key_the_setting_s_name_does_not_share_carries_nothing(
        subject: str, from_state: str, to_state: str, moved: list[str]) -> None:
    # Two states alone say little - one to two, v1 to v2 - and any key moving
    # that way would be credited. The key, or the key it sits under, has to
    # share a word with the name the investigation gave the setting.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=subject,
                                        from_state=from_state, to_state=to_state)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION,
                                                        ["@@ -1,3 +1,3 @@", *moved])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_setting_a_deploy_carried_is_dated_and_credited_as_that_deploy() -> None:
    # A setting is no change's reference: what carried it is a deploy, and only
    # that deploy's diff shows the setting moving - every part of its name in
    # one hunk, and its last on the lines that moved it from one state to the
    # other. Found there, the trigger is dated and credited as the deploy is,
    # and names its row.
    the_deploy = "2026-09-02T11:58:00Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="categoriser.model",
                                        from_state="v1", to_state="v2",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_EARLIER_REVISION, at="2026-09-01T09:00:00Z"),
                         _a_deploy_of(SOME_REVISION, at=the_deploy, actor="kuki")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -61,4 +61,4 @@ cache:",
                    " categoriser:",
                    "-  model: v1",
                    "+  model: v2"])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject="categoriser.model",
                                   from_state="v1",
                                   to_state="v2",
                                   changed_at=parse_iso(the_deploy),
                                   actor="kuki",
                                   carried_by="P2"))
        )


@pytest.mark.unit
def test_a_setting_of_the_same_last_name_moving_elsewhere_carries_nothing() -> None:
    # "model" ends the name of many settings. A scorer's model going from v1 to
    # v2 is not the categoriser's - though the categoriser's own block sits in
    # the same hunk, a line above the scorer's.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="categoriser.model",
                                        from_state="v1", to_state="v2",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -61,7 +61,7 @@ cache:",
                    " categoriser:",
                    "   model: v1",
                    " fraud_scorer:",
                    "-  model: v1",
                    "+  model: v2"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_setting_two_deploys_both_moved_carries_neither() -> None:
    # Which of two carried it is not something a diff can say, and a trigger
    # credited to either would be a guess said as a finding.
    the_move = [" categoriser:", "-  model: v1", "+  model: v2"]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="categoriser.model",
                                        from_state="v1", to_state="v2",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_EARLIER_REVISION, at="2026-09-02T11:50:00Z"),
                         _a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_EARLIER_REVISION, the_move),
                                    _what_the_deploy_of(SOME_REVISION, the_move)])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_deploy_after_the_onset_carried_nothing_that_began_it() -> None:
    # A change made after the incident began did not begin it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=ONSET,
                candidates=[a_candidate("dont care", subject="categoriser.model",
                                        from_state="v1", to_state="v2",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at=to_iso(ONSET + timedelta(minutes=5)))],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    " categoriser:", "-  model: v1", "+  model: v2"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_comment_or_a_blank_line_over_a_setting_does_not_hide_its_parent() -> None:
    # Walking up from the setting to its parent, a comment set in less far and
    # a blank line name nothing: the parent is the nearest line that names
    # something.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="categoriser.model",
                                        from_state="v1", to_state="v2",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    " categoriser:",
                    "",
                    " # retrained on the grown catalogue",
                    "-  model: v1",
                    "+  model: v2"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was("P1")
        )


@pytest.mark.unit
def test_a_setting_written_flat_is_carried_by_the_deploy_that_moved_it() -> None:
    # A flat key names the setting whole on its own line, with no parent above
    # it to walk up to - and "model" inside "categoriser.model" is no word of
    # its own.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="categoriser.model",
                                        from_state="v1", to_state="v2",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "-categoriser.model: v1",
                    "+categoriser.model: v2"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was("P1")
        )


@pytest.mark.unit
def test_a_setting_named_with_its_file_is_carried_by_the_deploy_that_moved_it_there() -> None:
    # The investigation names a nested key with the file it lives in -
    # `path:key`. Read as one dotted name, the file became a parent no line
    # names, and the deploy that moved the key carried nothing: the document
    # said no trigger was established beside a root cause naming that deploy.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject="deploy/values-production.yaml:"
                                                "ports.metrics.portName",
                                        from_state="metrics", to_state="http-metrics",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,4 +1,4 @@",
                    " ports:",
                    "   metrics:",
                    "-    portName: metrics",
                    "+    portName: http-metrics"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was("P1")
        )


@pytest.mark.unit
def test_a_setting_named_with_its_file_moving_in_another_file_carries_nothing() -> None:
    # The file is part of the name: the same key moving in another file is
    # another setting.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject="deploy/scrape.yaml:ports.metrics.portName",
                                        from_state="metrics", to_state="http-metrics",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,4 +1,4 @@",
                    " ports:",
                    "   metrics:",
                    "-    portName: metrics",
                    "+    portName: http-metrics"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_file_s_setting_with_no_states_is_carried_by_the_deploy_that_changed_it() -> None:
    # The investigation names a key with its file and says no states: what
    # carried it is the deploy whose part of the diff about that file changes
    # the key itself.
    the_deploy = "2026-09-02T11:58:00Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject="deploy/values-production.yaml:"
                                                "ports.metrics.portName")],
                changes=[_a_deploy_of(SOME_REVISION, at=the_deploy, actor="kuki")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,4 +1,4 @@",
                    " ports:",
                    "   metrics:",
                    "-    portName: metrics",
                    "+    portName: http-metrics"])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject="deploy/values-production.yaml:ports.metrics.portName",
                                   from_state=None,
                                   to_state=None,
                                   changed_at=parse_iso(the_deploy),
                                   actor="kuki",
                                   suspected=True,
                                   carried_by="P1"))
        )


@pytest.mark.unit
def test_a_file_s_setting_with_no_states_is_not_carried_by_another_change_to_it() -> None:
    # The key is the setting, not the file it lives in: a deploy that changed
    # the file and left the key alone did not carry it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject="deploy/values-production.yaml:"
                                                "ports.metrics.portName")],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,5 +1,5 @@",
                    "-replicas: 2",
                    "+replicas: 3",
                    " ports:",
                    "   metrics:",
                    "     portName: metrics"])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_comment_naming_a_file_s_setting_does_not_carry_it() -> None:
    # A comment that names the key is not the key's line: a deploy that added
    # one and left the setting alone did not carry it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject="deploy/values-production.yaml:"
                                                "ports.metrics.portName")],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,4 +1,5 @@",
                    " ports:",
                    "   metrics:",
                    "+    # portName must match the scrape",
                    "     portName: metrics"])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_comment_moving_between_a_setting_s_states_does_not_carry_it() -> None:
    # A comment can spell a setting and its states without being it: a deploy
    # that rewrote the comment and left the value moved nothing.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="categoriser.model",
                                        from_state="v1", to_state="v2",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    " categoriser:",
                    "-  # model: v1 until the catalogue grows",
                    "+  # model: v2 once the catalogue grows",
                    "   model: v1"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_value_followed_by_a_comment_is_carried_by_the_deploy_that_moved_it() -> None:
    # A comment after the value is no part of it: the key still goes from the
    # one state to the other.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="metrics port name",
                                        from_state="metrics", to_state="http-metrics")],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,3 +1,3 @@ ports:",
                    "   metrics:",
                    "-    portName: metrics  # what the scrape selects",
                    "+    portName: http-metrics  # the platform's convention"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was("P1")
        )


@pytest.mark.unit
def test_a_comment_naming_a_setting_in_words_does_not_hide_its_value_moving() -> None:
    # A comment that happens to spell the investigation's own words for the
    # setting is not a line naming the setting, so the value is still read.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="metrics port name",
                                        from_state="metrics", to_state="http-metrics")],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,3 +1,4 @@ ports:",
                    "   metrics:",
                    "+    # the metrics port name follows the platform's convention",
                    "-    portName: metrics",
                    "+    portName: http-metrics"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was("P1")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("from_state", "to_state", "changed"), [
    ("6379", "6380", [" cache:", "-  port: 6379", "+  port: 6380"]),
    (None, None, [" cache:", "-  port: 6379", "+  port: 6380"])],
    ids=["with-its-states", "with-no-states"])
def test_a_file_s_setting_set_off_by_a_space_is_carried_by_the_deploy_that_moved_it(
        from_state: str | None, to_state: str | None, changed: list[str]) -> None:
    # The investigation sets the file before the key with a space between them
    # rather than a colon: the file is still the file the diff names, and the
    # rest is the key in it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care",
                                        subject="deploy/values-production.yaml cache.port",
                                        from_state=from_state, to_state=to_state)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION,
                                                        ["@@ -1,3 +1,3 @@", *changed])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was("P1")
        )


@pytest.mark.unit
@pytest.mark.parametrize("subject", ["deploy/scrape.yaml ports.metrics.portName",
                                     "deploy/scrape.yaml portName",
                                     "deploy/scrape.yaml metrics port",
                                     "deploy/scrape.yaml"],
                         ids=["a-dotted-key", "a-last-name", "words", "the-file-alone"])
def test_a_setting_in_another_file_carries_nothing(subject: str) -> None:
    # The file is part of the name however it is set off from the key - by a
    # space too, where no diff read names it - and named alone it is the whole
    # of it: the same value moving in another file is another setting, though
    # that file's key shares the words of the one named.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=subject,
                                        from_state="metrics", to_state="http-metrics",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,4 +1,4 @@",
                    " ports:",
                    "   metrics:",
                    "-    portName: metrics",
                    "+    portName: http-metrics"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_file_named_with_states_is_carried_by_the_deploy_moving_one_key_between_them() -> None:
    # The investigation names the file alone and the two states: the setting is
    # the one key in that file's part of the diff going from the one to the
    # other.
    the_deploy = "2026-09-02T11:58:00Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="deploy/values-production.yaml",
                                        from_state="metrics", to_state="http-metrics")],
                changes=[_a_deploy_of(SOME_REVISION, at=the_deploy, actor="kuki")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,7 +1,7 @@ ports:",
                    "   web:",
                    "-    portName: web",
                    "+    portName: http",
                    "   metrics:",
                    "-    portName: metrics",
                    "+    portName: http-metrics"])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject="deploy/values-production.yaml",
                                   from_state="metrics",
                                   to_state="http-metrics",
                                   changed_at=parse_iso(the_deploy),
                                   actor="kuki",
                                   suspected=True,
                                   carried_by="P1"))
        )


@pytest.mark.unit
def test_a_file_named_with_states_two_of_its_keys_moved_between_carries_nothing() -> None:
    # Two keys in the file going between the same two states, and the diff
    # cannot say which of them the investigation meant.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="deploy/values-production.yaml",
                                        from_state="metrics", to_state="http-metrics",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,7 +1,7 @@",
                    " ports:",
                    "   metrics:",
                    "-    portName: metrics",
                    "+    portName: http-metrics",
                    " scrape:",
                    "-  selects: metrics",
                    "+  selects: http-metrics"])])
        ) \
        .when(
            lambda: getattr(trigger_of(evidence), "carried_by", None)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_suspect_naming_a_file_is_carried_by_the_deploy_that_changed_it() -> None:
    # The investigation blames a file, not a setting in it, and says no states:
    # the file is what the diff names a deploy as changing. That deploy, made by
    # the onset, is the change - dated and credited as it is, and suspected.
    the_deploy = "2026-09-02T11:58:00Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="deploy/values-production.yaml")],
                changes=[_a_deploy_of(SOME_REVISION, at=the_deploy, actor="kuki")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,1 +1,1 @@ ports:",
                    "-  portName: metrics",
                    "+  portName: http-metrics"])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject="deploy/values-production.yaml",
                                   from_state=None,
                                   to_state=None,
                                   changed_at=parse_iso(the_deploy),
                                   actor="kuki",
                                   suspected=True,
                                   carried_by="P1"))
        )


@pytest.mark.unit
def test_a_file_named_only_inside_a_deploys_patch_was_not_changed_by_it() -> None:
    # A comment pointing at another file names it without changing it: only
    # the line the diff names a changed file on says the deploy changed it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="deploy/scrape.yaml")],
                changes=[_a_deploy_of(SOME_REVISION, at="2026-09-02T11:58:00Z")],
                deployment_changes=[_what_the_deploy_of(SOME_REVISION, [
                    "@@ -1,1 +1,2 @@ ports:",
                    "+# selected by deploy/scrape.yaml",
                    "   portName: metrics"])])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_resolution_lists_each_action_as_argus_took_it() -> None:
    # In the order taken, with what each came to and whether it still stands -
    # one sentence, because the reader of this table wants both at once.
    some_moment = STARTED_AT + timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("revert-feature-flag on monthly-spend-feature",
                          verdict=Verdict.CONFIRMED, standing="still in place",
                          has_a_way_back=True, taken_at=some_moment)
            ])
        ) \
        .when(
            lambda: resolution_of(evidence)
        ) \
        .then(
            the_answer_was([ResolutionStep(
                at=some_moment,
                action="revert-feature-flag on monthly-spend-feature",
                by="Argus",
                has_a_way_back=True,
                outcome="confirmed, still in place",
                label="M1"
            )])
        )


@pytest.mark.unit
@pytest.mark.parametrize("left_behind_known", [True, False], ids=["known", "not-known"])
def test_resolution_says_whether_what_each_action_left_is_known(
        left_behind_known: bool) -> None:
    # What the page's Kind column is read from: an action nobody can account
    # for is not one with nothing to put back.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("Did not roll back the deployment of io-shop",
                          verdict=Verdict.ESCALATED,
                          standing="not known whether anything was changed",
                          has_a_way_back=False, left_behind_known=left_behind_known)
            ])
        ) \
        .when(
            lambda: [step.left_behind_known for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was([left_behind_known])
        )


@pytest.mark.unit
def test_resolution_lists_a_refusal_to_act_in_its_place_among_the_actions() -> None:
    # Declining an action is how an incident ended as much as taking one is -
    # the one rollback that would answer it undoing a change made on purpose.
    # Said and dated as the timeline's line says it, and under no label:
    # nothing was done, so no prose cites it as an action. And which refusal it
    # was, which is what the review reads to say whose the next step is.
    the_refusal = STARTED_AT + timedelta(minutes=1)
    the_action = STARTED_AT + timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[a_timeline_entry("Refused to act - some reason", at=the_refusal)],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED,
                                   standing="still in place", has_a_way_back=True,
                                   taken_at=the_action)]
            ).model_copy(update={"refusals": [
                RefusalRecord(line=0, refusal=Refusal.WOULD_UNDO_A_MEANT_CHANGE)]})
        ) \
        .when(
            lambda: [(step.at, step.action, step.has_a_way_back, step.outcome, step.label,
                      step.refused)
                     for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was([
                (the_refusal, "Refused to act - some reason", False, "not taken", None,
                 Refusal.WOULD_UNDO_A_MEANT_CHANGE),
                (the_action, "dont care", True, "confirmed, still in place", "M1", None)
            ])
        )


@pytest.mark.unit
def test_an_action_no_verdict_was_reached_on_says_so() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("dont care", verdict=None, standing="put back when it did not help")
            ])
        ) \
        .when(
            lambda: [step.outcome for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was(["no verdict recorded, put back when it did not help"])
        )


@pytest.mark.unit
def test_an_action_a_person_s_ending_stopped_was_not_judged() -> None:
    # Nothing was measured, so nothing was judged - and "withdrawn" said a
    # person withdrew an incident they may have resolved.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("dont care", verdict=Verdict.STOPPED, standing="still in place")
            ])
        ) \
        .when(
            lambda: [step.outcome for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was(["not judged, still in place"])
        )


@pytest.mark.unit
def test_an_action_a_person_s_ending_stopped_before_it_was_done_was_not_taken() -> None:
    # A person ended the incident between the walk choosing the action and
    # taking it. Nothing was judged because nothing was done - "not judged"
    # would say a test was begun.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("dont care", verdict=Verdict.STOPPED,
                          standing="nothing was changed").model_copy(
                    update={"progress": ActionProgress.NOT_PERFORMED})
            ])
        ) \
        .when(
            lambda: [step.outcome for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was(["not taken, nothing was changed"])
        )


@pytest.mark.unit
def test_an_action_never_performed_keeps_the_verdict_it_came_back_with() -> None:
    # Why it was not done is the verdict's to say - a platform that did not
    # answer is a different finding from a person's ending.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("dont care", verdict=Verdict.PLATFORM_UNREACHABLE,
                          standing="nothing was changed").model_copy(
                    update={"progress": ActionProgress.NOT_PERFORMED})
            ])
        ) \
        .when(
            lambda: [step.outcome for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was(["platform-unreachable, nothing was changed"])
        )


@pytest.mark.unit
def test_an_action_that_left_automatic_sync_off_is_marked_as_having_done_so() -> None:
    # Argus stops the platform syncing an application from its repository to
    # act on it, and leaves it stopped while the change stands - so nothing
    # merged reaches the service until somebody turns it back on. Marked on the
    # row of the action that did it and on no other, and apart from what the
    # action came to: the outcome is cited wherever the action is, and said
    # there the sync is said in every place that cites it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("rolled back io-shop", verdict=Verdict.CONFIRMED,
                          standing="still in place", paused_sync_of="io-shop"),
                an_action("scaled io-shop out", verdict=Verdict.REFUTED,
                          standing="put back when it did not help")
            ])
        ) \
        .when(
            lambda: [(step.outcome, step.sync_left_off) for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was([("confirmed, still in place", True),
                            ("refuted, put back when it did not help", False)])
        )


@pytest.mark.unit
def test_each_action_is_labelled_as_the_prompt_named_it() -> None:
    # The model cites an action in its prose as M1, M2; the row carries the
    # same label, so the page can point the prose at it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("dont care", verdict=Verdict.REFUTED),
                an_action("dont care either", verdict=Verdict.CONFIRMED)
            ])
        ) \
        .when(
            lambda: [step.label for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was(["M1", "M2"])
        )


@pytest.mark.unit
def test_every_candidate_is_listed_with_what_became_of_it() -> None:
    # Including the one nobody tried: an investigation that ran out of options
    # and one that was right first time differ in what was left on the list.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("a flag change", tested=True, result=Verdict.CONFIRMED,
                            confidence=0.8),
                a_candidate("a bad deployment", confidence=0.1)
            ])
        ) \
        .when(
            lambda: hypotheses_of(evidence)
        ) \
        .then(
            the_answer_was([
                HypothesisConsidered(summary="a flag change", confidence=0.8,
                                     result="confirmed", label="C1"),
                HypothesisConsidered(summary="a bad deployment", confidence=0.1,
                                     result="never tried", label="C2")
            ])
        )


@pytest.mark.unit
def test_a_candidate_never_tried_says_why_where_its_row_recorded_it() -> None:
    # The gate writes on the row why it held the test back, and "never tried"
    # alone dropped it - so the table, and the brief that says it in the same
    # words, left a reader to guess whether the investigation ran out or Argus
    # declined.
    some_reason = "some reason the gate held its test back"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("dont care", result=some_reason)])
        ) \
        .when(
            lambda: [hypothesis.result for hypothesis in hypotheses_of(evidence)]
        ) \
        .then(
            the_answer_was([f"never tried: {some_reason}"])
        )


@pytest.mark.unit
def test_a_candidate_acted_on_and_never_judged_was_tried_not_judged() -> None:
    # A person ended the incident while the service was watched, so the row was
    # left untested - nothing was measured. The action was its test all the
    # same, and "never tried" said no test was begun.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("dont care").model_copy(update={
                    "progress": ActionProgress.PERFORMED, "verdict_recorded": True})])
        ) \
        .when(
            lambda: [hypothesis.result for hypothesis in hypotheses_of(evidence)]
        ) \
        .then(
            the_answer_was(["tried, not judged"])
        )


@pytest.mark.unit
def test_a_candidate_acted_on_with_no_verdict_on_file_was_tried_with_none_recorded() -> None:
    # The worker died with the change made: before the wait judged it, or
    # before it wrote down what the wait judged - and the row cannot say which.
    # "Not judged" would claim the first.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("dont care").model_copy(update={
                    "progress": ActionProgress.PERFORMED, "verdict_recorded": False})])
        ) \
        .when(
            lambda: [hypothesis.result for hypothesis in hypotheses_of(evidence)]
        ) \
        .then(
            the_answer_was(["tried, no verdict recorded"])
        )


@pytest.mark.unit
@pytest.mark.parametrize("progress", [ActionProgress.CLAIMED, ActionProgress.UNKNOWN],
                         ids=["claimed", "unknown"])
def test_a_candidate_whose_action_nobody_can_account_for_is_not_known_to_be_tried(
        progress: ActionProgress) -> None:
    # The claim never said more. The change may have been made, so "never
    # tried" would tell a reader the service was left alone when nobody knows.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("dont care").model_copy(update={"progress": progress})])
        ) \
        .when(
            lambda: [hypothesis.result for hypothesis in hypotheses_of(evidence)]
        ) \
        .then(
            the_answer_was(["not known whether tried"])
        )


@pytest.mark.unit
def test_a_candidate_whose_attempt_ended_before_its_action_says_its_action_was_not_taken() -> None:
    # A platform that never answered, an action with nowhere left to go: a row
    # is written, and nothing was done - so the cause was not tried. Said as
    # its action not taken rather than never tried, which beside the action's
    # own row about this cause reads as no attempt at all.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("dont care").model_copy(update={
                    "progress": ActionProgress.NOT_PERFORMED, "verdict_recorded": True})])
        ) \
        .when(
            lambda: [hypothesis.result for hypothesis in hypotheses_of(evidence)]
        ) \
        .then(
            the_answer_was(["action not taken"])
        )


@pytest.mark.unit
def test_an_action_says_the_candidate_it_was_for_under_that_candidate_s_label() -> None:
    # The label the candidate's row goes by, so the resolution can point at it:
    # nothing else says which cause an action answered, and a reader left to
    # guess takes it for the leading candidate's.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("Rolled back the deployment of io-shop").model_copy(
                    update={"candidate": 3}),
                an_action("dont care")])
        ) \
        .when(
            lambda: [step.candidate for step in resolution_of(evidence)]
        ) \
        .then(
            the_answer_was(["C3", None])
        )


@pytest.mark.unit
def test_each_candidate_is_labelled_as_the_prompt_named_it() -> None:
    # The model cites a candidate in its prose as C1, C2; the row carries the
    # same label, so the page can point the prose at it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("dont care"),
                a_candidate("dont care either")
            ])
        ) \
        .when(
            lambda: [hypothesis.label for hypothesis in hypotheses_of(evidence)]
        ) \
        .then(
            the_answer_was(["C1", "C2"])
        )


@pytest.mark.unit
def test_candidates_blaming_the_same_move_are_one_row_under_each_label() -> None:
    # Two readings of one change are one cause, and listed twice they read as
    # two the investigation weighed. The row goes by the best-ranked one's
    # words and by every label, so a line citing either still lands on it; what
    # became of it is what became of the one tested. Each keeps its own words,
    # mode and confidence, and the row says whose test decided it: shown as the
    # row's own, one candidate's figures read as another's.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("the model was upgraded", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.8,
                            failure_mode="output-quality-degradation"),
                a_candidate("an alternative reading", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.3,
                            failure_mode="config-induced-failure",
                            tested=True, result=Verdict.CONFIRMED),
                a_candidate("a bad deploy", confidence=0.1)])
        ) \
        .when(
            lambda: hypotheses_of(evidence)
        ) \
        .then(
            the_answer_was([
                HypothesisConsidered(
                    summary="the model was upgraded", confidence=0.8, result="confirmed",
                    label="C1", also=["C2"],
                    members=[CandidateConsidered(label="C1", summary="the model was upgraded",
                                                 confidence=0.8,
                                                 failure_mode="output-quality-degradation"),
                             CandidateConsidered(label="C2", summary="an alternative reading",
                                                 confidence=0.3,
                                                 failure_mode="config-induced-failure")],
                    decided_by="C2"),
                HypothesisConsidered(summary="a bad deploy", confidence=0.1,
                                     result="never tried", label="C3")
            ])
        )


@pytest.mark.unit
def test_candidates_blaming_the_same_move_judged_alike_are_one_row() -> None:
    # Tested twice to the same verdict, what became of each is what became of
    # the one row, and nothing is hidden by showing it once.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("dont care", subject="categoriser.model", from_state="v1",
                            to_state="v2", tested=True, result=Verdict.REFUTED),
                a_candidate("dont care either", subject="categoriser.model", from_state="v1",
                            to_state="v2", tested=True, result=Verdict.REFUTED)])
        ) \
        .when(
            lambda: [(hypothesis.label, hypothesis.also, hypothesis.result)
                     for hypothesis in hypotheses_of(evidence)]
        ) \
        .then(
            the_answer_was([("C1", ["C2"], "refuted")])
        )


@pytest.mark.unit
@pytest.mark.parametrize("candidates", [
    pytest.param([a_candidate("dont care", subject="categoriser.model", from_state="v1",
                              to_state="v2", tested=True, result=Verdict.REFUTED),
                  a_candidate("dont care either", subject="categoriser.model", from_state="v1",
                              to_state="v2", tested=True, result=Verdict.CONFIRMED)],
                 id="judged-apart"),
    pytest.param([a_candidate("dont care"), a_candidate("dont care either")],
                 id="naming-no-subject")
])
def test_candidates_not_known_to_be_one_cause_are_rows_of_their_own(
    candidates: list[CandidateRecord]
) -> None:
    # Tested to different verdicts, two candidates are not one cause in the
    # record, and one row would show one verdict and hide the other. Naming no
    # subject, nothing says what either blamed.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=candidates)
        ) \
        .when(
            lambda: [(hypothesis.label, hypothesis.also) for hypothesis in hypotheses_of(evidence)]
        ) \
        .then(
            the_answer_was([("C1", []), ("C2", [])])
        )


@pytest.mark.unit
def test_the_record_implies_its_action_items_and_numbers_them_first() -> None:
    # What brought recovery is done; the fix proposed and the action Argus
    # declined are open, and nobody owns them yet. An action that did not help
    # is in Resolution, and is not something left to do.
    some_fix = OpenedPullRequest(number=7,
                                 url="https://github.invalid/ohadraz/io-shop/pull/7",
                                 branch="argus/fix-abc")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                actions=[an_action("revert-feature-flag on some-other-flag",
                                   verdict=Verdict.REFUTED),
                         an_action("revert-feature-flag on monthly-spend-feature",
                                   verdict=Verdict.CONFIRMED)],
                pull_request=some_fix,
                recommended_action="restarting io-shop"),
            the_service_back := STARTED_AT + timedelta(minutes=9)
        ) \
        .when(
            lambda: record_action_items_of(evidence, the_service_back)
        ) \
        .then(
            the_answer_was([
                ActionItem(number="AI-1",
                           text="revert-feature-flag on monthly-spend-feature",
                           type=ActionItemType.MITIGATE,
                           owner="Argus",
                           tracking=None,
                           status=ActionItemStatus.DONE),
                ActionItem(number="AI-2",
                           text="Review and merge the proposed fix",
                           type=ActionItemType.PREVENT,
                           owner=None,
                           tracking=some_fix.url,
                           status=ActionItemStatus.OPEN),
                ActionItem(number="AI-3",
                           text="restarting io-shop",
                           type=ActionItemType.MITIGATE,
                           owner=None,
                           tracking=None,
                           status=ActionItemStatus.OPEN)
            ])
        )


@pytest.mark.unit
def test_automatic_sync_left_off_is_an_item_left_to_do_after_the_fix() -> None:
    # The resolution says sync was left off; this is somebody turning it back
    # on, without which nothing merged reaches the service. After the fix, since
    # the fix is what should arrive once it is on, and once per application
    # however many actions stopped it.
    some_fix = OpenedPullRequest(number=7,
                                 url="https://github.invalid/ohadraz/io-shop/pull/7",
                                 branch="argus/fix-abc")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                actions=[an_action("scaled io-shop out", verdict=Verdict.CONFIRMED,
                                   standing="still in place", paused_sync_of="io-shop"),
                         an_action("rolled back io-shop", verdict=Verdict.CONFIRMED,
                                   standing="still in place", paused_sync_of="io-shop")],
                pull_request=some_fix),
            the_service_back := STARTED_AT + timedelta(minutes=9)
        ) \
        .when(
            lambda: [(item.number, item.text, item.type, item.status)
                     for item in record_action_items_of(evidence, the_service_back)]
        ) \
        .then(
            the_answer_was([
                ("AI-1", "scaled io-shop out", ActionItemType.MITIGATE, ActionItemStatus.DONE),
                ("AI-2", "rolled back io-shop", ActionItemType.MITIGATE, ActionItemStatus.DONE),
                ("AI-3", "Review and merge the proposed fix", ActionItemType.PREVENT,
                 ActionItemStatus.OPEN),
                ("AI-4", "Turn automatic sync of io-shop back on once its repository says "
                         "what should run - until then nothing merged reaches it, and turned "
                         "on sooner it puts back what the repository says, undoing what Argus "
                         "changed by hand", ActionItemType.MITIGATE, ActionItemStatus.OPEN)
            ])
        )


@pytest.mark.unit
@pytest.mark.parametrize(("back_to_normal_at", "kind"), [
    (STARTED_AT + timedelta(minutes=9), ActionItemType.PREVENT),
    (None, ActionItemType.MITIGATE)
], ids=["measured-back", "never-measured-back"])
def test_the_fix_is_a_mitigation_until_the_metrics_show_the_service_back(
        back_to_normal_at: datetime | None, kind: ActionItemType) -> None:
    # Typed prevent whatever happened, the fix read as a safeguard for next
    # time on an incident it was the only way out of. Where the metrics show
    # the service back it prevents a recurrence; where they do not, merging it
    # is what ends the incident.
    some_fix = OpenedPullRequest(number=7,
                                 url="https://github.invalid/ohadraz/io-shop/pull/7",
                                 branch="argus/fix-abc")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(pull_request=some_fix)
        ) \
        .when(
            lambda: [item.type for item in record_action_items_of(evidence, back_to_normal_at)
                     if item.tracking == some_fix.url]
        ) \
        .then(
            the_answer_was([kind])
        )


@pytest.mark.unit
def test_the_timeline_carries_its_four_markers_where_they_happened() -> None:
    # The onset and the recovery are properties of the metrics rather than
    # lines anybody said, so they arrive as rows of their own; so does the
    # alert, before the line about it, because the line is the reaction. The
    # mitigation was said - by the line that took the action - so its marker
    # is on that line.
    the_mitigation = STARTED_AT + timedelta(minutes=2)
    some_line_before = a_timeline_entry("received the alert", at=STARTED_AT)
    some_line_after = a_timeline_entry("turned the flag off", at=the_mitigation)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=ONSET,
                started_at=STARTED_AT,
                alert_title="HighErrorRate on io-shop",
                timeline=[some_line_before, some_line_after],
                actions=[an_action("revert-feature-flag on monthly-spend-feature",
                                   verdict=Verdict.CONFIRMED,
                                   taken_at=the_mitigation,
                                   line=1)])
        ) \
        .when(
            lambda: [(entry.at, entry.marker) for entry in
                     timeline_of(evidence, back_to_normal_at=RECOVERED_AT + timedelta(minutes=5))]
        ) \
        .then(
            the_answer_was([
                (ONSET, TimelineMarker.IMPACT_BEGINS),
                (STARTED_AT, TimelineMarker.DETECTED),
                (STARTED_AT, None),
                (the_mitigation, TimelineMarker.MITIGATION_APPLIED),
                (RECOVERED_AT + timedelta(minutes=5), TimelineMarker.IMPACT_ENDS)
            ])
        )


@pytest.mark.unit
def test_the_impact_ends_after_the_action_that_ended_it_at_the_same_moment() -> None:
    # A service back within the minute the action was taken in is back at the
    # action, so the end and the action share an instant. The end is what the
    # action brought about, not something it reacts to, so it follows the line
    # rather than leading it as the onset and the alert do.
    the_mitigation = STARTED_AT + timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=ONSET,
                started_at=STARTED_AT,
                timeline=[a_timeline_entry("dont care", at=STARTED_AT),
                          a_timeline_entry("dont care either", at=the_mitigation)],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED,
                                   taken_at=the_mitigation, line=1)])
        ) \
        .when(
            lambda: [entry.marker for entry in
                     timeline_of(evidence, back_to_normal_at=the_mitigation)]
        ) \
        .then(
            the_answer_was([
                TimelineMarker.IMPACT_BEGINS,
                TimelineMarker.DETECTED,
                None,
                TimelineMarker.MITIGATION_APPLIED,
                TimelineMarker.IMPACT_ENDS
            ])
        )


@pytest.mark.unit
def test_an_end_a_person_reported_is_marked_on_the_line_of_their_report() -> None:
    # A row of its own would say the service was back to normal - the metrics'
    # word for an end they never showed - and say the report a second time
    # beside the line that already says it, by whom and when.
    the_report = STARTED_AT + timedelta(minutes=3)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=ONSET,
                started_at=STARTED_AT,
                timeline=[a_timeline_entry("dont care", at=STARTED_AT),
                          a_timeline_entry("dont care either", at=the_report,
                                           outside_the_walk=True)],
                resolution=a_resolution(the_report, line=1))
        ) \
        .when(
            lambda: [(entry.marker, entry.label) for entry in
                     timeline_of(evidence, back_to_normal_at=the_report, ended_by_a_report=True)]
        ) \
        .then(
            the_answer_was([
                (TimelineMarker.IMPACT_BEGINS, None),
                (TimelineMarker.DETECTED, None),
                (None, "T1"),
                (TimelineMarker.IMPACT_ENDS, "XW1")
            ])
        )


@pytest.mark.unit
def test_an_end_a_person_reported_with_no_line_of_theirs_is_a_row_saying_their_report() -> None:
    # Where the account holds no line of the report, the end still has a row -
    # said as the report it was, by whom, never as back to normal.
    the_report = STARTED_AT + timedelta(minutes=3)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=ONSET,
                started_at=STARTED_AT,
                timeline=[a_timeline_entry("dont care", at=STARTED_AT)],
                resolution=a_resolution(the_report, by="Some Person"))
        ) \
        .when(
            lambda: [entry.text for entry in
                     timeline_of(evidence, back_to_normal_at=the_report, ended_by_a_report=True)
                     if entry.marker is TimelineMarker.IMPACT_ENDS]
        ) \
        .then(
            the_answer_was(["Some Person reported the incident resolved"])
        )


@pytest.mark.unit
def test_each_line_of_the_narration_is_labelled_as_the_prompt_named_it() -> None:
    # The model cites a line of the narration as T1, T2. The markers with rows
    # of their own are placed among those lines by code, were never shown to
    # the model, and so have no label - which is why the label is the line's
    # own, not its row's. A marker on a line keeps the line's label.
    the_mitigation = STARTED_AT + timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=ONSET,
                started_at=STARTED_AT,
                timeline=[a_timeline_entry("dont care", at=STARTED_AT),
                          a_timeline_entry("dont care either", at=the_mitigation)],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED,
                                   taken_at=the_mitigation, line=1)])
        ) \
        .when(
            lambda: [(entry.marker, entry.label) for entry in
                     timeline_of(evidence, back_to_normal_at=RECOVERED_AT + timedelta(minutes=5))]
        ) \
        .then(
            the_answer_was([
                (TimelineMarker.IMPACT_BEGINS, None),
                (TimelineMarker.DETECTED, None),
                (None, "T1"),
                (TimelineMarker.MITIGATION_APPLIED, "T2"),
                (TimelineMarker.IMPACT_ENDS, None)
            ])
        )


@pytest.mark.unit
def test_a_line_outside_the_walk_is_labelled_apart_from_the_walks_own() -> None:
    # A person's message lands among the walk's lines where timing puts it, so
    # numbered with them it renumbers every line after it. Numbered apart, a
    # walk's lines are T1, T2 however many people wrote, and wherever.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                started_at=STARTED_AT,
                timeline=[a_timeline_entry("dont care", at=STARTED_AT + timedelta(minutes=1)),
                          a_timeline_entry("dont care either",
                                           at=STARTED_AT + timedelta(minutes=2),
                                           outside_the_walk=True),
                          a_timeline_entry("dont care at all",
                                           at=STARTED_AT + timedelta(minutes=3))])
        ) \
        .when(
            lambda: [entry.label for entry in timeline_of(evidence, back_to_normal_at=None)
                     if entry.marker is None]
        ) \
        .then(
            the_answer_was(["T1", "XW1", "T2"])
        )


@pytest.mark.unit
def test_a_line_that_formed_candidates_names_them_by_the_labels_their_rows_go_by() -> None:
    # Said in full, it repeats each candidate's paragraph, which the
    # hypotheses considered already show under the same label.
    some_line = a_timeline_entry(
        "Formed 2 candidate causes, best first: dont care; dont care either"
    ).model_copy(update={"candidates": [0, 1]})

    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, timeline=[some_line])
        ) \
        .when(
            lambda: [entry.text for entry in timeline_of(evidence, back_to_normal_at=None)
                     if entry.marker is None]
        ) \
        .then(
            the_answer_was(["Formed 2 candidate causes, best first: C1, C2"])
        )


@pytest.mark.unit
def test_a_line_acting_for_a_candidate_names_it_by_the_label_its_row_goes_by() -> None:
    # In the narration's words, "candidate cause #3" beside a row, an action
    # and a resolution saying C3 reads as a second candidate.
    some_line = a_timeline_entry(
        "Did not roll back the deployment of io-shop for candidate cause #3 - ESCALATED"
    ).model_copy(update={"for_candidate": ForCandidate(place=2,
                                                       said_as="candidate cause #3")})

    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, timeline=[some_line])
        ) \
        .when(
            lambda: [entry.text for entry in timeline_of(evidence, back_to_normal_at=None)
                     if entry.marker is None]
        ) \
        .then(
            the_answer_was(["Did not roll back the deployment of io-shop for C3 - ESCALATED"])
        )


@pytest.mark.unit
def test_a_refusal_in_the_resolution_names_its_candidate_as_the_timeline_does() -> None:
    # Said as the document's timeline says its line - by the candidate's
    # label - and not as the narration wrote it, which would give the one
    # candidate two names a section apart.
    some_line = a_timeline_entry(
        "Refused to act on candidate cause #3 - some reason"
    ).model_copy(update={"for_candidate": ForCandidate(place=2,
                                                       said_as="candidate cause #3")})

    Scenario() \
        .given(
            evidence := an_evidence_bundle(timeline=[some_line]).model_copy(update={
                "refusals": [RefusalRecord(line=0, refusal=Refusal.WOULD_UNDO_A_MEANT_CHANGE)]})
        ) \
        .when(
            lambda: [(step.action, step.candidate) for step in resolution_of(evidence)
                     if step.refused]
        ) \
        .then(
            the_answer_was([("Refused to act on C3 - some reason", "C3")])
        )


@pytest.mark.unit
def test_a_marker_whose_moment_is_unknown_is_left_out() -> None:
    # No onset, nothing that brought recovery, no recovery: only the alert is
    # known, and a marker placed anywhere else would be a moment invented.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=None,
                timeline=[],
                actions=[an_action("dont care", verdict=Verdict.REFUTED)])
        ) \
        .when(
            lambda: [entry.marker for entry in timeline_of(evidence, back_to_normal_at=None)]
        ) \
        .then(
            the_answer_was([TimelineMarker.DETECTED])
        )


@pytest.mark.unit
def test_the_mitigation_applied_marker_is_the_line_that_took_the_action() -> None:
    # The line already says what was done, by whom and when. A row of the
    # marker's own would say the same action twice, back to back.
    the_line = a_timeline_entry("Turned the flag off", who="Mitigation Agent",
                                at=STARTED_AT + timedelta(minutes=2))

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=None,
                timeline=[the_line],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED, line=0)])
        ) \
        .when(
            lambda: [entry for entry in timeline_of(evidence, back_to_normal_at=None)
                     if entry.marker is TimelineMarker.MITIGATION_APPLIED]
        ) \
        .then(
            the_answer_was([the_line.model_copy(
                update={"marker": TimelineMarker.MITIGATION_APPLIED, "label": "T1"})])
        )


@pytest.mark.unit
def test_a_marked_line_keeps_its_place_among_lines_said_at_the_same_moment() -> None:
    # The agent is called in and takes the action in one breath, and under a
    # frozen clock the two lines share an instant. Marked, the action's line is
    # still the line after the one that called the agent in.
    the_mitigation = STARTED_AT + timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=None,
                timeline=[a_timeline_entry("Called in the Mitigation Agent", at=the_mitigation),
                          a_timeline_entry("Turned the flag off", at=the_mitigation)],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED, line=1)])
        ) \
        .when(
            lambda: [entry.text for entry in timeline_of(evidence, back_to_normal_at=None)
                     if entry.at == the_mitigation]
        ) \
        .then(
            the_answer_was(["Called in the Mitigation Agent", "Turned the flag off"])
        )


@pytest.mark.unit
def test_a_mitigation_no_line_says_is_not_marked() -> None:
    # Without its line, the action's only moment is the row's claim, written
    # before the action was taken - a marker placed there would be a moment
    # invented.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=None,
                timeline=[a_timeline_entry("dont care", at=STARTED_AT + timedelta(minutes=2))],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED, line=None)])
        ) \
        .when(
            lambda: [entry.marker for entry in timeline_of(evidence, back_to_normal_at=None)
                     if entry.marker is not None]
        ) \
        .then(
            the_answer_was([TimelineMarker.DETECTED])
        )


@pytest.mark.unit
def test_the_detected_marker_names_the_alert() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, timeline=[],
                                           alert_title="HighErrorRate on io-shop")
        ) \
        .when(
            lambda: timeline_of(evidence, back_to_normal_at=None)
        ) \
        .then(
            the_answer_was([TimelineEntry(at=STARTED_AT,
                                          who=None,
                                          text="HighErrorRate on io-shop fired",
                                          marker=TimelineMarker.DETECTED)])
        )


@pytest.mark.unit
def test_the_detected_marker_is_placed_when_the_alert_fired() -> None:
    some_firing = STARTED_AT - timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, timeline=[], started_at=STARTED_AT,
                                           alerted_at=some_firing)
        ) \
        .when(
            lambda: [(entry.at, entry.marker) for entry \
                     in timeline_of(evidence, back_to_normal_at=None)]
        ) \
        .then(
            the_answer_was([(some_firing, TimelineMarker.DETECTED)])
        )


@pytest.mark.unit
def test_the_onset_marker_says_the_incident_began_and_not_how() -> None:
    # The onset is a minute the metrics or the alert dated, whatever went wrong
    # in it. Said as the service failing, it is false of every incident whose
    # service kept answering and answered wrongly.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=ONSET, timeline=[])
        ) \
        .when(
            lambda: [entry.text for entry in timeline_of(evidence, back_to_normal_at=None)
                     if entry.marker is TimelineMarker.IMPACT_BEGINS]
        ) \
        .then(
            the_answer_was(["the incident began"])
        )


@pytest.mark.unit
def test_an_onset_the_metrics_stopped_at_is_marked_as_where_they_stopped() -> None:
    # Where the metrics carry no minute from the onset on, what the onset dates
    # is the metrics stopping. The service may have gone on serving as before,
    # and "impact begins" would say it was hurt from then.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=ONSET, timeline=[])
        ) \
        .when(
            lambda: [(entry.at, entry.marker, entry.text) for entry in
                     timeline_of(evidence, back_to_normal_at=None, metrics_stopped_at_onset=True)
                     if entry.marker is not TimelineMarker.DETECTED]
        ) \
        .then(
            the_answer_was([(ONSET, TimelineMarker.METRICS_STOP, "the metrics stopped")])
        )


@pytest.mark.unit
@pytest.mark.parametrize(("back_before_the_action", "said"), [
    (False, "the service was back to normal"),
    (True, "the service was back to normal, before the action credited with it")
], ids=["after-the-action", "before-the-action"])
def test_the_impact_ends_where_the_service_was_back_to_normal(
        back_before_the_action: bool, said: str) -> None:
    # The impact ends where the service was back inside the range it keeps when
    # nothing is wrong, not where it fell off the incident's level - and
    # "recovered" is Mitigation's word for that one. Back a whole minute before
    # the action credited with it, the action did not bring it back, and the
    # marker says so rather than leave the order to be noticed.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, timeline=[])
        ) \
        .when(
            lambda: [entry.text for entry in
                     timeline_of(evidence, back_to_normal_at=RECOVERED_AT,
                                 back_before_the_action=back_before_the_action)
                     if entry.marker is TimelineMarker.IMPACT_ENDS]
        ) \
        .then(
            the_answer_was([said])
        )


@pytest.mark.unit
def test_impact_is_measured_where_the_metrics_showed_the_recovery() -> None:
    # Carried rather than left to the page to subtract from the markers, for
    # the gap's reason: two renderers subtracting are two chances to disagree.
    Scenario() \
        .given(
            measured := a_measured_incident(
                duration_in_hours=0.5,
                back_to_normal_at=RECOVERED_AT,
                error_rates=ErrorRates(baseline=0.01, while_broken=0.3, at_its_worst=0.42,
                                       usual_ceiling=0.02, usual_worst=0.04))
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False)
        ) \
        .then(
            the_answer_was(Impact(duration=timedelta(minutes=30),
                                  extent=ImpactExtent.MEASURED,
                                  peak_error_rate=0.42,
                                  error_rates=ErrorRateLevels(before=0.01, while_broken=0.3,
                                                              rose=True)))
        )


@pytest.mark.unit
def test_a_disproven_alarm_has_no_impact_but_the_rules_series_it_was_judged_on() -> None:
    # There was no incident: no stretch, no failed requests, no harm - measured
    # from the alert to the close, it read as a service broken for seconds and
    # never back. In place of the figures, what the rule's series read over the
    # minutes the alarm claimed its condition held in, in the unit the rest of
    # the page says the series in.
    some_minute = ONSET - timedelta(minutes=6)

    Scenario() \
        .given(
            measured := a_measured_incident(
                onset_at=None, back_to_normal_at=None, loss=None,
                error_rates=ErrorRates(baseline=0.01, while_broken=0.01, at_its_worst=0.015,
                                       usual_ceiling=0.02, usual_worst=0.04),
                rule_series_unit="percentunit", rule_series_is_the_error_rate=True,
                rule_series_before_the_alert=RuleSeriesSpan(lowest=0.0, highest=0.015,
                                                            first_minute=some_minute,
                                                            last_minute=ONSET, line=0.1))
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=True)
        ) \
        .then(
            the_answer_was(Impact(duration=timedelta(0),
                                  extent=ImpactExtent.DISPROVEN,
                                  peak_error_rate=None,
                                  before_the_alert=RuleSeriesBeforeTheAlert(
                                      lowest=0.0, highest=0.015, first_minute=some_minute,
                                      last_minute=ONSET, line=0.1, unit="percentunit",
                                      is_the_error_rate=True)))
        )


@pytest.mark.unit
def test_an_impact_a_person_reported_the_end_of_is_said_to_end_at_their_report() -> None:
    # Not a measurement - the metrics showed no end - and not a floor either:
    # the person's report is the end (spec §16), and every figure is counted to
    # it.
    Scenario() \
        .given(
            measured := a_measured_incident(reported_by="Some Person")
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).extent
        ) \
        .then(
            the_answer_was(ImpactExtent.REPORTED)
        )


@pytest.mark.unit
def test_the_logs_in_a_stretch_the_metrics_missed_are_carried_with_how_far_they_reach() -> None:
    # Impact said the error rate was not measured, and never that the service's
    # own logs measured it through the gap. Which lines reach in and how far,
    # and where the reading of them ended - at the alert, where it ended there,
    # which is where it ends unless the investigation asked for more.
    some_lines = [f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"]
    the_alert = ONSET + timedelta(minutes=20)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=some_lines, alerted_at=the_alert,
                                           log_reading_ended=the_alert),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: logs_in_the_gap_of(evidence, measured)
        ) \
        .then(
            the_answer_was(LogsInTheGap(read=True,
                                        labels=labels_reaching_into(some_lines, ONSET),
                                        reach_until=ONSET + timedelta(minutes=4),
                                        read_until=the_alert,
                                        read_until_the_alert=True))
        )


@pytest.mark.unit
def test_whether_the_logs_show_the_service_serving_as_before_is_carried_beside_them() -> None:
    # The model's reading of the lines, and the one thing in the note it gives:
    # the document says it from this, so the model need not say it anywhere.
    some_lines = [f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=some_lines, log_reading_ended=None),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: logs_in_the_gap_of(evidence, measured, serving_as_before=False)
        ) \
        .then(
            the_answer_was(LogsInTheGap(read=True,
                                        labels=labels_reaching_into(some_lines, ONSET),
                                        reach_until=ONSET + timedelta(minutes=4),
                                        read_until=None,
                                        read_until_the_alert=False,
                                        serving_as_before=False))
        )


@pytest.mark.unit
def test_no_line_reaching_in_carries_no_reading_of_how_the_service_was_serving() -> None:
    # Nothing reaches in for it to be a reading of, so it is not asked - and
    # an answer given anyway says nothing the lines can bound.
    some_lines = [f"{to_iso(ONSET - timedelta(minutes=4))} WARN io-shop: dont care"]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=some_lines, log_reading_ended=None),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: logs_in_the_gap_of(evidence, measured, serving_as_before=True)
        ) \
        .then(
            the_answer_was(LogsInTheGap(read=True, labels=[], reach_until=None,
                                        read_until=None, read_until_the_alert=False,
                                        serving_as_before=None))
        )


@pytest.mark.unit
def test_logs_nobody_read_are_carried_as_unread() -> None:
    # Not as read and empty: where the metrics stopped, the service gone quiet
    # in its logs too is not nobody having looked.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[], log_reading_ended=None),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: logs_in_the_gap_of(evidence, measured)
        ) \
        .then(
            the_answer_was(LogsInTheGap(read=False, labels=[], reach_until=None,
                                        read_until=None, read_until_the_alert=False))
        )


@pytest.mark.unit
def test_metrics_that_never_stopped_leave_no_stretch_for_the_logs_to_reach_into() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                log_lines=[f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"]),
            measured := a_measured_incident(metrics_stopped_at=None)
        ) \
        .when(
            lambda: logs_in_the_gap_of(evidence, measured)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("unmeasured", "read"), [
    (Unmeasured.NOTHING_READ, False),
    (Unmeasured.NO_MINUTE_WHILE_BROKEN, True),
    (None, True)
], ids=["nothing-came-back", "some-came-back", "measured"])
def test_impact_carries_whether_any_minute_of_the_metrics_came_back(
        unmeasured: Unmeasured | None, read: bool) -> None:
    # For the review: a window that came back empty is one Argus can collect
    # no more of, and a window that came back is not, whatever it held.
    Scenario() \
        .given(
            measured := a_measured_incident().model_copy(
                update={"error_rates_unmeasured": unmeasured})
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).metrics_read
        ) \
        .then(
            the_answer_was(read)
        )


@pytest.mark.unit
def test_impact_carries_how_many_requests_failed() -> None:
    Scenario() \
        .given(
            measured := a_measured_incident(
                error_rates=ErrorRates(baseline=0.01, while_broken=0.3, at_its_worst=0.42,
                                       usual_ceiling=0.02, usual_worst=0.04,
                                       failed_requests=4210))
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).requests_failed
        ) \
        .then(
            the_answer_was(4210)
        )


@pytest.mark.unit
def test_impact_still_running_when_the_metrics_ran_out_is_a_lower_bound() -> None:
    # Printed alike, a floor reads as a measurement.
    Scenario() \
        .given(
            measured := a_measured_incident(back_to_normal_at=None)
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).extent
        ) \
        .then(
            the_answer_was(ImpactExtent.AT_LEAST)
        )


@pytest.mark.unit
def test_impact_whose_metrics_stopped_is_metrics_missing() -> None:
    # Not a stretch the service is known to have spent broken - a stretch
    # nobody could see, which a lower bound would misdescribe.
    Scenario() \
        .given(
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).extent
        ) \
        .then(
            the_answer_was(ImpactExtent.METRICS_MISSING)
        )


@pytest.mark.unit
def test_impact_states_no_peak_where_the_metrics_could_not_be_read() -> None:
    Scenario() \
        .given(
            measured := a_measured_incident(error_rates=None)
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).peak_error_rate
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("error_rates", "rose"), [
    (ErrorRates(baseline=0.01, while_broken=0.3, at_its_worst=0.42,
                usual_ceiling=0.02, usual_worst=0.04), True),
    (ErrorRates(baseline=0.01, while_broken=0.009, at_its_worst=0.02,
                usual_ceiling=0.02, usual_worst=0.04), False)
], ids=["rose", "did-not-rise"])
def test_impact_carries_the_error_rate_before_and_while_broken_and_whether_it_rose(
        error_rates: ErrorRates, rose: bool) -> None:
    # A rate that did not rise is still shown, as one that did not: left off,
    # a reader cannot tell it from one nobody measured, and a summary saying
    # pages kept loading rests on it.
    Scenario() \
        .given(
            measured := a_measured_incident(error_rates=error_rates)
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).error_rates
        ) \
        .then(
            the_answer_was(ErrorRateLevels(before=error_rates.baseline,
                                           while_broken=error_rates.while_broken,
                                           rose=rose))
        )


@pytest.mark.unit
def test_impact_carries_no_error_rate_levels_where_the_metrics_could_not_be_read() -> None:
    # Not a rate that did not rise: "no rise" is a claim, and nothing measured
    # it.
    Scenario() \
        .given(
            measured := a_measured_incident(error_rates=None)
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).error_rates
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_impact_carries_the_rules_series_where_it_got_worse() -> None:
    # The series is what paged, so where it got worse it is harm whatever the
    # failed requests did - and the only harm there is where every request
    # succeeded.
    Scenario() \
        .given(
            measured := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=0.899, while_broken=0.459,
                                             at_its_worst=0.391, worse_when="below",
                                             line=0.8))
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).rule_series_harm
        ) \
        .then(
            the_answer_was(RuleSeriesHarm(before=0.899, while_broken=0.459,
                                          at_its_worst=0.391, worse_when="below", line=0.8))
        )


@pytest.mark.unit
def test_impact_carries_the_unit_of_the_rules_series() -> None:
    # The page says the levels in it, as the brief does.
    Scenario() \
        .given(
            measured := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=120.0, while_broken=640.0,
                                             at_its_worst=910.0, worse_when="above"),
                rule_series_unit="ms")
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).rule_series_harm
        ) \
        .then(
            the_answer_was(RuleSeriesHarm(before=120.0, while_broken=640.0,
                                          at_its_worst=910.0, worse_when="above", unit="ms"))
        )


@pytest.mark.unit
def test_impact_carries_that_the_rules_series_is_the_error_rate() -> None:
    # Then the page already has the error rate's own figures for it, and says
    # only what those do not.
    Scenario() \
        .given(
            measured := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=0.01, while_broken=0.28,
                                             at_its_worst=0.38, worse_when="above"),
                rule_series_is_the_error_rate=True)
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).rule_series_harm
        ) \
        .then(
            the_answer_was(RuleSeriesHarm(before=0.01, while_broken=0.28, at_its_worst=0.38,
                                          worse_when="above", is_the_error_rate=True))
        )


@pytest.mark.unit
def test_impact_carries_no_rules_series_that_held() -> None:
    # Nothing is not a harm, and a series no worse than before carried as one
    # would put a card for it on the page.
    Scenario() \
        .given(
            measured := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=0.899, while_broken=0.95,
                                             at_its_worst=0.91, worse_when="below"))
        ) \
        .when(
            lambda: impact_of(measured, logs_in_the_gap=None, disproven=False).rule_series_harm
        ) \
        .then(
            the_answer_was(None)
        )


def _a_deploy_of(revision: str, at: str, actor: str | None = None) -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.DEPLOY,
                       occurred_at=at,
                       reference=revision,
                       summary="dont care",
                       actor=actor)


def _the_move(trigger: Trigger | None) -> tuple[str | None, str | None] | None:
    return (trigger.from_state, trigger.to_state) if trigger is not None else None


def _a_change_to(subject: str, at: str) -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                       occurred_at=at,
                       reference=subject,
                       summary="dont care")


def _what_the_deploy_of(revision: str, changed: list[str]) -> DeploymentChangesRecord:
    """What the deploy of `revision` changed, as the read tier says it: one file,
    its patch lines as `changed` gives them."""
    return DeploymentChangesRecord(revision=revision, said=[
        f"Deployment of revision {revision} to io-shop, compared against "
        f"{SOME_EARLIER_REVISION} - the revision deployed before it.",
        a_changed_file_line("modified", "deploy/values-production.yaml"),
        *(f"{PATCH_LINE_INDENT}{line}" for line in changed)
    ])
