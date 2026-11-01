"""The executive summary, written by code.

Asked to write it, write-ups left out how long the incident ran, told the
reader what the brief told the model, and said a draft fix "corrects" what
nothing ran. Everything in it but the cause is a fact the record holds - when it
broke and for how long, how bad it got, what customers lost, what Argus did and
what it left to a person - so code says it, in the words the rest of the
document says it in, and the model gives only what code cannot: the cause in
plain words, and what is still at risk.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels
from agent_postmortem.summary import said_off_the_page, the_executive_summary
from argus_core import level_said_in, to_iso
from argus_core.models import ActionProgress, OpenedPullRequest, Verdict, said_as_money
from argus_testkit import Assertion, Scenario, all_of, the_answer_was

from agent_postmortem_test.framework.builders import (
    ONSET,
    SOME_CURRENCY,
    STARTED_AT,
    a_candidate,
    a_measured_incident,
    an_action,
    an_evidence_bundle,
)

SOME_CAUSE = "A rename reached one of the two files that name the port."
SOME_RISK = "Any other service renamed the same way loses its metrics too."

# An action as the narration words it, which is how the record holds it: the
# opening of a sentence whose subject is Argus.
SOME_ACTION = "Reverted the feature flag checkout-v2"


@pytest.mark.unit
def test_an_ordinary_incident_is_summed_up_in_the_order_a_reader_asks_about_it() -> None:
    # When and for how long, how bad, the cause, what was done, what is still
    # at risk.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[an_action(SOME_ACTION,
                                                             verdict=Verdict.CONFIRMED)]),
            measured := a_measured_incident(loss=None)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, SOME_RISK)
        ) \
        .then(
            the_answer_was(
                "The service broke at 12:00 UTC and was back to normal at 12:10 UTC, "
                "10 minutes later. No loss was estimated: the shop's takings could not be "
                f"read. {SOME_CAUSE} What Argus did: reverted the feature flag checkout-v2 "
                f"(can be put back) - confirmed, still in place. {SOME_RISK}")
        )


@pytest.mark.unit
def test_a_service_never_seen_back_is_said_not_back_by_the_incident_s_ending(
) -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(back_to_normal_at=None, duration_in_hours=0.5)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("The service broke at 12:00 UTC and was not back to normal by 12:30 UTC, "
                  "at least 30 minutes later.")
        )


@pytest.mark.unit
def test_an_end_a_person_reported_is_said_as_their_report_never_as_back_to_normal() -> None:
    # Back to normal is what the metrics showing it means, everywhere else it is
    # said. The metrics showed nothing of this end: a person's word set it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(reported_by="Some Person")
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("The service broke at 12:00 UTC. Some Person reported the incident resolved "
                  "at 12:10 UTC, 10 minutes later.")
        )


@pytest.mark.unit
def test_an_end_a_person_reported_with_no_onset_is_counted_from_the_alert() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None),
            measured := a_measured_incident(reported_by="Some Person", onset_at=None)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("Some Person reported the incident resolved at 12:10 UTC, 10 minutes after "
                  "the alert.")
        )


@pytest.mark.unit
def test_an_incident_that_spans_days_dates_every_instant_in_its_summary() -> None:
    # The page dates the incident once, in its head, and leaves the day it
    # began unsaid after that. The summary is posted to Slack too, where there
    # is no head: an onset a week before the alert, said as a bare time, reads
    # as that evening.
    a_week_on = ONSET + timedelta(days=7, seconds=49)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(ended_at=a_week_on),
            measured := a_measured_incident(back_to_normal_at=None,
                                            duration_in_hours=(a_week_on - ONSET)
                                            / timedelta(hours=1))
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("The service broke at Sep 02, 12:00 UTC and was not back to normal by "
                  "Sep 09, 12:00:49 UTC, at least 7 days 49 seconds later.")
        )


@pytest.mark.unit
def test_metrics_that_stopped_are_said_unseen_with_where_the_logs_reach_and_their_reading_ended(
) -> None:
    # Not a stretch the service is known to have spent broken: its own logs
    # show it up to where they reach, and nothing after the reading ended was
    # read - said apart, since where the lines stop is as often where the
    # reading did. In Impact's words for it, so the page says it one way.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                log_lines=[f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"],
                log_reading_ended=ONSET + timedelta(minutes=20)),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET,
                                            duration_in_hours=0.5)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("No metrics were collected from 12:00 UTC on, and they had not resumed by "
                  "12:30 UTC, 30 minutes later. The "
                  "service's own logs reach into that stretch until 12:04 UTC, and they were "
                  "read up to 12:20 UTC.")
        )


@pytest.mark.unit
def test_logs_reaching_as_far_as_their_reading_ended_say_the_instant_once() -> None:
    # Said twice - "until 08:28 UTC, and they were read up to 08:28 UTC" - one
    # instant reads as two facts, and the Slack line the summary becomes says
    # it twice too.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                log_lines=[f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"],
                log_reading_ended=ONSET + timedelta(minutes=4)),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET,
                                            duration_in_hours=0.5)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("The service's own logs reach into that stretch until 12:04 UTC, as far as "
                  "they were read.")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("log_lines", "read_until", "said"), [
    ([], None, "No logs were read."),
    ([], ONSET + timedelta(minutes=20),
     "No log line read reaches into that stretch, and the logs were read up to 12:20 UTC."),
    ([f"{to_iso(ONSET - timedelta(minutes=10))} WARN io-shop: dont care"],
     ONSET + timedelta(minutes=20),
     "No log line read reaches into that stretch, and the logs were read up to 12:20 UTC.")
], ids=["no-logs-read", "read-and-empty", "none-reaching-in"])
def test_logs_that_show_nothing_of_the_unseen_stretch_are_said_to_show_nothing(
        log_lines: list[str], read_until: datetime | None, said: str) -> None:
    # Said rather than left out: a summary silent on the logs reads the same as
    # one whose logs nobody looked at. And a read that came back empty is a
    # read: where the metrics stopped, the service gone quiet in its logs too
    # is not nobody having looked.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=log_lines, log_reading_ended=read_until),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET,
                                            duration_in_hours=0.5)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says(said)
        )


@pytest.mark.unit
def test_with_no_onset_measured_the_summary_says_so_and_dates_it_from_the_alert() -> None:
    # Never as when it broke: the alert is when the rule fired.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None,
                                           alerted_at=ONSET + timedelta(minutes=2)),
            measured := a_measured_incident(onset_at=None, duration_in_hours=8 / 60)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("No onset was measured; the alert came at 12:02 UTC. The service was back "
                  "to normal at 12:10 UTC, 8 minutes after the alert.")
        )


@pytest.mark.unit
def test_failed_requests_are_said_where_they_rose_beyond_what_the_service_reaches_alone() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(error_rates=ErrorRates(
                baseline=0.02, while_broken=0.3, at_its_worst=0.4, usual_ceiling=0.03,
                usual_worst=0.05))
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("30.0% of requests failed while it was broken, against 2.0% before it began.")
        )


@pytest.mark.unit
def test_where_no_more_requests_failed_what_the_alert_watches_is_said_where_it_got_worse(
) -> None:
    # A fault in what the service answers fails no request; the series its
    # alert watches is what says what happened.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                error_rates=ErrorRates(baseline=0.02, while_broken=0.02, at_its_worst=0.03,
                                       usual_ceiling=0.03, usual_worst=0.05),
                rule_series=RuleSeriesLevels(baseline=0.9, while_broken=0.5,
                                             at_its_worst=0.46, worse_when="below"))
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says(f"What its alert watches went from {level_said_in(0.9, None)} before it "
                  f"began to {level_said_in(0.46, None)} at its worst.")
        )


@pytest.mark.unit
def test_where_both_moved_the_failed_requests_and_what_the_alert_watches_are_both_said() -> None:
    # The series its rule pages on is harm whatever the failed requests did: a
    # latency incident with a small rise in failures is not summed up by them.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                error_rates=ErrorRates(baseline=0.02, while_broken=0.3, at_its_worst=0.4,
                                       usual_ceiling=0.03, usual_worst=0.05),
                rule_series=RuleSeriesLevels(baseline=0.9, while_broken=0.5,
                                             at_its_worst=0.46, worse_when="below"))
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("30.0% of requests failed while it was broken, against 2.0% before it began. "
                  f"What its alert watches went from {level_said_in(0.9, None)} before it "
                  f"began to {level_said_in(0.46, None)} at its worst.")
        )


@pytest.mark.unit
def test_where_the_alert_watches_the_error_rate_its_worst_is_said_once_as_requests_failing(
) -> None:
    # The rule's series is the error rate itself, so what it watched is the
    # failed requests already said - only how bad the worst minute got is new.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                error_rates=ErrorRates(baseline=0.02, while_broken=0.3, at_its_worst=0.4,
                                       usual_ceiling=0.03, usual_worst=0.05),
                rule_series=RuleSeriesLevels(baseline=0.02, while_broken=0.3,
                                             at_its_worst=0.4, worse_when="above"),
                rule_series_is_the_error_rate=True)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(all_of(
            _says("30.0% of requests failed while it was broken, against 2.0% before it began. "
                  "At its worst, 40.0% failed."),
            _does_not_say("What its alert watches")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("loss", "back", "said"), [
    (Decimal("500"), True,
     f"The shop's takings fell short of the same hours on earlier weeks by "
     f"{said_as_money(Decimal('500'), SOME_CURRENCY)}, beyond how much those hours vary on "
     f"their own."),
    (Decimal("500"), False,
     f"So far, the shop's takings fell short of the same hours on earlier weeks by at least "
     f"{said_as_money(Decimal('500'), SOME_CURRENCY)}, beyond how much those hours vary on "
     f"their own."),
    (Decimal("0"), True,
     "The shop's takings fell short of the same hours on earlier weeks by no more than "
     "those hours vary on their own, if at all."),
    (Decimal("0"), False,
     "So far, the shop's takings fell short of the same hours on earlier weeks by no more "
     "than those hours vary on their own, if at all."),
    (None, True, "No loss was estimated: the shop's takings could not be read.")
], ids=["a-loss", "a-loss-so-far", "none", "none-so-far", "takings-unread"])
def test_what_customers_lost_is_said_as_the_brief_says_it(loss: Decimal | None, back: bool,
                                                         said: str) -> None:
    # A floor where the service was not seen back: its takings were counted
    # with it still going. And none as the brief says it: "took no less" reads
    # as at least as much, where it may have taken less within the variation.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(loss=loss,
                                            back_to_normal_at=(None if not back
                                                               else ONSET + timedelta(minutes=10)))
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says(said)
        )


@pytest.mark.unit
def test_no_loss_estimated_for_want_of_an_onset_is_said_for_that_reason() -> None:
    # Not the takings: with no onset there is no stretch to count them over.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None),
            measured := a_measured_incident(onset_at=None, loss=None)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("No loss was estimated: no onset was measured to count it from.")
        )


@pytest.mark.unit
def test_a_service_back_before_the_action_credited_is_said_back_not_because_of_it() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[an_action(
                SOME_ACTION, verdict=Verdict.CONFIRMED,
                taken_at=ONSET + timedelta(minutes=12))]),
            measured := a_measured_incident(back_before_the_action=True)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("The service was back to normal at 12:10 UTC, before Argus reverted the "
                  "feature flag checkout-v2 at 12:12 UTC - so not because of it.")
        )


@pytest.mark.unit
def test_each_action_is_said_as_the_narration_words_it_after_the_first() -> None:
    # The narration words an action as the opening of a sentence - "Restarted
    # io-shop" - and set after a semicolon it reads as one. One with no way back
    # says so once: its standing is "nothing to put back" whenever it has none,
    # and the same words in brackets beside it said it twice in one clause.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(SOME_ACTION, verdict=Verdict.REFUTED, standing="put back"),
                an_action("Restarted io-shop", verdict=Verdict.CONFIRMED,
                          standing="nothing to put back", has_a_way_back=False)])
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("What Argus did: reverted the feature flag checkout-v2 (can be put back) - "
                  "refuted, put back; restarted io-shop - confirmed, nothing to put back.")
        )


@pytest.mark.unit
def test_an_action_an_earlier_incident_had_tried_says_what_it_came_to_there() -> None:
    # Told only what this incident did, a revert reads as a fresh experiment
    # where it repeated one that had already failed - and nothing else a reader
    # sees first says so.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(SOME_ACTION, verdict=Verdict.REFUTED, standing="put back",
                          tried_before=[Verdict.REFUTED])])
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("On an earlier incident like this one, Argus had also reverted the feature "
                  "flag checkout-v2, and it was refuted there.")
        )


@pytest.mark.unit
def test_an_action_several_earlier_incidents_had_tried_says_what_it_came_to_on_each() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(SOME_ACTION, verdict=Verdict.REFUTED, standing="put back",
                          tried_before=[Verdict.REFUTED, Verdict.REFUTED])])
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("On 2 earlier incidents like this one, Argus had also reverted the feature "
                  "flag checkout-v2, and it was refuted on each.")
        )


@pytest.mark.unit
def test_an_action_earlier_incidents_judged_differently_says_how_often_each() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(SOME_ACTION, verdict=Verdict.REFUTED, standing="put back",
                          tried_before=[Verdict.REFUTED, Verdict.CONFIRMED, Verdict.REFUTED])])
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("On 3 earlier incidents like this one, Argus had also reverted the feature "
                  "flag checkout-v2: it was refuted on 2 and confirmed on 1.")
        )


@pytest.mark.unit
def test_an_action_never_performed_is_not_said_to_have_been_taken_again() -> None:
    # Its words say it was not done, and "Argus had also did not revert" says
    # nothing a reader can use.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("Did not revert the feature flag checkout-v2",
                          progress=ActionProgress.NOT_PERFORMED,
                          tried_before=[Verdict.REFUTED])])
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _does_not_say("earlier incident")
        )


@pytest.mark.unit
def test_a_cause_argus_held_back_from_testing_is_said_with_why_in_its_own_words() -> None:
    # The candidate's own words for why, not its row's "never tried: ...",
    # which would say it twice. By its place among the candidates formed, not
    # its summary: that is the investigator's own sentences, three of them in
    # one write-up, and set inside this one they run on into the reason. Not
    # its rank either, which restarts with each round. Its label after the
    # place, which leads to its row on the page and to nothing where the
    # summary is said on its own. Called the candidate, as its reason calls it:
    # "the cause it formed first" and then "the candidate" read as two things.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[a_candidate(
                "the rename broke the scrape", tested=False,
                result="rolling it back would undo a change somebody meant")])
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("Argus did not test the first candidate it formed (C1): rolling it back "
                  "would undo a change somebody meant.")
        )


@pytest.mark.unit
def test_a_summary_said_off_the_page_leaves_out_the_labels_that_lead_to_its_rows() -> None:
    # In a channel there is no row for "(C1)" to lead to, so it points nowhere -
    # and the place before it already says which candidate it was.
    Scenario() \
        .given(
            summary := the_executive_summary(
                an_evidence_bundle(candidates=[a_candidate(
                    "the rename broke the scrape", tested=False,
                    result="rolling it back would undo a change somebody meant")]),
                a_measured_incident(), SOME_CAUSE, "")
        ) \
        .when(
            lambda: said_off_the_page(summary)
        ) \
        .then(all_of(
            _says("Argus did not test the first candidate it formed: rolling it back would "
                  "undo a change somebody meant."),
            _does_not_say("(C1)")
        ))


@pytest.mark.unit
def test_a_held_back_cause_is_counted_as_its_label_counts_it() -> None:
    # Candidates blaming one move are one row; the label still counts each
    # candidate, and "the second candidate it formed (C3)" names a place the
    # label contradicts.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("dont care", subject="checkout-v2", from_state="off",
                            to_state="on"),
                a_candidate("dont care", subject="checkout-v2", from_state="off",
                            to_state="on"),
                a_candidate("dont care", subject="scorer", tested=False,
                            result="nothing could confirm it")])
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("Argus did not test the third candidate it formed (C3): nothing could "
                  "confirm it.")
        )


@pytest.mark.unit
def test_a_draft_fix_and_a_recommended_action_are_said_as_left_to_a_person() -> None:
    # Never as having fixed anything: nothing ran the fix, and nothing took
    # the recommendation. The fix by the name the rest of the document gives
    # it, which is the name a mention of it leads to the fix by.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                pull_request=OpenedPullRequest(number=315, url="https://github.invalid/pull/315",
                                               branch="dont-care"),
                recommended_action="Restart the scorer")
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("Argus opened a draft fix, PR #315, for a person to review and merge.",
                  "Argus recommends this and did not take it: restart the scorer.")
        )


@pytest.mark.unit
def test_a_draft_fix_written_against_a_branch_without_what_ran_is_said_to_need_a_deploy() -> None:
    # Told it in the brief, write-ups said it in fifteen of fifteen and then in
    # two of five, the rest dropping it - and with it that merging alone changes
    # nothing that runs. Said by the document, no answer can drop it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                pull_request=OpenedPullRequest(number=315, url="https://github.invalid/pull/315",
                                               branch="dont-care")
            ).model_copy(update={"fix_branch_read": "main", "fix_holds_what_ran": False})
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("Argus opened a draft fix, PR #315, for a person to review and merge. It "
                  "was written against main, which does not contain the revision that ran: "
                  "merged, it changes what runs only once a deploy carries it.")
        )


@pytest.mark.unit
@pytest.mark.parametrize("holds_what_ran", [True, None], ids=["it-does", "nobody-established"])
def test_a_draft_fix_whose_branch_is_not_known_to_lack_what_ran_needs_no_deploy_said(
        holds_what_ran: bool | None) -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                pull_request=OpenedPullRequest(number=315, url="https://github.invalid/pull/315",
                                               branch="dont-care")
            ).model_copy(update={"fix_branch_read": "main", "fix_holds_what_ran": holds_what_ran})
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _does_not_say("once a deploy carries it")
        )


@pytest.mark.unit
def test_automatic_sync_left_off_is_said_between_the_draft_fix_and_the_recommendation() -> None:
    # It decides whether merging the draft does anything, and turning it on too
    # soon is the one move that puts the fault back - which the record's own
    # item says, where whoever turns it on reads it. Said here as well, the page
    # carried the sentence twice, word for word: so with when, and by the item.
    # After the fix, as the action items take it: the fix is what should arrive
    # when it is.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                actions=[an_action(SOME_ACTION, paused_sync_of="io-shop")],
                pull_request=OpenedPullRequest(number=315, url="https://github.invalid/pull/315",
                                               branch="dont-care"),
                recommended_action="restart the scorer")
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(all_of(
            _says("for a person to review and merge. Argus left automatic sync of io-shop off, "
                  "to be turned back on once its repository says what should run (AI-2). "
                  "Argus recommends this"),
            _does_not_say("undoing what Argus changed by hand")
        ))


@pytest.mark.unit
def test_a_summary_said_off_the_page_leaves_out_the_item_sync_left_off_leads_to() -> None:
    # In a channel there is no row for "(AI-1)" to lead to - and so nothing to
    # say when sync goes back on but the sentence the label followed.
    Scenario() \
        .given(
            summary := the_executive_summary(
                an_evidence_bundle(actions=[an_action(SOME_ACTION, paused_sync_of="io-shop")]),
                a_measured_incident(), SOME_CAUSE, "")
        ) \
        .when(
            lambda: said_off_the_page(summary)
        ) \
        .then(all_of(
            _says("Argus left automatic sync of io-shop off, to be turned back on once its "
                  "repository says what should run."),
            _does_not_say("(AI-")
        ))


@pytest.mark.unit
def test_an_incident_argus_escalated_is_said_to_have_been_handed_to_a_person() -> None:
    # Saying only what Argus did, the summary of an incident it ran out of
    # moves on reads as one it closed.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(escalated=True)
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("Argus handed the incident to a person.")
        )


@pytest.mark.unit
def test_a_disproven_alarm_is_summed_up_as_an_alert_argus_closed_never_as_an_incident() -> None:
    # Measured as an incident, it read as a service broken from the alert and
    # never back, with a loss nobody could count. There was no incident: the
    # alert and when Argus closed it, then why in the model's words.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None,
                                           ended_at=STARTED_AT + timedelta(seconds=5),
                                           candidates=[], actions=[], disproven=True),
            measured := a_measured_incident(onset_at=None, back_to_normal_at=None,
                                            duration_in_hours=5 / 3600, loss=None,
                                            baseline_revenue=None, takings=None, rates=None)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, SOME_RISK)
        ) \
        .then(
            the_answer_was(f"The alert came at 12:10 UTC, and Argus closed it as disproven at "
                           f"12:10:05 UTC. {SOME_CAUSE} {SOME_RISK}")
        )


@pytest.mark.unit
def test_nothing_still_at_risk_is_left_unsaid() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[an_action(SOME_ACTION,
                                                             verdict=Verdict.CONFIRMED)]),
            measured := a_measured_incident(loss=None)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            the_answer_was(
                "The service broke at 12:00 UTC and was back to normal at 12:10 UTC, "
                "10 minutes later. No loss was estimated: the shop's takings could not be "
                f"read. {SOME_CAUSE} What Argus did: reverted the feature flag checkout-v2 "
                f"(can be put back) - confirmed, still in place.")
        )


def _says(*expected: str) -> Assertion[str]:
    def assertion(summary: str) -> bool:
        missing = [wanted for wanted in expected if wanted not in summary]
        if missing:
            raise AssertionError(f"Expected the summary to say {missing}, and it said: "
                                 f"{summary}")

        return True

    return assertion


def _does_not_say(unwanted: str) -> Assertion[str]:
    def assertion(summary: str) -> bool:
        if unwanted in summary:
            raise AssertionError(f"Expected the summary not to say [{unwanted}], and it said: "
                                 f"{summary}")

        return True

    return assertion
