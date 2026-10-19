"""The sections code writes from the record, never asking the model.

Detection, trigger, resolution, the hypotheses considered, the action items the
record implies and the timeline are each a fact the incident left behind,
arranged. A section here that disagreed with the
record would be a postmortem describing a different incident from the page
beside it, so each case names a record and the section it must come out as.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from agent_postmortem import CandidateRecord, DeploymentChangesRecord
from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels
from agent_postmortem.sections import (
    detection_of,
    hypotheses_of,
    impact_of,
    record_action_items_of,
    resolution_of,
    timeline_of,
    trigger_of,
)
from argus_core import parse_iso, to_iso
from argus_core.events import PATCH_LINE_INDENT
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    CandidateConsidered,
    ChangeEvent,
    ChangeKind,
    CitedEvidence,
    Detection,
    ErrorRateLevels,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    OpenedPullRequest,
    ResolutionStep,
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
                                   kind=ChangeKind.FLAG_TOGGLE))
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
    # The candidate was confirmed and the change itself was never read - a
    # trigger with its moment unknown, rather than one dated by a guess.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject=SOME_FLAG,
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[])
        ) \
        .when(
            lambda: trigger_of(evidence)
        ) \
        .then(
            the_answer_was(Trigger(subject=SOME_FLAG,
                                   from_state=None,
                                   to_state=None,
                                   changed_at=None))
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
                                   suspected=True))
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
def test_resolution_lists_each_action_as_argus_took_it() -> None:
    # In the order taken, with what each came to and whether it still stands -
    # one sentence, because the reader of this table wants both at once.
    some_moment = STARTED_AT + timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("revert-feature-flag on monthly-spend-feature",
                          verdict=Verdict.CONFIRMED, standing="still in place",
                          reversible=True, taken_at=some_moment)
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
                reversible=True,
                outcome="confirmed, still in place",
                label="M1"
            )])
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
                recommended_action="restarting io-shop")
        ) \
        .when(
            lambda: record_action_items_of(evidence)
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
                pull_request=some_fix)
        ) \
        .when(
            lambda: [(item.number, item.text, item.type, item.status)
                     for item in record_action_items_of(evidence)]
        ) \
        .then(
            the_answer_was([
                ("AI-1", "scaled io-shop out", ActionItemType.MITIGATE, ActionItemStatus.DONE),
                ("AI-2", "rolled back io-shop", ActionItemType.MITIGATE, ActionItemStatus.DONE),
                ("AI-3", "Review and merge the proposed fix", ActionItemType.PREVENT,
                 ActionItemStatus.OPEN),
                ("AI-4", "Turn automatic sync of io-shop back on - until then, nothing "
                         "merged reaches it", ActionItemType.MITIGATE, ActionItemStatus.OPEN)
            ])
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
            lambda: impact_of(measured)
        ) \
        .then(
            the_answer_was(Impact(duration=timedelta(minutes=30),
                                  extent=ImpactExtent.MEASURED,
                                  peak_error_rate=0.42,
                                  error_rates=ErrorRateLevels(before=0.01, while_broken=0.3,
                                                              rose=True)))
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
            lambda: impact_of(measured).requests_failed
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
            lambda: impact_of(measured).extent
        ) \
        .then(
            the_answer_was(ImpactExtent.AT_LEAST)
        )


@pytest.mark.unit
def test_impact_whose_metrics_stopped_is_unobserved() -> None:
    # Not a stretch the service is known to have spent broken - a stretch
    # nobody could see, which a lower bound would misdescribe.
    Scenario() \
        .given(
            measured := a_measured_incident(back_to_normal_at=None, unobserved_from=ONSET)
        ) \
        .when(
            lambda: impact_of(measured).extent
        ) \
        .then(
            the_answer_was(ImpactExtent.UNOBSERVED)
        )


@pytest.mark.unit
def test_impact_states_no_peak_where_the_metrics_could_not_be_read() -> None:
    Scenario() \
        .given(
            measured := a_measured_incident(error_rates=None)
        ) \
        .when(
            lambda: impact_of(measured).peak_error_rate
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
            lambda: impact_of(measured).error_rates
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
            lambda: impact_of(measured).error_rates
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
            lambda: impact_of(measured).rule_series_harm
        ) \
        .then(
            the_answer_was(RuleSeriesHarm(before=0.899, while_broken=0.459,
                                          at_its_worst=0.391, worse_when="below", line=0.8))
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
            lambda: impact_of(measured).rule_series_harm
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
        "modified deploy/values-production.yaml",
        *(f"{PATCH_LINE_INDENT}{line}" for line in changed)
    ])
