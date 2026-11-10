"""Argus's own screen, through the browser's door.

Nothing is stubbed: a request reaches the real app, reads through the real
repositories against a real Postgres, and comes back as the HTML a person
looking at the demo would get. The assertions are on data attributes the
templates carry deliberately - a page contract, rather than on prose, which is
free to change without any of these tests having an opinion.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus as HttpStatus

import httpx2
import psycopg
import pytest
from argus_core import connect_from_env, new_id, to_iso, utc_now
from argus_core.events import (
    ChangesRetrieved,
    HypothesisFormed,
    LogsRetrieved,
    MetricsRetrieved,
    PostmortemWritten,
    QuestionAnswered,
    StatusChanged,
)
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ActionType,
    AlarmClaim,
    Alert,
    ChainStep,
    ChangeEvent,
    ChangeKind,
    ChannelReading,
    CitedChange,
    CitedEvidence,
    ContributingFactor,
    Detection,
    Evidence,
    ExecutiveSynopsisDocument,
    FailureMode,
    FirstTold,
    FlagUndo,
    Hypothesis,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    IncidentStatus,
    Lessons,
    LogsInTheGap,
    MetricBucket,
    NoTrigger,
    OpenedPullRequest,
    PostmortemDocument,
    PostmortemLead,
    Reference,
    Report,
    ReportChannel,
    ResolutionStep,
    ReviewCriterion,
    RevisionSource,
    RuledOut,
    RuleSeriesHarm,
    Standing,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Undone,
    Verdict,
    Weighing,
    WhyNoTrigger,
)
from argus_incidents.repository import (
    events,
    hypotheses,
    incidents,
    postmortems,
    synopses,
    taken_actions,
)
from argus_testkit import Assertion, Scenario, all_of
from argus_web.app import app
from fastapi.testclient import TestClient

from argus_web_test.framework.assertions import (
    POLLS_FOR_MORE,
    the_page_keeps_asking,
    the_page_links_to,
    the_page_says,
    the_page_shows,
    the_response_was,
)
from argus_web_test.framework.reading import attribute, page_at

# What htmx's "ask again in a moment" looks like in the rendered page. Named
# because two assertions read it and they must read the same thing: one saying
# the page polls and one saying it has stopped, disagreeing about the spelling,
# would both pass on a page that does neither.

# The postmortem's sections, by the names the page gives them, in the order the
# template puts them.
POSTMORTEM_SECTIONS = ["summary", "impact", "cause", "hypotheses", "trigger", "resolution",
                       "detection", "action-items", "lessons", "timeline", "leads",
                       "response-effort", "supporting", "review"]

# The demo app's own names, taken from Argus-Demo-Target-App: its service, the
# rules it alerts by and the uid of the first of them, the flag its scenarios
# turn on, and the other service it calls. Any names would do in these tests;
# they must not change unless the demo app does.
SOME_SERVICE = "io-shop"
SOME_OTHER_SERVICE = "io-pricing"
SOME_ALERT_NAME = "HighErrorRate"
SOME_LATENCY_ALERT_NAME = "HighLatency"
SOME_RECONCILIATION_ALERT_NAME = "SpendTotalsDoNotReconcile"
SOME_CONFIDENCE_ALERT_NAME = "CategorisationConfidenceLow"
SOME_RULE_ID = "io-shop-high-error-rate"
SOME_FLAG = "monthly-spend-feature"

# The alert an incident is opened by, wherever nothing about the alert is read.
DONT_CARE_ALERT = Alert(service=SOME_SERVICE, alert_name=SOME_ALERT_NAME)

# What a field nothing reads is filled with.
DONT_CARE_WORDS = "dont care"
DONT_CARE_SUBJECT = "dont-care"
DONT_CARE_OTHER_SUBJECT = "dont-care-either"
DONT_CARE_ACTION: ActionType = REVERT_FEATURE_FLAG
DONT_CARE_CONFIDENCE = 0.9
DONT_CARE_CURRENCY = "usd"
DONT_CARE_CRITERION = "Root-cause analysis complete"
DONT_CARE_PERSON_ID = "U-some-person"
DONT_CARE_MOMENT = datetime(2026, 10, 11, 14, 11, tzinfo=UTC)
DONT_CARE_CHANGED_AT = to_iso(DONT_CARE_MOMENT)

# When an incident began, and a minute a candidate's finding names.
SOME_ONSET = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)
SOME_MINUTE = datetime(2026, 8, 30, 10, 14, tzinfo=UTC)

# The labels a document cites its rows by - one of each kind, and a second
# where a test needs two.
SOME_CANDIDATE_LABEL = "C1"
SOME_OTHER_CANDIDATE_LABEL = "C2"
SOME_STEP_LABEL = "M1"
SOME_ACTION_ITEM_NUMBER = "AI-1"
SOME_OTHER_ACTION_ITEM_NUMBER = "AI-2"
SOME_LINE_LABEL = "T1"
SOME_CHANGE_LABEL = "P1"
SOME_OTHER_CHANGE_LABEL = "P2"
SOME_LEAD_LABEL = "L1"

# Who did what, and the words a person ended an incident with.
SOME_ACTOR = "Argus"
SOME_PERSON = "Kuki Buki"
SOME_NOTE = "rolled the flag back by hand"

# A symptom, and the two states a flag moved between.
SOME_SYMPTOM = "Account pages failed"
SOME_FROM_STATE, SOME_TO_STATE = "off", "on"

# A repository, a revision deployed from it, and a later revision deployed in
# place of an earlier one.
SOME_REPOSITORY_NAME = "acme/shop"
SOME_REPOSITORY = f"https://github.com/{SOME_REPOSITORY_NAME}"
SOME_REVISION = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
SOME_EARLIER_REVISION = "4c810f22894e612ced87f5ee3f3062dfeb785050"
SOME_LATER_REVISION = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"

# The fix Code-Fix proposed, its address made of its number.
SOME_FIX_NUMBER = 7
A_FIX = OpenedPullRequest(number=SOME_FIX_NUMBER,
                          url=f"https://github.invalid/ohadraz/io-shop/pull/{SOME_FIX_NUMBER}",
                          branch="argus/fix-abc")


@pytest.mark.component
def test_the_history_lists_incidents_newest_first() -> None:
    # The history opens on what just happened. Oldest-first would put the
    # incident somebody came looking for at the bottom of the page.
    an_older_alert = Alert(service="older-service", alert_name=SOME_ALERT_NAME)
    a_newer_alert = Alert(service="newer-service", alert_name=SOME_ALERT_NAME)

    with connect_from_env() as conn:
        older = incidents.create(conn, an_older_alert, at=utc_now())
        conn.commit()  # `now()` is transaction time - one transaction, one timestamp
        newer = incidents.create(conn, a_newer_alert, at=utc_now())

    Scenario() \
        .given(
            older, newer
        ) \
        .when(
            lambda: page_at("/history")
        ) \
        .then(
            _the_page_lists(newer, above=older)
        )


@pytest.mark.component
def test_the_history_links_to_each_incident() -> None:
    # A list of incidents nobody can open is a list of ids.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at("/history")
        ) \
        .then(
            the_page_links_to(f"/incidents/{incident_id}")
        )


@pytest.mark.component
def test_the_history_keeps_asking_for_more() -> None:
    # The demo posture is somebody watching Argus's screen for it to react. A
    # history that only lists what existed when the page was opened means the
    # incident they are waiting for never arrives.
    Scenario() \
        .when(
            lambda: page_at("/history")
        ) \
        .then(
            the_page_keeps_asking()
        )


@pytest.mark.component
def test_the_polled_history_fragment_carries_the_incidents() -> None:
    # What the poll swaps in. If it did not carry the list, the page would
    # refresh itself into an empty one every two seconds.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at("/history/list")
        ) \
        .then(
            _the_page_lists_the_incident(incident_id)
        )


@pytest.mark.component
def test_a_time_is_shown_in_the_zone_it_is_written_in() -> None:
    # The shop's console stamps its minutes in UTC and says so. An unlabelled
    # time here reads as local, and on a screen beside that console it looks
    # like the two disagree about when the incident happened.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: [page_at("/history"), page_at(f"/incidents/{incident_id}")]
        ) \
        .then(
            _every_page_says("UTC")
        )


@pytest.mark.component
def test_an_incident_page_shows_every_candidate_by_its_number() -> None:
    # A walk rendered without the candidates it got wrong reads as a lucky
    # guess. In the order they were formed across the rounds, each by the
    # number the timeline and the chat said it by - a second round's first is
    # #3, where its rank would say #1 and name another candidate.
    some_first, some_second, some_third = "first", "second", "third"
    the_second_round_s_first = 3

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_candidate_recorded_for(conn, incident_id, subject=some_third, rank=1,
                                  number=the_second_round_s_first)
        _a_candidate_recorded_for(conn, incident_id, subject=some_second, rank=2,
                                  number=the_second_round_s_first - 1)
        _a_candidate_recorded_for(conn, incident_id, subject=some_first, rank=1,
                                  number=the_second_round_s_first - 2)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_shows("subject", some_first, some_second, some_third),
            the_page_says(f'<span class="number">#{the_second_round_s_first}</span>')
        ))


@pytest.mark.component
def test_the_timeline_says_each_candidate_by_its_own_number() -> None:
    # Under the line that formed them, by the number each keeps for the whole
    # incident, read rather than counted: a list counting from one again would
    # say a second round's first as #1, the first round's own number.
    the_second_round_s_first = 3

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, HypothesisFormed(
            incident_id=incident_id, hypothesis_id=new_id(), summary=DONT_CARE_WORDS,
            failure_mode=None, confidence=None, subject=None, rank=1,
            number=the_second_round_s_first))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_says(f'<li data-candidate="{the_second_round_s_first}" '
                          f'value="{the_second_round_s_first}">')
        )


@pytest.mark.component
def test_an_incident_page_distinguishes_a_candidate_the_walk_never_reached() -> None:
    # "Never reached" and "tried and refuted" are the difference between a walk
    # that ran out of options and one that stopped because it was right.
    dont_care_result = "confirmed"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        tried = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT, rank=1)
        _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_OTHER_SUBJECT, rank=2)
        hypotheses.record_outcome(conn, tried, tested=True, result=dont_care_result)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_shows("tested", "true", "false")
        )


@pytest.mark.component
def test_an_incident_page_says_a_candidate_whose_test_was_held_back_was_held_back() -> None:
    # The walk reached it and the gate declined its test, writing why on its
    # row. Said "never reached", a refusal read as a candidate nobody got to -
    # the same words the one after it, which nobody did get to, carried.
    some_reason = "some reason the gate held its test back"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        held_back = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT,
                                              rank=1)
        hypotheses.record_outcome(conn, held_back, tested=False, result=some_reason)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"test held back: {some_reason}"),
            _the_page_does_not_say("never reached")
        ))


@pytest.mark.component
def test_an_incident_page_says_a_candidate_whose_action_a_tier_could_not_take_was_not_taken(
) -> None:
    # The gate let the test through and the tier had nowhere to take the
    # action, writing why on the row. The write-up says "action not taken", and
    # the page says the same fact in the same words - not the gate's - with the
    # name it quotes set as code, as every line shown sets it.
    some_name = SOME_SERVICE
    some_rest_of_the_reason = "has no revision before the one it is running"
    reason_quoting_a_name = f"[{some_name}] {some_rest_of_the_reason}"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        not_taken = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT,
                                              rank=1)
        _an_attempt_taken_for(conn, incident_id, not_taken, outcome=Verdict.NOT_ATTEMPTED,
                              performed=False)
        hypotheses.record_outcome(conn, not_taken, tested=False,
                                  result=reason_quoting_a_name)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"action not taken: <code>{some_name}</code> "
                          f"{some_rest_of_the_reason}"),
            _the_page_does_not_say("test held back")
        ))


@pytest.mark.component
def test_an_incident_page_does_not_say_a_candidate_with_an_attempt_was_never_reached() -> None:
    # A walk stopped while its action was out - a person reported the incident
    # over - leaves the candidate untested and without a result, its attempt
    # shown beneath it. Said "never reached", the line denied the attempt
    # printed right under it.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        stopped = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT,
                                            rank=1)
        _an_attempt_taken_for(conn, incident_id, stopped, outcome=Verdict.STOPPED)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_does_not_say("never reached")
        )


@pytest.mark.component
def test_an_incident_page_shows_a_candidates_evidence_with_the_candidate() -> None:
    # Evidence in a dump of its own makes a reader match claims to timestamps,
    # which is the reader investigating the incident again. In words: the page
    # printed each as the record it is kept in, "claim='...' at=datetime...".
    a_cited_line = "error rate rose at 10:14"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_candidate_recorded_for(
            conn,
            incident_id,
            subject=DONT_CARE_SUBJECT,
            rank=1,
            evidence=[a_cited_line]
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(a_cited_line),
            _the_page_does_not_say("claim=")
        ))


@pytest.mark.component
def test_a_candidates_finding_naming_a_minute_the_page_holds_links_to_it() -> None:
    # As the same finding does in the timeline. Said in words and leading
    # nowhere, the minute the finding rests on was left for a reader to find -
    # on the page, and in the fragment its poll swaps in every two seconds.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _metrics_showing(incident_id, SOME_MINUTE))
        events.record(conn, _logs_read_at(incident_id, SOME_MINUTE))
        hypotheses.record(conn, Hypothesis(
            incident_id=incident_id,
            summary=DONT_CARE_WORDS,
            failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
            confidence=DONT_CARE_CONFIDENCE,
            supporting_evidence=[_a_finding_inside(SOME_MINUTE)],
            subject=DONT_CARE_SUBJECT,
            rank=1
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: [page_at(f"/incidents/{incident_id}"),
                     page_at(f"/incidents/{incident_id}/walk")]
        ) \
        .then(
            _the_candidates_link_to(f"#minute-{SOME_MINUTE:%Y-%m-%dT%H:%M:%SZ}",
                                    f"#log-at-{SOME_MINUTE:%Y-%m-%dT%H:%M}")
        )


@pytest.mark.component
def test_a_findings_links_are_named_for_the_minute_they_open() -> None:
    # Named "the minute" and "its log lines", a link after a claim naming
    # another moment read as that one: an alert whose oldest purchase was
    # Oct 17 20:36 led to Oct 24 20:35, the minute it fired.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _metrics_showing(incident_id, SOME_MINUTE))
        events.record(conn, _logs_read_at(incident_id, SOME_MINUTE))
        hypotheses.record(conn, Hypothesis(
            incident_id=incident_id,
            summary=DONT_CARE_WORDS,
            failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
            confidence=DONT_CARE_CONFIDENCE,
            supporting_evidence=[_a_finding_inside(SOME_MINUTE)],
            subject=DONT_CARE_SUBJECT,
            rank=1
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f">{SOME_MINUTE:%b %d %H:%M}</a>"),
            the_page_says(f">log lines at {SOME_MINUTE:%b %d %H:%M}</a>"),
            _the_page_does_not_say(">the minute</a>"),
            _the_page_does_not_say(">its log lines</a>")
        ))


@pytest.mark.component
def test_a_finding_in_the_timeline_names_its_links_for_the_minute_they_open() -> None:
    # As under Candidates. The timeline says a candidate's findings from the
    # event the Investigator formed it in, by a template of its own.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _metrics_showing(incident_id, SOME_MINUTE))
        events.record(conn, _logs_read_at(incident_id, SOME_MINUTE))
        events.record(conn, HypothesisFormed(
            incident_id=incident_id, hypothesis_id=new_id(), summary=DONT_CARE_WORDS,
            failure_mode=None, confidence=None, subject=DONT_CARE_SUBJECT, rank=1, number=1,
            evidence=[_a_finding_inside(SOME_MINUTE)]))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            _the_timeline_says(f">{SOME_MINUTE:%b %d %H:%M}</a>"),
            _the_timeline_says(f">log lines at {SOME_MINUTE:%b %d %H:%M}</a>")
        ))


@pytest.mark.component
def test_an_incident_page_shows_what_putting_each_refuted_attempt_back_did() -> None:
    # A reversible action that did not help is undone before its verdict is
    # returned, and the row says how: put back, or left as somebody else had
    # since set it. A page showing the attempt without that would leave a
    # reader believing the flag is still flipped - and one saying "put back"
    # for both would hand somebody's change back to Argus.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        restored = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT,
                                             rank=1)
        left = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT, rank=2)
        confirmed = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT,
                                              rank=3)
        _an_attempt_taken_for(conn, incident_id, restored, outcome=Verdict.REFUTED,
                              undone=Undone.RESTORED)
        _an_attempt_taken_for(conn, incident_id, left, outcome=Verdict.REFUTED,
                              undone=Undone.LEFT_AS_FOUND)
        _an_attempt_taken_for(conn, incident_id, confirmed, outcome=Verdict.CONFIRMED)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_shows("outcome", "refuted", "refuted", "confirmed"),
            the_page_shows("undone", "restored", "left-as-found", ""),
            the_page_says(">put back<"),
            the_page_says(">left as found<")
        ))


@pytest.mark.component
@pytest.mark.parametrize(("status", "said", "never_said"), [
    pytest.param(IncidentStatus.MITIGATING, "no verdict yet", "no verdict recorded",
                 id="still-worked"),
    pytest.param(IncidentStatus.ESCALATED, "no verdict recorded", "no verdict yet",
                 id="over")
])
def test_an_attempt_with_no_verdict_says_whether_one_is_still_coming(
        status: IncidentStatus, said: str, never_said: str) -> None:
    # While the incident is worked, an action with no verdict is one the
    # service has not answered yet. Once it is over, no answer is coming - the
    # worker taking it stopped - and "yet" would promise one.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        candidate = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT,
                                              rank=1)
        taken_actions.claim(conn, incident_id, hypothesis_id=candidate,
                            action_type=DONT_CARE_ACTION, subject=DONT_CARE_SUBJECT,
                            at=utc_now())
        incidents.transition(conn, incident_id, status, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(said),
            _the_page_never_says(never_said)
        ))


@pytest.mark.component
def test_a_running_incident_keeps_asking_for_more() -> None:
    # The point of watching it beside the shop's console: the walk moves on
    # this screen without anybody pressing refresh.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_keeps_asking()
        )


@pytest.mark.component
def test_a_finished_incident_stops_asking() -> None:
    # A finished incident's page that keeps polling is a page that will still
    # be polling tomorrow.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_has_stopped_asking()
        )


@pytest.mark.component
def test_the_polled_fragment_carries_the_walk_on_its_own() -> None:
    # What the poll swaps in. If it did not carry the walk, a page watched from
    # the first second would never show one.
    some_subject = "a-flag"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_candidate_recorded_for(conn, incident_id, subject=some_subject, rank=1)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/walk")
        ) \
        .then(
            the_page_shows("subject", some_subject)
        )


@pytest.mark.component
@pytest.mark.parametrize(("ending", "said"), [
    (None, "No explanation has been formed yet."),
    (IncidentStatus.ESCALATED, "No explanation was formed."),
    (IncidentStatus.DISPROVEN, "None: the alarm was disproven.")
], ids=["running", "ended", "disproven"])
def test_an_incident_with_no_candidate_says_whether_one_can_still_come(
        ending: IncidentStatus | None, said: str) -> None:
    # "Yet" promises an explanation, which an ended incident will never form -
    # and of a disproven alarm there was nothing to explain.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        if ending is not None:
            incidents.transition(conn, incident_id, ending, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/walk")
        ) \
        .then(
            the_page_says(f'<li class="empty">{said}</li>')
        )


@pytest.mark.component
def test_an_unknown_incident_is_reported_as_unknown() -> None:
    # An empty page for an id that never existed invents a record.
    a_nonexistent_id = "00000000-0000-0000-0000-000000000000"

    with TestClient(app) as client:
        Scenario() \
            .given(
                a_nonexistent_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{a_nonexistent_id}")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_a_postmortem_is_shown_on_its_own_page() -> None:
    # Its own page because it is the largest body Argus writes, and the
    # incident page beside it polls every two seconds.
    a_root_cause = "a-flag was enabled"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=a_root_cause,
                executive_summary=DONT_CARE_WORDS,
                customer_loss_estimate=None,
                estimate_currency=DONT_CARE_CURRENCY,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[DONT_CARE_WORDS]
            ),
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(a_root_cause)
        )


@pytest.mark.component
def test_a_postmortem_page_shows_a_name_its_candidates_and_summary_quote_as_code() -> None:
    # A candidate's result is the walk's own words, and the summary carries it;
    # the page says the name in either as its timeline does.
    some_name = SOME_SERVICE
    dont_care_label = "C1"
    some_lead_in = "action not taken:"
    some_result_said_of_it = "is old"
    some_summary_said_of_it = "is new."

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=None,
                executive_summary=f"Argus did not test {dont_care_label}: [{some_name}] "
                                  f"{some_summary_said_of_it}",
                customer_loss_estimate=None,
                estimate_currency=None,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[],
                hypotheses=[HypothesisConsidered(
                    summary=DONT_CARE_WORDS, confidence=None,
                    result=f"{some_lead_in} [{some_name}] {some_result_said_of_it}",
                    label=dont_care_label)]
            ),
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(f"{some_lead_in} <code>{some_name}</code> {some_result_said_of_it}"),
            the_page_says(f"<code>{some_name}</code> {some_summary_said_of_it}")
        ))


@pytest.mark.component
def test_an_incident_with_no_postmortem_says_so_rather_than_failing() -> None:
    # Most incidents have none for most of their life, and an error for the
    # ordinary case trains a reader to ignore errors.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/postmortem")
            ) \
            .then(
                the_response_was(HttpStatus.OK)
            )


@pytest.mark.component
def test_the_postmortem_page_offers_the_document_as_a_pdf() -> None:
    # The same words in a file a reader keeps, forwards and attaches.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("postmortem-pdf", f"/incidents/{incident_id}/postmortem.pdf")
        )


@pytest.mark.component
def test_the_postmortem_page_s_all_incidents_link_leads_to_the_list_of_them() -> None:
    # "/" is the live page - one incident, not a list of them - so a link
    # promising all of them and leading there leaves the reader on the wrong
    # page. The incident page's own link goes to the history, and this one says
    # the same words.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says('<a href="/history">all incidents</a>')
        )


@pytest.mark.component
def test_an_incident_with_no_postmortem_offers_no_pdf_of_one() -> None:
    # A download of nothing would be a file that fails to open.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_shows_no("postmortem-pdf")
        )


@pytest.mark.component
def test_the_postmortem_downloads_as_a_pdf_named_for_its_incident() -> None:
    # Saved among others like it, a file is found again by its name.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/postmortem.pdf")
            ) \
            .then(
                _a_pdf_to_save_as(f"argus-postmortem-{incident_id}.pdf")
            )


@pytest.mark.component
def test_an_incident_with_no_postmortem_has_no_pdf_of_one() -> None:
    # The page says so in words; a file has no words to say it with.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/postmortem.pdf")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_an_unknown_incident_has_no_pdf() -> None:
    a_nonexistent_id = "00000000-0000-0000-0000-000000000000"

    with TestClient(app) as client:
        Scenario() \
            .given(
                a_nonexistent_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{a_nonexistent_id}/postmortem.pdf")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_the_executive_synopsis_downloads_as_a_pdf_named_for_its_incident() -> None:
    # What the synopsis's Slack message links to, saved among others like it.
    dont_care_overview = "dont care what it says"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])
        _a_synopsis_recorded_for(conn, incident_id, overview=dont_care_overview)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/synopsis.pdf")
            ) \
            .then(
                _a_pdf_to_save_as(f"argus-executive-synopsis-{incident_id}.pdf")
            )


@pytest.mark.component
def test_an_incident_with_no_synopsis_has_no_pdf_of_one() -> None:
    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/synopsis.pdf")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_a_synopsis_given_up_has_no_pdf_of_one() -> None:
    # No overview, so nothing was sent and there is nothing to print.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])
        _a_synopsis_recorded_for(conn, incident_id, overview=None)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/synopsis.pdf")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_a_running_incident_can_be_withdrawn_from_its_page() -> None:
    # The first button anybody wants during an incident, and the only thing on
    # this screen that acts rather than reports.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"/incidents/{incident_id}/withdraw"),
            the_page_shows("withdraw", incident_id)
        ))


@pytest.mark.component
def test_a_finished_incident_offers_no_way_to_withdraw_it() -> None:
    # Nothing to stop. Offering it would invite somebody to undo a
    # mitigation that is holding the service up, and the answer would be a 409
    # they had no reason to expect.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_shows_no("withdraw")
        )


@pytest.mark.component
def test_a_running_incident_can_be_resolved_from_its_page() -> None:
    # The other thing a person may tell Argus: that it is over. Offered beside
    # the withdraw button, because the two are the two ways a person ends an
    # incident.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"/incidents/{incident_id}/resolve"),
            the_page_shows("resolve", incident_id)
        ))


@pytest.mark.component
def test_an_incident_argus_escalated_can_still_be_resolved_and_not_withdrawn() -> None:
    # Argus stopped and somebody carried on - exactly the person who comes back
    # to report it over. Withdrawing it is another matter: there is nothing of
    # Argus's left running to stop.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.ESCALATED, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_shows("resolve", incident_id),
            _the_page_shows_no("withdraw")
        ))


@pytest.mark.component
def test_a_withdrawn_incident_offers_no_way_to_resolve_it() -> None:
    # It ended for its own reason, and the answer to a press would be a 409
    # nobody had reason to expect.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        incidents.withdraw(conn, incident_id, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_shows_no("resolve")
        )


@pytest.mark.component
def test_the_postmortem_page_says_who_resolved_the_incident_and_what_they_said() -> None:
    # Beside the document rather than in it. A postmortem written before the
    # person reported the incident over is not rewritten, and one written after
    # is the model's prose - either way, who ended it, through which door, when
    # and in what words is read off the account and shown as it was recorded.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=DONT_CARE_WORDS,
                executive_summary=DONT_CARE_WORDS,
                customer_loss_estimate=None,
                estimate_currency=DONT_CARE_CURRENCY,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[DONT_CARE_WORDS]
            ),
            at=utc_now()
        )
        events.record(conn, StatusChanged(
            incident_id=incident_id,
            to_status=IncidentStatus.RESOLVED,
            reported=Report(by=SOME_PERSON, channel=ReportChannel.ARGUS_UI, note=SOME_NOTE)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(SOME_PERSON),
            the_page_says("the Argus UI"),
            the_page_says(SOME_NOTE)
        ))


@pytest.mark.component
def test_an_incident_a_person_resolved_before_any_postmortem_says_who_on_its_page() -> None:
    # The document may never come - the walk can end without one - and the
    # person who ended the incident is owed the line either way.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, StatusChanged(
            incident_id=incident_id,
            to_status=IncidentStatus.RESOLVED,
            reported=Report(by=SOME_PERSON, channel=ReportChannel.ARGUS_UI, note=SOME_NOTE)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_shows("resolution", SOME_PERSON),
            the_page_says(SOME_NOTE)
        ))


@pytest.mark.component
def test_the_postmortem_page_says_how_many_responded_and_what_they_were() -> None:
    # Minutes alone read as one person's night. The count is what makes them
    # person-minutes on the page as well as in the row, and the titles are the
    # part a reader can act on - a senior engineer and an SRE spending two
    # hours is a different sentence from "120".
    some_minutes = 88
    some_responders = 2
    some_title = "Principal Kuki Buki"
    some_other_title = "Senior Shuki Tuki"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=DONT_CARE_WORDS,
                executive_summary=DONT_CARE_WORDS,
                customer_loss_estimate=None,
                estimate_currency=DONT_CARE_CURRENCY,
                engineer_minutes=some_minutes,
                responders=some_responders,
                responder_titles=[some_title, some_other_title],
                tokens_spent=None,
                assumptions=[DONT_CARE_WORDS]
            ),
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(str(some_minutes)),
            the_page_says(str(some_responders)),
            the_page_says(some_title),
            the_page_says(some_other_title)
        ))


@pytest.mark.component
def test_the_postmortem_page_says_what_people_told_the_incident_and_what_it_changed() -> None:
    # The person who wrote a lead comes looking for what became of it. Their
    # words, what the investigation made of them and whether they changed what
    # was done are one answer, so the page gives all three together - and a
    # lead written too late to be weighed says so rather than standing bare.
    # Each is credited by name, and by the platform's id where it gave none.
    some_name = "Some Person"
    some_unnamed_person = "U-another-person"
    some_words = "the kuki flag was flipped at noon"
    some_reason = "the flag history agrees"
    some_effect = "it named the flag that was reverted"
    some_late_words = "it is the database again"
    dont_care_other_label = "L2"
    dont_care_later_moment = DONT_CARE_MOMENT + timedelta(minutes=11)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=DONT_CARE_WORDS,
                executive_summary=DONT_CARE_WORDS,
                customer_loss_estimate=None,
                estimate_currency=None,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[],
                leads=[
                    PostmortemLead(
                        label=SOME_LEAD_LABEL,
                        person_id=DONT_CARE_PERSON_ID,
                        person_name=some_name,
                        text=some_words,
                        written_at=DONT_CARE_MOMENT,
                        weighing=Weighing(standing=Standing.SUPPORTED, reason=some_reason),
                        effect=some_effect
                    ),
                    PostmortemLead(
                        label=dont_care_other_label,
                        person_id=some_unnamed_person,
                        person_name=None,
                        text=some_late_words,
                        written_at=dont_care_later_moment,
                        weighing=None,
                        effect=None
                    )
                ]
            ),
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(some_words),
            the_page_says(Standing.SUPPORTED.value),
            the_page_says(some_reason),
            the_page_says(some_effect),
            the_page_says(some_late_words),
            the_page_says("never weighed"),
            # Credited as the line credits them - by name, or by the id where
            # the platform gave no name - rather than found in an attribute.
            the_page_says(f"- {some_name},"),
            the_page_says(f"- {some_unnamed_person},")
        ))


@pytest.mark.component
def test_the_postmortem_page_shows_the_template_s_sections_in_its_order() -> None:
    # Google's order, the cause after what happened rather than before it: a
    # reader learns what broke and for how long before reading why.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[PostmortemLead(
            label=SOME_LEAD_LABEL,
            person_id=DONT_CARE_PERSON_ID,
            person_name=None,
            text=DONT_CARE_WORDS,
            written_at=DONT_CARE_MOMENT,
            weighing=None,
            effect=None
        )])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("section", *POSTMORTEM_SECTIONS)
        )


@pytest.mark.component
def test_a_postmortem_section_with_nothing_in_it_is_still_shown_but_what_people_said() -> None:
    # A section left out reads as one nobody thought to write; one that says
    # it has nothing reads as the answer it is. What people told the incident
    # is the exception - an incident nobody wrote in has no such section.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("section", *[section for section in POSTMORTEM_SECTIONS
                                        if section != "leads"])
        )


@pytest.mark.component
def test_the_postmortem_header_names_its_incident_and_tells_its_two_times_apart() -> None:
    # When the service was broken and when the document was written are both
    # times, and a reader taking one for the other dates the incident wrong.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_shows("postmortem-of", incident_id),
            the_page_shows("time", "incident", "written")
        ))


@pytest.mark.component
def test_the_postmortem_header_links_its_incident_in_full() -> None:
    # The id alone names the incident and leads nowhere; in full for the reason
    # the supporting links are - the document is read away from this screen.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("incident-link", f"http://testserver/incidents/{incident_id}")
        )


@pytest.mark.component
def test_the_postmortem_page_links_its_incident_by_its_title_and_in_full_alone() -> None:
    # The title leads to the incident, and the supporting information writes
    # its address out for a reader away from this screen. The id, an "incident
    # page" beside it and a footer's "the walk" would each say it again.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _links_to_its_incident(incident_id, times=2)
        )


@pytest.mark.component
def test_a_refusal_in_the_resolution_gives_its_row_no_anchor() -> None:
    # A refusal has no label, so its row has nothing for a citation to land on
    # - and an anchor of "None" on each refusal is an id two rows would share.
    dont_care_outcome = "not taken"
    some_refusal = ResolutionStep(at=DONT_CARE_MOMENT,
                                  action=f"Refused to act - {DONT_CARE_WORDS}", by=SOME_ACTOR,
                                  has_a_way_back=False, outcome=dont_care_outcome, label=None)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(resolution=[some_refusal]),
                           at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _gives_no_element_the_id(str(some_refusal.label))
        )


@pytest.mark.component
def test_the_postmortem_header_answers_its_five_questions_in_order() -> None:
    # What a reader asks before reading any of it: which incident, when, how
    # finished the document is, who wrote it, and who ended the incident.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("head", "incident", "date", "status", "written-by", "ended-by")
        )


@pytest.mark.component
def test_the_postmortem_header_says_when_argus_first_posted_before_who_ended_it() -> None:
    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(detection=Detection(
            alerted_at=DONT_CARE_MOMENT, rule=None, onset_at=None, gap=None,
            first_told=FirstTold(channel=ReportChannel.SLACK, at=DONT_CARE_MOMENT)
        )), at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_shows("head", "incident", "date", "status", "written-by", "first-told",
                           "ended-by"),
            _the_page_reads("First told Argus posted in Slack")
        ))


@pytest.mark.component
def test_the_postmortem_header_dates_the_incident_once_on_both_clocks() -> None:
    # The date said once and the window's ends as times of that day. Each end
    # is also carried whole, so the reader's own clock can say it in their zone.
    some_end = SOME_ONSET + timedelta(minutes=9)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(timeline=[
            TimelineEntry(at=SOME_ONSET, who=None, text=DONT_CARE_WORDS,
                          marker=TimelineMarker.IMPACT_BEGINS),
            TimelineEntry(at=some_end, who=None, text=DONT_CARE_WORDS,
                          marker=TimelineMarker.IMPACT_ENDS)
        ]),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(f"{SOME_ONSET:%b %d, %Y, %H:%M} to {some_end:%H:%M} UTC"),
            the_page_shows("local-from", f"{SOME_ONSET:%Y-%m-%dT%H:%M:%SZ}"),
            the_page_shows("local-to", f"{some_end:%Y-%m-%dT%H:%M:%SZ}")
        ))


@pytest.mark.component
def test_the_postmortem_header_counts_the_action_items_already_done() -> None:
    a_done_item_and_an_open_one = [
        ActionItem(number=SOME_ACTION_ITEM_NUMBER, text=DONT_CARE_WORDS,
                   type=ActionItemType.MITIGATE, owner=None, tracking=None,
                   status=ActionItemStatus.DONE),
        ActionItem(number=SOME_OTHER_ACTION_ITEM_NUMBER, text=DONT_CARE_WORDS,
                   type=ActionItemType.PREVENT, owner=None, tracking=None,
                   status=ActionItemStatus.OPEN)
    ]
    done = sum(item.status is ActionItemStatus.DONE for item in a_done_item_and_an_open_one)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id,
                           _a_document_with(action_items=a_done_item_and_an_open_one),
                           at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f"Draft. {done} of {len(a_done_item_and_an_open_one)} action items "
                          f"are done.")
        )


@pytest.mark.component
@pytest.mark.parametrize(("met", "said"), [(None, "Not reviewed yet."), (True, "Reviewed.")])
def test_the_postmortem_header_says_whether_a_person_has_reviewed_it(met: bool | None,
                                                                     said: str) -> None:
    # A box only a person can tick, left unticked, is a document nobody who
    # could disagree with it has read yet.
    dont_care_other_criterion = "dont care either"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(review=[
            ReviewCriterion(criterion=DONT_CARE_WORDS, met=True),
            ReviewCriterion(criterion=dont_care_other_criterion, met=met)
        ]),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says("Argus Postmortem agent"),
            the_page_says(said)
        ))


@pytest.mark.component
def test_a_check_left_for_a_person_says_what_they_would_do_on_the_page() -> None:
    # Said only in the tooltip of its cross, it is said to nobody: a reader
    # does not hover over a mark to learn what to do about it.
    some_because = "the cause rests on F1, a reading of the source nothing ran"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(review=[
            ReviewCriterion(criterion=DONT_CARE_CRITERION, met=None, because=some_because)
        ]),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_reads(some_because)
        )


@pytest.mark.component
def test_an_impact_card_shows_its_figure_its_label_and_its_note() -> None:
    # The figure is the comparison that makes it harm; what supports it is a
    # note of its own, rather than more figures in the label.
    dont_care_alert = Alert(service=SOME_SERVICE, alert_name=SOME_CONFIDENCE_ALERT_NAME)
    some_harm = RuleSeriesHarm(before=0.8994, while_broken=0.45943, at_its_worst=0.39071,
                               worse_when="below", line=0.8)
    dont_care_duration = timedelta(minutes=29)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(
            impact=Impact(duration=dont_care_duration, extent=ImpactExtent.MEASURED,
                          peak_error_rate=None, rule_series_harm=some_harm)),
                          at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_reads(f"{some_harm.before:.3f} to {some_harm.while_broken:.3f} what the "
                            f"alert watches, before onset and while broken on average worst "
                            f"minute {some_harm.at_its_worst:.3f}; the rule's line is "
                            f"{some_harm.line}")
        )


@pytest.mark.component
def test_the_postmortem_header_says_argus_ended_an_incident_nobody_reported_over() -> None:
    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(resolution=[
            ResolutionStep(at=DONT_CARE_MOMENT,
                           action=f"{DONT_CARE_ACTION} on {SOME_FLAG}",
                           by=SOME_ACTOR, has_a_way_back=True,
                           outcome=DONT_CARE_WORDS, label=SOME_STEP_LABEL)
        ]),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("ended-by", SOME_ACTOR)
        )


@pytest.mark.component
def test_the_postmortem_header_says_the_person_who_reported_the_incident_over_ended_it() -> None:
    # The person's word over the document's: a write-up composed before the
    # report is not rewritten, so who ended it is read off the account.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])
        events.record(conn, StatusChanged(
            incident_id=incident_id,
            to_status=IncidentStatus.RESOLVED,
            reported=Report(by=SOME_PERSON, channel=ReportChannel.ARGUS_UI, note=None)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("ended-by", SOME_PERSON)
        )


@pytest.mark.component
def test_the_postmortem_title_says_the_symptom_and_the_change_it_began_with() -> None:
    # The symptom in the model's words and the change in the record's: what a
    # reader looking for this incident again remembers it by.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(
            symptom=SOME_SYMPTOM,
            trigger=Trigger(subject=SOME_FLAG, from_state=SOME_FROM_STATE,
                            to_state=SOME_TO_STATE, changed_at=None)
        ),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("title", f"{SOME_SYMPTOM} while {SOME_FLAG} was {SOME_TO_STATE}")
        )


@pytest.mark.component
def test_a_postmortem_that_names_no_symptom_is_titled_by_its_alert() -> None:
    # A document written before the model was asked for one.
    some_alert = Alert(service=SOME_SERVICE, alert_name=SOME_ALERT_NAME)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("title", f"{some_alert.alert_name} on {some_alert.service}")
        )


@pytest.mark.component
def test_a_confirmed_cause_with_no_trigger_says_why_rather_than_none_established() -> None:
    # Beside a confirmed cause, "No trigger was established" reads as the
    # cause being in doubt.
    dont_care_alert = Alert(service=SOME_SERVICE, alert_name=SOME_LATENCY_ALERT_NAME)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(no_trigger=NoTrigger(
            why=WhyNoTrigger.ANOTHER_SERVICE_S_DEPLOYS_UNREAD, candidate=SOME_CANDIDATE_LABEL,
            service=SOME_OTHER_SERVICE
        )),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            _the_page_reads(f"{SOME_CANDIDATE_LABEL} was confirmed; it blames "
                            f"{SOME_OTHER_SERVICE}"),
            _the_page_reads("whose deploys Argus did not read."),
            _the_page_does_not_read("No trigger was established")
        ))


@pytest.mark.component
def test_the_trigger_says_what_kind_of_change_it_was_and_between_which_states() -> None:
    # A name alone reads as anything. Said as a flag, its two states are the
    # ones it moved between - the one it left, and the one it went to.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(trigger=Trigger(
            subject=SOME_FLAG, from_state=SOME_FROM_STATE, to_state=SOME_TO_STATE,
            changed_at=None, kind=ChangeKind.FLAG_TOGGLE
        )),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says("flag went from"),
            the_page_shows("from-state", SOME_FROM_STATE),
            the_page_shows("to-state", SOME_TO_STATE)
        ))


@pytest.mark.component
def test_a_deployment_trigger_says_which_service_went_between_which_revisions() -> None:
    # A deployment's subject is the service, and its two states are revisions.
    # Said the way a flag is said, the new revision stood where the service
    # goes, and both were shouted in capitals as though they were ON and OFF.
    some_alert = Alert(service=SOME_SERVICE, alert_name=SOME_RECONCILIATION_ALERT_NAME)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(trigger=Trigger(
            subject=SOME_LATER_REVISION, from_state=SOME_EARLIER_REVISION,
            to_state=SOME_LATER_REVISION, changed_at=None, kind=ChangeKind.DEPLOY
        )),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_reads(f"{some_alert.service} was deployed from "
                            f"{SOME_EARLIER_REVISION[:7]} to {SOME_LATER_REVISION[:7]}")
        )


@pytest.mark.component
def test_a_deployment_trigger_names_the_service_and_its_revision_in_the_title() -> None:
    # A flag's "while X was Y" said of a deployment is the revision twice over.
    some_alert = Alert(service=SOME_SERVICE, alert_name=SOME_RECONCILIATION_ALERT_NAME)
    some_symptom = "Stored spend totals were wrong"
    title = f"{some_symptom} while {some_alert.service} ran {SOME_LATER_REVISION[:7]}"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(
            symptom=some_symptom,
            trigger=Trigger(subject=SOME_LATER_REVISION,
                            from_state=SOME_EARLIER_REVISION,
                            to_state=SOME_LATER_REVISION, changed_at=None,
                            kind=ChangeKind.DEPLOY)
        ),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_shows("title", title),
            _the_page_reads(title)
        ))


@pytest.mark.component
def test_the_impact_says_how_many_requests_failed() -> None:
    some_requests_failed = 4210
    dont_care_duration = timedelta(minutes=9)
    dont_care_peak_error_rate = 0.338

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "impact": Impact(duration=dont_care_duration, extent=ImpactExtent.MEASURED,
                             peak_error_rate=dont_care_peak_error_rate,
                             requests_failed=some_requests_failed)
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f"{some_requests_failed:,}")
        )


@pytest.mark.component
def test_the_trigger_says_who_made_the_change() -> None:
    some_changer = "kuki"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(trigger=Trigger(
            subject=SOME_FLAG, from_state=SOME_FROM_STATE, to_state=SOME_TO_STATE,
            changed_at=None, kind=ChangeKind.FLAG_TOGGLE, actor=some_changer
        )),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f"by {some_changer}")
        )


@pytest.mark.component
def test_a_suspected_trigger_is_said_as_suspected() -> None:
    # Nothing tested it. Shown as the trigger plainly, it would read as the
    # cause established - which is the one thing the document cannot say.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(trigger=Trigger(
            subject=SOME_FLAG, from_state=SOME_FROM_STATE, to_state=SOME_TO_STATE,
            changed_at=None, suspected=True
        )),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("trigger", "suspected")
        )


@pytest.mark.component
def test_a_suspected_trigger_stays_out_of_the_title() -> None:
    # The title is the one line read by everybody who reads nothing else, and
    # "while the flag was on" there says the flag did it.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(
            symptom=SOME_SYMPTOM,
            trigger=Trigger(subject=SOME_FLAG, from_state=SOME_FROM_STATE,
                            to_state=SOME_TO_STATE, changed_at=None, suspected=True)
        ),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("title", SOME_SYMPTOM)
        )


@pytest.mark.component
@pytest.mark.parametrize(("extent", "said"), [
    (ImpactExtent.MEASURED, "measured"),
    (ImpactExtent.AT_LEAST, "a lower bound"),
    (ImpactExtent.METRICS_MISSING, "a lower bound")
])
def test_a_loss_over_an_incident_that_never_ended_is_said_to_be_at_least(
        extent: ImpactExtent, said: str) -> None:
    # Takings counted up to where the metrics stopped, of an incident still
    # going there: what it cost is that much or more, and a figure with no
    # "at least" reads as the whole of it.
    dont_care_loss = Decimal("500")
    dont_care_duration = timedelta(hours=2)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "customer_loss_estimate": dont_care_loss,
            "estimate_currency": DONT_CARE_CURRENCY,
            "impact": Impact(duration=dont_care_duration, extent=extent, peak_error_rate=None)
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("loss-is", said)
        )


@pytest.mark.component
@pytest.mark.parametrize(("extent", "read"), [
    (ImpactExtent.MEASURED, "none"),
    (ImpactExtent.AT_LEAST, "none so far"),
    (ImpactExtent.METRICS_MISSING, "none so far")
])
def test_no_loss_is_said_as_none_rather_than_as_an_amount(extent: ImpactExtent,
                                                          read: str) -> None:
    # "At least 0.00 USD" is true and reads as a figure somebody forgot to
    # fill in. Said as none, it is a finding - and "so far" keeps what the
    # "at least" was there to say, of an incident still going when the
    # takings were counted.
    no_loss = Decimal("0")
    dont_care_duration = timedelta(hours=2)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "customer_loss_estimate": no_loss,
            "estimate_currency": DONT_CARE_CURRENCY,
            "impact": Impact(duration=dont_care_duration, extent=extent, peak_error_rate=None)
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_reads(f"{read} customer loss (estimated)")
        )


@pytest.mark.component
def test_the_postmortem_page_shows_every_amount_to_the_cent() -> None:
    # Stored as computed, rounded only for show: twenty-six decimal places of
    # a loss estimate claim a precision nobody measured.
    some_loss = Decimal("1736.68485900091116011163646")
    some_currency = "usd"
    dont_care_minutes = 22
    dont_care_responders = 1
    dont_care_responder_cost = Decimal("412.5")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=None,
                executive_summary=None,
                customer_loss_estimate=some_loss,
                estimate_currency=some_currency,
                engineer_minutes=dont_care_minutes,
                responders=dont_care_responders,
                responder_cost_estimate=dont_care_responder_cost,
                responder_cost_currency=DONT_CARE_CURRENCY,
                tokens_spent=None,
                assumptions=[]
            ),
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f"{some_loss:,.2f} {some_currency.upper()}")
        )


@pytest.mark.component
def test_detection_names_the_alert_the_way_the_header_does() -> None:
    # One name for one alert across the page: the header says the alert, so
    # Detection does too, rather than the rule's own identifier beside it.
    some_alert = Alert(service=SOME_SERVICE, alert_name=SOME_ALERT_NAME)
    dont_care_gap = timedelta(minutes=2)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "detection": Detection(alerted_at=SOME_ONSET + dont_care_gap,
                                   rule=SOME_RULE_ID,
                                   onset_at=SOME_ONSET,
                                   gap=dont_care_gap)
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f"{some_alert.alert_name} fired at")
        )


@pytest.mark.component
def test_the_postmortem_page_says_how_long_the_alert_took_in_minutes_and_seconds() -> None:
    some_minutes, some_seconds = 2, 40
    some_gap = timedelta(minutes=some_minutes, seconds=some_seconds)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=None,
                executive_summary=None,
                customer_loss_estimate=None,
                estimate_currency=None,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[],
                detection=Detection(alerted_at=SOME_ONSET + some_gap,
                                    rule=SOME_ALERT_NAME,
                                    onset_at=SOME_ONSET,
                                    gap=some_gap)
            ),
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f"{some_minutes} minutes {some_seconds} seconds later")
        )


@pytest.mark.component
def test_the_resolution_names_the_fix_proposed_as_well_as_the_action_taken() -> None:
    # The mitigation ended the symptom; the fix is what ends the cause. Left
    # out of the resolution, the document reads as finished while the one
    # thing still owed sits in a list further down.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "pull_request": A_FIX
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("resolution-fix", A_FIX.url)
        )


@pytest.mark.component
def test_the_postmortem_page_links_its_walk_and_the_fix_in_full_and_not_itself() -> None:
    # In full, because the document is read away from the screen it came from -
    # sent onwards, printed - where an address relative to nothing leads
    # nowhere. Not itself: a page linking to the page it is is a link nobody
    # follows. The test client serves the app at its own default host.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=None,
                executive_summary=None,
                customer_loss_estimate=None,
                estimate_currency=None,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[],
                pull_request=A_FIX
            ),
            at=utc_now()
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("link",
                           f"http://testserver/incidents/{incident_id}",
                           A_FIX.url)
        )


@pytest.mark.component
def test_every_row_the_prose_can_cite_answers_to_its_label() -> None:
    # The prose cites hypotheses, actions, action items, lines of the
    # narration, changes and log messages read, and leads by label, and a link
    # to one has to land on its row. A marker was never shown to the model, so
    # nothing cites it.
    some_log_label = "G3fa2"
    dont_care_who = "Investigator"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(
            timeline=[
                TimelineEntry(at=DONT_CARE_MOMENT, who=None, text=DONT_CARE_WORDS,
                              marker=TimelineMarker.DETECTED),
                TimelineEntry(at=DONT_CARE_MOMENT, who=dont_care_who, text=DONT_CARE_WORDS,
                              label=SOME_LINE_LABEL)
            ],
            action_items=[
                ActionItem(number=SOME_ACTION_ITEM_NUMBER, text=DONT_CARE_WORDS,
                           type=ActionItemType.MITIGATE, owner=None, tracking=None,
                           status=ActionItemStatus.DONE)
            ],
            resolution=[
                ResolutionStep(at=DONT_CARE_MOMENT, action=DONT_CARE_WORDS, by=SOME_ACTOR,
                               has_a_way_back=True, outcome=DONT_CARE_WORDS,
                               label=SOME_STEP_LABEL)
            ]
        ).model_copy(update={
            "hypotheses": [HypothesisConsidered(summary=DONT_CARE_WORDS, confidence=None,
                                                result=DONT_CARE_WORDS,
                                                label=SOME_CANDIDATE_LABEL)],
            "changes_read": [_a_change_read(SOME_CHANGE_LABEL)],
            "log_messages_read": [CitedEvidence(label=some_log_label, text=DONT_CARE_WORDS)],
            "leads": [PostmortemLead(label=SOME_LEAD_LABEL, person_id=DONT_CARE_PERSON_ID,
                                     person_name=None, text=DONT_CARE_WORDS,
                                     written_at=DONT_CARE_MOMENT, weighing=None, effect=None)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(f'id="{SOME_CANDIDATE_LABEL}"'),
            the_page_says(f'id="{SOME_STEP_LABEL}"'),
            the_page_says(f'id="{SOME_ACTION_ITEM_NUMBER}"'),
            the_page_says(f'id="{SOME_LINE_LABEL}"'),
            the_page_says(f'id="{SOME_CHANGE_LABEL}"'),
            the_page_says(f'id="{some_log_label}"'),
            the_page_says(f'id="{SOME_LEAD_LABEL}"')
        ))


@pytest.mark.component
def test_the_impact_names_the_log_rows_that_reach_into_the_stretch_the_metrics_missed() -> None:
    # Named and leading to them: the rows are where a reader checks what the
    # service's own logs said of the stretch nothing else measured.
    some_log_label = "G46bc"
    dont_care_duration = timedelta(minutes=40)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(impact=Impact(
            duration=dont_care_duration, extent=ImpactExtent.METRICS_MISSING,
            peak_error_rate=None,
            logs_in_the_gap=LogsInTheGap(read=True, labels=[some_log_label],
                                         reach_until=DONT_CARE_MOMENT,
                                         read_until=None, read_until_the_alert=False)
        )).model_copy(update={
            "log_messages_read": [CitedEvidence(label=some_log_label, text=DONT_CARE_WORDS)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            _the_page_reads("The service's own logs reach into the stretch the metrics missed"),
            the_page_links_to(f"#{some_log_label}")
        ))


@pytest.mark.component
def test_what_the_alert_said_answers_to_its_label() -> None:
    # The chain's symptom rests on it, and a citation of it has to land.
    some_label = "AL1"
    some_finding = "240 totals are off"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "detection": Detection(alerted_at=DONT_CARE_MOMENT,
                                   rule=DONT_CARE_WORDS, onset_at=None, gap=None,
                                   said=CitedEvidence(label=some_label, text=some_finding))
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(f'id="{some_label}"'),
            the_page_says(some_finding)
        ))


@pytest.mark.component
@pytest.mark.parametrize("prose", [
    pytest.param({"executive_summary": f"{SOME_CANDIDATE_LABEL} was right."}, id="summary"),
    pytest.param({"root_cause": f"{SOME_CANDIDATE_LABEL} was right."}, id="root_cause"),
    pytest.param({"causal_chain": [ChainStep(text=f"{SOME_CANDIDATE_LABEL} was right.",
                                             cites=[])]},
                 id="causal_chain"),
    pytest.param({"causal_chain": [ChainStep(text=DONT_CARE_WORDS,
                                             cites=[CitedEvidence(label=SOME_CANDIDATE_LABEL,
                                                                  text=DONT_CARE_WORDS)])]},
                 id="causal_chain_evidence"),
    pytest.param({"causal_chain": [ChainStep(
                     text=DONT_CARE_WORDS, cites=[],
                     ruled_out=[RuledOut(text=f"{SOME_CANDIDATE_LABEL} was refuted.",
                                         cites=[])])]},
                 id="ruled_out"),
    pytest.param({"causal_chain": [ChainStep(text=DONT_CARE_WORDS, cites=[],
                                             ruled_out=[RuledOut(
                                                 text=DONT_CARE_WORDS,
                                                 cites=[CitedEvidence(label=SOME_CANDIDATE_LABEL,
                                                                      text=DONT_CARE_WORDS)])])]},
                 id="ruled_out_evidence"),
    pytest.param({"contributing_factors": [ContributingFactor(
                     text=f"{SOME_CANDIDATE_LABEL} was right.", addressed_by=[])]},
                 id="contributing_factor"),
    pytest.param({"action_items": [ActionItem(number=SOME_ACTION_ITEM_NUMBER,
                                              text=f"Keep {SOME_CANDIDATE_LABEL} from coming "
                                                   f"back.",
                                              type=ActionItemType.PREVENT, owner=None,
                                              tracking=None, status=ActionItemStatus.OPEN)]},
                 id="action_item"),
    pytest.param({"recommended_action": f"Undo what {SOME_CANDIDATE_LABEL} named."},
                 id="recommended_action"),
    pytest.param({"lessons": Lessons(went_well=[f"{SOME_CANDIDATE_LABEL} was right."])},
                 id="lessons"),
    pytest.param({"leads": [PostmortemLead(label=SOME_LEAD_LABEL, person_id=DONT_CARE_PERSON_ID,
                                           person_name=None, text=DONT_CARE_WORDS,
                                           written_at=DONT_CARE_MOMENT, weighing=None,
                                           effect=f"It named what {SOME_CANDIDATE_LABEL} "
                                                  f"blamed.")]},
                 id="lead_effect"),
    pytest.param({"assumptions": [f"{SOME_CANDIDATE_LABEL} was taken at its word."]},
                 id="assumptions")
])
def test_a_label_cited_in_any_prose_links_to_its_row(prose: dict[str, object]) -> None:
    # Wherever the model writes, it may cite a row by its label, and a reader
    # following the citation is taken to the row rather than left to find it.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "hypotheses": [HypothesisConsidered(summary=DONT_CARE_WORDS, confidence=None,
                                                result=DONT_CARE_WORDS,
                                                label=SOME_CANDIDATE_LABEL)],
            **prose
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_links_to(f"#{SOME_CANDIDATE_LABEL}")
        )


@pytest.mark.component
def test_what_a_step_ruled_out_is_said_under_it() -> None:
    # On the step it was ruled out at, rather than as a step the page would
    # number among the whys.
    some_ruled_out = "The earlier deploy was healthy."

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "causal_chain": [ChainStep(text=DONT_CARE_WORDS, cites=[],
                                       ruled_out=[RuledOut(text=some_ruled_out, cites=[])])]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says("Ruled out:"),
            # A line of its own in the claim's ink, apart from the quieter rows
            # that ruled it out - set among them, it read as one more of them.
            the_page_says(f'<p class="ruled">{some_ruled_out}</p>')
        ))


@pytest.mark.component
def test_a_row_standing_for_several_candidates_answers_to_each_label() -> None:
    # A link to either candidate lands on the one row, which is labelled with
    # both.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "hypotheses": [HypothesisConsidered(summary=DONT_CARE_WORDS, confidence=None,
                                                result=DONT_CARE_WORDS,
                                                label=SOME_CANDIDATE_LABEL,
                                                also=[SOME_OTHER_CANDIDATE_LABEL])]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(f'id="{SOME_CANDIDATE_LABEL}"'),
            the_page_says(f'id="{SOME_OTHER_CANDIDATE_LABEL}"'),
            the_page_says(f'<td class="label">{SOME_CANDIDATE_LABEL}, '
                          f'{SOME_OTHER_CANDIDATE_LABEL}</td>')
        ))


@pytest.mark.component
def test_a_time_said_again_on_the_reader_s_clock_leaves_no_space_where_it_is_not() -> None:
    # A reader whose clock is UTC is shown no local time, and a space left
    # before the empty box sat alone before whatever followed the time:
    # "13:13 UTC , in the deploy".

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(), at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _no_space_before_a_local_time()
        )


@pytest.mark.component
def test_a_candidate_a_line_of_the_timeline_names_links_to_its_row() -> None:
    # The line that formed the candidates names them by label, and a reader
    # follows each to what it was.
    dont_care_who = "Investigator Agent"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "hypotheses": [HypothesisConsidered(summary=DONT_CARE_WORDS, confidence=None,
                                                result=DONT_CARE_WORDS,
                                                label=SOME_CANDIDATE_LABEL)],
            "timeline": [TimelineEntry(at=DONT_CARE_MOMENT,
                                       who=dont_care_who,
                                       text=f"Formed 1 candidate cause, best first: "
                                            f"{SOME_CANDIDATE_LABEL}",
                                       label=SOME_LINE_LABEL)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'best first: <a href="#{SOME_CANDIDATE_LABEL}">'
                          f'{SOME_CANDIDATE_LABEL}</a>')
        )


@pytest.mark.component
def test_a_postmortem_line_about_an_earlier_incident_leads_to_its_page() -> None:
    # As the walk page's line does: the id is no name to look up by hand, and
    # the document is read away from the screen, so the address is whole.
    the_earlier_incident = "3f2b1a09-0000-4000-8000-00000000000a"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "timeline": [TimelineEntry(at=DONT_CARE_MOMENT,
                                       who=SOME_ACTOR,
                                       text=f"the closest match being incident "
                                            f"{the_earlier_incident}",
                                       names_incident=the_earlier_incident,
                                       label=SOME_LINE_LABEL)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'<a href="http://testserver/incidents/{the_earlier_incident}" '
                          f'target="_blank" rel="noopener noreferrer">{the_earlier_incident}</a>')
        )


@pytest.mark.component
def test_a_step_and_a_line_of_the_timeline_show_the_label_they_are_cited_by() -> None:
    # Every other row a citation lands on says its label, and a reader running
    # an eye down the timeline for T1 finds it there too.
    dont_care_action = "Turned the flag off"
    dont_care_line = "The flag went on."

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(
            resolution=[ResolutionStep(at=DONT_CARE_MOMENT,
                                       action=dont_care_action, by=SOME_ACTOR,
                                       has_a_way_back=True, outcome=DONT_CARE_WORDS,
                                       label=SOME_STEP_LABEL)],
            timeline=[TimelineEntry(at=DONT_CARE_MOMENT,
                                    who=SOME_ACTOR, text=dont_care_line,
                                    label=SOME_LINE_LABEL)]),
                                    at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(f'<td class="label">{SOME_STEP_LABEL}</td>'),
            the_page_says(f'<td class="label">{SOME_LINE_LABEL}</td>')
        ))


@pytest.mark.component
def test_a_label_a_check_left_for_a_person_cites_links_to_its_row() -> None:
    some_item = SOME_OTHER_ACTION_ITEM_NUMBER

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(
            action_items=[ActionItem(number=some_item, text=DONT_CARE_WORDS,
                                     type=ActionItemType.PREVENT, owner=None, tracking=None,
                                     status=ActionItemStatus.OPEN)],
            review=[ReviewCriterion(criterion=DONT_CARE_CRITERION, met=None,
                                    because=f"running the proposed fix's tests would "
                                            f"confirm it ({some_item})")]),
                                            at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'confirm it (<a href="#{some_item}">{some_item}</a>)')
        )


@pytest.mark.component
def test_a_change_the_root_cause_names_links_to_its_row() -> None:
    # "The deploy P2" means nothing to a reader until it leads somewhere: to
    # the change, said as the model was shown it.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": f"The deploy {SOME_OTHER_CHANGE_LABEL} switched the model.",
            "changes_read": [_a_change_read(SOME_OTHER_CHANGE_LABEL)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to(f"#{SOME_OTHER_CHANGE_LABEL}"),
            the_page_says(f'id="{SOME_OTHER_CHANGE_LABEL}"')
        ))


@pytest.mark.component
def test_a_kind_of_change_with_no_row_is_said_beneath_the_rows_there_are() -> None:
    # A flag row alone says nothing of the deploys, and a reader takes them as
    # read and ruled out. What came of reading them is said beneath the rows.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "changes_read": [_a_change_read(SOME_OTHER_CHANGE_LABEL)],
            "deploys_reading": ChannelReading.NOT_ASKED,
            "flags_reading": ChannelReading.READ
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(f'id="{SOME_OTHER_CHANGE_LABEL}"'),
            the_page_says('<p class="empty">Deploys not read.</p>')
        ))


@pytest.mark.component
def test_what_a_deployment_changed_the_root_cause_names_links_to_its_row() -> None:
    # "As D1 shows" leads to the diff, every line of it as the model read it.
    some_label = "D1"
    some_removed_line = "  -  model: v1"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": f"As {some_label} shows, the categoriser's model went from v1 to v2.",
            "deployment_changes_read": [CitedEvidence(
                label=some_label,
                text=f"modified deploy/values-production.yaml\n{some_removed_line}\n"
                     f"  +  model: v2")]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to(f"#{some_label}"),
            the_page_says(f'id="{some_label}"'),
            the_page_says(some_removed_line)
        ))


@pytest.mark.component
def test_what_code_fix_read_the_root_cause_names_links_to_its_row() -> None:
    # "As F1 reads the code" leads to the reading, said as one nothing ran.
    some_label = "F1"
    dont_care_reading = "the categoriser does not lowercase"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": f"As {some_label} reads the code, v2 meets input it was not built "
                          f"for.",
            "code_read": [CitedEvidence(label=some_label, text=dont_care_reading)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to(f"#{some_label}"),
            the_page_says(f'id="{some_label}"'),
            the_page_says("nothing ran to check it")
        ))


@pytest.mark.component
def test_a_file_as_it_ran_the_root_cause_names_links_to_its_row() -> None:
    # "As S1 shows" leads to the file's row, and the row to the file as it ran.
    some_label = "S1"
    some_revision = "53f02e9f"
    # The demo app's own scrape file, taken from Argus-Demo-Target-App; it must
    # not change unless the demo app does.
    some_path = "deploy/scrape.yaml"
    where_it_opens = (f"https://github.invalid/{SOME_REPOSITORY_NAME}/blob/{some_revision}/"
                      f"{some_path}")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": f"As {some_label} shows, the scrape still selects the port named "
                          f"metrics.",
            "as_it_ran_read": [CitedEvidence(
                label=some_label,
                text=f"{some_path} at {some_revision[:7]}\nselector:\n  port: metrics",
                address=where_it_opens)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to(f"#{some_label}"),
            the_page_says(f'id="{some_label}"'),
            the_page_links_to(where_it_opens)
        ))


@pytest.mark.component
def test_a_use_outside_the_patch_the_root_cause_cites_links_to_its_row() -> None:
    # "As U1 shows" leads to the line outside the patch and what it does,
    # under a heading saying the code said it.
    some_label = "U1"
    # The demo app's own names, taken from Argus-Demo-Target-App
    # (`io_shop/spend_reconciliation.py`); they must not change unless the demo
    # app does.
    some_use = "compares it with _bought_this_month(account)"
    dont_care_where = ("total_this_month_cents at src/io_shop/spend_reconciliation.py:109, in "
                       "reconcile_monthly_totals")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": f"As {some_label} shows, the reconciliation checks the stored figure.",
            "uses_outside_read": [CitedEvidence(label=some_label,
                                                text=f"{dont_care_where}: {some_use}")]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to(f"#{some_label}"),
            the_page_says(f'id="{some_label}"'),
            the_page_says("How the code outside Code-Fix&#39;s patch uses what it changes, "
                          "read off the code"),
            the_page_says(some_use)
        ))


@pytest.mark.component
def test_a_measurement_of_the_confirmed_cause_the_root_cause_cites_links_to_its_row() -> None:
    # "As R1 shows" leads to the load Argus measured, under a heading saying
    # Argus measured it.
    dont_care_alert = Alert(service=SOME_SERVICE, alert_name=SOME_LATENCY_ALERT_NAME)
    some_label = "R1"
    some_highest = 5400

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": f"As {some_label} shows, the load outgrew the CPU the service had.",
            "cause_measured": [CitedEvidence(
                label=some_label,
                text=f"Requests a minute: 1200 before it began, 4200 on average while it was "
                     f"broken, {some_highest} at its highest.")]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to(f"#{some_label}"),
            the_page_says(f'id="{some_label}"'),
            the_page_says("What the metrics show of the confirmed cause, measured by Argus"),
            the_page_says(f"{some_highest} at its highest")
        ))


@pytest.mark.component
def test_a_postmortem_that_measured_no_cause_has_no_heading_for_one() -> None:
    # Every incident whose confirmed cause is not the load: a heading over
    # nothing would say a measurement was missed.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "cause_measured": []
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_does_not_say("What the metrics show of the confirmed cause")
        )


@pytest.mark.component
def test_what_code_fix_read_is_shown_in_bold_and_on_its_lines_without_its_marks() -> None:
    # Code-Fix writes in Markdown, in paragraphs and lists. Its asterisks were
    # printed, and its lines run together into one block.
    dont_care_label = "F1"
    some_bold, some_rest, some_bold_item = "The fix.", "It hands off.", "Input:"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "code_read": [CitedEvidence(
                label=dont_care_label,
                text=f"**{some_bold}** {some_rest}\n- **{some_bold_item}** an export")]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(f"<strong>{some_bold}</strong> {some_rest}\n"
                          f"• <strong>{some_bold_item}</strong>"),
            the_page_says('<td class="keeps-lines">'),
            _the_page_does_not_say("**")
        ))


@pytest.mark.component
def test_a_change_read_links_out_to_its_commit_its_repository_and_its_directory() -> None:
    # The row says where the change came from, and a reader opens it there.
    some_directory = "deploy"
    commit = f"{SOME_REPOSITORY}/commit/{SOME_REVISION}"
    directory = f"{SOME_REPOSITORY}/tree/{SOME_REVISION}/{some_directory}"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "changes_read": [CitedChange(
                label=SOME_CHANGE_LABEL,
                change=ChangeEvent(
                    kind=ChangeKind.DEPLOY,
                    occurred_at=DONT_CARE_CHANGED_AT,
                    reference=SOME_REVISION,
                    summary=(f"deployed revision {SOME_REVISION} from the "
                             f"{SOME_REPOSITORY_NAME} repository's {some_directory}/ directory"),
                    revision_source=RevisionSource(
                        repository=SOME_REPOSITORY_NAME,
                        repository_address=SOME_REPOSITORY,
                        revision_address=commit,
                        directory=some_directory,
                        directory_address=directory)),
                short_reference=SOME_REVISION[:7])]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to(commit),
            the_page_links_to(SOME_REPOSITORY),
            the_page_links_to(directory)
        ))


@pytest.mark.component
def test_a_deployment_trigger_s_revision_opens_its_commit() -> None:
    # The trigger names the revision deployed as its row does, and a reader
    # opens it from the sentence that says what set the incident off.
    commit = f"{SOME_REPOSITORY}/commit/{SOME_REVISION}"
    dont_care_earlier_revision = "4c810f2aa1e9a6f3b7c9d0e1f2a3b4c5d6e7f809"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "trigger": Trigger(subject=DONT_CARE_WORDS,
                               from_state=dont_care_earlier_revision,
                               to_state=SOME_REVISION,
                               changed_at=None,
                               kind=ChangeKind.DEPLOY),
            "changes_read": [_a_deploy_cited(SOME_REVISION, SOME_REPOSITORY)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'data-to-state="{SOME_REVISION[:7]}"><a href="{commit}"')
        )


@pytest.mark.component
def test_a_revision_the_root_cause_names_opens_its_commit() -> None:
    # The prose names the deploy by its revision, and a reader opens it from
    # there - not only from the row listing the change, which links it too.
    commit = f"{SOME_REPOSITORY}/commit/{SOME_REVISION}"
    some_rest_of_it = "broke it."

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": f"The deploy of revision {SOME_REVISION[:7]} {some_rest_of_it}",
            "changes_read": [_a_deploy_cited(SOME_REVISION, SOME_REPOSITORY)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'<a href="{commit}" target="_blank" rel="noopener noreferrer">'
                          f'{SOME_REVISION[:7]}</a> {some_rest_of_it}')
        )


@pytest.mark.component
def test_a_revision_a_hypothesis_names_opens_its_commit() -> None:
    # The candidate wrote it whole; the row says it short, as the trigger and
    # the timeline beside it do, and a reader opens it from there.
    commit = f"{SOME_REPOSITORY}/commit/{SOME_REVISION}"
    some_rest_of_it = "made every page slow"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "hypotheses": [HypothesisConsidered(
                summary=f"{SOME_REVISION} {some_rest_of_it}", confidence=DONT_CARE_CONFIDENCE,
                result=DONT_CARE_WORDS, label=SOME_CANDIDATE_LABEL)],
            "changes_read": [_a_deploy_cited(SOME_REVISION, SOME_REPOSITORY)]
        }),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'<a href="{commit}" target="_blank" rel="noopener noreferrer">'
                          f'{SOME_REVISION[:7]}</a> {some_rest_of_it}')
        )


@pytest.mark.component
def test_a_revision_the_walk_names_opens_its_commit_from_the_incident_page() -> None:
    # Said short as the postmortem says it, and so a name a reader cannot look
    # up by hand.
    commit = f"{SOME_REPOSITORY}/commit/{SOME_REVISION}"
    some_rest_of_it = "made every page slow"
    some_cause = f"[{SOME_REVISION}] {some_rest_of_it}"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _a_deploy_read_on(incident_id, SOME_REVISION, SOME_REPOSITORY))
        events.record(conn, PostmortemWritten(
            incident_id=incident_id,
            executive_summary=some_cause,
            cause_in_plain_words=some_cause))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_says(f'<a href="{commit}" target="_blank" rel="noopener noreferrer">'
                          f'{SOME_REVISION[:7]}</a> {some_rest_of_it}')
        )


@pytest.mark.component
def test_a_revision_a_candidate_names_opens_its_commit_in_the_timeline_and_the_walk() -> None:
    # Named whole and leading nowhere in a candidate's subject and findings,
    # beside the changes table naming it short and opening it, one page named
    # one revision two ways.
    linked = (f'<a href="{SOME_REPOSITORY}/commit/{SOME_LATER_REVISION}" target="_blank" '
              f'rel="noopener noreferrer">{SOME_LATER_REVISION[:7]}</a>')
    some_finding, some_other_finding = "rewrote the totals", "rewrote the history"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _a_deploy_read_on(incident_id, SOME_LATER_REVISION, SOME_REPOSITORY))
        events.record(conn, HypothesisFormed(
            incident_id=incident_id, hypothesis_id=new_id(), summary=DONT_CARE_WORDS,
            failure_mode=None, confidence=None, subject=SOME_LATER_REVISION, rank=1, number=1,
            evidence=[Evidence(claim=f"{SOME_LATER_REVISION} {some_finding}", at=None)]))
        _a_candidate_recorded_for(conn, incident_id, subject=SOME_LATER_REVISION, rank=1,
                                  evidence=[f"{SOME_LATER_REVISION} {some_other_finding}"])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"{linked} {some_finding}"),
            the_page_says(f"{linked} {some_other_finding}"),
            the_page_says(f"<code>{linked}</code>")
        ))


@pytest.mark.component
@pytest.mark.parametrize(("attempted", "lead_in"), [
    (False, "test held back"),
    (True, "action not taken")
], ids=["held-back", "not-taken"])
def test_a_revision_the_reason_a_candidate_went_untested_names_opens_its_commit_in_the_walk(
        attempted: bool, lead_in: str
) -> None:
    # Named whole and leading nowhere in why the candidate went untested,
    # beside its subject and findings naming the same revision short and
    # opening it. With an attempt the reason is the tier's, without one the
    # gate's, and each is said on a line of its own.
    linked = (f'<a href="{SOME_REPOSITORY}/commit/{SOME_LATER_REVISION}" target="_blank" '
              f'rel="noopener noreferrer">{SOME_LATER_REVISION[:7]}</a>')
    some_reason = "nothing runs before"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _a_deploy_read_on(incident_id, SOME_LATER_REVISION, SOME_REPOSITORY))
        untested = _a_candidate_recorded_for(conn, incident_id, subject=DONT_CARE_SUBJECT,
                                             rank=1)
        if attempted:
            _an_attempt_taken_for(conn, incident_id, untested, outcome=Verdict.NOT_ATTEMPTED,
                                  performed=False)
        hypotheses.record_outcome(conn, untested, tested=False,
                                  result=f"{some_reason} {SOME_LATER_REVISION}")

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_says(f"{lead_in}: {some_reason} {linked}")
        )


@pytest.mark.component
def test_a_revision_a_candidate_moved_from_or_to_opens_its_commit_in_the_timeline_and_the_walk(
) -> None:
    # Whole and leading nowhere beside the same candidate's subject named short.
    # The timeline's candidate and the walk's row blame the move each way round,
    # so each template is seen on its own.
    linked = (f'<a href="{SOME_REPOSITORY}/commit/{SOME_LATER_REVISION}" target="_blank" '
              f'rel="noopener noreferrer">{SOME_LATER_REVISION[:7]}</a>')
    linked_earlier = (f'<a href="{SOME_REPOSITORY}/commit/{SOME_EARLIER_REVISION}" '
                      f'target="_blank" rel="noopener noreferrer">{SOME_EARLIER_REVISION[:7]}</a>')

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _a_deploy_read_on(incident_id, SOME_LATER_REVISION, SOME_REPOSITORY))
        events.record(conn, _a_deploy_read_on(incident_id, SOME_EARLIER_REVISION,
                                              SOME_REPOSITORY))
        events.record(conn, HypothesisFormed(
            incident_id=incident_id, hypothesis_id=new_id(), summary=DONT_CARE_WORDS,
            failure_mode=None, confidence=None, subject=None, rank=1, number=1,
            from_state=SOME_EARLIER_REVISION, to_state=SOME_LATER_REVISION))
        hypotheses.record(conn, Hypothesis(
            incident_id=incident_id, summary=DONT_CARE_WORDS,
            failure_mode=FailureMode.FEATURE_FLAG_TOGGLE, confidence=DONT_CARE_CONFIDENCE,
            supporting_evidence=[], subject=SOME_SERVICE, rank=1,
            from_state=SOME_LATER_REVISION, to_state=SOME_EARLIER_REVISION))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"<s>{linked_earlier}</s>"),
            the_page_says(f"<s>{linked}</s>")
        ))


@pytest.mark.component
def test_an_answer_in_markdown_is_shown_formatted_on_the_incident_page() -> None:
    # Shown as the model wrote it, `**` and all, an answer reads as markup
    # nobody rendered.
    dont_care_message = Reference(source="some-chat", kind="some-kind", value="some-message")
    some_heading_word = "Investigation"
    some_heading = f"{some_heading_word} (14:15)"
    some_item = "Reverted the flag"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, QuestionAnswered(
            incident_id=incident_id,
            message=dont_care_message,
            answer=f"**{some_heading}**\n- {some_item}"
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"<p><strong>{some_heading}</strong></p>"
                          f"<ul><li>{some_item}</li></ul>"),
            _the_page_does_not_read(f"**{some_heading_word}")
        ))


@pytest.mark.component
def test_a_change_read_is_named_on_the_incident_page_as_its_postmortem_row_names_it() -> None:
    # Short, and opening where it was committed; what it did in the same words,
    # the repository opening where it is - and its revision not named again,
    # since the row's reference already names it.
    commit = f"{SOME_REPOSITORY}/commit/{SOME_REVISION}"
    some_lead_in = "deployed revision"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _a_deploy_read_on(
            incident_id, SOME_REVISION, SOME_REPOSITORY,
            summary=f"{some_lead_in} {SOME_REVISION} from the {SOME_REPOSITORY_NAME} "
                    f"repository"))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            _the_page_does_not_read(f"<code>{SOME_REVISION}</code>"),
            _the_page_does_not_read(some_lead_in),
            the_page_links_to(commit),
            the_page_links_to(SOME_REPOSITORY)
        ))


@pytest.mark.component
def test_the_changes_read_say_their_times_are_utc_as_every_other_time_column_does() -> None:
    # Its times said as a clock says them, "15:39", under a heading of "when",
    # it was the one time column on the page that named no zone.
    dont_care_revision = "dont-care-revision"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        events.record(conn, _a_deploy_read_on(incident_id, dont_care_revision, SOME_REPOSITORY))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_says("<tr><th>when (UTC)</th><th>kind</th>")
        )


@pytest.mark.component
def test_a_contributing_factor_links_to_the_action_items_that_answer_it() -> None:
    # The items are named, not written out, so the name is the only way from
    # the condition to what is being done about it.

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(action_items=[
            ActionItem(number=SOME_ACTION_ITEM_NUMBER, text=DONT_CARE_WORDS,
                       type=ActionItemType.PREVENT, owner=None, tracking=None,
                       status=ActionItemStatus.OPEN)
        ]).model_copy(update={"contributing_factors": [
            ContributingFactor(text=DONT_CARE_WORDS, addressed_by=[SOME_ACTION_ITEM_NUMBER])
        ]}),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_links_to(f"#{SOME_ACTION_ITEM_NUMBER}")
        )


@pytest.mark.component
def test_a_timeline_row_on_a_new_day_says_its_date() -> None:
    # A time of day alone reads in order only within one day: an onset a week
    # before the alert, said as 16:10 above 16:08, reads as time running
    # backwards. The date is said where the day changes, and only there.
    dont_care_alert = Alert(service=SOME_SERVICE, alert_name=SOME_RECONCILIATION_ALERT_NAME)
    onset = datetime(2026, 9, 28, 16, 10, tzinfo=UTC)
    later_that_day = onset + timedelta(hours=1)
    # A week on, and a little before the onset's own time of day.
    found = onset + timedelta(weeks=1) - timedelta(minutes=1, seconds=22)
    some_began, some_went_on, some_was_found = ("the incident began", "it went on",
                                                "it was found")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(timeline=[
            TimelineEntry(at=onset, who=None, text=some_began),
            TimelineEntry(at=later_that_day, who=None, text=some_went_on),
            TimelineEntry(at=found, who=None, text=some_was_found)
        ]),
        at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            _the_page_reads(f"{onset:%b %d %H:%M} {some_began}"),
            _the_page_reads(f"{later_that_day:%H:%M} {some_went_on}"),
            _the_page_does_not_read(f"{later_that_day:%b %d %H:%M}"),
            _the_page_reads(f"{found:%b %d %H:%M:%S} {some_was_found}")
        ))


@pytest.mark.component
def test_the_impact_says_what_the_alert_found() -> None:
    # Where the damage is not a rate - totals written wrong rather than requests
    # failed - the cards read "not measured" and "not counted", and the one
    # measurement there is sits in the alert. Left there, the impact section
    # reads as an incident that did nothing.
    some_finding = "240 of 240 stored totals are wrong; the widest is 1,297.31 short"
    an_alert_with_a_finding = Alert(service=SOME_SERVICE,
                                    alert_name=SOME_RECONCILIATION_ALERT_NAME,
                                    summary=some_finding, claim=AlarmClaim.ITS_OWN_FINDING)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, an_alert_with_a_finding, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(), at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_reads(f"customer loss (estimated) What the alert found: {some_finding}")
        )


@pytest.mark.component
def test_an_alert_that_found_nothing_in_words_adds_nothing_to_the_impact() -> None:
    an_alert_with_no_finding = Alert(service=SOME_SERVICE, alert_name=SOME_ALERT_NAME)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, an_alert_with_no_finding, at=utc_now())
        postmortems.record(conn, incident_id, _a_document_with(), at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_does_not_read("What the alert found")
        )


def _a_postmortem_recorded_for(conn: psycopg.Connection,
                               incident_id: str,
                               leads: list[PostmortemLead]) -> None:
    """A document with nothing in any section but the leads it is given."""
    postmortems.record(
        conn,
        incident_id,
        PostmortemDocument(
            root_cause=None,
            executive_summary=None,
            customer_loss_estimate=None,
            estimate_currency=None,
            engineer_minutes=None,
            responders=None,
            tokens_spent=None,
            assumptions=[],
            leads=leads
        ),
        at=utc_now()
    )


def _a_synopsis_recorded_for(conn: psycopg.Connection,
                             incident_id: str,
                             overview: str | None) -> None:
    """A synopsis with nothing in it but its overview - or none, given up."""
    synopses.record(
        conn,
        incident_id,
        ExecutiveSynopsisDocument(overview=overview,
                                  withheld_because=None if overview else DONT_CARE_WORDS,
                                  cost_by_title=[],
                                  breakdown_unmatched=False),
        at=utc_now()
    )


def _the_page_reads(text: str) -> Assertion[str]:
    """What a reader sees, markup and line breaks aside.

    Read off the text rather than the markup, because a value can sit in an
    attribute in one spelling and on the page in another - and the reader only
    ever sees the second.
    """
    def assertion(page: str) -> bool:
        if text not in _what_a_reader_sees(page):
            raise AssertionError(f"Expected the page to read [{text}], it did not.")

        return True

    return assertion


def _the_page_does_not_read(text: str) -> Assertion[str]:
    """What a reader must not see, markup and line breaks aside."""
    def assertion(page: str) -> bool:
        if text in _what_a_reader_sees(page):
            raise AssertionError(f"Expected the page not to read [{text}], it did.")

        return True

    return assertion


def _no_space_before_a_local_time() -> Assertion[str]:
    """Each box for a time on the reader's own clock follows its time with
    nothing between - the space before it is the script's to add, with the
    time it fills the box with."""
    def assertion(page: str) -> bool:
        boxes = page.count('<span class="local"')
        spaced = re.findall(r'\S{0,12}\s+<span class="local"', page)

        if not boxes or spaced:
            raise AssertionError(f"Expected each of the page's {boxes} local-time boxes to "
                                 f"follow its time with no space, found one after {spaced}.")

        return True

    return assertion


def _what_a_reader_sees(page: str) -> str:
    """The page's words with its markup gone, its line breaks closed up, and
    what the template escaped said as the browser says it - an apostrophe is
    `&#39;` in the markup and `'` on the screen."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _a_document_with(timeline: list[TimelineEntry] | None = None,
                     action_items: list[ActionItem] | None = None,
                     review: list[ReviewCriterion] | None = None,
                     resolution: list[ResolutionStep] | None = None,
                     symptom: str | None = None,
                     trigger: Trigger | None = None,
                     no_trigger: NoTrigger | None = None,
                     impact: Impact | None = None,
                     detection: Detection | None = None) -> PostmortemDocument:
    """A document with nothing in any section but the ones it is given."""
    return PostmortemDocument(
        root_cause=None,
        executive_summary=None,
        customer_loss_estimate=None,
        estimate_currency=None,
        engineer_minutes=None,
        responders=None,
        tokens_spent=None,
        assumptions=[],
        timeline=timeline or [],
        action_items=action_items or [],
        review=review or [],
        resolution=resolution or [],
        symptom=symptom,
        trigger=trigger,
        no_trigger=no_trigger,
        impact=impact,
        detection=detection
    )


def _a_change_read(label: str) -> CitedChange:
    """A flag toggled, read under `label`."""
    return CitedChange(label=label,
                       change=ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                          occurred_at=DONT_CARE_CHANGED_AT,
                                          reference=DONT_CARE_SUBJECT,
                                          summary=DONT_CARE_WORDS),
                       short_reference=DONT_CARE_SUBJECT)


def _a_pdf_to_save_as(filename: str) -> Assertion[httpx2.Response]:
    """A PDF, handed over as a file to save under `filename` rather than shown
    in the browser's tab."""
    def assertion(response: httpx2.Response) -> bool:
        got = (response.status_code, response.headers.get("content-type"),
               response.headers.get("content-disposition"), response.content[:5])
        expected = (HttpStatus.OK, "application/pdf", f'attachment; filename="{filename}"',
                    b"%PDF-")

        if got != expected:
            raise AssertionError(f"Expected the status, type, disposition and first bytes "
                                 f"{expected}, got {got}.")

        return True

    return assertion


def _the_page_shows_no(name: str) -> Assertion[str]:
    """That one `data-` attribute is absent altogether.

    Its own assertion rather than an empty `the_page_shows`, because "shows
    nothing" is the claim being made, and a call with no values to show reads
    as one somebody forgot to finish.
    """
    def assertion(page: str) -> bool:
        shown = attribute(name, page)

        if shown:
            raise AssertionError(f"Expected no [{name}] at all, got {shown}.")

        return True

    return assertion


def _the_page_lists(this: str, above: str) -> Assertion[str]:
    """That one incident is shown before another, wherever the rest of the
    history put them.

    Relative rather than positional: this page is every incident there has ever
    been, so an assertion pinning the positions would be an assertion about
    whatever the tests before it left behind.
    """
    def assertion(page: str) -> bool:
        listed = attribute("incident", page)

        for incident_id in (this, above):
            if incident_id not in listed:
                raise AssertionError(
                    f"Expected [{incident_id}] to be listed at all, got {listed}."
                )

        if listed.index(this) > listed.index(above):
            raise AssertionError(
                f"Expected [{this}] above [{above}], the order was {listed}."
            )

        return True

    return assertion


def _the_page_lists_the_incident(incident_id: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        listed = attribute("incident", page)

        if incident_id not in listed:
            raise AssertionError(f"Expected [{incident_id}] to be listed, got {listed}.")

        return True

    return assertion


def _every_page_says(text: str) -> Assertion[list[str]]:
    """The same claim against more than one page, named rather than repeated.

    A time is written in a zone on every screen that shows one, so the test is
    about the pages together - and asserting it of one page at a time would
    pass while the other read as local.
    """
    def assertion(pages: list[str]) -> bool:
        silent = [number for number, page in enumerate(pages, start=1) if text not in page]

        if silent:
            raise AssertionError(f"Expected every page to say [{text}], {silent} did not.")

        return True

    return assertion


def _the_page_has_stopped_asking() -> Assertion[str]:
    def assertion(page: str) -> bool:
        if POLLS_FOR_MORE in page:
            raise AssertionError("Expected the page to have stopped asking, it had not.")

        return True

    return assertion


def _a_deploy_read_on(incident_id: str,
                      revision: str,
                      repository: str,
                      summary: str = DONT_CARE_WORDS) -> ChangesRetrieved:
    """A deploy of `revision` read, which can be opened where `repository` is,
    by a read whose window holds the moment it was deployed."""
    reach = timedelta(minutes=5)

    return ChangesRetrieved(
        incident_id=incident_id,
        window_start=to_iso(DONT_CARE_MOMENT - reach),
        window_end=to_iso(DONT_CARE_MOMENT + reach),
        changes=[_a_deploy_of(revision, repository, summary)])


def _a_deploy_cited(revision: str, repository: str) -> CitedChange:
    """A deploy of `revision` cited among the changes read, said short as the
    document says it, and opening where `repository` is."""
    return CitedChange(label=SOME_CHANGE_LABEL,
                       change=_a_deploy_of(revision, repository, DONT_CARE_WORDS),
                       short_reference=revision[:7])


def _a_deploy_of(revision: str, repository: str, summary: str) -> ChangeEvent:
    """A deploy of `revision`, which can be opened at its commit in `repository`."""
    return ChangeEvent(kind=ChangeKind.DEPLOY,
                       occurred_at=DONT_CARE_CHANGED_AT,
                       reference=revision,
                       summary=summary,
                       revision_source=RevisionSource(
                           repository=SOME_REPOSITORY_NAME,
                           repository_address=repository,
                           revision_address=f"{repository}/commit/{revision}"))


def _logs_read_at(incident_id: str, minute: datetime) -> LogsRetrieved:
    """One logs read whose window holds `minute`, with one line logged inside it."""
    reach = timedelta(minutes=10)
    logged_at = minute + timedelta(seconds=12)

    return LogsRetrieved(incident_id=incident_id,
                         window_start=to_iso(minute - reach),
                         window_end=to_iso(minute + reach),
                         lines=[f"{to_iso(logged_at)} ERROR checkout failed"])


def _a_finding_inside(minute: datetime) -> Evidence:
    """A finding resting on a moment inside `minute`, and saying nothing of it."""
    return Evidence(claim=DONT_CARE_WORDS, at=minute + timedelta(seconds=30))


def _metrics_showing(incident_id: str, minute: datetime) -> MetricsRetrieved:
    """One metrics read that came back with a single minute in it."""
    return MetricsRetrieved(
        incident_id=incident_id,
        window_start=to_iso(minute),
        window_end=to_iso(minute),
        buckets=[MetricBucket(
            bucket_id=to_iso(minute),
            error_rate=0.2,
            p50_ms=120,
            p95_ms=240,
            p99_ms=420,
            request_volume=200,
            memory_used_bytes=440 * 1024**2,
            process_start_time_seconds=1_756_000_000.0,
            cpu_used_cores=0.77,
            cpu_limit_cores=3.0
        )]
    )


def _the_candidates_link_to(*addresses: str) -> Assertion[list[str]]:
    """Under Candidates, on every page asked: the timeline above it links its
    own findings, and a link there says nothing about these."""
    def assertion(pages: list[str]) -> bool:
        missing = [(number, address)
                   for number, page in enumerate(pages, start=1)
                   for address in addresses
                   if f'href="{address}"' not in page.partition("<h2>Candidates</h2>")[2]]

        if missing:
            raise AssertionError(f"Expected every page to link to {list(addresses)} under "
                                 f"Candidates, and (page, link) {missing} did not.")

        return True

    return assertion


def _the_timeline_says(text: str) -> Assertion[str]:
    """Above Candidates, where the timeline is: the candidates below it say
    their findings too, and a line there says nothing about these."""
    def assertion(page: str) -> bool:
        if text not in page.partition("<h2>Candidates</h2>")[0]:
            raise AssertionError(f"Expected the timeline to say [{text}], and it did not.")

        return True

    return assertion


def _the_page_does_not_say(text: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        if text in page:
            raise AssertionError(f"Expected the page not to say [{text}], and it did.")

        return True

    return assertion


def _a_candidate_recorded_for(conn: psycopg.Connection,
                              incident_id: str,
                              subject: str,
                              rank: int,
                              evidence: list[str] | None = None,
                              number: int = 1) -> str:
    hypothesis = Hypothesis(
        incident_id=incident_id,
        summary=f"{DONT_CARE_WORDS} - {subject}",
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=DONT_CARE_CONFIDENCE,
        supporting_evidence=[Evidence(claim=cited, at=None) for cited in evidence or []],
        subject=subject,
        rank=rank,
        number=number
    )
    hypotheses.record(conn, hypothesis)

    return hypothesis.id


def _the_page_never_says(text: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        if text in page:
            raise AssertionError(f"Expected the page never to say [{text}], it did.")

        return True

    return assertion


def _an_attempt_taken_for(conn: psycopg.Connection,
                          incident_id: str,
                          hypothesis_id: str,
                          outcome: Verdict,
                          undone: Undone | None = None,
                          performed: bool = True) -> None:
    taken_actions.record(
        conn,
        incident_id,
        hypothesis_id=hypothesis_id,
        action_type=DONT_CARE_ACTION,
        subject=DONT_CARE_SUBJECT,
        outcome=outcome,
        undo_descriptor=(FlagUndo(flag=DONT_CARE_SUBJECT, was_enabled=True) if performed
                         else None),
        at=utc_now(),
        performed=performed,
        left_behind_known=True,
        undone=undone
    )


def _links_to_its_incident(incident_id: str, times: int) -> Assertion[str]:
    """The page links to its incident's own page `times` times, by the page's
    full address or by its path - and not to a page under it, as the PDF is."""
    def assertion(page: str) -> bool:
        linked = sum(page.count(f'href="{address}"')
                     for address in (f"http://testserver/incidents/{incident_id}",
                                     f"/incidents/{incident_id}"))

        if linked != times:
            raise AssertionError(f"Expected the page to link to its incident {times} times, "
                                 f"and it linked to it {linked} times.")

        return True

    return assertion


def _gives_no_element_the_id(value: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        if f'id="{value}"' in page:
            raise AssertionError(f"Expected no element of the page to have the id [{value}], "
                                 f"one did.")

        return True

    return assertion
