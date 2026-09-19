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

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from argus_core import new_id
from argus_core.events import (
    ActionRefused,
    ActionTaken,
    AgentInvoked,
    AlertAcknowledged,
    CandidateSelected,
    CandidatesReordered,
    ChangesRetrieved,
    ChangeUndone,
    CommunicationFailed,
    FixAttempted,
    FlagChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    IncidentRemembered,
    MetricsRetrieved,
    MitigationResumed,
    OnsetDetected,
    PostmortemWritten,
    RecoveryChecked,
    RememberingFailed,
    RetrievalRequested,
    StatusChanged,
    VerdictReached,
)
from argus_core.models import (
    Actor,
    Alert,
    ChangeEvent,
    ChangeKind,
    Evidence,
    FailureMode,
    FixOutcome,
    FlagChange,
    IncidentStatus,
    MetricBucket,
    OpenedPullRequest,
    Refusal,
    RetrievalChannel,
    Undone,
    Verdict,
)
from argus_narration.narrating import NarrationLine, build_narration
from argus_testkit import Assertion, Scenario, all_of

_OPENED_AT = datetime(2026, 8, 30, 10, 15, tzinfo=UTC)

SOME_MINUTE = "2026-08-30T10:14:00Z"
AN_EARLIER_MINUTE = "2026-08-30T10:13:00Z"
SOME_FLAG = "some-ramped-flag"


@pytest.mark.unit
def test_the_narration_keeps_the_order_the_events_were_published_in() -> None:
    # The account is a sequence, and its order is the order things happened in.
    # A view that re-sorted it would be telling a different story from the one
    # that was recorded.
    some_incident = new_id()

    three_things_that_happened: list[IncidentEvent] = [
        AlertAcknowledged(incident_id=some_incident, alert=_an_alert()),
        OnsetDetected(incident_id=some_incident, onset=SOME_MINUTE),
        StatusChanged(
            incident_id=some_incident, to_status=IncidentStatus.MITIGATING
        )
    ]

    Scenario() \
        .given(three_things_that_happened) \
        .when(lambda: build_narration(three_things_that_happened)) \
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
                     _the_only_line_mentions("1 minute"),
                     _the_only_line_mentions(SOME_MINUTE[11:16])))


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
def test_a_changes_retrieval_carries_what_changed_on_the_service() -> None:
    # What changed is what a cause actually is, so it travels on the line that
    # read it rather than being summarised away.
    some_deploy = ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=SOME_MINUTE,
        reference="abc1234",
        summary="checkout: swap the account page renderer"
    )
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
    some_toggle = FlagChange(
        flag=SOME_FLAG, enabled=True, occurred_at=SOME_MINUTE, actor="a-human"
    )
    some_read = FlagChangesRetrieved(incident_id=new_id(), changes=[some_toggle])

    Scenario() \
        .given(some_read) \
        .when(lambda: build_narration([some_read])) \
        .then(_the_only_line_carries_the_flag_changes([some_toggle]))


@pytest.mark.unit
def test_a_candidate_is_the_hypothesis_that_was_recorded() -> None:
    # Not restated and not re-derived: the narration and the walk have to be
    # the same hypothesis seen twice, rather than two accounts to reconcile.
    some_cause = "legacy-checkout-fallback was enabled"
    some_finding = _a_hypothesis(summary=some_cause, rank=1)

    Scenario() \
        .given(some_finding) \
        .when(lambda: build_narration([some_finding])) \
        .then(_the_only_line_offers_the_causes([some_cause]))


@pytest.mark.unit
def test_a_candidate_shows_the_move_it_blamed_the_way_the_flag_table_does() -> None:
    # One spelling for a flag's position across the whole page, so a change
    # reads as the same kind of thing whether it appears in the flag table or
    # under a candidate. The states arrive as the model wrote them - the page
    # is what decides how they are said.
    some_candidate_blaming_a_toggle = _a_hypothesis(
        summary="the flag was switched on", rank=1, from_state="off", to_state="on"
    )

    Scenario() \
        .given(some_candidate_blaming_a_toggle) \
        .when(lambda: build_narration([some_candidate_blaming_a_toggle])) \
        .then(_the_only_candidate_moved(was="OFF", now="ON"))


@pytest.mark.unit
def test_the_candidates_formed_together_are_one_line() -> None:
    # An investigation forms its explanations in one breath, and a story that
    # spent a line on each would bury what it did next under a list. They are
    # one finding with a ranking inside it.
    some_incident = new_id()

    two_candidates_then_something_else: list[IncidentEvent] = [
        _a_hypothesis(summary="the flag", rank=1, incident_id=some_incident),
        _a_hypothesis(summary="the deploy", rank=2, incident_id=some_incident),
        OnsetDetected(incident_id=some_incident, onset=SOME_MINUTE)
    ]

    Scenario() \
        .given(two_candidates_then_something_else) \
        .when(lambda: build_narration(two_candidates_then_something_else)) \
        .then(all_of(_the_kinds_are(["hypothesis-formed", "onset-detected"]),
                     _the_first_line_ranks_the_causes([1, 2])))


@pytest.mark.unit
def test_candidates_formed_in_two_rounds_are_two_lines() -> None:
    # Consecutive only. Two candidates with something in between were formed in
    # two different rounds of the walk - the second after the first was tried
    # and refuted - and folding those together would say the investigation had
    # known both at once.
    some_incident = new_id()

    a_candidate_a_refutation_and_another: list[IncidentEvent] = [
        _a_hypothesis(summary="the flag", rank=1, incident_id=some_incident),
        VerdictReached(
            incident_id=some_incident, hypothesis_id=new_id(), outcome=Verdict.REFUTED
        ),
        _a_hypothesis(summary="the deploy", rank=1, incident_id=some_incident)
    ]

    Scenario() \
        .given(a_candidate_a_refutation_and_another) \
        .when(lambda: build_narration(a_candidate_a_refutation_and_another)) \
        .then(_the_kinds_are(
            ["hypothesis-formed", "verdict-reached", "hypothesis-formed"]
        ))


@pytest.mark.unit
def test_a_candidate_shows_what_it_was_formed_from() -> None:
    # The findings are what make a claim checkable. Without them the page asks
    # an audience to take Argus's word for the whole investigation.
    what_it_rests_on = "monthly-spend-feature began evaluating ON at 10:05"
    some_finding = _a_hypothesis(
        summary="dont care", rank=1, evidence=[what_it_rests_on]
    )

    Scenario() \
        .given(some_finding) \
        .when(lambda: build_narration([some_finding])) \
        .then(_the_only_line_cites([what_it_rests_on]))


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
            it_looked_and_found_the_same_thing := [
                RecoveryChecked(
                    incident_id=some_incident, minute=SOME_MINUTE, recovered=False
                )
                for _ in range(how_many_times_it_looked)
            ]
        ) \
        .when(lambda: build_narration(it_looked_and_found_the_same_thing)) \
        .then(_the_only_line_stands_for(how_many_times_it_looked))


@pytest.mark.unit
def test_a_look_that_found_something_different_is_a_line_of_its_own() -> None:
    # The moment the whole wait was for. Folded into the count above it, the
    # page would report that Argus looked twice and never that the service came
    # back.
    some_incident = new_id()

    Scenario() \
        .given(
            it_looked_twice_and_the_answer_changed := [
                RecoveryChecked(
                    incident_id=some_incident, minute=SOME_MINUTE, recovered=False
                ),
                RecoveryChecked(
                    incident_id=some_incident, minute=SOME_MINUTE, recovered=True
                )
            ]
        ) \
        .when(lambda: build_narration(it_looked_twice_and_the_answer_changed)) \
        .then(_the_lines_each_stand_for([1, 1]))


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
def test_an_action_line_marks_the_flag_and_shows_the_move() -> None:
    # The action names one flag, and the move is shown the way the flag table
    # shows one, so a change reads as a change wherever it appears. Where that
    # flag's row is on a page is the page's business, not the account's.
    some_action = ActionTaken(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        action_type="revert-feature-flag",
        subject=SOME_FLAG,
        enabled=False
    )

    Scenario() \
        .given(some_action) \
        .when(lambda: build_narration([some_action])) \
        .then(all_of(
            _the_only_line_moved("ON", "OFF"),
            _the_only_line_marks(SOME_FLAG)))


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
def test_a_refusal_marks_why_the_action_was_not_taken() -> None:
    # The autonomy boundary holding, said as the one thing a reader can act on.
    # Which candidate went untested is on the candidate's own row; what a person
    # scanning the account needs is which of the two refusals this was - an
    # investigation with nothing reversible to offer, or something to do that
    # could not be undone. Marked for the reason a refused message marks its
    # refusal: the reason is the actionable half.
    some_refusal = ActionRefused(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        refusal=Refusal.NOT_REVERSIBLE
    )

    Scenario() \
        .given(some_refusal) \
        .when(lambda: build_narration([some_refusal])) \
        .then(all_of(
            _the_only_line_marks("cannot be undone"),
            _the_lines_are_credited_to(["Argus"])))


@pytest.mark.unit
def test_moving_to_the_next_candidate_marks_the_explanation_now_under_test() -> None:
    # The ranked list was published once, and the walk skips any candidate it
    # cannot act on - so which explanation an attempt belongs to is not
    # derivable from that list. The summary is marked because it is what the
    # next few lines are about, and a reader who missed it reads an action on
    # nothing in particular.
    some_summary = "the checkout fallback flag was switched off"
    some_move = CandidateSelected(
        incident_id=new_id(),
        hypothesis_id=new_id(),
        summary=some_summary,
        confidence=0.72
    )

    Scenario() \
        .given(some_move) \
        .when(lambda: build_narration([some_move])) \
        .then(all_of(
            _the_only_line_marks(some_summary),
            _the_lines_are_credited_to(["Argus"])))


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
            _the_lines_are_credited_to(["Argus"])))


@pytest.mark.unit
def test_a_change_put_back_marks_the_flag_it_was_about() -> None:
    # One line per change rather than one per withdrawal: an incident that
    # moved three flags and restored two of them is not a withdrawal that
    # worked. The flag is marked the way an action marks it, because the
    # restore and the change it reverses are the same subject a page apart.
    some_restore = ChangeUndone(
        incident_id=new_id(),
        flag=SOME_FLAG,
        outcome=Undone.RESTORED,
        detail="put back the way Argus found it"
    )

    Scenario() \
        .given(some_restore) \
        .when(lambda: build_narration([some_restore])) \
        .then(all_of(
            _the_only_line_marks(SOME_FLAG),
            _the_lines_are_credited_to(["Argus"])))


@pytest.mark.unit
def test_a_flag_somebody_else_touched_is_said_to_have_been_left_alone() -> None:
    # The distinction the outcome exists for. "Nothing was written" means two
    # things here, and only one of them is Argus declining to overwrite
    # somebody else's change - the other is a flag nobody could read. A
    # withdrawal reported as complete when a flag was left as found would
    # promise a world Argus did not restore.
    some_untouched = ChangeUndone(
        incident_id=new_id(),
        flag=SOME_FLAG,
        outcome=Undone.LEFT_AS_FOUND,
        detail="somebody else has changed it since Argus did"
    )

    Scenario() \
        .given(some_untouched) \
        .when(lambda: build_narration([some_untouched])) \
        .then(_the_only_line_mentions("left as found"))


@pytest.mark.unit
def test_the_orchestrator_narrates_as_argus_and_an_agent_as_itself() -> None:
    # From outside, "the orchestrator called in the Investigator" is one system
    # talking about its own internals. What happened is that Argus did - and a
    # story where every sentence has the same silent subject reads as one
    # program doing everything, which is the opposite of what this system is.
    some_incident = new_id()

    argus_calling_in_an_agent_that_then_acts: list[IncidentEvent] = [
        AgentInvoked(incident_id=some_incident, agent=Actor.INVESTIGATOR),
        OnsetDetected(incident_id=some_incident, onset=SOME_MINUTE)
    ]

    Scenario() \
        .given(argus_calling_in_an_agent_that_then_acts) \
        .when(lambda: build_narration(argus_calling_in_an_agent_that_then_acts)) \
        .then(_the_lines_are_credited_to(["Argus", "Investigator Agent"]))


@pytest.mark.unit
def test_a_line_that_never_reached_a_channel_says_which_one_and_why() -> None:
    # The page's line about the page's own rival. Every other sentence here was
    # read in Slack too; this is the one saying which sentence was not - and
    # the refusal is set apart because it is the actionable half, a renamed
    # channel and a revoked token being fixed by different people.
    some_refusal = "channel_not_found"
    a_channel_that_is_not_there = "#war-room"

    what_slack_would_not_take = CommunicationFailed(
        incident_id=new_id(),
        channel=a_channel_that_is_not_there,
        refusal=some_refusal,
        about_kind="verdict-reached"
    )

    Scenario() \
        .given(what_slack_would_not_take) \
        .when(lambda: build_narration([what_slack_would_not_take])) \
        .then(all_of(_the_only_line_mentions(a_channel_that_is_not_there),
                     _the_only_line_marks(some_refusal),
                     _the_lines_are_credited_to(["Communicator Agent"])))


@pytest.mark.unit
def test_a_postmortem_line_carries_what_a_reader_stops_at() -> None:
    # The write-up in the few lines somebody reads first: what caused it, what
    # it says, what it cost and how long people spent. The cause is the marked
    # word - it is what a reader scanning a channel of endings is looking for -
    # and the money is to the penny, because a figure rounded to the pound in
    # one place and not in another reads as two different figures.
    the_cause = "monthly-spend-feature divided by a month with no purchases"
    the_summary = "Account pages failed for a third of shoppers."

    the_write_up = PostmortemWritten(
        incident_id=new_id(),
        root_cause=the_cause,
        executive_summary=the_summary,
        customer_loss_estimate=Decimal("1240.5"),
        estimate_currency="USD",
        engineer_minutes=34
    )

    Scenario() \
        .given(the_write_up) \
        .when(lambda: build_narration([the_write_up])) \
        .then(all_of(_the_only_line_marks(the_cause),
                     _the_only_line_mentions(the_summary),
                     _the_only_line_mentions("USD 1240.50"),
                     _the_only_line_mentions("34 engineer minutes"),
                     _the_lines_are_credited_to(["Postmortem Agent"])))


@pytest.mark.unit
def test_an_order_memory_changed_says_what_moved_and_what_moved_it() -> None:
    # A walk that tried its second-best candidate first, with nothing saying
    # why, is a walk a human reading the incident back cannot account for. The
    # subject is the marked word because it is what moved; the past incident is
    # in the sentence, because it is the reason rather than the subject.
    the_flag_that_was_moved_down = "new-checkout-flow"
    the_incident_that_moved_it = "3f2b1a09-0000-4000-8000-00000000000a"

    what_memory_did = CandidatesReordered(
        incident_id=new_id(),
        subject=the_flag_that_was_moved_down,
        on_the_strength_of=the_incident_that_moved_it
    )

    Scenario() \
        .given(what_memory_did) \
        .when(lambda: build_narration([what_memory_did])) \
        .then(all_of(_the_only_line_marks(the_flag_that_was_moved_down),
                     _the_only_line_mentions(the_incident_that_moved_it),
                     _the_lines_are_credited_to(["Argus"])))


@pytest.mark.unit
def test_what_was_filed_about_this_incident_names_what_was_tried() -> None:
    # The last thing said about an incident, and the only line about a store
    # nobody reads until the next incident. The subjects are the marked words
    # because they are the whole content: what a later walk gets from this
    # record is which things were changed and how each turned out.
    a_flag_that_did_not_help = "new-checkout-flow"
    another_flag_that_did_not_help = "payments-fallback"

    what_was_filed = IncidentRemembered(
        incident_id=new_id(),
        subjects=[a_flag_that_did_not_help, another_flag_that_did_not_help]
    )

    Scenario() \
        .given(what_was_filed) \
        .when(lambda: build_narration([what_was_filed])) \
        .then(all_of(_the_only_line_mentions(a_flag_that_did_not_help),
                     _the_only_line_mentions(another_flag_that_did_not_help),
                     _the_lines_are_credited_to(["Argus"])))


@pytest.mark.unit
def test_a_memory_that_could_not_be_written_says_so_and_why() -> None:
    # A store that is down costs the next incident an advantage and costs this
    # one nothing - which is exactly why it has to be said out loud. Silence
    # here is indistinguishable from an incident that had nothing to file, and
    # the two call for different things from whoever reads it.
    why_it_could_not_be_written = "connection refused"

    what_was_not_filed = RememberingFailed(
        incident_id=new_id(),
        refusal=why_it_could_not_be_written
    )

    Scenario() \
        .given(what_was_not_filed) \
        .when(lambda: build_narration([what_was_not_filed])) \
        .then(all_of(_the_only_line_marks(why_it_could_not_be_written),
                     _the_lines_are_credited_to(["Argus"])))


@pytest.mark.unit
def test_a_proposed_fix_is_said_as_the_place_it_can_be_read() -> None:
    # Argus's last act on a bug is to hand the work to somebody, so the line is
    # the address. The URL is the marked word because it is the only part a
    # reader does anything with - everything else on the line explains why they
    # are being sent there.
    where_it_can_be_read = "https://example.invalid/pull/7"

    a_proposal = FixAttempted(
        incident_id=new_id(),
        outcome=FixOutcome.PROPOSED,
        pull_request=OpenedPullRequest(
            number=7, url=where_it_can_be_read, branch="argus/fix-abc"
        ),
        detail="dont care what the node said"
    )

    Scenario() \
        .given(a_proposal) \
        .when(lambda: build_narration([a_proposal])) \
        .then(all_of(_the_only_line_marks(where_it_can_be_read),
                     _the_only_line_mentions("draft"),
                     _the_lines_are_credited_to(["Code-Fix Agent"])))


@pytest.mark.unit
def test_a_proposed_fix_names_the_address_it_can_be_read_at() -> None:
    # Said as a value, not as markup: the page makes it a link, Slack makes it
    # a link of its own, and a destination with neither reads the sentence. The
    # line already spells the URL out for that last reader - this is how the
    # other two know that the word they are marking is somewhere to go.
    where_it_can_be_read = "https://example.invalid/pull/7"

    a_proposal = FixAttempted(
        incident_id=new_id(),
        outcome=FixOutcome.PROPOSED,
        pull_request=OpenedPullRequest(
            number=7, url=where_it_can_be_read, branch="argus/fix-abc"
        ),
        detail="dont care what the node said"
    )

    Scenario() \
        .given(a_proposal) \
        .when(lambda: build_narration([a_proposal])) \
        .then(_the_only_line_names_the_address(where_it_can_be_read))


@pytest.mark.unit
def test_a_fix_that_proposed_nothing_names_no_address() -> None:
    # The marked word on a failed attempt is the refusal, which is prose. A
    # destination that took every marked word for an address would turn "could
    # not reach the repository" into a link to nowhere.
    could_not = FixAttempted(
        incident_id=new_id(),
        outcome=FixOutcome.NOT_POSSIBLE,
        pull_request=None,
        detail="the repository refused the branch"
    )

    Scenario() \
        .given(could_not) \
        .when(lambda: build_narration([could_not])) \
        .then(_the_only_line_names_the_address(""))


@pytest.mark.unit
def test_a_fix_that_was_not_warranted_reads_as_a_verdict_on_the_code() -> None:
    # The true answer for every incident a flag caused, and a useful one: the
    # code was read and there was nothing in it to change. A line that merely
    # said "no pull request" would describe the absence rather than the finding.
    nothing_to_change = FixAttempted(
        incident_id=new_id(),
        outcome=FixOutcome.NOT_WARRANTED,
        pull_request=None,
        detail="dont care what the node said"
    )

    Scenario() \
        .given(nothing_to_change) \
        .when(lambda: build_narration([nothing_to_change])) \
        .then(all_of(_the_only_line_mentions("no code-level fix"),
                     _the_lines_are_credited_to(["Code-Fix Agent"])))


@pytest.mark.unit
def test_a_fix_that_could_not_be_proposed_says_what_stopped_it() -> None:
    # The one outcome somebody can act on before asking again, so the reason is
    # the line rather than a detail behind it. This is the case that cost a
    # session: a repository that refused reached the timeline looking exactly
    # like a model that had read the code and found it clean.
    what_stopped_it = "could not create branch [argus/fix-abc]: 403 Forbidden"

    a_refusal = FixAttempted(
        incident_id=new_id(),
        outcome=FixOutcome.NOT_POSSIBLE,
        pull_request=None,
        detail=what_stopped_it
    )

    Scenario() \
        .given(a_refusal) \
        .when(lambda: build_narration([a_refusal])) \
        .then(all_of(_the_only_line_mentions(what_stopped_it),
                     _the_lines_are_credited_to(["Code-Fix Agent"])))


def _an_alert() -> Alert:
    return Alert(service="io-shop", alert_name="HighErrorRate")


def _a_bucket(bucket_id: str) -> MetricBucket:
    """One minute of metrics, with figures nothing here reads."""
    return MetricBucket(
        bucket_id=bucket_id,
        error_rate=0.31,
        p50_ms=120,
        p95_ms=240,
        request_volume=200,
        memory_used_bytes=440 * 1024**2,
        process_start_time_seconds=1_756_000_000.0
    )


def _a_hypothesis(summary: str,
                  rank: int,
                  evidence: list[str] | None = None,
                  incident_id: str | None = None,
                  from_state: str | None = None,
                  to_state: str | None = None) -> HypothesisFormed:
    return HypothesisFormed(
        incident_id=incident_id or new_id(),
        hypothesis_id=new_id(),
        summary=summary,
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        subject=SOME_FLAG,
        rank=rank,
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


def _the_first_line_ranks_the_causes(expected: list[int]) -> Assertion[list[NarrationLine]]:
    def assertion(narration: list[NarrationLine]) -> bool:
        ranked = [candidate.rank for candidate in narration[0].candidates]

        if ranked != expected:
            raise AssertionError(f"Expected the ranks {expected}, got {ranked}.")

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
