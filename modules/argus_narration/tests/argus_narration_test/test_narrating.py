"""Turning the recorded account into the lines a reader sees.

Every event becomes exactly one line. Nothing here decides what an event meant,
groups two of them into a conclusion, or drops one it finds uninteresting - the
moment this had an opinion about the investigation, the page would be a second
investigator.

Two exceptions, and both are counting rather than judging: candidates formed in
one breath are gathered onto one line, and identical looks at a service that
has not recovered are counted rather than repeated. Both are here, and so is
the case each must not swallow - candidates formed in two different rounds, and
a look that found something different.

What a line is made *of* is another module's subject. A metrics line carries
its buckets and a log line its lines, but which minutes are marked and how a
level is read belong to `metrics` and `logs`, and are tested there.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from argus_core import new_id, to_iso
from argus_core.anomaly import THE_JUDGED_SIGNALS
from argus_core.events import (
    ActionRecommended,
    ActionRefused,
    ActionTaken,
    AgentInvoked,
    AlarmDisproven,
    AlertAcknowledged,
    AnchoredOnTheAlarm,
    AwaitingRecovery,
    CandidateSelected,
    CandidatesReordered,
    ChangesRetrieved,
    ChangeUndone,
    CommunicationFailed,
    DeploymentChangesRead,
    ExecutiveSynopsisWithheld,
    ExecutiveSynopsisWritten,
    FixAttempted,
    FlagChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    IncidentRemembered,
    LeadWeighed,
    MessageUnderstood,
    MetricsRetrieved,
    MitigationResumed,
    OfferExpired,
    OnsetDetected,
    PersonWrote,
    PlacementRecorded,
    PlatformUnavailable,
    PostmortemWritten,
    QuestionAnswered,
    RecoveryChecked,
    RememberingFailed,
    ResolutionOffered,
    RetrievalRequested,
    RetrievalUnanswered,
    RolloutRead,
    ServiceRegisterRead,
    SimilarIncidentsRecalled,
    StatusChanged,
    VerdictReached,
    WithdrawalOffered,
)
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    DISCARD_CACHE_ENTRIES,
    FLAG_PROVIDER,
    PIN_AUTOSCALER,
    PIN_TO_ACCELERATOR,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    RULE_READING_FIELD,
    SCALE_OUT,
    ActionIdentity,
    ActionType,
    Actor,
    Alert,
    ChangeEvent,
    ChangeKind,
    DeploymentComparison,
    Evidence,
    FailureMode,
    FixOutcome,
    FlagChange,
    IncidentStatus,
    Meaning,
    MetricBucket,
    OpenedPullRequest,
    Ownership,
    PodPlacement,
    RecalledIncident,
    RecordedPlacement,
    Reference,
    Refusal,
    Report,
    ReportChannel,
    RetrievalChannel,
    RolloutAccount,
    RolloutProgress,
    ServiceDependency,
    Standing,
    Undone,
    Verdict,
    WhatWasTried,
    the_actions_through,
    why_it_was_refused,
)
from argus_narration.narrating import (
    CandidateNamed,
    NarrationLine,
    build_narration,
    each_wait_told_once,
    said_as_meant,
    said_in_full,
    what_to_do,
    what_was_done,
    what_was_not_done,
)
from argus_testkit import Assertion, Scenario, all_of, the_answer_was

# The minute most lines here are about, and the one before it: a window from
# the one to the other spans the minutes between them.
SOME_MINUTE_AT = datetime(2026, 8, 30, 10, 14, tzinfo=UTC)
MINUTES_BETWEEN_THEM = 1
AN_EARLIER_MINUTE_AT = SOME_MINUTE_AT - timedelta(minutes=MINUTES_BETWEEN_THEM)
SOME_MINUTE = to_iso(SOME_MINUTE_AT)
AN_EARLIER_MINUTE = to_iso(AN_EARLIER_MINUTE_AT)
SOME_MINUTE_A_WEEK_EARLIER_AT = SOME_MINUTE_AT - timedelta(weeks=1)

_OPENED_AT = SOME_MINUTE_AT + timedelta(minutes=1)

# The onset the placements are read against, at the earlier of the two minutes.
SOME_ONSET = AN_EARLIER_MINUTE_AT
SOME_TIME_LONG_BEFORE_THE_ONSET = SOME_ONSET - timedelta(hours=2)

# How a reader is shown a moment: by the clock, to the second where it has one,
# and with its day where that is not the day of the line it is said on.
BY_THE_CLOCK = "%H:%M"
TO_THE_SECOND = "%H:%M:%S"
WITH_ITS_DAY = "%b %d %H:%M"
WITH_ITS_DAY_TO_THE_SECOND = "%b %d %H:%M:%S"
SOME_MINUTE_BY_THE_CLOCK = f"{SOME_MINUTE_AT:{BY_THE_CLOCK}}"
AN_EARLIER_MINUTE_BY_THE_CLOCK = f"{AN_EARLIER_MINUTE_AT:{BY_THE_CLOCK}}"

# A window an alarm was judged over: its first minute, how many it holds, and
# the last, which those minutes put it at.
SOME_MINUTES_JUDGED = 30
SOME_FIRST_MINUTE_JUDGED_AT = SOME_MINUTE_AT
SOME_LAST_MINUTE_JUDGED_AT = (SOME_FIRST_MINUTE_JUDGED_AT
                              + timedelta(minutes=SOME_MINUTES_JUDGED - 1))

# Taken from the demo app (Argus-Demo-Target-App): its service, the alert rule
# it fires, two of its flags, the dependency its register names and that
# dependency's owner, and the card its replicas run on. They must not change
# unless the demo app does.
SOME_SERVICE = "io-shop"
SOME_ALERT_NAME = "HighErrorRate"
SOME_FALLBACK_FLAG = "legacy-checkout-fallback"
SOME_SPEND_FLAG = "monthly-spend-feature"
SOME_DEPENDENCY = "io-pricing"
SOME_DEPENDENCY_OWNER = "checkout-platform"
SOME_CARD = "Tesla-V100-SXM2-16GB"

SOME_FLAG = "some-ramped-flag"
SOME_SUBJECT = "some-subject"
ANOTHER_CARD = "Tesla-T4"
SOME_POD = f"{SOME_SERVICE}-a"
ANOTHER_POD = f"{SOME_SERVICE}-b"
YET_ANOTHER_POD = f"{SOME_SERVICE}-c"
SOME_REVISION = "9c1f0ab2d4e6"
AN_EARLIER_REVISION = "544cef36a8ea"
SOME_PR_NUMBER = 7
SOME_PR_URL = f"https://example.invalid/pull/{SOME_PR_NUMBER}"
SOME_BRANCH = "argus/fix-abc"
SOME_PERSON = "some person"
SOME_MESSAGE = Reference(source="some-chat", kind="some-kind", value="some-message")
DONT_CARE_SECONDS_ALLOWED = 180.0

# A candidate cause by the number the line that formed it gave it, and as every
# line acting for it says it.
SOME_CANDIDATE_NUMBER = 3
SOME_CANDIDATE_SAID_AS = f"candidate cause #{SOME_CANDIDATE_NUMBER}"

# Where the ranking of a round's candidates starts, every round.
THE_LEADING_RANK = 1

# A flag's two positions, as every line says them.
SAID_ON = "ON"
SAID_OFF = "OFF"

# Whom each line is credited to, as every destination names them.
ARGUS = "Argus"
INVESTIGATOR_AGENT = "Investigator Agent"
INTENT_AGENT = "Intent Agent"
CODE_FIX_AGENT = "Code-Fix Agent"
POSTMORTEM_AGENT = "Postmortem Agent"
COMMUNICATOR_AGENT = "Communicator Agent"
UNNAMED_PERSON = "A person"

# What Code-Fix said of the code it read, where a fix is no pull request.
SOME_EXPLANATION = ("The scrape selects the metrics port by its old name, so "
                    "scrape.yaml would have to name http-metrics instead.")


# Built here rather than with the helpers at the end, because the parametrized
# cases below are built as the module loads.


def _a_person_writing(text: str = "rolled the flag back by hand, we're fine") -> PersonWrote:
    """Somebody writing in the incident's thread, with an id nothing here reads."""
    return PersonWrote(incident_id=new_id(), message=SOME_MESSAGE, person_id="some-person-id",
                       text=text)


def _a_reading(meaning: Meaning) -> MessageUnderstood:
    return MessageUnderstood(incident_id=new_id(), message=SOME_MESSAGE, meaning=meaning)


def _an_offer(offered: type[ResolutionOffered] | type[WithdrawalOffered],
              person_name: str | None = SOME_PERSON) -> ResolutionOffered | WithdrawalOffered:
    """An offer to end the incident, answering words nothing here reads."""
    return offered(incident_id=new_id(), message=SOME_MESSAGE, person_id="some-person-id",
                   person_name=person_name, said="rolled the flag back by hand, we're fine")


def _an_expiry() -> OfferExpired:
    return OfferExpired(incident_id=new_id(), message=SOME_MESSAGE)


def _an_answer(answer: str = "Argus reverted the checkout flag at 10:16") -> QuestionAnswered:
    return QuestionAnswered(incident_id=new_id(), message=SOME_MESSAGE, answer=answer)


def _a_weighing(standing: Standing,
                reason: str = "the checkout flag moved at the onset") -> LeadWeighed:
    return LeadWeighed(incident_id=new_id(), message=SOME_MESSAGE, standing=standing,
                       reason=reason)


def _a_post_slack_refused(channel: str = "#some-channel",
                          refusal: str = "some_refusal") -> CommunicationFailed:
    """A line Slack would not take, about a kind of line nothing here reads."""
    return CommunicationFailed(incident_id=new_id(), channel=channel, refusal=refusal,
                               about_kind="verdict-reached")


@pytest.mark.unit
def test_the_narration_keeps_the_order_the_events_were_published_in() -> None:
    # The account is a sequence, and its order is the order things happened in.
    # A view that re-sorted it would be telling a different story from the one
    # that was recorded.
    some_incident = new_id()

    an_account_of_three_things: list[IncidentEvent] = [
        AlertAcknowledged(incident_id=some_incident, alert=_an_alert()),
        OnsetDetected(incident_id=some_incident, onset=SOME_MINUTE),
        StatusChanged(
            incident_id=some_incident, to_status=IncidentStatus.MITIGATING
        )
    ]

    Scenario() \
        .given(an_account_of_three_things) \
        .when(lambda: build_narration(an_account_of_three_things)) \
        .then(_the_kinds_are(
            ["alert-acknowledged", "onset-detected", "status-changed"]
        ))


@pytest.mark.unit
def test_every_line_is_timed_by_the_moment_its_event_happened() -> None:
    # Not by when the page was rendered, and not by when the row was written:
    # the moment belongs to the thing that happened.
    some_event = OnsetDetected(incident_id=new_id(), onset=SOME_MINUTE)

    Scenario() \
        .given(some_event) \
        .when(lambda: build_narration([some_event])) \
        .then(_the_only_line_happened_at(some_event.at))


@pytest.mark.unit
def test_the_alert_line_names_the_alert_first() -> None:
    # The first line in the channel, read in a busy one: what fired and where
    # comes first, in the alert's own name, rather than behind "Received the
    # alert".
    some_event = AlertAcknowledged(incident_id=new_id(), alert=_an_alert())

    Scenario() \
        .given(some_event) \
        .when(lambda: build_narration([some_event])) \
        .then(_the_only_line_mentions(f"Received {SOME_ALERT_NAME} on {SOME_SERVICE}"))


@pytest.mark.unit
def test_a_retrieval_line_names_the_channel_and_the_window_it_asked_about() -> None:
    # A retrieval whose window is not shown cannot be checked against what came
    # back, which is the one thing a reader wants from it.
    some_request = RetrievalRequested(
        incident_id=new_id(),
        channel=RetrievalChannel.LOGS,
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE
    )

    Scenario() \
        .given(some_request) \
        .when(lambda: build_narration([some_request])) \
        .then(all_of(_the_only_line_mentions("log"),
                     _the_only_line_mentions(f"{MINUTES_BETWEEN_THEM} minute"),
                     _the_only_line_mentions(SOME_MINUTE_BY_THE_CLOCK)))


@pytest.mark.unit
def test_a_retrieval_line_dates_a_window_from_another_day() -> None:
    # Asked today about a minute a week ago: said as a clock time alone, the
    # reader takes the minute for today's.
    some_request = RetrievalRequested(
        incident_id=new_id(),
        channel=RetrievalChannel.LOGS,
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE,
        at=SOME_MINUTE_AT + timedelta(weeks=1)
    )

    Scenario() \
        .given(some_request) \
        .when(lambda: build_narration([some_request])) \
        .then(_the_only_line_mentions(f"{SOME_MINUTE_AT:{WITH_ITS_DAY}}"))


@pytest.mark.unit
def test_a_change_retrieval_line_says_it_asked_for_flag_changes_too() -> None:
    # The read takes in the flag provider's history beside deploys and
    # releases. Said as deploys and releases alone, a read that found a flag
    # change reads as one that could not have, and a write-up blames the read
    # for missing what it never claimed to look for.
    some_request = RetrievalRequested(
        incident_id=new_id(),
        channel=RetrievalChannel.CHANGES,
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE
    )

    Scenario() \
        .given(some_request) \
        .when(lambda: build_narration([some_request])) \
        .then(_the_only_line_mentions("deploys, releases and flag changes"))


@pytest.mark.unit
def test_a_metrics_retrieval_carries_the_minutes_it_read_back() -> None:
    # The evidence travels on the line that read it, so the story can gather it
    # into a table afterwards. What is marked in that table is `metrics`' own
    # subject and is tested there.
    some_bucket = _a_bucket(SOME_MINUTE)
    some_read = MetricsRetrieved(
        incident_id=new_id(),
        window_start=SOME_MINUTE,
        window_end=SOME_MINUTE,
        buckets=[some_bucket]
    )

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_carries_the_minutes([SOME_MINUTE]))


@pytest.mark.unit
def test_a_metrics_read_whose_rows_stop_is_said_as_an_absence() -> None:
    # The count is true and it is a count of the wrong thing. Six minutes were
    # read back, and all six are from before the incident: what the story has to
    # say is that the rows stop and that nothing covers the minutes since, which
    # is the incident rather than a detail of it.
    #
    # One line, and it reaches the dashboard, Slack and the postmortem together -
    # so a count here is a short window reported in three places.
    some_read = MetricsRetrieved(
        incident_id=new_id(),
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE,
        buckets=[_a_bucket(AN_EARLIER_MINUTE), _a_bucket(SOME_MINUTE)],
        stopped_before_the_alert=True
    )

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(all_of(_the_only_line_mentions("stop"),
                     _the_only_line_mentions(SOME_MINUTE_BY_THE_CLOCK)))


@pytest.mark.unit
def test_a_metrics_read_whose_rows_stop_names_the_last_minute_they_cover_by_the_clock() -> None:
    # The window's end is the start of the last minute read, so "they stop at
    # 00:08" reads as nothing from 00:08 on, when 00:08 was read - and a
    # postmortem retelling it said the metrics stopped at 00:08 in one place
    # and 00:09 in another. Said by the clock, like every other line: the wire
    # format is what the tools speak to each other.
    some_read = MetricsRetrieved(
        incident_id=new_id(),
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE,
        buckets=[_a_bucket(AN_EARLIER_MINUTE), _a_bucket(SOME_MINUTE)],
        stopped_before_the_alert=True
    )

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(all_of(_the_only_line_mentions("stop after the minute at"),
                     _the_only_line_mentions(SOME_MINUTE_BY_THE_CLOCK),
                     _the_only_line_does_not_say(SOME_MINUTE)))


@pytest.mark.unit
def test_a_metrics_read_that_ran_to_the_alert_is_said_as_a_count() -> None:
    # The guard on the case above. Every incident before a window could stop is
    # this one, and what its line says has not changed.
    some_read = MetricsRetrieved(
        incident_id=new_id(),
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE,
        buckets=[_a_bucket(AN_EARLIER_MINUTE), _a_bucket(SOME_MINUTE)]
    )

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_mentions(f"{len(some_read.buckets)} minutes"))


@pytest.mark.unit
def test_a_changes_retrieval_carries_what_changed_on_the_service() -> None:
    # What changed is what a cause actually is, so it travels on the line that
    # read it rather than being summarised away.
    some_deploy = _a_deploy(SOME_REVISION, SOME_MINUTE)
    some_read = ChangesRetrieved(
        incident_id=new_id(),
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE,
        changes=[some_deploy]
    )

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_carries_the_changes([some_deploy]))


@pytest.mark.unit
def test_a_flag_history_is_carried_as_the_changes_it_reported() -> None:
    # Which flag moved, which way and when: the three facts the action was
    # chosen from, and the ones an audience checks it against.
    dont_care_who_moved_it = "a-human"
    some_toggle = FlagChange(
        flag=SOME_FLAG, enabled=True, occurred_at=SOME_MINUTE, actor=dont_care_who_moved_it
    )
    some_read = FlagChangesRetrieved(incident_id=new_id(), changes=[some_toggle])

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_carries_the_flag_changes([some_toggle]))


@pytest.mark.unit
def test_a_flag_history_read_is_credited_to_argus() -> None:
    # The walk reads the flag history itself, every round, before any agent is
    # called in to act on it. Credited to the Mitigation Agent, the line put a
    # read by an agent ahead of the line calling that agent in - and on an
    # incident that never called it in at all.
    some_read = FlagChangesRetrieved(incident_id=new_id(), changes=[])

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_lines_are_credited_to([ARGUS]))


@pytest.mark.unit
def test_a_flag_history_read_says_the_window_it_covered_and_whose_changes_it_counts() -> None:
    # "Recent" has no span, so a write-up saying no flag moved lately ruled out
    # a stretch nobody could see. And Argus's own toggles are left out of the
    # read: over a window ending now, a count of none says nothing of one Argus
    # made.
    some_read = FlagChangesRetrieved(incident_id=new_id(), changes=[],
                                     window_start=AN_EARLIER_MINUTE, window_end=SOME_MINUTE,
                                     at=SOME_MINUTE_AT + timedelta(seconds=30))

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_says(
            f"{len(some_read.changes)} flag changes by anyone but Argus",
            f"{MINUTES_BETWEEN_THEM} minute before {SOME_MINUTE_BY_THE_CLOCK}"))


@pytest.mark.unit
def test_a_flag_history_read_recorded_with_no_window_is_said_as_recent() -> None:
    # Recorded before the window was carried: said as it always was, rather
    # than with a span made up for it.
    some_read = FlagChangesRetrieved(incident_id=new_id(), changes=[])

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_says(f"{len(some_read.changes)} recent flag changes"))


@pytest.mark.unit
def test_a_read_of_what_a_deployment_changed_names_the_deployment() -> None:
    # The read that tells a configuration change from a code change, and what a
    # reader of the page is given of it is which deployment was looked into.
    dont_care_what_the_diff_said = ["some line of the diff"]
    some_read = DeploymentChangesRead(incident_id=new_id(), revision=SOME_REVISION,
                                      said=dont_care_what_the_diff_said)

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_says(f"what the deployment of {SOME_REVISION} changed"))


@pytest.mark.unit
@pytest.mark.parametrize(("comparison", "said"), [
    (DeploymentComparison.NOTHING_BEFORE_IT,
     f"it is the earliest deployment of {SOME_SERVICE} the history holds, so there was "
     "nothing before it to compare it against"),
    (DeploymentComparison.NOT_DEPLOYED, f"no deployment of {SOME_SERVICE} has that revision")
], ids=["nothing-before-it", "not-deployed"])
def test_a_read_with_no_comparison_behind_it_says_why_and_claims_no_diff_read(
        comparison: DeploymentComparison, said: str) -> None:
    # Nothing was compared, so "read what it changed" would be false: what came
    # back is a fact about the history, and the line says which.
    dont_care_what_the_diff_said = ["dont care"]
    some_read = DeploymentChangesRead(incident_id=new_id(), revision=SOME_REVISION,
                                      said=dont_care_what_the_diff_said, comparison=comparison,
                                      service=SOME_SERVICE)

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(all_of(
            _the_only_line_says(f"Asked what the deployment of {SOME_REVISION} changed", said),
            _the_only_line_does_not_say("Read what the deployment")))


@pytest.mark.unit
def test_a_converged_rollout_names_the_revision_every_replica_runs_and_when_it_landed() -> None:
    # The ordinary answer, and a finding: it rules out two revisions serving at
    # once. Said from the read tier's value - by the clock, like every other
    # line - rather than in the sentences the model was shown. To the second,
    # since the line reaches a model, and what a model is given is exact.
    some_fleet_size = 6
    some_instant_at = SOME_MINUTE_AT + timedelta(seconds=37)
    some_instant = to_iso(some_instant_at)
    some_deploy = _a_deploy(SOME_REVISION, some_instant)
    some_read = RolloutRead(incident_id=new_id(), account=RolloutAccount(
        progress=RolloutProgress(replicas_wanted=some_fleet_size,
                                 replicas_serving=some_fleet_size,
                                 replicas_updated=some_fleet_size),
        going_out=some_deploy, before_it=None))

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(all_of(
            _the_only_line_mentions(f"all {some_fleet_size} replicas run revision {SOME_REVISION}"),
            _the_only_line_mentions(f"{some_instant_at:{TO_THE_SECOND}}"),
            _the_only_line_does_not_say(some_instant),
            _the_lines_are_credited_to([INVESTIGATOR_AGENT])))


@pytest.mark.unit
def test_a_split_rollout_names_both_revisions_how_many_run_each_and_a_pause() -> None:
    # The answer the mode turns on: neither revision is the subject while both
    # are serving. The pause is a different fact from the split - a person
    # stopped it, rather than the platform being slow.
    some_fleet_size = 6
    some_updated = 2
    some_instant_at = SOME_MINUTE_AT + timedelta(seconds=37)
    some_read = RolloutRead(incident_id=new_id(), account=RolloutAccount(
        progress=RolloutProgress(replicas_wanted=some_fleet_size,
                                 replicas_serving=some_fleet_size,
                                 replicas_updated=some_updated, is_paused=True),
        going_out=_a_deploy(SOME_REVISION, to_iso(some_instant_at)),
        before_it=_a_deploy(AN_EARLIER_REVISION, AN_EARLIER_MINUTE)))

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(all_of(_the_only_line_mentions(f"{some_updated} of {some_fleet_size} replicas run "
                                             f"revision {SOME_REVISION}"),
                     _the_only_line_mentions(f"{some_instant_at:{TO_THE_SECOND}}"),
                     _the_only_line_mentions(f"{some_fleet_size - some_updated} still run "
                                             f"revision {AN_EARLIER_REVISION}"),
                     _the_only_line_mentions("paused")))


@pytest.mark.unit
def test_a_split_rollout_running_more_replicas_than_its_size_says_the_size() -> None:
    # A rolling update surging past its size: "3 of 6" alone reads as a fleet
    # of six the rollout finishes with, where it finishes with three.
    some_size = 3
    some_serving_past_it = 2 * some_size
    some_updated = some_size
    some_read = RolloutRead(incident_id=new_id(), account=RolloutAccount(
        progress=RolloutProgress(replicas_wanted=some_size,
                                 replicas_serving=some_serving_past_it,
                                 replicas_updated=some_updated),
        going_out=_a_deploy(SOME_REVISION, SOME_MINUTE),
        before_it=_a_deploy(AN_EARLIER_REVISION, AN_EARLIER_MINUTE)))

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(all_of(_the_only_line_mentions(f"{some_updated} of {some_serving_past_it} replicas "
                                             f"run revision {SOME_REVISION}"),
                     _the_only_line_mentions(f"of a deployment sized for {some_size}")))


@pytest.mark.unit
def test_a_split_rollout_running_its_size_says_no_size_beside_it() -> None:
    # Where the counts agree, the size is the count already said.
    the_size = 6
    some_updated = 2
    some_read = RolloutRead(incident_id=new_id(), account=RolloutAccount(
        progress=RolloutProgress(replicas_wanted=the_size, replicas_serving=the_size,
                                 replicas_updated=some_updated),
        going_out=_a_deploy(SOME_REVISION, SOME_MINUTE),
        before_it=_a_deploy(AN_EARLIER_REVISION, AN_EARLIER_MINUTE)))

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_does_not_say("sized for"))


@pytest.mark.unit
def test_a_converged_rollout_of_one_replica_is_said_in_the_singular() -> None:
    # "all 1 replicas run" is the line a reader stops at.
    one_replica = 1
    some_read = RolloutRead(incident_id=new_id(), account=RolloutAccount(
        progress=RolloutProgress(replicas_wanted=one_replica, replicas_serving=one_replica,
                                 replicas_updated=one_replica),
        going_out=_a_deploy(SOME_REVISION, SOME_MINUTE),
        before_it=None))

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_mentions(f"its {one_replica} replica runs revision {SOME_REVISION}"))


@pytest.mark.unit
@pytest.mark.parametrize(("serving", "updated", "said_of_the_new", "said_of_the_old"), [
    (2, 1, "{updated} of {serving} replicas runs revision {new}",
     "{not_updated} still runs revision {old}"),
    (1, 0, "{updated} of {serving} replica run revision {new}",
     "{not_updated} still runs revision {old}")
], ids=["one-on-each-side", "one-serving"])
def test_a_split_rollout_with_one_replica_on_a_side_says_that_side_in_the_singular(
        serving: int, updated: int, said_of_the_new: str, said_of_the_old: str) -> None:
    # Each count agrees with what it counts: "1 still run" is the line a
    # reader stops at.
    dont_care_size = 1
    some_read = RolloutRead(incident_id=new_id(), account=RolloutAccount(
        progress=RolloutProgress(replicas_wanted=dont_care_size, replicas_serving=serving,
                                 replicas_updated=updated),
        going_out=_a_deploy(SOME_REVISION, SOME_MINUTE),
        before_it=_a_deploy(AN_EARLIER_REVISION, AN_EARLIER_MINUTE)))
    the_counts_and_revisions = {"updated": updated, "serving": serving,
                                "not_updated": serving - updated,
                                "new": SOME_REVISION, "old": AN_EARLIER_REVISION}

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(all_of(
            _the_only_line_mentions(said_of_the_new.format(**the_counts_and_revisions)),
            _the_only_line_mentions(said_of_the_old.format(**the_counts_and_revisions))))


@pytest.mark.unit
def test_a_split_rollout_with_nothing_before_it_says_the_older_revision_is_not_named() -> None:
    # The replicas not yet updated run *something*, and the history cannot say
    # what - said, rather than left out, or the split reads as one revision.
    some_fleet_size = 6
    some_updated = 2
    some_read = RolloutRead(incident_id=new_id(), account=RolloutAccount(
        progress=RolloutProgress(replicas_wanted=some_fleet_size,
                                 replicas_serving=some_fleet_size,
                                 replicas_updated=some_updated),
        going_out=_a_deploy(SOME_REVISION, SOME_MINUTE),
        before_it=None))

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_mentions(f"{some_fleet_size - some_updated} still run an earlier "
                                      f"revision the history does not name"))


@pytest.mark.unit
def test_a_register_read_names_each_dependency_and_whose_it_is() -> None:
    # A cause resting on a dependency rests on this read: whose it is decided
    # whether anything could be done, and the account is owed the fact under
    # the conclusion.
    dont_care_purpose = "dont care"
    dont_care_host = "dont care"
    some_read = ServiceRegisterRead(incident_id=new_id(), dependencies=[
        ServiceDependency(name=SOME_DEPENDENCY, purpose=dont_care_purpose, host=dont_care_host,
                          owner=SOME_DEPENDENCY_OWNER, ownership=Ownership.INTERNAL)])

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(all_of(_the_only_line_mentions(f"{SOME_DEPENDENCY} (internal, "
                                             f"owned by {SOME_DEPENDENCY_OWNER})"),
                     _the_lines_are_credited_to([INVESTIGATOR_AGENT])))


@pytest.mark.unit
def test_an_empty_register_read_says_the_service_calls_nothing_it_knows_of() -> None:
    # Read and empty is a finding, and a line saying nothing of it would read
    # as a register nobody asked.
    some_read = ServiceRegisterRead(incident_id=new_id(), dependencies=[])

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_mentions("records nothing the service calls"))


@pytest.mark.unit
def test_a_candidate_is_the_hypothesis_that_was_recorded() -> None:
    # Not restated and not re-derived: the narration and the walk have to be
    # the same hypothesis seen twice, rather than two accounts to reconcile.
    some_cause = f"{SOME_FALLBACK_FLAG} was enabled"
    some_candidate = _a_hypothesis(summary=some_cause)

    Scenario() \
        .given(some_candidate) \
        .when(lambda: build_narration([some_candidate])) \
        .then(_the_only_line_offers_the_causes([some_cause]))


@pytest.mark.unit
def test_a_candidate_carries_the_hypothesis_it_was_recorded_as() -> None:
    # So whatever lays the candidates out somewhere else - the write-up, under
    # labels of its own - can tell which line formed which.
    some_candidate = _a_hypothesis()

    Scenario() \
        .given(some_candidate) \
        .when(lambda: [candidate.hypothesis_id
                       for candidate in build_narration([some_candidate])[0].candidates]) \
        .then(the_answer_was([some_candidate.hypothesis_id]))


@pytest.mark.unit
def test_a_candidate_quoting_an_instant_on_another_day_keeps_its_date() -> None:
    # Said beside the line it was formed on: a deploy a week before that line,
    # written as a clock time alone, reads as one this morning.
    some_candidate = _a_hypothesis(
        summary=f"The deploy at {to_iso(SOME_MINUTE_A_WEEK_EARLIER_AT)} broke it"
    ).model_copy(update={"at": _OPENED_AT})

    Scenario() \
        .given(some_candidate) \
        .when(lambda: build_narration([some_candidate])) \
        .then(_the_only_line_offers_the_causes(
            [f"The deploy at {SOME_MINUTE_A_WEEK_EARLIER_AT:{WITH_ITS_DAY}} broke it"]
        ))


@pytest.mark.unit
def test_an_onset_on_another_day_is_placed_with_its_date() -> None:
    # A fault found a week after it began - a total that drifted all week - and
    # its onset as a clock time alone reads as this morning.
    some_onset = OnsetDetected(incident_id=new_id(),
                               onset=to_iso(SOME_MINUTE_A_WEEK_EARLIER_AT),
                               at=_OPENED_AT)

    Scenario() \
        .given(some_onset) \
        .when(lambda: build_narration([some_onset])) \
        .then(_the_only_line_mentions(f"at {SOME_MINUTE_A_WEEK_EARLIER_AT:{WITH_ITS_DAY}}"))


@pytest.mark.unit
def test_the_alarms_minute_is_said_as_where_the_investigation_looked_from_not_as_a_start(
) -> None:
    # Nothing dated the incident, and the minute is only where every window was
    # anchored. Said as a start, the page and the postmortem dated the incident
    # from the moment the alarm went off.
    some_anchor = AnchoredOnTheAlarm(incident_id=new_id(), minute=SOME_MINUTE)

    Scenario() \
        .given(some_anchor) \
        .when(lambda: build_narration([some_anchor])) \
        .then(all_of(
            _the_only_line_says("the minute the alarm fired in"),
            _the_only_line_says("nothing dates when the incident began"),
            _the_only_line_does_not_say("start")
        ))


@pytest.mark.unit
def test_a_candidate_shows_the_move_it_blamed_the_way_the_flag_table_does() -> None:
    # One spelling for a flag's position across the whole page, so a change
    # reads as the same kind of thing whether it appears in the flag table or
    # under a candidate. The states arrive as the model wrote them - the page
    # is what decides how they are said.
    some_state_as_the_model_wrote_it = "off"
    another_state_as_the_model_wrote_it = "on"
    some_candidate_blaming_a_toggle = _a_hypothesis(
        from_state=some_state_as_the_model_wrote_it,
        to_state=another_state_as_the_model_wrote_it
    )

    Scenario() \
        .given(some_candidate_blaming_a_toggle) \
        .when(lambda: build_narration([some_candidate_blaming_a_toggle])) \
        .then(_the_only_candidate_moved(was=SAID_OFF, now=SAID_ON))


@pytest.mark.unit
def test_the_candidates_formed_together_are_one_line() -> None:
    # An investigation forms its explanations in one breath, and a story that
    # spent a line on each would bury what it did next under a list. They are
    # one finding with a ranking inside it - each said by its number, which a
    # later round's carry on from the rounds before, where its rank starts at
    # one again.
    some_incident = new_id()
    some_number = SOME_CANDIDATE_NUMBER
    the_leading_candidate = _a_hypothesis(rank=THE_LEADING_RANK, incident_id=some_incident,
                                          number=some_number)
    the_candidate_after_it = _a_hypothesis(rank=THE_LEADING_RANK + 1, incident_id=some_incident,
                                           number=some_number + 1)
    something_else = OnsetDetected(incident_id=some_incident, onset=SOME_MINUTE)

    a_round_of_two_candidates_then_something_else: list[IncidentEvent] = [
        the_leading_candidate,
        the_candidate_after_it,
        something_else
    ]

    Scenario() \
        .given(a_round_of_two_candidates_then_something_else) \
        .when(lambda: build_narration(a_round_of_two_candidates_then_something_else)) \
        .then(all_of(_the_kinds_are(["hypothesis-formed", "onset-detected"]),
                     _the_first_line_numbers_the_causes([some_number, some_number + 1])))


@pytest.mark.unit
def test_candidates_formed_in_two_rounds_are_two_lines() -> None:
    # Consecutive only. Two candidates with something in between were formed in
    # two different rounds of the walk - the second after the first was tried
    # and refuted - and folding those together would say the investigation had
    # known both at once.
    some_incident = new_id()

    a_candidate_a_refutation_and_another: list[IncidentEvent] = [
        _a_hypothesis(incident_id=some_incident),
        VerdictReached(
            incident_id=some_incident, hypothesis_id=new_id(), outcome=Verdict.REFUTED
        ),
        _a_hypothesis(incident_id=some_incident)
    ]

    Scenario() \
        .given(a_candidate_a_refutation_and_another) \
        .when(lambda: build_narration(a_candidate_a_refutation_and_another)) \
        .then(_the_kinds_are(
            ["hypothesis-formed", "verdict-reached", "hypothesis-formed"]
        ))


@pytest.mark.unit
def test_an_action_a_person_s_ending_stopped_is_said_as_never_judged() -> None:
    # A person resolved or withdrew the incident while the service was watched,
    # so nothing was judged. "Judged the action WITHDRAWN" read as a verdict
    # reached, and as a withdrawal of an incident a person had resolved.
    a_stopped_judgement = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.STOPPED
    )
    the_stop = "Stopped before judging the action"

    Scenario() \
        .given(a_stopped_judgement) \
        .when(lambda: build_narration([a_stopped_judgement])) \
        .then(all_of(
            _the_only_line_reads(f"{the_stop} - a person ended the incident"),
            _the_only_line_marks(the_stop)
        ))


@pytest.mark.unit
def test_a_candidate_shows_what_it_was_formed_from() -> None:
    # The findings are what make a claim checkable. Without them the page asks
    # an audience to take Argus's word for the whole investigation.
    what_it_rests_on = f"{SOME_SPEND_FLAG} began evaluating ON at 10:05"
    some_candidate = _a_hypothesis(evidence=[what_it_rests_on])

    Scenario() \
        .given(some_candidate) \
        .when(lambda: build_narration([some_candidate])) \
        .then(_the_only_line_cites([what_it_rests_on]))


@pytest.mark.unit
def test_a_finding_quoting_an_instant_on_another_day_keeps_its_date() -> None:
    # Said beside the line its candidate was formed on, as the candidate's own
    # summary is: a deploy a week before that line, written as a clock time
    # alone, reads as one this morning.
    a_candidate_citing_an_instant = _a_hypothesis(
        evidence=[f"The deploy at {to_iso(SOME_MINUTE_A_WEEK_EARLIER_AT)} broke it"]
    ).model_copy(update={"at": _OPENED_AT})

    Scenario() \
        .given(a_candidate_citing_an_instant) \
        .when(lambda: build_narration([a_candidate_citing_an_instant])) \
        .then(_the_only_line_cites(
            [f"The deploy at {SOME_MINUTE_A_WEEK_EARLIER_AT:{WITH_ITS_DAY}} broke it"]
        ))


@pytest.mark.unit
def test_identical_looks_at_a_service_that_has_not_recovered_are_counted() -> None:
    # The wait re-reads every few seconds and, until the moment it recovers,
    # has the same thing to say each time. A dozen identical rows push
    # everything else off the screen to report one unchanged fact - and none at
    # all is a page that looks stuck, which is why the count is kept.
    some_incident = new_id()
    how_many_times_it_looked = 3

    Scenario() \
        .given(
            a_run_of_looks_that_found_the_same_thing := [
                RecoveryChecked(
                    incident_id=some_incident, minute=SOME_MINUTE, recovered=False
                )
                for _ in range(how_many_times_it_looked)
            ]
        ) \
        .when(lambda: build_narration(a_run_of_looks_that_found_the_same_thing)) \
        .then(_the_only_line_stands_for(how_many_times_it_looked))


@pytest.mark.unit
def test_a_look_that_found_something_different_is_a_line_of_its_own() -> None:
    # The moment the whole wait was for. Folded into the count above it, the
    # page would report that Argus looked twice and never that the service came
    # back.
    some_incident = new_id()
    one_look = 1

    Scenario() \
        .given(
            a_pair_of_looks_whose_answer_changed := [
                RecoveryChecked(
                    incident_id=some_incident, minute=SOME_MINUTE, recovered=False
                ),
                RecoveryChecked(
                    incident_id=some_incident, minute=SOME_MINUTE, recovered=True
                )
            ]
        ) \
        .when(lambda: build_narration(a_pair_of_looks_whose_answer_changed)) \
        .then(_the_lines_each_stand_for(
            [one_look] * len(a_pair_of_looks_whose_answer_changed)
        ))


@pytest.mark.unit
def test_a_look_that_found_the_service_back_says_which_minute_it_came_back_at() -> None:
    # The two minutes a look holds are different facts and only one is about the
    # service. 10:14 is where the verdict is read from, which is about Argus and
    # is already said by the line above this one; 10:13 is when the shop actually
    # came back, and a reader never told it cannot see that the recovery preceded
    # whatever Argus did about it. So the waited-from minute stays off the line
    # for the reason it always has, and this one goes on.
    some_incident = new_id()

    Scenario() \
        .given(
            a_look_that_found_the_service_back := RecoveryChecked(
                incident_id=some_incident,
                minute=SOME_MINUTE,
                recovered=True,
                recovered_minute=AN_EARLIER_MINUTE
            )
        ) \
        .when(lambda: build_narration([a_look_that_found_the_service_back])) \
        .then(all_of(
            _the_only_line_says(AN_EARLIER_MINUTE_BY_THE_CLOCK),
            _the_only_line_does_not_say(SOME_MINUTE_BY_THE_CLOCK),
            _the_only_line_names_the_minute(AN_EARLIER_MINUTE)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("look", "said"), [
    (RecoveryChecked(incident_id=new_id(), minute=SOME_MINUTE, recovered=True,
                     recovered_minute=AN_EARLIER_MINUTE),
     f"no longer at the incident's level since {AN_EARLIER_MINUTE_BY_THE_CLOCK}"),
    (RecoveryChecked(incident_id=new_id(), minute=SOME_MINUTE, recovered=True),
     "no longer at the incident's level"),
    (RecoveryChecked(incident_id=new_id(), minute=SOME_MINUTE, recovered=False),
     "still at the incident's level"),
    (RecoveryChecked(incident_id=new_id(), minute=SOME_MINUTE, recovered=False,
                     saw_no_minute=True),
     "no new minute read yet")
], ids=["dated", "undated", "not-yet", "nothing-to-judge"])
def test_a_look_says_what_it_judged_rather_than_that_the_service_was_back_to_normal(
        look: RecoveryChecked, said: str) -> None:
    # A look judges whether the service fell off the incident's own level, which
    # is what a verdict on an action needs - not whether it was back inside the
    # range it keeps when nothing is wrong. A fix landing mid-minute leaves that
    # minute off the incident's level and still outside its range, and "back at
    # its baseline" said of it claims what nothing measured.
    Scenario() \
        .given(look) \
        .when(lambda: build_narration([look])) \
        .then(all_of(
            _the_only_line_says(said),
            _the_only_line_does_not_say("baseline")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("look", "said"), [
    (RecoveryChecked(incident_id=new_id(), minute=SOME_MINUTE, recovered=True,
                     recovered_minute=AN_EARLIER_MINUTE, read_again=True),
     f"its metrics could be read again from {AN_EARLIER_MINUTE_BY_THE_CLOCK}"),
    (RecoveryChecked(incident_id=new_id(), minute=SOME_MINUTE, recovered=True,
                     read_again=True),
     "its metrics could be read again")
], ids=["dated", "undated"])
def test_a_look_that_finds_a_blind_spot_read_again_says_so_rather_than_a_level(
        look: RecoveryChecked, said: str) -> None:
    # A blind spot had no level read while its minutes were missing, so it has
    # none to leave: what came back is the metrics themselves. Said as a level,
    # the page tells a reader the service was read at one the whole time.
    Scenario() \
        .given(look) \
        .when(lambda: build_narration([look])) \
        .then(all_of(
            _the_only_line_says(said),
            _the_only_line_does_not_say("level"),
            _the_only_line_does_not_say("back to normal")
        ))


@pytest.mark.unit
def test_a_wait_asks_what_its_looks_answer_rather_than_waiting_for_an_answer() -> None:
    # "Waiting for the service to answer" reads as a service that had stopped
    # answering - said of a latency incident in which it answered throughout,
    # only slowly. The wait asks the question the looks after it answer, in
    # their words.
    Scenario() \
        .given(
            some_wait := AwaitingRecovery(incident_id=new_id(), from_minute=SOME_MINUTE,
                                          seconds_allowed=DONT_CARE_SECONDS_ALLOWED)
        ) \
        .when(lambda: build_narration([some_wait])) \
        .then(all_of(
            _the_only_line_says("whether the service is still at the incident's level"),
            _the_only_line_does_not_say("answer")
        ))


@pytest.mark.unit
def test_a_wait_on_a_blind_spot_asks_whether_its_metrics_can_be_read_again() -> None:
    # No level was read while its minutes were missing, so there is none to be
    # still at: the wait asks what the look after it answers.
    Scenario() \
        .given(
            some_wait := AwaitingRecovery(incident_id=new_id(), from_minute=SOME_MINUTE,
                                          seconds_allowed=DONT_CARE_SECONDS_ALLOWED,
                                          until_read_again=True)
        ) \
        .when(lambda: build_narration([some_wait])) \
        .then(all_of(
            _the_only_line_says("Waiting to see whether its metrics can be read again, from "),
            _the_only_line_does_not_say("level")
        ))


@pytest.mark.unit
def test_the_onset_line_names_the_minute_it_placed() -> None:
    # It names one minute out of ninety, and the account carries which one so
    # that a reader is never left to find it by eye. What a page then does with
    # that - an anchor at the minute's own row - is the page's business.
    some_onset = OnsetDetected(incident_id=new_id(), onset=SOME_MINUTE)

    Scenario() \
        .given(some_onset) \
        .when(lambda: build_narration([some_onset])) \
        .then(_the_only_line_names_the_minute(SOME_MINUTE))


@pytest.mark.unit
def test_the_line_saying_where_the_investigation_looked_from_names_that_minute() -> None:
    # One minute out of ninety, as the onset's line names its own: a reader is
    # never left to find it by eye.
    some_anchor = AnchoredOnTheAlarm(incident_id=new_id(), minute=SOME_MINUTE)

    Scenario() \
        .given(some_anchor) \
        .when(lambda: build_narration([some_anchor])) \
        .then(_the_only_line_names_the_minute(SOME_MINUTE))


@pytest.mark.unit
def test_an_action_line_marks_the_flag_and_shows_the_move() -> None:
    # The action names one flag, and the move is shown the way the flag table
    # shows one, so a change reads as a change wherever it appears. Where that
    # flag's row is on a page is the page's business, not the account's.
    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=REVERT_FEATURE_FLAG,
        subject=SOME_FLAG,
        enabled=False
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(all_of(
            _the_only_line_moved(SAID_ON, SAID_OFF),
            _the_only_line_marks(SOME_FLAG)))


@pytest.mark.unit
def test_an_action_said_in_full_says_which_way_the_flag_moved() -> None:
    # A destination with no flag table to strike a state through - a document,
    # a message - still owes the reader the move, in words.
    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=REVERT_FEATURE_FLAG,
        subject=SOME_FLAG,
        enabled=False
    )

    Scenario() \
        .given(
            some_line := _the_only(build_narration([some_action]))
        ) \
        .when(
            lambda: said_in_full(some_line)
        ) \
        .then(
            _ends_with(f"moved from {SAID_ON} to {SAID_OFF}")
        )


@pytest.mark.unit
def test_the_candidates_said_in_full_are_named_after_the_count() -> None:
    # "best first:" introduces the list a page lays out beneath the line. Said
    # alone, the colon has to be followed by what it promised.
    some_cause = f"{SOME_FALLBACK_FLAG} was enabled"
    some_candidate = _a_hypothesis(summary=some_cause)

    Scenario() \
        .given(
            some_line := _the_only(build_narration([some_candidate]))
        ) \
        .when(
            lambda: said_in_full(some_line)
        ) \
        .then(
            _ends_with(f"best first: {some_cause}")
        )


@pytest.mark.unit
def test_one_production_change_is_one_change() -> None:
    some_deploy = _a_deploy(SOME_REVISION, SOME_MINUTE)
    some_read = ChangesRetrieved(
        incident_id=new_id(),
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE,
        changes=[some_deploy]
    )

    Scenario() \
        .given(
            some_read
        ) \
        .when(
            lambda: _the_only(build_narration([some_read])).text
        ) \
        .then(
            _ends_with(f"Read back {len(some_read.changes)} production change")
        )


def _ends_with(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if not said.endswith(expected):
            raise AssertionError(f"Expected a sentence ending [{expected}], got [{said}].")

        return True

    return assertion


@pytest.mark.unit
def test_an_action_done_is_said_in_words_rather_than_by_its_tag() -> None:
    # A document lists what was done long after anybody reads the action's
    # tag, so it says it the way the account's own line does.
    Scenario() \
        .given(
            SOME_FLAG
        ) \
        .when(
            lambda: what_was_done(REVERT_FEATURE_FLAG, SOME_FLAG)
        ) \
        .then(
            _ends_with(f"Reverted the feature flag {SOME_FLAG}")
        )


@pytest.mark.unit
def test_a_pin_done_is_said_with_the_card_it_held_the_pods_to() -> None:
    # Said without it, an overview that also spoke of purchases held for
    # review read "held the pods" as a pause: the card is what they were held
    # to, as the account's own line says.
    some_application = SOME_SERVICE
    some_card = SOME_CARD

    Scenario() \
        .when(
            lambda: what_was_done(PIN_TO_ACCELERATOR, some_application, some_card)
        ) \
        .then(
            _ends_with(f"Held the pods of {some_application} to {some_card}")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("action_type", "said"), [
    (REVERT_FEATURE_FLAG, f"Revert {SOME_SUBJECT}"),
    (RESTART_SERVICE, f"Restart {SOME_SUBJECT}"),
    (ROLL_BACK_DEPLOYMENT, f"Roll {SOME_SUBJECT} back"),
    (SCALE_OUT, f"Scale {SOME_SUBJECT} out"),
    (PIN_AUTOSCALER, f"Hold {SOME_SUBJECT}'s autoscaler still"),
    (DISCARD_CACHE_ENTRIES, f"Discard {SOME_SUBJECT}'s stale cached figures"),
    (PIN_TO_ACCELERATOR, f"Hold {SOME_SUBJECT}'s pods to one accelerator card")
])
def test_an_action_left_to_do_is_said_as_an_instruction(action_type: ActionType,
                                                         said: str) -> None:
    # An action item is something a person does, and the list it sits in says
    # the rest as instructions - "Review and merge the proposed fix". The
    # gerund the account's own line uses, "rolling io-shop back", reads there
    # as a phrase left unfinished. The same verb, so the item and the line
    # read as one action.
    Scenario() \
        .given(SOME_SUBJECT) \
        .when(lambda: what_to_do(action_type, SOME_SUBJECT)) \
        .then(the_answer_was(said))


@pytest.mark.unit
@pytest.mark.parametrize(("action_type", "said"), [
    (REVERT_FEATURE_FLAG, f"Did not revert the feature flag {SOME_SUBJECT}"),
    (RESTART_SERVICE, f"Did not restart {SOME_SUBJECT}"),
    (ROLL_BACK_DEPLOYMENT, f"Did not roll back the deployment of {SOME_SUBJECT}"),
    (SCALE_OUT, f"Did not scale out the deployment of {SOME_SUBJECT}"),
    (PIN_AUTOSCALER, f"Did not raise the autoscaler floor of {SOME_SUBJECT}"),
    (DISCARD_CACHE_ENTRIES, f"Did not discard the stale cached figures of {SOME_SUBJECT}"),
    (PIN_TO_ACCELERATOR, f"Did not hold the pods of {SOME_SUBJECT}")
])
def test_an_action_never_performed_is_said_as_not_done(action_type: ActionType,
                                                       said: str) -> None:
    # An attempt that ended before its write - a platform that did not answer,
    # an action with nowhere left to go. Said in the past tense, it tells a
    # reader the service was changed when nothing was.
    Scenario() \
        .given(SOME_SUBJECT) \
        .when(lambda: what_was_not_done(action_type, SOME_SUBJECT)) \
        .then(the_answer_was(said))


@pytest.mark.unit
def test_a_verdict_on_an_action_never_performed_says_what_was_not_done() -> None:
    # Nothing announced the action - the announcement is made once a change is
    # - so this is the one line saying what was reached for. "Judged the action"
    # would claim a test that never ran.
    some_application = SOME_SERVICE
    a_verdict_on_nothing_done = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.PLATFORM_UNREACHABLE,
        action_type=ROLL_BACK_DEPLOYMENT, subject=some_application, performed=False
    )
    the_outcome_said = "PLATFORM-UNREACHABLE"

    Scenario() \
        .given(a_verdict_on_nothing_done) \
        .when(lambda: build_narration([a_verdict_on_nothing_done])) \
        .then(all_of(
            _the_only_line_reads(f"Did not roll back the deployment of {some_application} "
                                 f"- {the_outcome_said}"),
            _the_only_line_marks(the_outcome_said)
        ))


@pytest.mark.unit
def test_a_verdict_on_an_action_never_performed_says_the_candidate_it_was_for() -> None:
    # The one line saying what was reached for, so the one saying for which
    # candidate: nothing else does, and a reader takes it for the leader's.
    some_application = SOME_SERVICE
    a_verdict_on_nothing_done = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.ESCALATED,
        action_type=ROLL_BACK_DEPLOYMENT, subject=some_application, performed=False,
        candidate_number=SOME_CANDIDATE_NUMBER
    )

    Scenario() \
        .given(a_verdict_on_nothing_done) \
        .when(lambda: build_narration([a_verdict_on_nothing_done])) \
        .then(
            _the_only_line_reads(f"Did not roll back the deployment of {some_application} "
                                 f"for {SOME_CANDIDATE_SAID_AS} - ESCALATED")
        )


@pytest.mark.unit
def test_a_verdict_on_an_action_never_performed_says_why_in_the_tier_s_words() -> None:
    # The only reason this line has for an explanation passed over untested,
    # and nothing else live says it.
    some_application = SOME_SERVICE
    some_reason = f"[{some_application}] has no revision before the one it is running"
    a_verdict_on_nothing_done = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.NOT_ATTEMPTED,
        action_type=ROLL_BACK_DEPLOYMENT, subject=some_application, performed=False,
        candidate_number=SOME_CANDIDATE_NUMBER, not_performed_because=some_reason
    )
    the_outcome_said = "NOT-ATTEMPTED"

    Scenario() \
        .given(a_verdict_on_nothing_done) \
        .when(lambda: build_narration([a_verdict_on_nothing_done])) \
        .then(all_of(
            _the_only_line_reads(f"Did not roll back the deployment of {some_application} "
                                 f"for {SOME_CANDIDATE_SAID_AS} - "
                                 f"{the_outcome_said}: {some_reason}"),
            _the_only_line_marks(the_outcome_said)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("undone, said", [
    (Undone.RESTORED, f"was put back {SAID_ON}"),
    (Undone.LEFT_AS_FOUND,
     "was left as found: it has been changed from outside since Argus set it")
], ids=["restored", "left-as-found"])
def test_a_refuted_change_says_what_putting_it_back_did(undone: Undone, said: str) -> None:
    # Nothing else live says it: the cleanup's own line comes only when an
    # incident is unwound, and a thread without it reads as the flag still off.
    a_refutation_put_back = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.REFUTED,
        action_type=REVERT_FEATURE_FLAG, subject=SOME_FLAG,
        undone=undone, undone_detail=said
    )
    the_outcome_said = "REFUTED"

    Scenario() \
        .given(a_refutation_put_back) \
        .when(lambda: build_narration([a_refutation_put_back])) \
        .then(all_of(
            _the_only_line_reads(f"Judged the action {the_outcome_said} - {SOME_FLAG} {said}"),
            _the_only_line_marks(the_outcome_said)
        ))


@pytest.mark.unit
def test_an_escalated_undo_is_not_said_again_on_the_verdict_s_line() -> None:
    # The undo could not be established, and the move to ESCALATED beside this
    # line says it in the same words. Said here too, a reader reads it twice.
    some_detail = ("was not written: whether anybody changed it since Argus "
                   "set it could not be established")
    an_escalated_undo = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.ESCALATED,
        action_type=REVERT_FEATURE_FLAG, subject=SOME_FLAG,
        undone=Undone.NOT_ESTABLISHED,
        undone_detail=some_detail
    )

    Scenario() \
        .given(an_escalated_undo) \
        .when(lambda: build_narration([an_escalated_undo])) \
        .then(
            _the_only_line_reads("Judged the action ESCALATED")
        )


@pytest.mark.unit
def test_an_action_taken_says_the_candidate_it_was_for() -> None:
    # By the number the line that formed it gave it. The move to mitigating
    # names no candidate, so without this a reader takes every action for the
    # leading candidate's - and an action for the third reads as the first's.
    some_application = SOME_SERVICE
    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        candidate_number=SOME_CANDIDATE_NUMBER,
        action_type=ROLL_BACK_DEPLOYMENT,
        subject=some_application,
        enabled=None
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(
            _the_only_line_reads(f"Rolled back the deployment of {some_application} "
                                 f"for {SOME_CANDIDATE_SAID_AS}")
        )


@pytest.mark.unit
def test_the_move_to_mitigating_names_no_candidate() -> None:
    # Made once a round, as the walk first reaches for a candidate, and not
    # again as it passes over one it has no action for - so the leading
    # candidate it used to name was, as often as not, one nobody acted on.
    a_move_to_mitigating = StatusChanged(incident_id=new_id(),
                                         to_status=IncidentStatus.MITIGATING)

    Scenario() \
        .given(a_move_to_mitigating) \
        .when(lambda: build_narration([a_move_to_mitigating])) \
        .then(
            _the_only_line_reads("Moved the incident to MITIGATING to act on a candidate")
        )


@pytest.mark.unit
def test_an_action_a_person_s_ending_stopped_before_it_was_done_is_said_as_never_taken() -> None:
    # A person ended the incident between the walk choosing the action and
    # taking it. Nothing was judged, and nothing was done either.
    a_stop_before_the_write = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.STOPPED,
        action_type=REVERT_FEATURE_FLAG, subject=SOME_FLAG, performed=False
    )
    the_stop = "Stopped before taking the action"

    Scenario() \
        .given(a_stop_before_the_write) \
        .when(lambda: build_narration([a_stop_before_the_write])) \
        .then(all_of(
            _the_only_line_reads(f"{the_stop} - a person ended the incident"),
            _the_only_line_marks(the_stop)
        ))


@pytest.mark.unit
def test_a_verdict_on_a_change_nothing_could_read_says_it_could_not_be_judged() -> None:
    # The change was made and every look at the service went unanswered.
    # "Judged the action ESCALATED" says a judgement was reached, and the same
    # word stands for a refutation whose undo failed - which was judged.
    a_verdict_on_an_unread_wait = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.ESCALATED,
        action_type=REVERT_FEATURE_FLAG, subject=SOME_FLAG, judged=False
    )
    the_outcome_said = "ESCALATED"

    Scenario() \
        .given(a_verdict_on_an_unread_wait) \
        .when(lambda: build_narration([a_verdict_on_an_unread_wait])) \
        .then(all_of(
            _the_only_line_reads(f"Could not judge the action - {the_outcome_said}"),
            _the_only_line_marks(the_outcome_said)
        ))


@pytest.mark.unit
def test_a_verdict_on_a_change_that_was_read_says_it_was_judged() -> None:
    # A refutation whose undo failed escalates too, and it was judged.
    a_judged_escalation = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.ESCALATED,
        action_type=REVERT_FEATURE_FLAG, subject=SOME_FLAG
    )

    Scenario() \
        .given(a_judged_escalation) \
        .when(lambda: build_narration([a_judged_escalation])) \
        .then(
            _the_only_line_reads("Judged the action ESCALATED")
        )


@pytest.mark.unit
def test_a_verdict_an_older_version_wrote_on_an_action_never_performed_names_no_action() -> None:
    # An event that says nothing was done and names no action: there is no
    # action to name, and the line still says nothing was done.
    an_older_verdict = VerdictReached(
        incident_id=new_id(), hypothesis_id=new_id(), outcome=Verdict.NOT_ATTEMPTED,
        performed=False
    )

    Scenario() \
        .given(an_older_verdict) \
        .when(lambda: build_narration([an_older_verdict])) \
        .then(
            _the_only_line_reads("Did not take the action - NOT-ATTEMPTED")
        )


@pytest.mark.unit
def test_a_status_change_marks_the_status_it_moved_to() -> None:
    # The word a reader scanning from across a room finds first. Split into
    # three plain strings rather than marked up here: a view that returned HTML
    # would be a view that could inject it.
    some_move = StatusChanged(incident_id=new_id(), to_status=IncidentStatus.MITIGATING)

    Scenario() \
        .given(some_move) \
        .when(lambda: build_narration([some_move])) \
        .then(_the_only_line_marks(str(IncidentStatus.MITIGATING).upper()))


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.RESOLVED, IncidentStatus.WITHDRAWN])
def test_a_status_change_a_person_reported_is_said_in_their_name(ending: IncidentStatus) -> None:
    # The one move Argus did not make. Credited to Argus, the account would
    # say Argus decided the incident was over - and the person, the door they
    # came through and what they added are the whole of what a reader of this
    # line is owed.
    some_note = "rolled the flag back by hand"
    some_report = StatusChanged(
        incident_id=new_id(),
        to_status=ending,
        reported=Report(by=SOME_PERSON, channel=ReportChannel.ARGUS_UI, note=some_note)
    )

    Scenario() \
        .given(some_report) \
        .when(lambda: build_narration([some_report])) \
        .then(all_of(
            _the_lines_are_credited_to([SOME_PERSON]),
            _the_only_line_marks(str(ending).upper()),
            _the_only_line_says("the Argus UI", some_note)
        ))


@pytest.mark.unit
def test_a_resolution_from_the_paging_tool_names_that_tool() -> None:
    # Whoever reads the account and wants a word with the resolver goes to the
    # tool they resolved it in - so the line names that tool, as the place it
    # happened.
    some_report = StatusChanged(
        incident_id=new_id(),
        to_status=IncidentStatus.RESOLVED,
        reported=Report(by=SOME_PERSON, channel=ReportChannel.PAGERDUTY)
    )

    Scenario() \
        .given(some_report) \
        .when(lambda: build_narration([some_report])) \
        .then(_the_only_line_says("from PagerDuty"))


@pytest.mark.unit
def test_a_resolution_from_the_slack_thread_names_slack() -> None:
    # The thread is where the person said it, and where a reader goes to ask
    # them what they meant.
    some_report = StatusChanged(
        incident_id=new_id(),
        to_status=IncidentStatus.RESOLVED,
        reported=Report(by=SOME_PERSON, channel=ReportChannel.SLACK)
    )

    Scenario() \
        .given(some_report) \
        .when(lambda: build_narration([some_report])) \
        .then(_the_only_line_says("from Slack"))


@pytest.mark.unit
def test_a_report_without_a_note_says_nothing_in_its_place() -> None:
    # Most people press the button and type nothing. A line that printed the
    # absence, or left a dash hanging where the note would go, would read as
    # something lost.
    some_report = StatusChanged(
        incident_id=new_id(),
        to_status=IncidentStatus.RESOLVED,
        reported=Report(by=SOME_PERSON, channel=ReportChannel.ARGUS_UI)
    )

    Scenario() \
        .given(some_report) \
        .when(lambda: build_narration([some_report])) \
        .then(_the_only_line_does_not_say("None", " - "))


@pytest.mark.unit
@pytest.mark.parametrize("refusal", list(Refusal), ids=lambda refusal: refusal.value)
def test_a_refusal_marks_why_the_action_was_not_taken_in_the_sentence_every_reader_says(
    refusal: Refusal
) -> None:
    # The autonomy boundary holding, said as the one thing a reader can act on.
    # Which candidate went untested is on the candidate's own row; what a person
    # scanning the account needs is which refusal this was, since each sends
    # them to somebody different. Marked for the reason a refused message marks
    # its refusal: the reason is the actionable half. And in the kernel's own
    # sentence, which the candidate's row and the review say too - three
    # spellings of one reason read as three reasons.
    #
    # Over the whole enum: a refusal nobody wrote a sentence for raises while
    # the incident is being narrated, in the one path that exists to say what
    # happened.
    some_refusal = ActionRefused(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        refusal=refusal
    )

    Scenario() \
        .given(some_refusal) \
        .when(lambda: build_narration([some_refusal])) \
        .then(all_of(
            _the_only_line_marks(why_it_was_refused(refusal)),
            _the_only_line_says(f"Refused to act - {why_it_was_refused(refusal)}"),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_a_recommendation_names_the_action_somebody_should_take() -> None:
    # The refusal beside it says Argus declined to act and why. That is half an
    # account: a reader of a refusal learns something did not happen, and this
    # is the only line that says what should. Without it the incident reports a
    # cause, a reason for inaction, and no next step - which is worse than
    # escalating, because escalation at least announces that a person is needed.
    #
    # The subject is marked rather than the kind. "Revert a feature flag" is
    # not something anybody can go and do; the flag's name is.
    some_flag = "monthly-spend-summary"
    some_recommendation = ActionRecommended(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=REVERT_FEATURE_FLAG,
        subject=some_flag
    )

    Scenario() \
        .given(some_recommendation) \
        .when(lambda: build_narration([some_recommendation])) \
        .then(all_of(
            _the_only_line_marks(some_flag),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_a_refusal_says_the_candidate_whose_action_it_refused() -> None:
    # The move to mitigating names no candidate, and a chat has no candidate
    # panel beside it: a later round's refusal reads as the first round's, and
    # two candidates refused for one reason read as one.
    some_refusal = ActionRefused(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        candidate_number=SOME_CANDIDATE_NUMBER,
        refusal=Refusal.NOTHING_COULD_CONFIRM_IT
    )

    Scenario() \
        .given(some_refusal) \
        .when(lambda: build_narration([some_refusal])) \
        .then(
            _the_only_line_says(f"Refused to act on {SOME_CANDIDATE_SAID_AS} - "
                                f"{why_it_was_refused(Refusal.NOTHING_COULD_CONFIRM_IT)}")
        )


@pytest.mark.unit
def test_a_recommendation_says_the_candidate_it_answers() -> None:
    # For the refusal's reason: the action left for a person is one cause's,
    # and which is what tells a reader what it would settle.
    some_recommendation = ActionRecommended(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        candidate_number=SOME_CANDIDATE_NUMBER,
        action_type=ROLL_BACK_DEPLOYMENT,
        subject=SOME_SERVICE
    )

    Scenario() \
        .given(some_recommendation) \
        .when(lambda: build_narration([some_recommendation])) \
        .then(
            _the_only_line_says(f"Left for a person to do - rolling {SOME_SERVICE} back "
                                f"for {SOME_CANDIDATE_SAID_AS}")
        )


@pytest.mark.unit
@pytest.mark.parametrize("a_line_acting_for_a_candidate", [
    lambda hypothesis_id: ActionTaken(incident_id=new_id(), hypothesis_id=hypothesis_id,
                                      candidate_number=SOME_CANDIDATE_NUMBER,
                                      action_type=ROLL_BACK_DEPLOYMENT,
                                      subject=SOME_SERVICE),
    lambda hypothesis_id: VerdictReached(incident_id=new_id(), hypothesis_id=hypothesis_id,
                                         candidate_number=SOME_CANDIDATE_NUMBER,
                                         outcome=Verdict.ESCALATED,
                                         action_type=ROLL_BACK_DEPLOYMENT,
                                         subject=SOME_SERVICE, performed=False),
    lambda hypothesis_id: ActionRefused(incident_id=new_id(), hypothesis_id=hypothesis_id,
                                        candidate_number=SOME_CANDIDATE_NUMBER,
                                        refusal=Refusal.NOTHING_COULD_CONFIRM_IT),
    lambda hypothesis_id: ActionRecommended(incident_id=new_id(), hypothesis_id=hypothesis_id,
                                            candidate_number=SOME_CANDIDATE_NUMBER,
                                            action_type=ROLL_BACK_DEPLOYMENT,
                                            subject=SOME_SERVICE)
], ids=["taken", "not-performed", "refused", "recommended"])
def test_a_line_acting_for_a_candidate_says_which_and_in_what_words(
    a_line_acting_for_a_candidate: Callable[[str], IncidentEvent]
) -> None:
    # So a destination with labels of its own for the candidates - the
    # write-up's C3 - can say it by the label: beside a row and a resolution
    # saying C3, "candidate cause #3" reads as a second candidate.
    some_hypothesis = new_id()
    some_event = a_line_acting_for_a_candidate(some_hypothesis)

    Scenario() \
        .given(some_event) \
        .when(lambda: build_narration([some_event])[0].names_candidate) \
        .then(
            the_answer_was(CandidateNamed(hypothesis_id=some_hypothesis,
                                          said_as=SOME_CANDIDATE_SAID_AS))
        )


@pytest.mark.unit
def test_a_verdict_on_an_action_performed_names_no_candidate() -> None:
    # Its action's own line said which; "Judged the action REFUTED" does not
    # name one, and a destination told it did would look for words that are
    # not there.
    some_verdict = VerdictReached(incident_id=new_id(), hypothesis_id=new_id(),
                                  candidate_number=SOME_CANDIDATE_NUMBER,
                                  outcome=Verdict.REFUTED)

    Scenario() \
        .given(some_verdict) \
        .when(lambda: build_narration([some_verdict])[0].names_candidate) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_disproven_alarm_says_what_was_ruled_out_and_over_what() -> None:
    # The only line on any timeline that reports the absence of an incident.
    # Everything else says what Argus found or did about something that was
    # happening, so a reader scanning for this one needs it to say plainly that
    # the rule fired and the service did not fail.
    #
    # The condition is marked rather than the service or the status, because the
    # condition is the thing found not to be there - and which series the rule
    # was about decides what a reader does next.
    #
    # The span and the count are both in the line for the reason they are both
    # on the event: nothing later checks a disproof, so whoever reads the
    # timeline is the last check there is. A window holding fewer minutes than
    # its ends suggest is exactly the one to doubt a disproof over, and that is
    # invisible unless both figures are said.
    #
    # Its ends as every other row says a minute, and its signals as the
    # metrics table beside it heads them: `p95_ms` above a column headed `p95`
    # is one signal said two ways.
    some_condition = "error rate above 5% for 5m"
    some_signals_judged = ("error_rate", "p95_ms")
    some_disproof = AlarmDisproven(
        incident_id=new_id(),
        condition=some_condition,
        signals_judged=some_signals_judged,
        earliest_minute=to_iso(SOME_FIRST_MINUTE_JUDGED_AT),
        latest_minute=to_iso(SOME_LAST_MINUTE_JUDGED_AT),
        minutes_judged=SOME_MINUTES_JUDGED
    )

    Scenario() \
        .given(some_disproof) \
        .when(lambda: build_narration([some_disproof])) \
        .then(all_of(
            _the_only_line_marks(some_condition),
            _the_only_line_says("in errors or p95,", str(SOME_MINUTES_JUDGED),
                                f"between {SOME_FIRST_MINUTE_JUDGED_AT:{BY_THE_CLOCK}} and "
                                f"{SOME_LAST_MINUTE_JUDGED_AT:{BY_THE_CLOCK}}"),
            _the_only_line_does_not_say(*some_signals_judged,
                                        SOME_FIRST_MINUTE_JUDGED_AT.date().isoformat()),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_every_signal_a_window_is_judged_on_is_said_as_the_metrics_table_heads_it() -> None:
    # Read off the kernel rather than listed here: a signal added to the
    # judgement and not to the headings would be said by its field name, beside
    # a table that calls it something else.
    dont_care_condition = "dont care"
    some_disproof = AlarmDisproven(
        incident_id=new_id(),
        condition=dont_care_condition,
        signals_judged=(*THE_JUDGED_SIGNALS, RULE_READING_FIELD),
        earliest_minute=to_iso(SOME_FIRST_MINUTE_JUDGED_AT),
        latest_minute=to_iso(SOME_LAST_MINUTE_JUDGED_AT),
        minutes_judged=SOME_MINUTES_JUDGED
    )

    Scenario() \
        .given(some_disproof) \
        .when(lambda: build_narration([some_disproof])) \
        .then(
            _the_only_line_says("in errors, p50, p95, p99, memory or the alert rule's series,")
        )


@pytest.mark.unit
def test_an_unavailable_platform_says_which_actions_went_with_it() -> None:
    # Without this line an incident mitigated by the one action on a live
    # platform reads as though Argus preferred that action - which is the record
    # misstating the reasoning it exists to hold.
    #
    # The actions are said rather than only the platform. A reader told a
    # platform's name has to go and work out which of Argus's five went with it,
    # from a mapping they may not have; and the answer is what they actually
    # want, because it says what Argus could not do about the incident they are
    # now holding.
    some_outage = PlatformUnavailable(
        incident_id=new_id(),
        platform=DEPLOYMENT_PLATFORM,
        actions_unavailable=the_actions_through(DEPLOYMENT_PLATFORM)
    )

    Scenario() \
        .given(some_outage) \
        .when(lambda: build_narration([some_outage])) \
        .then(all_of(
            _the_only_line_marks(DEPLOYMENT_PLATFORM),
            _the_only_line_says(
                "restarting", "rolling", "scaling", "autoscaler", "accelerator card"
            ),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_a_read_that_went_unanswered_names_what_was_asked_and_the_minute() -> None:
    # The stretch of an incident with the least to show for itself is the wait
    # after an action, and a pass that could not read the service leaves no
    # trace in it at all: the looks that succeeded are published, and the one
    # that failed used to be the reason the incident stopped. A reader then sees
    # a confirmation that took longer than the window it was measured over and
    # nothing saying why.
    #
    # The minute is the half that makes it about the verdict rather than about
    # plumbing. "A read failed" is a fact about Argus; "the shop could not be
    # read for the minute this action is being judged on" is a fact about the
    # judgement, and only the second is worth a line on the page.
    some_question = "the service's metrics"
    some_reason = "timed out"
    some_unanswered_read = RetrievalUnanswered(
        incident_id=new_id(),
        what_was_asked=some_question,
        because=some_reason,
        minute=SOME_MINUTE
    )

    Scenario() \
        .given(some_unanswered_read) \
        .when(lambda: build_narration([some_unanswered_read])) \
        .then(all_of(
            _the_only_line_says(some_question, SOME_MINUTE_BY_THE_CLOCK, some_reason),
            # Argus's own voice, not Mitigation's, though this one is published
            # from inside a mitigation. `PlatformUnavailable` is credited the
            # same way and for the same reason: the tier reported a call that
            # failed, and what is being said here is the walk's conclusion about
            # what it therefore does not know.
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_an_unavailable_platform_says_only_the_actions_it_actually_took() -> None:
    # The half that makes the line worth reading. A sentence naming every action
    # Argus has would tell a reader the flag revert was gone too - and the flag
    # revert is the one that ended this incident, so the line would contradict
    # the line after it.
    #
    # Read from the event rather than from the mapping, which is what makes an
    # old incident still legible: the event says what went away then, and the
    # mapping says what would go away now.
    some_outage = PlatformUnavailable(
        incident_id=new_id(),
        platform=DEPLOYMENT_PLATFORM,
        actions_unavailable=the_actions_through(DEPLOYMENT_PLATFORM)
    )

    Scenario() \
        .given(some_outage) \
        .when(lambda: build_narration([some_outage])) \
        .then(_the_only_line_does_not_say("reverting"))


@pytest.mark.unit
def test_a_platform_that_took_one_action_says_that_one() -> None:
    # Generated from what the event carries rather than written for the platform
    # that happens to carry four. A line hard-wired to the deployment platform's
    # phrasing would read as four actions lost whenever the flag provider was the
    # one that went - and that is the incident where nothing is left to narrow
    # to, which is the one a reader most needs told accurately.
    some_outage = PlatformUnavailable(
        incident_id=new_id(),
        platform=FLAG_PROVIDER,
        actions_unavailable=the_actions_through(FLAG_PROVIDER)
    )

    Scenario() \
        .given(some_outage) \
        .when(lambda: build_narration([some_outage])) \
        .then(all_of(
            _the_only_line_marks(FLAG_PROVIDER),
            _the_only_line_says("reverting"),
            _the_only_line_does_not_say("restarting", "rolling", "scaling")))


@pytest.mark.unit
def test_moving_to_the_next_candidate_names_it_as_the_lines_acting_for_it_do() -> None:
    # The walk skips any candidate it cannot act on, so which explanation the
    # next few lines are about is not derivable from the ranked list. Named by
    # its number, as every line acting for it is, and never in its own words:
    # a summary is the Investigator's claims, and said on Argus's line they
    # read as what happened.
    some_hypothesis = new_id()
    some_move = CandidateSelected(
        incident_id=new_id(),
        hypothesis_id=some_hypothesis,
        candidate_number=SOME_CANDIDATE_NUMBER
    )

    Scenario() \
        .given(some_move) \
        .when(lambda: build_narration([some_move])) \
        .then(all_of(
            _the_only_line_reads(f"Moving on to {SOME_CANDIDATE_SAID_AS}"),
            _the_only_line_names_the_candidate(CandidateNamed(hypothesis_id=some_hypothesis,
                                                              said_as=SOME_CANDIDATE_SAID_AS)),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_moving_to_a_candidate_whose_number_was_never_carried_names_none() -> None:
    # An event written before the number travelled: the move is still said,
    # and no candidate it cannot name is claimed for it.
    some_move = CandidateSelected(
        incident_id=new_id(),
        hypothesis_id=new_id()
    )

    Scenario() \
        .given(some_move) \
        .when(lambda: build_narration([some_move])) \
        .then(all_of(
            _the_only_line_reads("Moving on to the next candidate cause"),
            _the_only_line_names_the_candidate(None)))


@pytest.mark.unit
def test_a_resumed_attempt_says_the_verdict_was_already_on_the_row() -> None:
    # The gap in the account, filled. A walk that restarted after the verdict
    # was written reads it back rather than acting again, and an incident whose
    # story jumps from a taken action to a conclusion reads as one that lost a
    # step - or worse, as one that acted twice. Said here and nowhere else: the
    # thread already heard the verdict from the walk that reached it.
    some_resumption = MitigationResumed(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        outcome=Verdict.REFUTED
    )

    Scenario() \
        .given(some_resumption) \
        .when(lambda: build_narration([some_resumption])) \
        .then(all_of(
            _the_only_line_marks(str(Verdict.REFUTED).upper()),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_a_change_put_back_marks_the_flag_it_was_about() -> None:
    # One line per change rather than one per withdrawal: an incident that
    # moved three flags and restored two of them is not a withdrawal that
    # worked. The flag is marked the way an action marks it, because the
    # restore and the change it reverses are the same subject a page apart.
    dont_care_detail = "put back the way Argus found it"
    some_restore = ChangeUndone(
        incident_id=new_id(),
        subject=SOME_FLAG,
        outcome=Undone.RESTORED,
        detail=dont_care_detail
    )

    Scenario() \
        .given(some_restore) \
        .when(lambda: build_narration([some_restore])) \
        .then(all_of(
            _the_only_line_marks(SOME_FLAG),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_a_change_put_back_is_said_once_as_its_subject_and_what_became_of_it() -> None:
    # The restore's own answer says what became of the change, verb and all, so
    # the line is the subject followed by that answer. A verb of the line's own
    # in front of it said the restore twice: "was put back - flag [X] was put
    # back ON".
    some_detail = f"was put back {SAID_ON}"
    some_restore = ChangeUndone(
        incident_id=new_id(),
        subject=SOME_FLAG,
        outcome=Undone.RESTORED,
        detail=some_detail
    )

    Scenario() \
        .given(some_restore) \
        .when(lambda: build_narration([some_restore])) \
        .then(_the_only_line_reads(f"{SOME_FLAG} {some_detail}"))


@pytest.mark.unit
@pytest.mark.parametrize(("outcome", "detail"), [
    (Undone.LEFT_AS_FOUND, "was left as found: somebody else has changed it since Argus did"),
    (Undone.NOT_ESTABLISHED, f"could not be put back {SAID_ON}: the provider would not answer"),
    (Undone.NO_UNDO_WAS_OWED,
     "needed nothing put back: what it removed was a copy of records it never touched")
], ids=["left-as-found", "not-established", "no-undo-owed"])
def test_every_answer_about_a_change_is_said_as_its_subject_and_what_became_of_it(
        outcome: Undone, detail: str) -> None:
    # As a restore is: the answer carries its own verb, because which one fits
    # is the kind of change's to know - a write that failed could not be put
    # back, one half done was only partly put back, a flag nobody could account
    # for was not written. A heading of the line's own over all of them said
    # "could not be read" over writes that were never a read.
    some_answer = ChangeUndone(
        incident_id=new_id(),
        subject=SOME_FLAG,
        outcome=outcome,
        detail=detail
    )

    Scenario() \
        .given(some_answer) \
        .when(lambda: build_narration([some_answer])) \
        .then(_the_only_line_reads(f"{SOME_FLAG} {detail}"))


@pytest.mark.unit
def test_the_orchestrator_narrates_as_argus_and_an_agent_as_itself() -> None:
    # From outside, "the orchestrator called in the Investigator" is one system
    # talking about its own internals. What happened is that Argus did - and a
    # story where every sentence has the same silent subject reads as one
    # program doing everything, which is the opposite of what this system is.
    some_incident = new_id()

    an_agent_called_in_that_then_acts: list[IncidentEvent] = [
        AgentInvoked(incident_id=some_incident, agent=Actor.INVESTIGATOR),
        OnsetDetected(incident_id=some_incident, onset=SOME_MINUTE)
    ]

    Scenario() \
        .given(an_agent_called_in_that_then_acts) \
        .when(lambda: build_narration(an_agent_called_in_that_then_acts)) \
        .then(_the_lines_are_credited_to([ARGUS, INVESTIGATOR_AGENT]))


@pytest.mark.unit
def test_a_line_that_never_reached_a_channel_says_which_one_and_why() -> None:
    # The page's line about the page's own rival. Every other sentence here was
    # read in Slack too; this is the one saying which sentence was not - and
    # the refusal is set apart because it is the actionable half, a renamed
    # channel and a revoked token being fixed by different people.
    some_refusal = "channel_not_found"
    a_channel_that_is_not_there = "#war-room"

    a_post_slack_would_not_take = _a_post_slack_refused(
        channel=a_channel_that_is_not_there,
        refusal=some_refusal
    )

    Scenario() \
        .given(a_post_slack_would_not_take) \
        .when(lambda: build_narration([a_post_slack_would_not_take])) \
        .then(all_of(_the_only_line_mentions(a_channel_that_is_not_there),
                     _the_only_line_marks(some_refusal),
                     _the_lines_are_credited_to([COMMUNICATOR_AGENT])))


@pytest.mark.unit
def test_what_a_person_wrote_is_said_in_their_own_words() -> None:
    # The one line on the page Argus did not write. Their words are the marked
    # part, untouched: a paraphrase would be Argus putting its reading of them
    # where the reader expects the person - and the reading has a line of its
    # own.
    the_words = "rolled the flag back by hand, we're fine"
    some_message = _a_person_writing(the_words)

    Scenario() \
        .given(some_message) \
        .when(lambda: build_narration([some_message])) \
        .then(all_of(_the_only_line_marks(the_words),
                     _the_lines_are_credited_to([UNNAMED_PERSON])))


@pytest.mark.unit
@pytest.mark.parametrize(("meaning", "said"), [
    (Meaning.RESOLVE, "Reported the incident resolved"),
    (Meaning.WITHDRAW, "Asked Argus to stand down")
], ids=["resolve", "withdraw"])
def test_a_message_that_ended_the_incident_is_said_as_the_report_it_was(meaning: Meaning,
                                                                        said: str) -> None:
    # Said as no more than something written, a report reads as one Argus was
    # free to pass over. Their words stay the marked part, untouched, and the
    # line is theirs by name.
    the_words = "rolled it back, all fine"
    some_line = build_narration([_a_person_writing(the_words)])[0]

    Scenario() \
        .given(some_line) \
        .when(lambda: [said_as_meant(some_line, meaning, SOME_PERSON)]) \
        .then(all_of(_the_only_line_marks(the_words),
                     _the_lines_are_credited_to([SOME_PERSON]),
                     _the_only_line_says(said)))


@pytest.mark.unit
@pytest.mark.parametrize("meaning", [Meaning.QUESTION, Meaning.INFORMATION, Meaning.OTHER])
def test_a_message_that_ended_nothing_is_said_as_written(meaning: Meaning) -> None:
    # What came of it is its own line, in the intent agent's voice.
    dont_care_who_wrote_it = "dont care"
    some_line = build_narration([_a_person_writing()])[0]

    Scenario() \
        .given(some_line) \
        .when(lambda: said_as_meant(some_line, meaning, dont_care_who_wrote_it)) \
        .then(the_answer_was(some_line))


@pytest.mark.unit
def test_a_report_from_somebody_the_platform_could_not_name_is_said_by_a_person() -> None:
    some_line = build_narration([_a_person_writing()])[0]

    Scenario() \
        .given(some_line) \
        .when(lambda: [said_as_meant(some_line, Meaning.RESOLVE, None)]) \
        .then(_the_lines_are_credited_to([UNNAMED_PERSON]))


@pytest.mark.unit
@pytest.mark.parametrize(("meaning", "said_as"), [
    (Meaning.RESOLVE, "a resolution"),
    (Meaning.QUESTION, "a question"),
    (Meaning.INFORMATION, "new information"),
    (Meaning.WITHDRAW, "a request to stand down"),
    (Meaning.OTHER, "nothing to act on")
])
def test_what_a_message_was_classified_as_is_said_by_the_intent_agent(meaning: Meaning,
                                                                      said_as: str) -> None:
    # Every message gets a line saying what Argus made of it, including that it
    # made nothing of it - the person who wrote "thanks" can see it was understood.
    some_reading = _a_reading(meaning)

    Scenario() \
        .given(some_reading) \
        .when(lambda: build_narration([some_reading])) \
        .then(all_of(_the_only_line_marks(said_as),
                     _the_lines_are_credited_to([INTENT_AGENT])))


@pytest.mark.unit
@pytest.mark.parametrize(("person_name", "asked"), [
    (SOME_PERSON, SOME_PERSON),
    (None, "whoever wrote it")
])
def test_an_offer_to_resolve_names_who_was_asked(person_name: str | None,
                                                 asked: str) -> None:
    # The offer is addressed to one person and only their press counts, so the
    # line says who - and a person the chat platform could not name is still
    # somebody who was asked, not nobody.
    some_offer = _an_offer(ResolutionOffered, person_name)

    Scenario() \
        .given(some_offer) \
        .when(lambda: build_narration([some_offer])) \
        .then(all_of(_the_only_line_marks(asked),
                     _the_lines_are_credited_to([INTENT_AGENT])))


@pytest.mark.unit
@pytest.mark.parametrize(("person_name", "asked"), [
    (SOME_PERSON, SOME_PERSON),
    (None, "whoever wrote it")
])
def test_an_offer_to_withdraw_names_who_was_asked_and_what_confirming_does(
        person_name: str | None, asked: str) -> None:
    # Said, because it is the one thing a press does that a person might not
    # expect: Argus stops, and puts back what it changed.
    some_offer = _an_offer(WithdrawalOffered, person_name)

    Scenario() \
        .given(some_offer) \
        .when(lambda: build_narration([some_offer])) \
        .then(all_of(_the_only_line_marks(asked),
                     _the_only_line_says("stand down", "put back"),
                     _the_lines_are_credited_to([INTENT_AGENT])))


@pytest.mark.unit
@pytest.mark.parametrize("offered", [ResolutionOffered, WithdrawalOffered],
                         ids=["resolution", "withdrawal"])
def test_an_offer_carries_the_message_it_asks_to_confirm(
        offered: type[ResolutionOffered] | type[WithdrawalOffered]) -> None:
    # The line a destination turns into a button, so it says which message the
    # button answers: only the person who wrote that message may press it, and
    # the press is matched to the offer by it.
    some_offer = _an_offer(offered)

    Scenario() \
        .given(some_offer) \
        .when(lambda: build_narration([some_offer])) \
        .then(_the_only_line_asks_to_confirm(SOME_MESSAGE))


@pytest.mark.unit
@pytest.mark.parametrize("about_a_message", [
    _a_person_writing(),
    _a_reading(Meaning.RESOLVE)
], ids=["person-wrote", "message-understood"])
def test_a_line_about_a_message_asks_nothing_of_its_writer(
        about_a_message: IncidentEvent) -> None:
    # About the same message as the offer, and asking nothing. A destination
    # that put a button on these would offer to resolve before Argus had
    # decided there was anything to offer.
    Scenario() \
        .given(about_a_message) \
        .when(lambda: build_narration([about_a_message])) \
        .then(all_of(_the_only_line_asks_to_confirm(None),
                     _the_only_line_offers_to_end_as(None)))


@pytest.mark.unit
@pytest.mark.parametrize(("offered", "ending"), [
    (ResolutionOffered, IncidentStatus.RESOLVED),
    (WithdrawalOffered, IncidentStatus.WITHDRAWN)
], ids=["resolution", "withdrawal"])
def test_an_offer_says_which_ending_its_press_brings_about(
        offered: type[ResolutionOffered] | type[WithdrawalOffered],
        ending: IncidentStatus) -> None:
    # The one button looks the same whatever it confirms, so a destination
    # learns here what to write on it - and which incident endings take it
    # away again, since a mitigated incident still takes a resolution and no
    # longer takes a withdrawal.
    some_offer = _an_offer(offered)

    Scenario() \
        .given(some_offer) \
        .when(lambda: build_narration([some_offer])) \
        .then(_the_only_line_offers_to_end_as(ending))


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.RESOLVED,
                                    IncidentStatus.WITHDRAWN,
                                    IncidentStatus.DISPROVEN])
def test_a_move_past_any_resolution_says_so(ending: IncidentStatus) -> None:
    # Resolved, withdrawn, or found to be no incident: whatever was still
    # asking whether it is resolved has its answer. A destination holding an
    # offer to resolve closes it with this line.
    an_incident_ending = StatusChanged(incident_id=new_id(), to_status=ending)

    Scenario() \
        .given(an_incident_ending) \
        .when(lambda: build_narration([an_incident_ending])) \
        .then(_the_only_line_leaves_nothing_to_resolve(True))


@pytest.mark.unit
@pytest.mark.parametrize("move", [IncidentStatus.MITIGATED,
                                  IncidentStatus.ESCALATED,
                                  IncidentStatus.RECOMMENDED,
                                  IncidentStatus.FIXING,
                                  IncidentStatus.INVESTIGATING])
def test_a_move_that_still_takes_a_resolution_does_not(move: IncidentStatus) -> None:
    # Three of these end Argus's part and none ends the incident: something is
    # still owed, and a person who goes on to finish the job resolves it from
    # here. An offer closed by one of them is a button taken away from the
    # person it was for while it could still do what it says.
    an_incident_moving = StatusChanged(incident_id=new_id(), to_status=move)

    Scenario() \
        .given(an_incident_moving) \
        .when(lambda: build_narration([an_incident_moving])) \
        .then(_the_only_line_leaves_nothing_to_resolve(False))


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.MITIGATED,
                                    IncidentStatus.RESOLVED,
                                    IncidentStatus.ESCALATED,
                                    IncidentStatus.RECOMMENDED,
                                    IncidentStatus.DISPROVEN,
                                    IncidentStatus.WITHDRAWN])
def test_a_move_to_any_ending_leaves_nothing_to_withdraw(ending: IncidentStatus) -> None:
    # Mitigated among them, where a resolution is still taken: there is no work
    # left to take over once Argus has stopped, and a withdrawal's unwind would
    # put back the change holding the service up. A destination holding an
    # offer to withdraw closes it with this line.
    an_incident_ending = StatusChanged(incident_id=new_id(), to_status=ending)

    Scenario() \
        .given(an_incident_ending) \
        .when(lambda: build_narration([an_incident_ending])) \
        .then(_the_only_line_leaves_nothing_to_withdraw(True))


@pytest.mark.unit
@pytest.mark.parametrize("move", [IncidentStatus.ACKNOWLEDGED,
                                  IncidentStatus.INVESTIGATING,
                                  IncidentStatus.MITIGATING,
                                  IncidentStatus.FIXING])
def test_a_move_argus_is_still_working_through_still_takes_a_withdrawal(
        move: IncidentStatus) -> None:
    an_incident_moving = StatusChanged(incident_id=new_id(), to_status=move)

    Scenario() \
        .given(an_incident_moving) \
        .when(lambda: build_narration([an_incident_moving])) \
        .then(_the_only_line_leaves_nothing_to_withdraw(False))


@pytest.mark.unit
@pytest.mark.parametrize("standing", list(Standing))
def test_a_lead_weighed_is_said_by_the_investigator_with_its_standing_and_why(
        standing: Standing) -> None:
    # The answer the person who wrote it is owed, in the thread they wrote it
    # in: what the Investigator made of it, set apart, and why - a standing
    # with no reason is a verdict nobody can check.
    some_reason = "the checkout flag moved at the onset"
    some_weighing = _a_weighing(standing, some_reason)

    Scenario() \
        .given(some_weighing) \
        .when(lambda: build_narration([some_weighing])) \
        .then(all_of(_the_only_line_marks(standing.value),
                     _the_only_line_says(some_reason),
                     _the_lines_are_credited_to([INVESTIGATOR_AGENT])))


@pytest.mark.unit
def test_an_answer_to_a_question_is_said_whole_by_the_intent_agent() -> None:
    # The reply the person who asked is owed, in the thread they asked it in:
    # the answer itself, set apart and never shortened - a line that sends a
    # reader elsewhere for the rest is no answer.
    some_answer = ("Argus reverted the checkout flag at 10:16 and is waiting "
                   "for the error rate to recover")
    some_answering = _an_answer(some_answer)

    Scenario() \
        .given(some_answering) \
        .when(lambda: build_narration([some_answering])) \
        .then(all_of(_the_only_line_marks(some_answer),
                     _the_lines_are_credited_to([INTENT_AGENT])))


@pytest.mark.unit
def test_an_answer_is_marked_as_written_in_markdown() -> None:
    # The model answers in Markdown. Said so rather than rendered here: each
    # destination renders it in its own markup, and the record keeps what the
    # model wrote.
    dont_care_answer = "**Investigation (14:15)**\n- Reverted the flag"
    some_answering = _an_answer(dont_care_answer)

    Scenario() \
        .given(some_answering) \
        .when(lambda: build_narration([some_answering])) \
        .then(_the_only_line_is_in_markdown(True))


@pytest.mark.unit
def test_a_line_of_the_walk_s_own_is_not_marked_as_markdown() -> None:
    dont_care_detail = f"was put back {SAID_ON}"
    some_restore = ChangeUndone(
        incident_id=new_id(),
        subject=SOME_FLAG,
        outcome=Undone.RESTORED,
        detail=dont_care_detail
    )

    Scenario() \
        .given(some_restore) \
        .when(lambda: build_narration([some_restore])) \
        .then(_the_only_line_is_in_markdown(False))


@pytest.mark.unit
def test_an_offer_not_confirmed_in_time_is_said_by_argus() -> None:
    # The walk waited on a person and went on without them. Argus's own line,
    # because it was Argus that decided to carry on - and it says why, so a
    # reader does not take the next step for one taken over a person's head.
    some_expiry = _an_expiry()

    # Not "the offer to resolve": an expiry carries only the message, and the
    # offer it ends may have been to withdraw.
    Scenario() \
        .given(some_expiry) \
        .when(lambda: build_narration([some_expiry])) \
        .then(all_of(_the_only_line_marks("not confirmed in time"),
                     _the_only_line_does_not_say("resolve"),
                     _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
@pytest.mark.parametrize(("event", "expires"), [
    (_an_expiry(), True),
    (_an_offer(ResolutionOffered), False),
    (_an_offer(WithdrawalOffered), False),
    (StatusChanged(incident_id=new_id(), to_status=IncidentStatus.RESOLVED), False)
], ids=["offer-expired", "resolution-offered", "withdrawal-offered", "resolved"])
def test_only_an_expiry_expires_the_offers(event: IncidentEvent, expires: bool) -> None:
    # A destination holding an offer takes its button away with this line, and
    # the incident can still be resolved afterwards - so it is not the same
    # thing as leaving nothing to resolve, which is the incident's ending.
    Scenario() \
        .given(event) \
        .when(lambda: build_narration([event])) \
        .then(_the_only_line_expires_the_offers(expires))


@pytest.mark.unit
@pytest.mark.parametrize("event", [
    _a_person_writing(),
    StatusChanged(incident_id=new_id(), to_status=IncidentStatus.RESOLVED,
                  reported=Report(by=SOME_PERSON, channel=ReportChannel.SLACK)),
    _a_reading(Meaning.RESOLVE),
    _an_offer(ResolutionOffered),
    _an_offer(WithdrawalOffered),
    _an_expiry(),
    _an_answer(),
    _a_post_slack_refused()
], ids=["person-wrote", "status-reported", "message-understood", "resolution-offered",
        "withdrawal-offered", "offer-expired", "question-answered", "communication-failed"])
def test_a_line_written_outside_the_walk_says_so(event: IncidentEvent) -> None:
    # Written because somebody wrote in the thread or pressed on a page, or by
    # the relay posting to Slack - never by the walk, so where one lands among
    # the walk's lines is a matter of timing. A destination numbering the walk's
    # lines numbers these apart, or a person writing a second earlier renumbers
    # every line of the walk after it.
    Scenario() \
        .given(event) \
        .when(lambda: build_narration([event])) \
        .then(_the_only_line_is_outside_the_walk(True))


@pytest.mark.unit
@pytest.mark.parametrize("event", [
    StatusChanged(incident_id=new_id(), to_status=IncidentStatus.MITIGATED),
    OnsetDetected(incident_id=new_id(), onset=SOME_MINUTE),
    _a_weighing(Standing.SUPPORTED)
], ids=["status-changed", "onset-detected", "lead-weighed"])
def test_a_line_the_walk_wrote_says_so(event: IncidentEvent) -> None:
    # A lead weighed among them: it answers what a person wrote, and it is still
    # the walk's line, taken at the walk's own step.
    Scenario() \
        .given(event) \
        .when(lambda: build_narration([event])) \
        .then(_the_only_line_is_outside_the_walk(False))


@pytest.mark.unit
def test_each_wait_is_told_once_by_the_look_that_settled_it() -> None:
    # For a destination that numbers the walk's lines. How many looks a wait
    # took, and which of them a person's message fell between, is timing: told
    # look by look, one walk numbers differently from one run to the next. The
    # last look is the one that says what the wait came to, and a line outside
    # the walk stays where it fell without ending the wait around it.
    some_incident = new_id()
    some_moment_the_wait_began = SOME_MINUTE_AT + timedelta(minutes=2)
    a_look_while_it_was_not_back = RecoveryChecked(
        incident_id=some_incident, at=some_moment_the_wait_began + timedelta(seconds=10),
        minute=SOME_MINUTE, recovered=False
    )
    a_message_written_mid_wait = _a_person_writing().model_copy(update={
        "incident_id": some_incident,
        "at": some_moment_the_wait_began + timedelta(seconds=15)
    })
    the_look_that_ended_the_first_wait = RecoveryChecked(
        incident_id=some_incident, at=some_moment_the_wait_began + timedelta(seconds=20),
        minute=SOME_MINUTE, recovered=False
    )
    the_second_wait = AwaitingRecovery(
        incident_id=some_incident, at=some_moment_the_wait_began + timedelta(minutes=1),
        from_minute=SOME_MINUTE, seconds_allowed=DONT_CARE_SECONDS_ALLOWED
    )
    another_look_while_it_was_not_back = RecoveryChecked(
        incident_id=some_incident,
        at=some_moment_the_wait_began + timedelta(minutes=1, seconds=10),
        minute=SOME_MINUTE, recovered=False
    )
    the_look_that_found_it_back = RecoveryChecked(
        incident_id=some_incident,
        at=some_moment_the_wait_began + timedelta(minutes=2, seconds=10),
        minute=SOME_MINUTE, recovered=True, recovered_minute=SOME_MINUTE
    )

    Scenario() \
        .given(a_narration := build_narration([a_look_while_it_was_not_back,
                                               a_message_written_mid_wait,
                                               the_look_that_ended_the_first_wait,
                                               the_second_wait,
                                               another_look_while_it_was_not_back,
                                               the_look_that_found_it_back])) \
        .when(lambda: each_wait_told_once(a_narration)) \
        .then(_the_lines_are_dated([a_message_written_mid_wait.at,
                                    the_look_that_ended_the_first_wait.at,
                                    the_second_wait.at,
                                    the_look_that_found_it_back.at]))


@pytest.mark.unit
def test_a_postmortem_line_is_its_summary_with_the_cause_marked() -> None:
    # The write-up in the few lines somebody reads first. The summary already
    # says the cause in plain words, and what customers lost as the page says
    # it - a floor so far where the service was not seen back - so the root
    # cause and the loss said again beside it were the cause twice and the loss
    # twice, the second as a final figure. The cause is the marked part: it is
    # what a reader scanning a channel of endings is looking for.
    the_cause = "A flag change turned off the fallback checkout relies on."
    the_summary = f"The service broke at 12:00 UTC. {the_cause} What Argus did: reverted it."
    some_engineer_minutes = 34

    a_write_up = PostmortemWritten(
        incident_id=new_id(),
        cause_in_plain_words=the_cause,
        executive_summary=the_summary,
        engineer_minutes=some_engineer_minutes
    )

    Scenario() \
        .given(a_write_up) \
        .when(lambda: build_narration([a_write_up])) \
        .then(all_of(_the_only_line_marks(the_cause),
                     _the_only_line_says(f"Wrote the postmortem - {the_summary}",
                                         f"{some_engineer_minutes} engineer minutes"),
                     _the_lines_are_credited_to([POSTMORTEM_AGENT])))


@pytest.mark.unit
def test_a_postmortem_with_no_summary_is_said_to_have_been_written_and_no_more() -> None:
    # "Naming no cause" spoke of a root cause the line no longer carries, and a
    # summary nobody wrote is nothing to say.
    a_write_up = PostmortemWritten(incident_id=new_id())

    Scenario() \
        .given(a_write_up) \
        .when(lambda: build_narration([a_write_up])) \
        .then(_the_only_line_reads("Wrote the postmortem"))


@pytest.mark.unit
def test_a_postmortem_line_says_nothing_of_minutes_nobody_spent() -> None:
    # Nobody paged, or nobody engaged: the page says "none" and why, and a
    # line in a channel saying so tells a reader nothing.
    no_engineer_minutes = 0
    a_write_up = PostmortemWritten(incident_id=new_id(), engineer_minutes=no_engineer_minutes)

    Scenario() \
        .given(a_write_up) \
        .when(lambda: build_narration([a_write_up])) \
        .then(_the_only_line_does_not_mention("engineer minutes"))


@pytest.mark.unit
def test_a_synopsis_written_is_said_without_a_word_of_it() -> None:
    # What it says shows pay, and is for the people it is sent to: the
    # timeline is for everyone.
    a_synopsis = ExecutiveSynopsisWritten(incident_id=new_id())

    Scenario() \
        .given(a_synopsis) \
        .when(lambda: build_narration([a_synopsis])) \
        .then(all_of(_the_only_line_reads("Wrote the executive synopsis"),
                     _the_lines_are_credited_to([POSTMORTEM_AGENT])))


@pytest.mark.unit
def test_a_synopsis_withheld_is_said_with_why() -> None:
    # Nothing is sent for it, and the timeline is where anybody waiting for one
    # finds out why.
    some_reason = "the overview was refused twice"
    a_synopsis = ExecutiveSynopsisWithheld(incident_id=new_id(), reason=some_reason)

    Scenario() \
        .given(a_synopsis) \
        .when(lambda: build_narration([a_synopsis])) \
        .then(_the_only_line_reads(f"Withheld the executive synopsis - {some_reason}"))


@pytest.mark.unit
def test_an_order_memory_changed_says_what_moved_and_what_moved_it() -> None:
    # A walk that tried its second-best candidate first, with nothing saying
    # why, is a walk a human reading the incident back cannot account for. The
    # action is the marked phrase because taking it again is what the walk is
    # being spared; the past incident is in the sentence, because it is the
    # reason rather than the subject.
    the_flag_that_was_moved_down = "new-checkout-flow"
    the_incident_that_moved_it = new_id()

    a_reordering = CandidatesReordered(
        incident_id=new_id(),
        action_type=REVERT_FEATURE_FLAG,
        subject=the_flag_that_was_moved_down,
        on_the_strength_of=the_incident_that_moved_it
    )

    Scenario() \
        .given(a_reordering) \
        .when(lambda: build_narration([a_reordering])) \
        .then(all_of(
            _the_only_line_marks(f"reverting {the_flag_that_was_moved_down}"),
            _the_only_line_mentions(the_incident_that_moved_it),
            # As the narration says a verdict - "Judged the action REFUTED" -
            # and not as a service that "did not recover", which is one of
            # three findings a refutation can rest on.
            _the_only_line_mentions("refuted there"),
            _the_only_line_does_not_say("did not recover"),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_what_memory_recalled_says_how_many_and_which_was_nearest() -> None:
    # The line that says memory was consulted at all. A reordering is written only
    # where something moved, and whether anything can move depends on how many
    # candidates the round offered - so on a walk where memory was read and did
    # find something, this is the only account of it. The count is the marked
    # phrase because it is what a reader scanning a timeline can act on; the
    # nearest incident is in the sentence, because it is the record the line after
    # this one may move a candidate on the strength of.
    the_nearest_incident = new_id()
    the_one_behind_it = new_id()
    the_incidents_recalled = [_recalled(the_nearest_incident), _recalled(the_one_behind_it)]

    a_recall = SimilarIncidentsRecalled(
        incident_id=new_id(),
        recalled=the_incidents_recalled
    )

    Scenario() \
        .given(a_recall) \
        .when(lambda: build_narration([a_recall])) \
        .then(all_of(
            _the_only_line_marks(f"{len(the_incidents_recalled)} earlier incidents"),
            _the_only_line_mentions(the_nearest_incident),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_a_recalled_line_names_the_nearest_incident_for_a_destination_to_link() -> None:
    # Carried as the value it is rather than as a link, as the minute an onset
    # names is: a destination with a page per incident leads there, and one
    # without simply reads the sentence.
    the_nearest_incident = new_id()
    some_incident_behind_it = new_id()

    a_recall = SimilarIncidentsRecalled(
        incident_id=new_id(),
        recalled=[_recalled(the_nearest_incident), _recalled(some_incident_behind_it)]
    )

    Scenario() \
        .given(a_recall) \
        .when(lambda: build_narration([a_recall])) \
        .then(_the_only_line_names_the_incident(the_nearest_incident))


@pytest.mark.unit
def test_a_single_recalled_incident_is_not_said_in_the_plural() -> None:
    # One match is the ordinary case - a service has usually had one incident
    # resembling this one rather than several - so the singular is the wording
    # most readers will see, and "1 earlier incidents" is the kind of line that
    # makes a reader distrust the rest of the timeline.
    the_only_incident_like_it = new_id()
    the_incidents_recalled = [_recalled(the_only_incident_like_it)]

    a_recall = SimilarIncidentsRecalled(
        incident_id=new_id(),
        recalled=the_incidents_recalled
    )

    Scenario() \
        .given(a_recall) \
        .when(lambda: build_narration([a_recall])) \
        .then(all_of(
            _the_only_line_marks(f"{len(the_incidents_recalled)} earlier incident"),
            _no_line_mentions("earlier incidents")))


@pytest.mark.unit
def test_what_memory_recalled_says_what_the_nearest_incident_tried_and_what_came_of_it() -> None:
    # An id alone sends a reader off to look the incident up, and what they
    # would find there is an action and whether it helped - here a revert this
    # incident may be about to try again, refuted there. Said in the words the
    # line that filed it used, so the two read as one fact.
    the_nearest_incident = new_id()

    a_recall = SimilarIncidentsRecalled(
        incident_id=new_id(),
        recalled=[_recalled(the_nearest_incident,
                            (REVERT_FEATURE_FLAG, SOME_FLAG, Verdict.REFUTED))]
    )

    Scenario() \
        .given(a_recall) \
        .when(lambda: build_narration([a_recall])) \
        .then(_the_only_line_mentions(
            f"incident {the_nearest_incident}, which tried reverting {SOME_FLAG} "
            "(refuted)"))


@pytest.mark.unit
def test_what_memory_recalled_says_each_action_the_nearest_incident_tried() -> None:
    # Every action, in the order the record holds them, each with what it came
    # to: one refuted and one confirmed are different evidence, and a reader
    # needs both.
    a_recall = SimilarIncidentsRecalled(
        incident_id=new_id(),
        recalled=[_recalled(new_id(),
                            (REVERT_FEATURE_FLAG, SOME_FLAG, Verdict.REFUTED),
                            (RESTART_SERVICE, SOME_SERVICE, Verdict.CONFIRMED))]
    )

    Scenario() \
        .given(a_recall) \
        .when(lambda: build_narration([a_recall])) \
        .then(_the_only_line_mentions(
            f"which tried reverting {SOME_FLAG} (refuted), "
            f"restarting {SOME_SERVICE} (confirmed)"))


@pytest.mark.unit
def test_what_memory_recalled_says_what_only_the_nearest_incident_tried() -> None:
    # The line names the nearest incident alone, so it says what that one
    # tried; another incident's actions beside it would read as the nearest's.
    a_recall = SimilarIncidentsRecalled(
        incident_id=new_id(),
        recalled=[_recalled(new_id(),
                            (REVERT_FEATURE_FLAG, SOME_FLAG, Verdict.REFUTED)),
                  _recalled(new_id(),
                            (RESTART_SERVICE, SOME_SERVICE, Verdict.CONFIRMED))]
    )

    Scenario() \
        .given(a_recall) \
        .when(lambda: build_narration([a_recall])) \
        .then(_no_line_mentions(f"restarting {SOME_SERVICE}"))


@pytest.mark.unit
def test_an_incident_recalled_with_nothing_tried_is_named_alone() -> None:
    # A record is filed only for an incident that tried something, but the
    # line is read back from rows, and one saying "which tried" of nothing
    # would be a sentence with no end.
    the_nearest_incident = new_id()

    a_recall = SimilarIncidentsRecalled(
        incident_id=new_id(),
        recalled=[_recalled(the_nearest_incident)]
    )

    Scenario() \
        .given(a_recall) \
        .when(lambda: build_narration([a_recall])) \
        .then(all_of(
            _the_only_line_mentions(f"the closest match being incident {the_nearest_incident}"),
            _no_line_mentions("which tried")))


@pytest.mark.unit
def test_an_order_memory_changed_names_a_restart_as_a_restart() -> None:
    # Why the event carries a kind at all. Said as its subject alone the line
    # read "moved io-shop down the list" whether io-shop was a service
    # somebody restarted or a flag somebody reverted - and those are not the
    # same evidence about the candidate being moved. Said as a gerund, because
    # the action is the one thing on this line that did not happen here.
    the_service_that_was_moved_down = SOME_SERVICE

    a_reordering = CandidatesReordered(
        incident_id=new_id(),
        action_type=RESTART_SERVICE,
        subject=the_service_that_was_moved_down,
        on_the_strength_of=new_id()
    )

    Scenario() \
        .given(a_reordering) \
        .when(lambda: build_narration([a_reordering])) \
        .then(_the_only_line_marks(f"restarting {the_service_that_was_moved_down}"))


@pytest.mark.unit
def test_what_was_filed_about_this_incident_names_what_was_tried() -> None:
    # The last thing said about an incident, and the only line about a store
    # nobody reads until the next incident. The actions are the marked words
    # because they are the whole content: what a later walk gets from this
    # record is what was done here and how each one turned out.
    a_flag_that_did_not_help = "new-checkout-flow"
    a_service_that_was_restarted = SOME_SERVICE

    a_filing = IncidentRemembered(
        incident_id=new_id(),
        tried=[
            ActionIdentity(action_type=REVERT_FEATURE_FLAG,
                           subject=a_flag_that_did_not_help),
            ActionIdentity(action_type=RESTART_SERVICE,
                           subject=a_service_that_was_restarted)
        ]
    )

    Scenario() \
        .given(a_filing) \
        .when(lambda: build_narration([a_filing])) \
        .then(all_of(
            _the_only_line_marks(
                f"reverting {a_flag_that_did_not_help}, "
                f"restarting {a_service_that_was_restarted}"
            ),
            _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_a_memory_that_could_not_be_written_says_so_and_why() -> None:
    # A store that is down costs the next incident an advantage and costs this
    # one nothing - which is exactly why it has to be said out loud. Silence
    # here is indistinguishable from an incident that had nothing to file, and
    # the two call for different things from whoever reads it.
    why_it_could_not_be_written = "connection refused"

    a_failed_filing = RememberingFailed(
        incident_id=new_id(),
        refusal=why_it_could_not_be_written
    )

    Scenario() \
        .given(a_failed_filing) \
        .when(lambda: build_narration([a_failed_filing])) \
        .then(all_of(_the_only_line_marks(why_it_could_not_be_written),
                     _the_lines_are_credited_to([ARGUS])))


@pytest.mark.unit
def test_a_proposed_fix_is_said_as_the_place_it_can_be_read() -> None:
    # Argus's last act on a bug is to hand the work to somebody, so the line is
    # the address. The URL is the marked word because it is the only part a
    # reader does anything with - everything else on the line explains why they
    # are being sent there.
    a_proposal = _a_fix_attempt(FixOutcome.PROPOSED, pull_request=_a_pull_request())

    Scenario() \
        .given(a_proposal) \
        .when(lambda: build_narration([a_proposal])) \
        .then(all_of(_the_only_line_marks(SOME_PR_URL),
                     _the_only_line_mentions("draft"),
                     _the_lines_are_credited_to([CODE_FIX_AGENT])))


@pytest.mark.unit
def test_a_proposed_fix_names_the_address_it_can_be_read_at() -> None:
    # Said as a value, not as markup: the page makes it a link, Slack makes it
    # a link of its own, and a destination with neither reads the sentence. The
    # line already spells the URL out for that last reader - this is how the
    # other two know that the word they are marking is somewhere to go.
    a_proposal = _a_fix_attempt(FixOutcome.PROPOSED, pull_request=_a_pull_request())

    Scenario() \
        .given(a_proposal) \
        .when(lambda: build_narration([a_proposal])) \
        .then(_the_only_line_names_the_address(SOME_PR_URL))


@pytest.mark.unit
def test_a_fix_that_proposed_nothing_names_no_address() -> None:
    # The marked word on a failed attempt is the refusal, which is prose. A
    # destination that took every marked word for an address would turn "could
    # not reach the repository" into a link to nowhere.
    some_detail = "the repository refused the branch"
    no_address = ""
    a_fix_that_could_not_be_proposed = _a_fix_attempt(FixOutcome.NOT_POSSIBLE,
                                                      detail=some_detail)

    Scenario() \
        .given(a_fix_that_could_not_be_proposed) \
        .when(lambda: build_narration([a_fix_that_could_not_be_proposed])) \
        .then(_the_only_line_names_the_address(no_address))


@pytest.mark.unit
def test_a_model_that_declined_is_not_read_as_a_repository_that_refused() -> None:
    # Two very different afternoons reached the same line. "Could not propose
    # a fix" is what a reader sees when the repository refuses - so a model
    # that simply said no sent somebody hunting for an outage that never
    # happened. Nothing is broken here and no wider budget helps: the same
    # question over the same code is declined again.
    some_detail = "the model declined to write one"
    a_declined_fix = _a_fix_attempt(FixOutcome.DECLINED, detail=some_detail)

    Scenario() \
        .given(a_declined_fix) \
        .when(lambda: build_narration([a_declined_fix])) \
        .then(_the_only_line_mentions("declined"))


@pytest.mark.unit
def test_a_model_that_declined_for_no_reason_given_says_nothing_after_it() -> None:
    # A refusal comes with no words, so the attempt carries no reason - and a
    # line that went on to one anyway would end on a dash with nothing after it.
    no_reason_given = ""
    a_declined_fix = _a_fix_attempt(FixOutcome.DECLINED, detail=no_reason_given)

    Scenario() \
        .given(a_declined_fix) \
        .when(lambda: build_narration([a_declined_fix])) \
        .then(_the_only_line_reads("The model declined to propose a fix"))


@pytest.mark.unit
def test_a_fix_that_stopped_says_which_bound_stopped_it() -> None:
    # It said "ran out of turns" while turns were the only way to run out.
    # There are three now, they are widened in three different places, and a
    # reader told the wrong one widens a budget that was never the problem -
    # an answer too large to write arrives here too, and no number of extra
    # turns makes a file fit.
    ran_out_of_tokens = "tokens"
    a_fix_that_stopped = _a_fix_attempt(
        FixOutcome.NOT_ANSWERED,
        detail=f"the agent read until it ran out of {ran_out_of_tokens}"
    )

    Scenario() \
        .given(a_fix_that_stopped) \
        .when(lambda: build_narration([a_fix_that_stopped])) \
        .then(_the_only_line_mentions(ran_out_of_tokens))


@pytest.mark.unit
def test_a_fix_that_was_not_warranted_reads_as_a_verdict_on_the_code() -> None:
    # The true answer for every incident a flag caused, and a useful one: the
    # code was read and there was nothing in it to change. A line that merely
    # said "no pull request" would describe the absence rather than the finding.
    a_fix_not_warranted = _a_fix_attempt(FixOutcome.NOT_WARRANTED)

    Scenario() \
        .given(a_fix_not_warranted) \
        .when(lambda: build_narration([a_fix_not_warranted])) \
        .then(all_of(_the_only_line_mentions("no code-level fix"),
                     _the_lines_are_credited_to([CODE_FIX_AGENT])))


@pytest.mark.unit
def test_a_fix_that_needs_code_outside_reads_as_written_and_not_kept() -> None:
    # Neither a proposal nor a verdict. The model wrote a fix and said it helps
    # nobody until code outside the repository changes too - so a reader told
    # "no code-level fix" would close the question the fix answers.
    a_fix_not_opened = _a_fix_attempt(FixOutcome.NOT_OPENED)

    Scenario() \
        .given(a_fix_not_opened) \
        .when(lambda: build_narration([a_fix_not_opened])) \
        .then(all_of(_the_only_line_mentions("kept none of it"),
                     _the_lines_are_credited_to([CODE_FIX_AGENT])))


@pytest.mark.unit
def test_a_fix_that_could_not_be_proposed_says_what_stopped_it() -> None:
    # The one outcome somebody can act on before asking again, so the reason is
    # the line rather than a detail behind it. This is the case that cost a
    # session: a repository that refused reached the timeline looking exactly
    # like a model that had read the code and found it clean.
    what_stopped_it = f"could not create branch [{SOME_BRANCH}]: 403 Forbidden"

    a_refusal = _a_fix_attempt(FixOutcome.NOT_POSSIBLE, detail=what_stopped_it)

    Scenario() \
        .given(a_refusal) \
        .when(lambda: build_narration([a_refusal])) \
        .then(all_of(_the_only_line_mentions(what_stopped_it),
                     _the_lines_are_credited_to([CODE_FIX_AGENT])))


@pytest.mark.unit
@pytest.mark.parametrize("outcome", [
    FixOutcome.NOT_WARRANTED, FixOutcome.NOT_OPENED, FixOutcome.DECLINED
])
def test_what_code_fix_said_of_the_code_travels_beside_a_fix_no_pull_request_holds(
        outcome: FixOutcome) -> None:
    # What the model said would have to change somewhere else reached the
    # postmortem alone: the page and the thread said "found no code-level fix"
    # and nothing of where to look instead. Labelled as a reading nothing ran,
    # so it is not taken for a plan of Argus's.
    some_fix = _a_fix_attempt(outcome, explanation=SOME_EXPLANATION)

    Scenario() \
        .given(some_fix) \
        .when(lambda: build_narration([some_fix])) \
        .then(_the_only_lines_aside_says(SOME_EXPLANATION, "nothing ran"))


@pytest.mark.unit
def test_a_proposed_fix_carries_no_aside_as_its_pull_request_holds_the_explanation() -> None:
    some_proposal = _a_fix_attempt(FixOutcome.PROPOSED, pull_request=_a_pull_request(),
                                   explanation=SOME_EXPLANATION)

    Scenario() \
        .given(some_proposal) \
        .when(lambda: build_narration([some_proposal])) \
        .then(_the_only_line_carries_no_aside())


@pytest.mark.unit
def test_a_fix_attempt_that_said_nothing_of_the_code_carries_no_aside() -> None:
    some_detail = "the repository refused the branch"
    a_fix_that_could_not_be_proposed = _a_fix_attempt(FixOutcome.NOT_POSSIBLE,
                                                      detail=some_detail)

    Scenario() \
        .given(a_fix_that_could_not_be_proposed) \
        .when(lambda: build_narration([a_fix_that_could_not_be_proposed])) \
        .then(_the_only_line_carries_no_aside())


@pytest.mark.unit
def test_a_line_said_in_full_leaves_its_aside_out() -> None:
    # Said in full is how the postmortem's model reads the timeline, and the
    # document already carries what Code-Fix said in a finding of its own:
    # said here as well, the same paragraph would reach it twice.
    some_fix = _a_fix_attempt(FixOutcome.NOT_WARRANTED, explanation=SOME_EXPLANATION)

    Scenario() \
        .given(
            some_line := _the_only(build_narration([some_fix]))
        ) \
        .when(
            lambda: said_in_full(some_line)
        ) \
        .then(
            _does_not_say(SOME_EXPLANATION)
        )


@pytest.mark.unit
def test_a_rollback_is_said_as_a_rollback_when_it_is_taken() -> None:
    # Words for the third kind of action. Without them the line rendered as
    # the tag's own identifier - "roll-back-deployment" - which reads as a
    # bug in the page and compiles perfectly.
    an_application_rolled_back = SOME_SERVICE

    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=ROLL_BACK_DEPLOYMENT,
        subject=an_application_rolled_back,
        enabled=None
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(_the_only_line_marks(an_application_rolled_back))


@pytest.mark.unit
def test_an_order_memory_changed_names_a_rollback_as_a_rollback() -> None:
    # The gerund form, for the two lines that talk about an action without it
    # having happened here: what memory demoted, and what was filed.
    the_application_that_was_moved_down = SOME_SERVICE

    a_reordering = CandidatesReordered(
        incident_id=new_id(),
        action_type=ROLL_BACK_DEPLOYMENT,
        subject=the_application_that_was_moved_down,
        on_the_strength_of=new_id()
    )

    Scenario() \
        .given(a_reordering) \
        .when(lambda: build_narration([a_reordering])) \
        .then(_the_only_line_marks(
            f"rolling {the_application_that_was_moved_down} back"
        ))


@pytest.mark.unit
def test_a_restart_of_a_dependency_says_whose_dependency_it_is() -> None:
    # Argus restarted something it was never paged about, and the account has
    # to carry the reason it was allowed to: the service that alerted calls
    # this one. Without the clause the line names a service that appears
    # nowhere else in the incident, and a reader's only way to find out why it
    # was touched is to go and read the register themselves.
    the_service_that_alerted = SOME_SERVICE
    the_dependency_restarted = SOME_DEPENDENCY

    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=RESTART_SERVICE,
        subject=the_dependency_restarted,
        enabled=None,
        a_dependency_of=the_service_that_alerted
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(all_of(
            _the_only_line_marks(the_dependency_restarted),
            _the_only_line_mentions(f"a dependency of {the_service_that_alerted}")))


@pytest.mark.unit
def test_a_restart_of_the_service_that_alerted_says_nothing_about_dependencies() -> None:
    # The ordinary restart, unchanged. Argus has been restarting the service it
    # was paged about since before there was a register, and a clause on every
    # one of those would be a sentence that explains nothing said on the line
    # that needs no explaining.
    the_service_that_alerted = SOME_SERVICE

    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=RESTART_SERVICE,
        subject=the_service_that_alerted,
        enabled=None
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(all_of(
            _the_only_line_marks(the_service_that_alerted),
            _the_only_line_does_not_mention("dependency")))


@pytest.mark.unit
def test_a_scale_out_is_said_as_a_scale_out_when_it_is_taken() -> None:
    # Words for the fourth kind of action. Without them the line rendered as the
    # tag's own identifier - "scale-out" - which reads as a bug in the page and
    # compiles perfectly. Said as adding capacity rather than as a change to a
    # setting: what a reader has to take from the line is that the deployment is
    # now larger than the one anybody declared.
    an_application_scaled_out = SOME_SERVICE

    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=SCALE_OUT,
        subject=an_application_scaled_out,
        enabled=None
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(all_of(
            _the_only_line_marks(an_application_scaled_out),
            _the_only_line_mentions("Scaled out")
        ))


@pytest.mark.unit
def test_an_order_memory_changed_names_a_scale_out_as_a_scale_out() -> None:
    # The gerund form, for the two lines that talk about an action without it
    # having happened here: what memory demoted, and what was filed. A
    # deployment already scaled out on an earlier incident is the one case where
    # this line matters most - the reader is being told why Argus is not
    # reaching for capacity again.
    the_application_that_was_moved_down = SOME_SERVICE

    a_reordering = CandidatesReordered(
        incident_id=new_id(),
        action_type=SCALE_OUT,
        subject=the_application_that_was_moved_down,
        on_the_strength_of=new_id()
    )

    Scenario() \
        .given(a_reordering) \
        .when(lambda: build_narration([a_reordering])) \
        .then(_the_only_line_marks(
            f"scaling {the_application_that_was_moved_down} out"
        ))


@pytest.mark.unit
def test_a_pin_is_said_as_a_floor_raised_and_never_as_a_count_set() -> None:
    # Words for the fifth kind of action, and the first that stops something
    # rather than adding or restoring something. Two actions in this estate now
    # decide how many replicas run, so a line that called them both scaling would
    # leave a reader unable to say which of them owns the number - which is the
    # whole distinction between the mode this answers and the one beside it.
    an_application_held_still = SOME_SERVICE

    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=PIN_AUTOSCALER,
        subject=an_application_held_still,
        enabled=None
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(all_of(
            _the_only_line_marks(an_application_held_still),
            _the_only_line_mentions("Raised the autoscaler floor"),
            _no_line_mentions("Scaled")
        ))


@pytest.mark.unit
def test_an_order_memory_changed_names_a_pin_as_a_floor_raised() -> None:
    # The gerund form, for the two lines that talk about an action without it
    # having happened here. It matters most of all for this kind: a reader told
    # that Argus is not reaching for a pin again has to be able to tell that from
    # Argus not reaching for capacity again, and the two are one word apart.
    the_application_that_was_moved_down = SOME_SERVICE

    a_reordering = CandidatesReordered(
        incident_id=new_id(),
        action_type=PIN_AUTOSCALER,
        subject=the_application_that_was_moved_down,
        on_the_strength_of=new_id()
    )

    Scenario() \
        .given(a_reordering) \
        .when(lambda: build_narration([a_reordering])) \
        .then(_the_only_line_marks(
            f"holding {the_application_that_was_moved_down}'s autoscaler still"
        ))


@pytest.mark.unit
def test_a_discard_is_said_as_copies_thrown_away_and_never_as_data_lost() -> None:
    # Words for the sixth kind, and the first that removes something. The line
    # has to carry the one fact that makes the action unalarming: what went was a
    # copy, and the records it was derived from never moved. A reader told only
    # that Argus deleted something from a store has been told the frightening
    # half of a harmless act.
    a_service_whose_copies_went = SOME_SERVICE

    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=DISCARD_CACHE_ENTRIES,
        subject=a_service_whose_copies_went,
        enabled=None
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(all_of(
            _the_only_line_marks(a_service_whose_copies_went),
            _the_only_line_mentions("Discarded the stale cached figures"),
            _no_line_mentions("Deleted")
        ))


@pytest.mark.unit
def test_an_order_memory_changed_names_a_discard_as_copies_thrown_away() -> None:
    # The gerund form. This kind needs it for a reason the pin's does not: a
    # reader told Argus is not reaching for a discard again has to be able to
    # tell that from Argus not reaching for a restart again, and both are
    # answers to a service whose symptom is nothing moving at all.
    the_service_that_was_moved_down = SOME_SERVICE

    a_reordering = CandidatesReordered(
        incident_id=new_id(),
        action_type=DISCARD_CACHE_ENTRIES,
        subject=the_service_that_was_moved_down,
        on_the_strength_of=new_id()
    )

    Scenario() \
        .given(a_reordering) \
        .when(lambda: build_narration([a_reordering])) \
        .then(_the_only_line_marks(
            f"discarding {the_service_that_was_moved_down}'s stale cached figures"
        ))


@pytest.mark.unit
def test_a_placement_names_each_pods_card_and_marks_the_ones_placed_at_the_onset() -> None:
    # The one record of a replica that moved to another card with nothing
    # deployed, so it is said in full: every pod and the card it ran on. The pods
    # placed at the onset are the ones marked, because a card is a suspect only
    # by being where those pods landed - and a reader scanning the line is
    # looking for which of them did.
    the_card_before_the_onset = SOME_CARD
    the_card_at_the_onset = ANOTHER_CARD

    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(
                _a_pod(SOME_POD, the_card_before_the_onset,
                       SOME_TIME_LONG_BEFORE_THE_ONSET),
                _a_pod(ANOTHER_POD, the_card_before_the_onset,
                       SOME_TIME_LONG_BEFORE_THE_ONSET),
                _a_pod(YET_ANOTHER_POD, the_card_at_the_onset, SOME_ONSET)
            )
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(all_of(
            _the_only_line_says(
                f"{SOME_POD} on {the_card_before_the_onset}",
                f"{ANOTHER_POD} on {the_card_before_the_onset}"
            ),
            _the_only_line_marks(f"{YET_ANOTHER_POD} on {the_card_at_the_onset}"),
            _the_lines_are_credited_to([INVESTIGATOR_AGENT])
        ))


@pytest.mark.unit
def test_a_placement_read_against_the_alarm_marks_its_pods_as_at_the_alarm_not_the_onset(
) -> None:
    # Nothing dated the incident, and the minute is the alarm's own: a pod placed
    # then was placed as the alarm went off, and said as started at the
    # onset it reads as the cause.
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(
                _a_pod(SOME_POD, SOME_CARD, SOME_TIME_LONG_BEFORE_THE_ONSET),
                _a_pod(ANOTHER_POD, ANOTHER_CARD, SOME_ONSET)
            ),
            against_the_alarm=True
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(all_of(
            _the_only_line_says(f"at the alarm: {ANOTHER_POD}"),
            _the_only_line_does_not_say("onset")
        ))


@pytest.mark.unit
def test_a_pod_whose_node_reports_no_card_is_said_to_report_none() -> None:
    # Said as what the platform reported rather than as a card nobody named. A
    # pod with no card is the one thing that stops a pin, and a reader shown
    # a blank where the card goes cannot tell that from a line that lost it.
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(_a_pod(SOME_POD, None, SOME_TIME_LONG_BEFORE_THE_ONSET),)
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(all_of(
            _the_only_line_says(SOME_POD, "no accelerator reported"),
            _the_only_line_does_not_say("None")
        ))


@pytest.mark.unit
def test_a_placement_with_no_pod_placed_at_the_onset_says_nothing_about_the_onset() -> None:
    # The ordinary incident, in which nothing moved. A clause naming an empty
    # set of pods placed at the onset would read as a finding about the onset,
    # and there is none to make.
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(
                _a_pod(SOME_POD, SOME_CARD, SOME_TIME_LONG_BEFORE_THE_ONSET),
            )
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(_the_only_line_does_not_say("onset"))


@pytest.mark.unit
def test_a_placement_on_one_card_since_long_before_the_onset_is_said_in_a_line() -> None:
    # Several pods, every one on the same card and serving long before the
    # onset: listed pod by pod, the line is a paragraph telling nothing apart,
    # and the brief, the dashboard and the channel all carry it. How many, and
    # the card, is the whole of what it tells - that nothing moved.
    the_card = SOME_CARD
    the_pods = (SOME_POD, ANOTHER_POD, YET_ANOTHER_POD)
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=tuple(_a_pod(pod, the_card, SOME_TIME_LONG_BEFORE_THE_ONSET)
                       for pod in the_pods)
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(all_of(
            _the_only_line_says(f"{len(the_pods)} replicas", f"all on {the_card}"),
            _the_only_line_does_not_say(*the_pods)
        ))


@pytest.mark.unit
def test_a_placement_on_one_card_all_started_together_after_the_onset_is_said_in_a_line() -> None:
    # Restarted together well after the onset, every pod was said with the
    # same card and the same moment - three times over, in the timeline, the
    # evidence and the brief, telling nothing apart. How many, the card and
    # when, once. The moment beside "started", not beside "the onset": said
    # "started after the onset at Sep 05 10:13:07", it reads as when the onset
    # was.
    the_card = SOME_CARD
    the_pods = (SOME_POD, ANOTHER_POD, YET_ANOTHER_POD)
    some_time_days_after_the_onset = SOME_ONSET + timedelta(days=6, seconds=7)
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=tuple(_a_pod(pod, the_card, some_time_days_after_the_onset)
                       for pod in the_pods)
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(all_of(
            _the_only_line_says(f"{len(the_pods)} replicas run - all on {the_card}, started "
                                f"at {some_time_days_after_the_onset:{WITH_ITS_DAY_TO_THE_SECOND}}"
                                f", after the onset"),
            _the_only_line_does_not_say(*the_pods)
        ))


@pytest.mark.unit
def test_pods_on_one_card_started_apart_after_the_onset_are_each_said_with_when() -> None:
    # Started apart, each moment is something the line tells, and folded into
    # one the others would be lost.
    some_time_days_after_the_onset = SOME_ONSET + timedelta(days=6, seconds=7)
    some_later_time = some_time_days_after_the_onset + timedelta(seconds=55)
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(_a_pod(SOME_POD, ANOTHER_CARD, some_time_days_after_the_onset),
                  _a_pod(ANOTHER_POD, ANOTHER_CARD, some_later_time))
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(_the_only_line_says(
            f"{SOME_POD} on {ANOTHER_CARD} at "
            f"{some_time_days_after_the_onset:{WITH_ITS_DAY_TO_THE_SECOND}}",
            f"{ANOTHER_POD} on {ANOTHER_CARD} at "
            f"{some_later_time:{WITH_ITS_DAY_TO_THE_SECOND}}"
        ))


@pytest.mark.unit
def test_a_placement_whose_every_pod_started_at_the_onset_marks_them_all() -> None:
    # Nothing served before the incident, so there is nothing to list ahead of
    # the mark - and every pod there is still has to be the marked part.
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(_a_pod(SOME_POD, ANOTHER_CARD, SOME_ONSET),)
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(_the_only_line_marks(f"{SOME_POD} on {ANOTHER_CARD}"))


@pytest.mark.unit
def test_a_pod_placed_long_after_the_onset_is_said_to_have_started_after_it() -> None:
    # Placed six days after the onset, on an incident nothing about the pods
    # explains: "started at the onset" would be false, and would mark it as a
    # suspect it is not.
    some_time_days_after_the_onset = SOME_ONSET + timedelta(days=6)
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(_a_pod(SOME_POD, ANOTHER_CARD, some_time_days_after_the_onset),)
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(all_of(
            _the_only_line_says(f"after the onset: {SOME_POD} on {ANOTHER_CARD}"),
            _the_only_line_does_not_say("at the onset")
        ))


@pytest.mark.unit
def test_a_pod_placed_after_the_onset_is_said_with_when_it_started() -> None:
    # "After the onset" alone reads as any time after it, and a reader took a
    # pod placed a week later for the rollout that began the incident.
    some_time_days_after_the_onset = SOME_ONSET + timedelta(days=6, seconds=7)
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(_a_pod(SOME_POD, ANOTHER_CARD, some_time_days_after_the_onset),)
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(_the_only_line_says(
            f"{SOME_POD} on {ANOTHER_CARD} at "
            f"{some_time_days_after_the_onset:{WITH_ITS_DAY_TO_THE_SECOND}}"
        ))


@pytest.mark.unit
def test_a_pod_placed_after_the_onset_on_the_onset_s_day_is_said_with_its_day() -> None:
    # Hours after the onset, in a line recorded the day after: said against
    # the onset, its time came out bare, and read as a time of the line's day.
    some_time_hours_after_the_onset = SOME_ONSET + timedelta(hours=9, minutes=3, seconds=7)
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(
            onset=SOME_ONSET,
            pods=(_a_pod(SOME_POD, ANOTHER_CARD, some_time_hours_after_the_onset),)
        )
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(_the_only_line_says(
            f"{SOME_POD} on {ANOTHER_CARD} at "
            f"{some_time_hours_after_the_onset:{WITH_ITS_DAY_TO_THE_SECOND}}"
        ))


@pytest.mark.unit
def test_a_placement_of_no_pods_says_the_platform_reported_none() -> None:
    # A tree with no pods in it is an answer, and a different one from a
    # platform that would not answer: said as nothing at all, the line ends on
    # a dash and reads as one that lost its list.
    some_placement = PlacementRecorded(
        incident_id=new_id(),
        placement=RecordedPlacement(onset=SOME_ONSET, pods=())
    )

    Scenario() \
        .given(some_placement) \
        .when(lambda: build_narration([some_placement])) \
        .then(all_of(
            _the_only_line_says("no pods"),
            _the_only_line_does_not_say("onset")
        ))


@pytest.mark.unit
def test_a_pin_to_an_accelerator_names_the_card_it_held_the_pods_to() -> None:
    # The application is marked, as every deployment action marks it, and the
    # card is said: it is the half a reader checks against the placement line
    # above, and the subject alone says only that the pods were held somewhere.
    an_application_held_to_a_card = SOME_SERVICE
    the_card_it_was_held_to = SOME_CARD

    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type=PIN_TO_ACCELERATOR,
        subject=an_application_held_to_a_card,
        accelerator=the_card_it_was_held_to
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(all_of(
            _the_only_line_marks(an_application_held_to_a_card),
            _the_only_line_says(the_card_it_was_held_to)
        ))


@pytest.mark.unit
def test_an_order_memory_changed_names_a_pin_to_an_accelerator_as_pods_held_to_a_card() -> None:
    # The gerund form, and without the card: the identity memory reorders by is
    # the kind and the application, so which card an earlier incident held the
    # pods to is not something this line has to say.
    the_application_that_was_moved_down = SOME_SERVICE

    a_reordering = CandidatesReordered(
        incident_id=new_id(),
        action_type=PIN_TO_ACCELERATOR,
        subject=the_application_that_was_moved_down,
        on_the_strength_of=new_id()
    )

    Scenario() \
        .given(a_reordering) \
        .when(lambda: build_narration([a_reordering])) \
        .then(_the_only_line_marks(
            f"holding {the_application_that_was_moved_down}'s pods to one accelerator card"
        ))


def _no_line_mentions(absent: str) -> Assertion[list[NarrationLine]]:
    """No line says this, which is what a wrong word looks like here.

    The pin and the scale-out both end with a deployment at a size Argus chose,
    so the way this goes wrong is not a missing line but a line borrowing the
    other action's verb - which reads perfectly and says the wrong thing about
    which action owns the replica count.
    """
    def assertion(narration: list[NarrationLine]) -> bool:
        said = [line for line in narration if absent in "".join(line.text)]

        if said:
            raise AssertionError(
                f"Expected no line to say [{absent}], and {len(said)} does: "
                f"{[line.text for line in said]}."
            )

        return True

    return assertion


def _an_alert() -> Alert:
    return Alert(service=SOME_SERVICE, alert_name=SOME_ALERT_NAME)


def _a_bucket(bucket_id: str) -> MetricBucket:
    """One minute of metrics, with figures nothing here reads."""
    return MetricBucket(
        bucket_id=bucket_id,
        error_rate=0.31,
        p50_ms=120,
        p95_ms=240,
        p99_ms=420,
        request_volume=200,
        memory_used_bytes=440 * 1024**2,
        process_start_time_seconds=1_756_000_000.0,
        cpu_used_cores=0.77,
        cpu_limit_cores=3.0
    )


def _a_deploy(revision: str, occurred_at: str) -> ChangeEvent:
    """A deploy of one revision, with a summary nothing here reads."""
    return ChangeEvent(kind=ChangeKind.DEPLOY, occurred_at=occurred_at, reference=revision,
                       summary="dont care")


def _a_pull_request() -> OpenedPullRequest:
    return OpenedPullRequest(number=SOME_PR_NUMBER, url=SOME_PR_URL, branch=SOME_BRANCH)


def _a_fix_attempt(outcome: FixOutcome,
                   detail: str = "dont care what the node said",
                   pull_request: OpenedPullRequest | None = None,
                   explanation: str | None = None) -> FixAttempted:
    return FixAttempted(incident_id=new_id(), outcome=outcome, pull_request=pull_request,
                        detail=detail, explanation=explanation)


def _a_pod(pod: str, accelerator: str | None, started_at: datetime) -> PodPlacement:
    """One pod, on a node nothing here reads."""
    return PodPlacement(
        pod=pod, node="dont-care-node", accelerator=accelerator, started_at=started_at
    )


def _a_hypothesis(summary: str = "dont care",
                  rank: int = THE_LEADING_RANK,
                  evidence: list[str] | None = None,
                  incident_id: str | None = None,
                  from_state: str | None = None,
                  to_state: str | None = None,
                  number: int = 1) -> HypothesisFormed:
    return HypothesisFormed(
        incident_id=incident_id or new_id(),
        hypothesis_id=new_id(),
        summary=summary,
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        subject=SOME_FLAG,
        rank=rank,
        number=number,
        from_state=from_state,
        to_state=to_state,
        evidence=[Evidence(claim=cited, at=None) for cited in evidence or []]
    )


def _the_only(narration: list[NarrationLine]) -> NarrationLine:
    """The single line one event becomes.

    Every event shapes into exactly one line, and an assertion that indexed
    `[0]` inline would be quietly checking that too, in the one place a reader
    is not looking.
    """
    if len(narration) != 1:
        raise AssertionError(f"Expected one line, got {len(narration)}.")

    return narration[0]


def _the_kinds_are(expected: list[str]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        kinds = [line.kind for line in narration]

        if kinds != expected:
            raise AssertionError(f"Expected the lines {expected}, got {kinds}.")

        return True

    return assertion


def _the_only_line_happened_at(expected: datetime) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.at != expected:
            raise AssertionError(f"Expected the line timed [{expected}], got [{line.at}].")

        return True

    return assertion


def _the_only_line_mentions(expected: str) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if expected not in line.text:
            raise AssertionError(f"Expected [{expected}] in [{line.text}].")

        return True

    return assertion


def _the_only_line_carries_the_minutes(expected: list[str]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        carried = [bucket.bucket_id for bucket in _the_only(narration).buckets]

        if carried != expected:
            raise AssertionError(f"Expected the minutes {expected}, got {carried}.")

        return True

    return assertion


def _the_only_line_carries_the_changes(
    expected: list[ChangeEvent]
) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        carried = _the_only(narration).changes

        if carried != expected:
            raise AssertionError(f"Expected the changes {expected}, got {carried}.")

        return True

    return assertion


def _the_only_line_carries_the_flag_changes(
    expected: list[FlagChange]
) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        carried = _the_only(narration).flag_changes

        if carried != expected:
            raise AssertionError(f"Expected the toggles {expected}, got {carried}.")

        return True

    return assertion


def _the_only_line_offers_the_causes(expected: list[str]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        offered = [candidate.summary for candidate in _the_only(narration).candidates]

        if offered != expected:
            raise AssertionError(f"Expected the causes {expected}, got {offered}.")

        return True

    return assertion


def _the_first_line_numbers_the_causes(expected: list[int]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        numbered = [candidate.number for candidate in narration[0].candidates]

        if numbered != expected:
            raise AssertionError(f"Expected the numbers {expected}, got {numbered}.")

        return True

    return assertion


def _the_only_line_cites(expected: list[str]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        cited = [
            finding.text
            for candidate in _the_only(narration).candidates
            for finding in candidate.evidence
        ]

        if cited != expected:
            raise AssertionError(f"Expected the findings {expected}, got {cited}.")

        return True

    return assertion


def _the_only_line_stands_for(expected: int) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.repeated != expected:
            raise AssertionError(
                f"Expected one line standing for {expected} looks, "
                f"it stands for {line.repeated}."
            )

        return True

    return assertion


def _the_lines_are_dated(expected: list[datetime]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        dated = [line.at for line in narration]

        if dated != expected:
            raise AssertionError(f"Expected the lines dated {expected}, got {dated}.")

        return True

    return assertion


def _the_lines_each_stand_for(expected: list[int]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        counted = [line.repeated for line in narration]

        if counted != expected:
            raise AssertionError(f"Expected the counts {expected}, got {counted}.")

        return True

    return assertion


def _the_only_line_names_the_minute(expected: str) -> Assertion[list[NarrationLine]]:
    """The minute a line is about, carried as a value rather than as a link.

    The account's job stops here: a page turns this into an anchor at the
    minute's own row, and a channel with no table reads the sentence alone.
    """
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.names_minute != expected:
            raise AssertionError(
                f"Expected it about [{expected}], it is about [{line.names_minute}]."
            )

        return True

    return assertion


def _the_only_line_moved(was: str, now: str) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if (line.moved_from, line.moved_to) != (was, now):
            raise AssertionError(
                f"Expected a move from [{was}] to [{now}], "
                f"got [{line.moved_from}] to [{line.moved_to}]."
            )

        return True

    return assertion


def _the_only_line_names_the_address(expected: str) -> Assertion[list[NarrationLine]]:
    """Where the line points, carried as the value it is.

    Separate from the marked word on purpose: they are the same string on a
    proposal and different things on every other outcome, and a destination
    linking whatever happens to be marked is the bug this exists to prevent.
    """
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.names_url != expected:
            raise AssertionError(
                f"Expected the line to name [{expected}], got [{line.names_url}]."
            )

        return True

    return assertion


def _the_only_lines_aside_says(*expected: str) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)
        missing = [one for one in expected if one not in line.aside]

        if missing:
            raise AssertionError(
                f"Expected the line's aside to say {missing}, and it said [{line.aside}]."
            )

        return True

    return assertion


def _the_only_line_carries_no_aside() -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.aside:
            raise AssertionError(f"Expected the line to carry no aside, and it carried "
                                 f"[{line.aside}].")

        return True

    return assertion


def _does_not_say(unwanted: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if unwanted in said:
            raise AssertionError(f"Expected no [{unwanted}] in [{said}].")

        return True

    return assertion


def _the_only_line_asks_to_confirm(expected: Reference | None) -> Assertion[list[NarrationLine]]:
    """The message a line asks its writer to confirm, or that it asks nothing.

    Carried as the reference it is rather than as words, because what a
    destination does with it is make a button, and the button has to name the
    one message whose writer may press it.
    """
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.asks_to_confirm != expected:
            raise AssertionError(
                f"Expected the line to ask to confirm [{expected}], "
                f"got [{line.asks_to_confirm}]."
            )

        return True

    return assertion


def _the_only_line_offers_to_end_as(
        expected: IncidentStatus | None) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.offers_to_end_as != expected:
            raise AssertionError(
                f"Expected the line to offer to end the incident as [{expected}], it "
                f"offers [{line.offers_to_end_as}]."
            )

        return True

    return assertion


def _the_only_line_leaves_nothing_to_resolve(expected: bool) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.leaves_nothing_to_resolve != expected:
            raise AssertionError(
                f"Expected the line {'' if expected else 'not '}to leave nothing to "
                f"resolve, it says [{line.leaves_nothing_to_resolve}]."
            )

        return True

    return assertion


def _the_only_line_leaves_nothing_to_withdraw(expected: bool) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.leaves_nothing_to_withdraw != expected:
            raise AssertionError(
                f"Expected the line {'' if expected else 'not '}to leave nothing to "
                f"withdraw, it says [{line.leaves_nothing_to_withdraw}]."
            )

        return True

    return assertion


def _the_only_line_expires_the_offers(expected: bool) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.expires_the_offers != expected:
            raise AssertionError(
                f"Expected the line {'' if expected else 'not '}to expire the "
                f"incident's offers, it says [{line.expires_the_offers}]."
            )

        return True

    return assertion


def _the_only_line_is_outside_the_walk(expected: bool) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.outside_the_walk != expected:
            raise AssertionError(
                f"Expected the line {'' if expected else 'not '}to be written outside "
                f"the walk, it says [{line.outside_the_walk}]."
            )

        return True

    return assertion


def _the_only_line_is_in_markdown(expected: bool) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.emphasis_is_markdown is not expected:
            raise AssertionError(
                f"Expected the marked part in Markdown to be [{expected}], got "
                f"[{line.emphasis_is_markdown}]."
            )

        return True

    return assertion


def _the_only_line_marks(expected: str) -> Assertion[list[NarrationLine]]:
    """The word the page sets apart, and the sentence still reading as one.

    Both together, because the three strings are a split rather than a rewrite:
    a marked word that did not come out of the text would be the page inventing
    emphasis.
    """
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.emphasis != expected:
            raise AssertionError(f"Expected [{expected}] marked, got [{line.emphasis}].")

        rejoined = f"{line.before_emphasis}{line.emphasis}{line.after_emphasis}"

        if rejoined != line.text:
            raise AssertionError(
                f"Expected the three parts to rejoin as [{line.text}], got [{rejoined}]."
            )

        return True

    return assertion


def _the_lines_are_credited_to(expected: list[str]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        credited = [line.who for line in narration]

        if credited != expected:
            raise AssertionError(f"Expected {expected} credited, got {credited}.")

        return True

    return assertion


def _the_only_candidate_moved(was: str, now: str) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        candidate = _the_only(narration).candidates[0]

        if (candidate.moved_from, candidate.moved_to) != (was, now):
            raise AssertionError(
                f"Expected the candidate to have moved [{was}] to [{now}], "
                f"got [{candidate.moved_from}] to [{candidate.moved_to}]."
            )

        return True

    return assertion


def _the_only_line_does_not_mention(unwanted: str) -> Assertion[list[NarrationLine]]:
    """The ordinary restart, and the clause it must not acquire.

    A line saying an action was taken on a dependency is only worth anything if
    the line about the service that alerted does not say it too - said of every
    restart, the clause stops distinguishing anything and becomes noise on the
    one account a responder reads under pressure.
    """
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if unwanted in line.text:
            raise AssertionError(f"Expected no [{unwanted}] in [{line.text}].")

        return True

    return assertion


def _the_only_line_names_the_incident(expected: str) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.names_incident != expected:
            raise AssertionError(
                f"Expected the line to name incident [{expected}], got "
                f"[{line.names_incident}]."
            )

        return True

    return assertion


def _the_only_line_names_the_candidate(
        expected: CandidateNamed | None) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.names_candidate != expected:
            raise AssertionError(
                f"Expected the line to name the candidate [{expected}], got "
                f"[{line.names_candidate}].")

        return True

    return assertion


def _the_only_line_reads(expected: str) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)

        if line.text != expected:
            raise AssertionError(f"Expected the line to read [{expected}], got [{line.text}].")

        return True

    return assertion


def _the_only_line_says(*wanted: str) -> Assertion[list[NarrationLine]]:
    """The one line mentions each of these, wherever it puts them.

    Substrings rather than a whole sentence, because what is held is which facts
    a reader is given and not the prose around them: a test pinning the wording
    fails on every rewording and passes a sentence that quietly dropped a fact.
    """
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)
        missing = [one for one in wanted if one not in line.text]

        if missing:
            raise AssertionError(
                f"Expected the line to say {missing}, and it said [{line.text}]."
            )

        return True

    return assertion


def _the_only_line_does_not_say(*unwanted: str) -> Assertion[list[NarrationLine]]:
    """The pair to the assertion above, for the lines that are as much about what
    they leave out.

    Its own helper rather than a flag on that one, because the two are different
    claims and a case usually makes both: what the line has to tell a reader, and
    what it must not tell them that is false.
    """
    def assertion(narration: list[NarrationLine]) -> bool:
        line = _the_only(narration)
        present = [one for one in unwanted if one in line.text]

        if present:
            raise AssertionError(
                f"Expected the line not to say {present}, and it said "
                f"[{line.text}]."
            )

        return True

    return assertion


def _recalled(incident_id: str,
              *tried: tuple[ActionType, str, Verdict]) -> RecalledIncident:
    """An incident memory found, with each action it tried and what that came to."""
    return RecalledIncident(incident_id=incident_id, tried=[
        WhatWasTried(identity=ActionIdentity(action_type=action_type, subject=subject),
                     verdict=verdict)
        for action_type, subject, verdict in tried])
