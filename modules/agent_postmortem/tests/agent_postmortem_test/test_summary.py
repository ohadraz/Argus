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

from datetime import timedelta
from decimal import Decimal

import pytest
from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels
from agent_postmortem.summary import the_executive_summary
from argus_core import level_said_in, to_iso
from argus_core.models import OpenedPullRequest, Verdict, said_as_money
from argus_testkit import Assertion, Scenario, the_answer_was

from agent_postmortem_test.framework.builders import (
    ONSET,
    SOME_CURRENCY,
    a_candidate,
    a_measured_incident,
    an_action,
    an_evidence_bundle,
)

SOME_CAUSE = "A rename reached one of the two files that name the port."
SOME_RISK = "Any other service renamed the same way loses its metrics too."


@pytest.mark.unit
def test_an_ordinary_incident_is_summed_up_in_the_order_a_reader_asks_about_it() -> None:
    # When and for how long, how bad, the cause, what was done, what is still
    # at risk.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[an_action("turned checkout-v2 off",
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
                f"read. {SOME_CAUSE} What Argus did: turned checkout-v2 off (can be put "
                f"back) - confirmed, still in place. {SOME_RISK}")
        )


@pytest.mark.unit
def test_a_service_never_seen_back_is_said_broken_for_at_least_as_long_as_argus_worked_on_it(
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
            _says("The service broke at 12:00 UTC and was not back to normal when Argus "
                  "stopped working on the incident at 12:30 UTC, at least 30 minutes later.")
        )


@pytest.mark.unit
def test_metrics_that_stopped_are_said_unseen_with_where_the_logs_reach_and_their_reading_ended(
) -> None:
    # Not a stretch the service is known to have spent broken: its own logs
    # show it up to where they reach, and nothing after the reading ended was
    # read - said apart, since where the lines stop is as often where the
    # reading did.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                log_lines=[f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"],
                logs_read_until=ONSET + timedelta(minutes=20)),
            measured := a_measured_incident(back_to_normal_at=None, unobserved_from=ONSET,
                                            duration_in_hours=0.5)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("No metrics were collected from 12:00 UTC on, and they had not resumed when "
                  "Argus stopped working on the incident at 12:30 UTC, 30 minutes later. The "
                  "service's own logs show it until 12:04 UTC, and the logs were read up to "
                  "12:20 UTC.")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("log_lines", "said"), [
    ([], "No logs were read."),
    ([f"{to_iso(ONSET - timedelta(minutes=10))} WARN io-shop: dont care"],
     "No log line read reaches into that stretch, and the logs were read up to 12:20 UTC.")
], ids=["no-logs-read", "none-reaching-in"])
def test_logs_that_show_nothing_of_the_unseen_stretch_are_said_to_show_nothing(
        log_lines: list[str], said: str) -> None:
    # Said rather than left out: a summary silent on the logs reads the same as
    # one whose logs nobody looked at.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=log_lines,
                                           logs_read_until=ONSET + timedelta(minutes=20)),
            measured := a_measured_incident(back_to_normal_at=None, unobserved_from=ONSET,
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
@pytest.mark.parametrize(("loss", "back", "said"), [
    (Decimal("500"), True,
     f"The shop's takings fell short of the same hours on earlier weeks by "
     f"{said_as_money(Decimal('500'), SOME_CURRENCY)}, beyond how much those hours vary on "
     f"their own."),
    (Decimal("500"), False,
     f"The shop's takings fell short of the same hours on earlier weeks by at least "
     f"{said_as_money(Decimal('500'), SOME_CURRENCY)} so far, beyond how much those hours "
     f"vary on their own."),
    (Decimal("0"), True,
     "The shop's takings fell short of the same hours on earlier weeks by no more than "
     "those hours vary on their own, if at all."),
    (Decimal("0"), False,
     "The shop's takings fell short of the same hours on earlier weeks by no more than "
     "those hours vary on their own so far, if at all."),
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
                "turned checkout-v2 off", verdict=Verdict.CONFIRMED,
                taken_at=ONSET + timedelta(minutes=12))]),
            measured := a_measured_incident(back_before_the_action=True)
        ) \
        .when(
            lambda: the_executive_summary(evidence, measured, SOME_CAUSE, "")
        ) \
        .then(
            _says("The service was back to normal at 12:10 UTC, before turned checkout-v2 off "
                  "at 12:12 UTC - so not because of it.")
        )


@pytest.mark.unit
def test_a_cause_argus_held_back_from_testing_is_said_with_why_in_its_own_words() -> None:
    # The candidate's own words for why, not its row's "never tried: ...",
    # which would say it twice. By its rank, not its summary: that is the
    # investigator's own sentences, three of them in one write-up, and set
    # inside this one they run on into the reason. Its label after the rank,
    # which leads to its row on the page and to nothing where the summary is
    # said on its own.
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
            _says("Argus did not test the cause it ranked first (C1): rolling it back would "
                  "undo a change somebody meant.")
        )


@pytest.mark.unit
def test_a_draft_fix_and_a_recommended_action_are_said_as_left_to_a_person() -> None:
    # Never as having fixed anything: nothing ran the fix, and nothing took
    # the recommendation.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                pull_request=OpenedPullRequest(number=315, url="https://github.invalid/pull/315",
                                               branch="dont-care"),
                recommended_action="restart the scorer")
        ) \
        .when(
            lambda: the_executive_summary(evidence, a_measured_incident(), SOME_CAUSE, "")
        ) \
        .then(
            _says("Argus opened a draft fix, pull request #315, for a person to review and "
                  "merge.",
                  "Argus recommends this and did not take it: restart the scorer.")
        )


@pytest.mark.unit
def test_nothing_still_at_risk_is_left_unsaid() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[an_action("turned checkout-v2 off",
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
                f"read. {SOME_CAUSE} What Argus did: turned checkout-v2 off (can be put "
                f"back) - confirmed, still in place.")
        )


def _says(*expected: str) -> Assertion[str]:
    def assertion(summary: str) -> bool:
        missing = [wanted for wanted in expected if wanted not in summary]
        if missing:
            raise AssertionError(f"Expected the summary to say {missing}, and it said: "
                                 f"{summary}")

        return True

    return assertion
