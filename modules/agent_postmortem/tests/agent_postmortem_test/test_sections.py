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
from agent_postmortem.estimate import ErrorRates
from agent_postmortem.sections import (
    detection_of,
    hypotheses_of,
    impact_of,
    record_action_items_of,
    resolution_of,
    timeline_of,
    trigger_of,
)
from argus_core import parse_iso
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ChangeEvent,
    ChangeKind,
    Detection,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    OpenedPullRequest,
    ResolutionStep,
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
def test_the_timeline_carries_its_four_markers_where_they_happened() -> None:
    # The onset and the recovery are properties of the metrics rather than
    # lines anybody said, so they arrive as markers of their own. The alert's
    # marker sits before the line about it, because the line is the reaction;
    # the mitigation's sits after the line that took it, because it is the
    # result.
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
                                   taken_at=the_mitigation)])
        ) \
        .when(
            lambda: [(entry.at, entry.marker) for entry in
                     timeline_of(evidence, recovered_at=RECOVERED_AT + timedelta(minutes=5))]
        ) \
        .then(
            the_answer_was([
                (ONSET, TimelineMarker.IMPACT_BEGINS),
                (STARTED_AT, TimelineMarker.DETECTED),
                (STARTED_AT, None),
                (the_mitigation, None),
                (the_mitigation, TimelineMarker.MITIGATED),
                (RECOVERED_AT + timedelta(minutes=5), TimelineMarker.IMPACT_ENDS)
            ])
        )


@pytest.mark.unit
def test_each_line_of_the_narration_is_labelled_as_the_prompt_named_it() -> None:
    # The model cites a line of the narration as T1, T2. The markers are
    # placed among those lines by code, were never shown to the model, and so
    # have no label - which is why the label is the line's own, not its row's.
    the_mitigation = STARTED_AT + timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                onset_at=ONSET,
                started_at=STARTED_AT,
                timeline=[a_timeline_entry("dont care", at=STARTED_AT),
                          a_timeline_entry("dont care either", at=the_mitigation)],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED,
                                   taken_at=the_mitigation)])
        ) \
        .when(
            lambda: [(entry.marker, entry.label) for entry in
                     timeline_of(evidence, recovered_at=RECOVERED_AT + timedelta(minutes=5))]
        ) \
        .then(
            the_answer_was([
                (TimelineMarker.IMPACT_BEGINS, None),
                (TimelineMarker.DETECTED, None),
                (None, "T1"),
                (None, "T2"),
                (TimelineMarker.MITIGATED, None),
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
            lambda: [entry.label for entry in timeline_of(evidence, recovered_at=None)
                     if entry.marker is None]
        ) \
        .then(
            the_answer_was(["T1", "XW1", "T2"])
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
            lambda: [entry.marker for entry in timeline_of(evidence, recovered_at=None)]
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
            lambda: timeline_of(evidence, recovered_at=None)
        ) \
        .then(
            the_answer_was([TimelineEntry(at=STARTED_AT,
                                          who=None,
                                          text="HighErrorRate on io-shop fired",
                                          marker=TimelineMarker.DETECTED)])
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
            lambda: [entry.text for entry in timeline_of(evidence, recovered_at=None)
                     if entry.marker is TimelineMarker.IMPACT_BEGINS]
        ) \
        .then(
            the_answer_was(["the incident began"])
        )


@pytest.mark.unit
def test_impact_is_measured_where_the_metrics_showed_the_recovery() -> None:
    # Carried rather than left to the page to subtract from the markers, for
    # the gap's reason: two renderers subtracting are two chances to disagree.
    Scenario() \
        .given(
            measured := a_measured_incident(
                duration_in_hours=0.5,
                recovered_at=RECOVERED_AT,
                error_rates=ErrorRates(baseline=0.01, while_broken=0.3, at_its_worst=0.42))
        ) \
        .when(
            lambda: impact_of(measured)
        ) \
        .then(
            the_answer_was(Impact(duration=timedelta(minutes=30),
                                  extent=ImpactExtent.MEASURED,
                                  peak_error_rate=0.42))
        )


@pytest.mark.unit
def test_impact_carries_how_many_requests_failed() -> None:
    Scenario() \
        .given(
            measured := a_measured_incident(
                error_rates=ErrorRates(baseline=0.01, while_broken=0.3, at_its_worst=0.42,
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
            measured := a_measured_incident(recovered_at=None)
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
            measured := a_measured_incident(recovered_at=None, unobserved_from=ONSET)
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


def _a_deploy_of(revision: str, at: str) -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.DEPLOY,
                       occurred_at=at,
                       reference=revision,
                       summary="dont care")


def _a_change_to(subject: str, at: str) -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                       occurred_at=at,
                       reference=subject,
                       summary="dont care")
