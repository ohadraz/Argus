"""What the record rules out, said as the record says it.

A write-up asked what else the record ruled out restates a read in its own
words, and restating is where it goes wrong: "flag changes before it were not
read" over a row that read them for the whole day. So where a rule-out rests
on Argus's own reads alone, code says it - the class of change the read found
none of, then the rows' own lines - and the model's words go. Where it rests
on anything else, they stay: on evidence of another kind, on a person's word,
on a read that found every kind, on an attempt judged refuted (whose subject
may still be the cause). And where it rests on rows that rule nothing out and
names nothing that could be ruled out, it is no rule-out, and is dropped.
Within one step, the rule-outs code says that share a read or a class are said
as one, so no read and no class is said twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_postmortem.prompting import SubmittedPostmortem, SubmittedRuledOut, SubmittedStep
from agent_postmortem.ruling import is_said_by_code, with_what_the_record_rules_out
from argus_core.models import RetrievalChannel, TimelineEntry
from argus_testkit import Assertion, Scenario, the_answer_was

# The kinds of line the timeline carries, mirroring the events' own `kind`s.
RETRIEVAL_REQUESTED = "retrieval-requested"
CHANGES_RETRIEVED = "changes-retrieved"
FLAG_CHANGES_RETRIEVED = "flag-changes-retrieved"
ROLLOUT_READ = "rollout-read"
PLACEMENT_RECORDED = "placement-recorded"
METRICS_RETRIEVED = "metrics-retrieved"
ONSET_DETECTED = "onset-detected"
ACTION_TAKEN = "action-taken"
VERDICT_REACHED = "verdict-reached"

INVESTIGATOR = "Investigator Agent"
MITIGATION = "Mitigation Agent"
ARGUS = "Argus"
A_PERSON = "A person"

# What each read rules out, mirroring narration's NO_* leads.
NO_CHANGE_OF_ANY_KIND = "A deploy, release or flag change on the service"
NO_DEPLOY = "A deploy or release on the service"
NO_FLAG_CHANGE_BY_ANYONE_ELSE = "A flag change by anyone but Argus"
NO_ROLLOUT_UNDER_WAY = "A rollout still under way"
NO_RESTART = "A restart of the replicas"

# Each row's words, as the narration said them - opening capitalised, as a
# line does - and as a rule-out goes on with them, lowered.
ASKED_FOR_CHANGES = ("Asked for production change events - deploys and releases, and flag changes "
                     "from the flag provider's history, the 1 hour before 11:34")
READ_NO_CHANGES = "Read back 0 production changes"
READ_NO_FLAG_CHANGES = ("Read the flag provider's history - 0 flag changes by anyone but Argus, "
                        "the day before 11:34")
READ_THE_METRICS = "Read back 30 minutes of metrics"
PLACED_THE_ONSET = "Placed the start of the incident at 11:02"
RECORDED_THE_REPLICAS = ("Recorded where the 2 replicas run - all on Tesla-T4, started at 11:20, "
                         "after the onset")
READ_ONLY_FLAG_CHANGES = "Read back 3 production changes"
READ_EVERY_KIND = "Read back 4 production changes"
READ_THE_ROLLOUT = "Read how far the deployment had rolled out - all 2 replicas run revision a1"
REVERTED_THE_FLAG = "Reverted flag monthly-spend-feature"
JUDGED_IT_REFUTED = "Judged the action REFUTED"
WROTE_IN_THE_THREAD = "Wrote in the incident's thread: no deploy went out today"

SOME_MOMENT = datetime(2026, 11, 10, 11, 34, 33, tzinfo=UTC)

# The labels each row goes by.
AN_EARLIER_REQUEST, AN_EARLIER_READ = "T8", "T9"
THE_FLAGS_READ, THE_PLACEMENT = "T17", "T7"
THE_METRICS_READ, THE_ONSET = "T5", "T6"
A_LATER_REQUEST, A_READ_OF_ONLY_FLAGS, THE_ROLLOUT_READ = "T27", "T28", "T32"
A_READ_OF_EVERY_KIND = "T33"
THE_REVERT, THE_VERDICT = "T19", "T21"
A_PERSON_S_LINE = "XW1"
A_LINE_OF_AN_OLDER_DOCUMENT = "T30"
AN_UNANSWERED_REQUEST, A_REQUEST_ANSWERED_LATER, ITS_READ = "T40", "T41", "T42"
A_READ_NOTHING_ASKED_FOR = "T50"
SOME_CHANGE, SOME_DEPLOYMENT_READ, SOME_LOG_GROUP = "P1", "D1", "G1"
# cfou's and fralf's changes reads, by the brief's own labels for those rows.
CFOUS_FIRST_ASK, CFOUS_FIRST_READ = "T8", "T9"
CFOUS_SECOND_ASK, CFOUS_SECOND_READ = "T13", "T14"
FRALFS_FIRST_ASK, FRALFS_FIRST_READ, FRALFS_FIRST_ROLLOUT_READ = "T8", "T9", "T10"
FRALFS_SECOND_ASK, FRALFS_SECOND_READ, FRALFS_SECOND_ROLLOUT_READ = "T29", "T30", "T31"


def _a_row(who: str, text: str, kind: str | None = None, rules_out: str = "",
           channel: RetrievalChannel | None = None,
           outside_the_walk: bool = False) -> TimelineEntry:
    """A row of the timeline, dated by where `_in_order` puts it."""
    return TimelineEntry(at=SOME_MOMENT, who=who, text=text, kind=kind, rules_out=rules_out,
                         channel=channel, outside_the_walk=outside_the_walk)


def _in_order(rows: dict[str, TimelineEntry]) -> dict[str, TimelineEntry]:
    """The rows by label, in the order they are given - as the walk recorded
    them - each a second after the one before."""
    return {label: row.model_copy(update={"at": SOME_MOMENT + timedelta(seconds=position)})
            for position, (label, row) in enumerate(rows.items())}


def _asked_for_changes(asked: str = ASKED_FOR_CHANGES) -> TimelineEntry:
    return _a_row(INVESTIGATOR, asked, RETRIEVAL_REQUESTED, channel=RetrievalChannel.CHANGES)


THE_EARLIER_CHANGES_READ = _a_row(INVESTIGATOR, READ_NO_CHANGES, CHANGES_RETRIEVED,
                                  NO_CHANGE_OF_ANY_KIND)

SOME_ROWS = _in_order({
    AN_EARLIER_REQUEST: _asked_for_changes(),
    AN_EARLIER_READ: THE_EARLIER_CHANGES_READ,
    THE_FLAGS_READ: _a_row(ARGUS, READ_NO_FLAG_CHANGES, FLAG_CHANGES_RETRIEVED,
                           NO_FLAG_CHANGE_BY_ANYONE_ELSE),
    THE_METRICS_READ: _a_row(INVESTIGATOR, READ_THE_METRICS, METRICS_RETRIEVED),
    THE_ONSET: _a_row(INVESTIGATOR, PLACED_THE_ONSET, ONSET_DETECTED),
    THE_PLACEMENT: _a_row(INVESTIGATOR, RECORDED_THE_REPLICAS, PLACEMENT_RECORDED, NO_RESTART),
    A_LATER_REQUEST: _asked_for_changes(),
    A_READ_OF_ONLY_FLAGS: _a_row(INVESTIGATOR, READ_ONLY_FLAG_CHANGES, CHANGES_RETRIEVED,
                                 NO_DEPLOY),
    THE_ROLLOUT_READ: _a_row(INVESTIGATOR, READ_THE_ROLLOUT, ROLLOUT_READ, NO_ROLLOUT_UNDER_WAY),
    A_READ_OF_EVERY_KIND: _a_row(INVESTIGATOR, READ_EVERY_KIND, CHANGES_RETRIEVED),
    THE_REVERT: _a_row(MITIGATION, REVERTED_THE_FLAG, ACTION_TAKEN),
    THE_VERDICT: _a_row(MITIGATION, JUDGED_IT_REFUTED, VERDICT_REACHED),
    A_PERSON_S_LINE: _a_row(A_PERSON, WROTE_IN_THE_THREAD, outside_the_walk=True),
    # A changes read like the earlier one, as a document written before lines
    # said their kind and what they ruled out holds it.
    A_LINE_OF_AN_OLDER_DOCUMENT: THE_EARLIER_CHANGES_READ.model_copy(
        update={"kind": None, "rules_out": ""}),
    AN_UNANSWERED_REQUEST: _asked_for_changes(),
    A_REQUEST_ANSWERED_LATER: _asked_for_changes(),
    ITS_READ: _a_row(INVESTIGATOR, READ_NO_CHANGES, CHANGES_RETRIEVED, NO_CHANGE_OF_ANY_KIND),
    A_READ_NOTHING_ASKED_FOR: _a_row(INVESTIGATOR, READ_NO_CHANGES, CHANGES_RETRIEVED,
                                     NO_CHANGE_OF_ANY_KIND)
})
# A changes read with no request before it since the last read: the request
# that came before answered by an earlier one.
ROWS_WITH_A_READ_NOTHING_ASKED_FOR = {
    AN_EARLIER_REQUEST: SOME_ROWS[AN_EARLIER_REQUEST],
    AN_EARLIER_READ: SOME_ROWS[AN_EARLIER_READ],
    A_READ_NOTHING_ASKED_FOR: SOME_ROWS[A_READ_NOTHING_ASKED_FOR]
}
SOME_OUTSIDE = frozenset({SOME_CHANGE, SOME_DEPLOYMENT_READ, SOME_LOG_GROUP})

DONT_CARE_STEP = "dont care which step"
# A step's own cites: required, and never read by ruling.
DONT_CARE_STEP_CITES = [AN_EARLIER_READ]
# The model's words for a rule-out: kept, where code cannot say it, and
# replaced where it can.
SOME_WORDS = "An earlier deploy: the record shows none"
DONT_CARE_WORDS = "dont care what the model wrote for it"

# cfou's two requests, each over its own window, as its both replay recorded
# them.
CFOUS_FIRST_ASKED = ("Asked for production change events - deploys and releases, and flag "
                     "changes from the flag provider's history, the 1 day 54 minutes 23 seconds "
                     "before Nov 10 19:07:23")
CFOUS_SECOND_ASKED = ("Asked for production change events - deploys and releases, and flag "
                      "changes from the flag provider's history, the 5 days 20 hours before "
                      "Nov 09 18:13")
CFOUS_ROWS = _in_order({
    CFOUS_FIRST_ASK: _asked_for_changes(CFOUS_FIRST_ASKED),
    CFOUS_FIRST_READ: _a_row(INVESTIGATOR, READ_NO_CHANGES, CHANGES_RETRIEVED,
                             NO_CHANGE_OF_ANY_KIND),
    CFOUS_SECOND_ASK: _asked_for_changes(CFOUS_SECOND_ASKED),
    CFOUS_SECOND_READ: _a_row(INVESTIGATOR, READ_NO_CHANGES, CHANGES_RETRIEVED,
                              NO_CHANGE_OF_ANY_KIND)
})


def _lowered(line: str) -> str:
    return line[:1].lower() + line[1:]


def _the(who: str) -> str:
    return f"the {who}"


@pytest.mark.unit
def test_a_rule_out_resting_on_the_changes_read_is_said_as_its_rows_say_it() -> None:
    # Cited without the request it answered, the read is said with it: the
    # request says what was asked for and over when, the read what came back.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[AN_EARLIER_READ])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_CHANGE_OF_ANY_KIND}: {_the(INVESTIGATOR)} "
                     f"{_lowered(ASKED_FOR_CHANGES)}; {_the(INVESTIGATOR)} "
                     f"{_lowered(READ_NO_CHANGES)}.",
                cites=[AN_EARLIER_REQUEST, AN_EARLIER_READ], by_the_record=True)])
        )


@pytest.mark.unit
def test_a_rule_out_resting_on_the_flag_provider_s_read_is_said_as_its_row_says_it() -> None:
    # The cfo-A1 shape: "flag changes before it were not read", citing the row
    # that read them for the whole day before.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(
                what="A flag change: none in the window, and flag changes before it were not "
                     "read", cites=[THE_FLAGS_READ])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_FLAG_CHANGE_BY_ANYONE_ELSE}: {ARGUS} {_lowered(READ_NO_FLAG_CHANGES)}.",
                cites=[THE_FLAGS_READ], by_the_record=True)])
        )


@pytest.mark.unit
def test_a_rule_out_resting_on_where_the_replicas_ran_is_said_as_its_row_says_it() -> None:
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[THE_PLACEMENT])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_RESTART}: {_the(INVESTIGATOR)} {_lowered(RECORDED_THE_REPLICAS)}.",
                cites=[THE_PLACEMENT], by_the_record=True)])
        )


@pytest.mark.unit
def test_a_read_that_found_only_flag_changes_rules_out_a_deploy_beside_its_own_request() -> None:
    # rh-11's shape: a second changes read, after an earlier pair, found only
    # the flag - so it rules out a deploy, and never the flag that was the
    # cause - and a rollout read beside it. Paired with its own request, not
    # the earlier one the earlier read answered.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(
                what="A deploy: the change events read held no deploy, only changes to this "
                     "flag, and the rollout read showed every replica on one revision.",
                cites=[A_LATER_REQUEST, A_READ_OF_ONLY_FLAGS, THE_ROLLOUT_READ])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_DEPLOY}: {_the(INVESTIGATOR)} {_lowered(ASKED_FOR_CHANGES)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(READ_ONLY_FLAG_CHANGES)}. "
                     f"{NO_ROLLOUT_UNDER_WAY}: {_the(INVESTIGATOR)} "
                     f"{_lowered(READ_THE_ROLLOUT)}.",
                cites=[A_LATER_REQUEST, A_READ_OF_ONLY_FLAGS, THE_ROLLOUT_READ],
                by_the_record=True)])
        )


@pytest.mark.unit
def test_a_request_no_read_answered_is_not_said_with_a_later_request_s_read() -> None:
    # A request that went unanswered, then another that was: the read answered
    # the second, and the first rules nothing out.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=SOME_WORDS, cites=[AN_UNANSWERED_REQUEST])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([a_rule_out])
        )


@pytest.mark.unit
def test_a_changes_read_no_request_came_before_is_said_alone() -> None:
    # The request before it was answered by an earlier read: nothing asked
    # for this one that the record shows.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS,
                                            cites=[A_READ_NOTHING_ASKED_FOR])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), ROWS_WITH_A_READ_NOTHING_ASKED_FOR,
                SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_CHANGE_OF_ANY_KIND}: {_the(INVESTIGATOR)} {_lowered(READ_NO_CHANGES)}.",
                cites=[A_READ_NOTHING_ASKED_FOR], by_the_record=True)])
        )


@pytest.mark.unit
def test_a_rule_out_resting_on_two_reads_says_each_with_what_it_rules_out() -> None:
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(
                what=DONT_CARE_WORDS, cites=[THE_FLAGS_READ, AN_EARLIER_REQUEST, AN_EARLIER_READ])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_CHANGE_OF_ANY_KIND}: {_the(INVESTIGATOR)} "
                     f"{_lowered(ASKED_FOR_CHANGES)}; {_the(INVESTIGATOR)} "
                     f"{_lowered(READ_NO_CHANGES)}. {NO_FLAG_CHANGE_BY_ANYONE_ELSE}: {ARGUS} "
                     f"{_lowered(READ_NO_FLAG_CHANGES)}.",
                cites=[AN_EARLIER_REQUEST, AN_EARLIER_READ, THE_FLAGS_READ], by_the_record=True)])
        )


@pytest.mark.unit
def test_a_rule_out_resting_on_two_reads_of_one_class_says_the_class_once() -> None:
    # cfou's rows, as its both replay recorded them: two changes reads that
    # found nothing, each answering a request over its own window. The class
    # said before each read reads as two things ruled out; said once, both
    # reads follow it whole, in the order they ran - each request with its
    # answer, though the answers word alike.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=list(CFOUS_ROWS))
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), CFOUS_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_CHANGE_OF_ANY_KIND}: {_the(INVESTIGATOR)} "
                     f"{_lowered(CFOUS_FIRST_ASKED)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(READ_NO_CHANGES)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(CFOUS_SECOND_ASKED)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(READ_NO_CHANGES)}.",
                cites=list(CFOUS_ROWS), by_the_record=True)])
        )


@pytest.mark.unit
def test_a_read_another_of_one_class_words_alike_is_said_once() -> None:
    # fralf's rows, as its grep replay recorded them: two rounds, each a
    # changes read and a rollout read. Each class is said once, the two
    # classes interleaving as the reads did; the two rollout reads say the
    # same words, and twice they say nothing the first did not. The changes
    # reads differ - their windows and their counts - so both stay. Every read
    # stays cited.
    first_ask = ("Asked for production change events - deploys and releases, and flag changes "
                 "from the flag provider's history, the 1 day 1 minute before Nov 10 18:00")
    first_read = "Read back 1 production change"
    second_ask = ("Asked for production change events - deploys and releases, and flag changes "
                  "from the flag provider's history, the 1 day 6 hours 59 minutes before "
                  "Nov 10 18:16")
    second_read = "Read back 2 production changes"
    the_rollout_read = ("Read how far the deployment had rolled out - all 3 replicas run one "
                        "revision, which the history does not name")
    fralfs_rows = _in_order({
        FRALFS_FIRST_ASK: _asked_for_changes(first_ask),
        FRALFS_FIRST_READ: _a_row(INVESTIGATOR, first_read, CHANGES_RETRIEVED, NO_DEPLOY),
        FRALFS_FIRST_ROLLOUT_READ: _a_row(INVESTIGATOR, the_rollout_read, ROLLOUT_READ,
                                          NO_ROLLOUT_UNDER_WAY),
        FRALFS_SECOND_ASK: _asked_for_changes(second_ask),
        FRALFS_SECOND_READ: _a_row(INVESTIGATOR, second_read, CHANGES_RETRIEVED, NO_DEPLOY),
        FRALFS_SECOND_ROLLOUT_READ: _a_row(INVESTIGATOR, the_rollout_read, ROLLOUT_READ,
                                           NO_ROLLOUT_UNDER_WAY)
    })

    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=list(fralfs_rows))
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), fralfs_rows, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_DEPLOY}: {_the(INVESTIGATOR)} {_lowered(first_ask)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(first_read)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(second_ask)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(second_read)}. "
                     f"{NO_ROLLOUT_UNDER_WAY}: {_the(INVESTIGATOR)} "
                     f"{_lowered(the_rollout_read)}.",
                cites=list(fralfs_rows), by_the_record=True)])
        )


@pytest.mark.unit
def test_two_rule_outs_code_says_that_share_a_read_are_said_as_one() -> None:
    # udf grep's shape, widened: the model ruled out a change of any kind on
    # the changes read beside the flag provider's, and again beside where the
    # replicas ran. Said each alone, the changes read is said twice. Said as
    # one, in the place the first stood, every read once and every read
    # cited. The model's own rule-outs keep their words and their places -
    # one before it citing the same changes read among others, which sharing
    # a read does not pull into the merge, and one between the two it merges.
    Scenario() \
        .given(
            a_rule_out_in_the_model_s_words := SubmittedRuledOut(
                what=SOME_WORDS, cites=[AN_EARLIER_READ, THE_REVERT]),
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS,
                                            cites=[AN_EARLIER_READ, THE_FLAGS_READ]),
            another_rule_out_in_the_model_s_words := SubmittedRuledOut(
                what=SOME_WORDS, cites=[THE_REVERT]),
            another_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS,
                                                  cites=[AN_EARLIER_READ, THE_PLACEMENT])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out_in_the_model_s_words, a_rule_out,
                                       another_rule_out_in_the_model_s_words,
                                       another_rule_out]),
                SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([
                a_rule_out_in_the_model_s_words,
                SubmittedRuledOut(
                    what=f"{NO_CHANGE_OF_ANY_KIND}: {_the(INVESTIGATOR)} "
                         f"{_lowered(ASKED_FOR_CHANGES)}; {_the(INVESTIGATOR)} "
                         f"{_lowered(READ_NO_CHANGES)}. {NO_FLAG_CHANGE_BY_ANYONE_ELSE}: {ARGUS} "
                         f"{_lowered(READ_NO_FLAG_CHANGES)}. {NO_RESTART}: {_the(INVESTIGATOR)} "
                         f"{_lowered(RECORDED_THE_REPLICAS)}.",
                    cites=[AN_EARLIER_REQUEST, AN_EARLIER_READ, THE_FLAGS_READ, THE_PLACEMENT],
                    by_the_record=True),
                another_rule_out_in_the_model_s_words])
        )


@pytest.mark.unit
def test_rule_outs_code_says_are_merged_through_one_that_shares_with_each() -> None:
    # The first and the second share nothing; the third shares a read with
    # each. Merged only with its own neighbour, the third would still say a
    # read the other says - so all three are one, in the first's place.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[AN_EARLIER_READ]),
            another_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[THE_PLACEMENT]),
            a_rule_out_sharing_with_both := SubmittedRuledOut(
                what=DONT_CARE_WORDS, cites=[AN_EARLIER_READ, THE_PLACEMENT])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out, another_rule_out,
                                       a_rule_out_sharing_with_both]),
                SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_CHANGE_OF_ANY_KIND}: {_the(INVESTIGATOR)} "
                     f"{_lowered(ASKED_FOR_CHANGES)}; {_the(INVESTIGATOR)} "
                     f"{_lowered(READ_NO_CHANGES)}. {NO_RESTART}: {_the(INVESTIGATOR)} "
                     f"{_lowered(RECORDED_THE_REPLICAS)}.",
                cites=[AN_EARLIER_REQUEST, AN_EARLIER_READ, THE_PLACEMENT],
                by_the_record=True)])
        )


@pytest.mark.unit
def test_two_rule_outs_code_says_of_one_class_over_different_reads_are_said_as_one() -> None:
    # cfou's two changes reads, each cited by a rule-out of its own: said each
    # alone, the class heads both, and reads as two things ruled out.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[CFOUS_FIRST_READ]),
            another_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS,
                                                  cites=[CFOUS_SECOND_READ])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out, another_rule_out]), CFOUS_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([SubmittedRuledOut(
                what=f"{NO_CHANGE_OF_ANY_KIND}: {_the(INVESTIGATOR)} "
                     f"{_lowered(CFOUS_FIRST_ASKED)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(READ_NO_CHANGES)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(CFOUS_SECOND_ASKED)}; "
                     f"{_the(INVESTIGATOR)} {_lowered(READ_NO_CHANGES)}.",
                cites=list(CFOUS_ROWS), by_the_record=True)])
        )


@pytest.mark.unit
def test_two_rule_outs_code_says_that_share_nothing_stay_two() -> None:
    # Two things ruled out on two reads of two classes: the model gave them
    # apart, and nothing is said twice by keeping them so.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[AN_EARLIER_READ]),
            another_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[THE_PLACEMENT])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out, another_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([
                SubmittedRuledOut(
                    what=f"{NO_CHANGE_OF_ANY_KIND}: {_the(INVESTIGATOR)} "
                         f"{_lowered(ASKED_FOR_CHANGES)}; {_the(INVESTIGATOR)} "
                         f"{_lowered(READ_NO_CHANGES)}.",
                    cites=[AN_EARLIER_REQUEST, AN_EARLIER_READ], by_the_record=True),
                SubmittedRuledOut(
                    what=f"{NO_RESTART}: {_the(INVESTIGATOR)} {_lowered(RECORDED_THE_REPLICAS)}.",
                    cites=[THE_PLACEMENT], by_the_record=True)])
        )


@pytest.mark.unit
@pytest.mark.parametrize("cites", [
    [SOME_CHANGE],
    [AN_EARLIER_READ, SOME_DEPLOYMENT_READ],
    [AN_EARLIER_READ, THE_METRICS_READ],
    [A_READ_OF_EVERY_KIND],
    [THE_REVERT, THE_VERDICT],
    [A_PERSON_S_LINE],
    [A_LINE_OF_AN_OLDER_DOCUMENT]
], ids=["evidence-of-another-kind", "a-read-beside-evidence-of-another-kind",
        "a-read-beside-a-row-that-rules-nothing-out", "a-read-that-found-every-kind",
        "an-attempt-judged-refuted", "a-person-s-word", "a-line-of-an-older-document"])
def test_a_rule_out_resting_on_anything_but_reads_that_rule_out_keeps_the_model_s_words(
        cites: list[str]) -> None:
    # A refuted attempt is about the attempt, not its subject: rh's revert was
    # refuted, and its flag was the cause. A person's word is no read Argus can
    # restate. And a line written before lines said what they ruled out says
    # nothing code can go on.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=SOME_WORDS, cites=cites)
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([a_rule_out])
        )


@pytest.mark.unit
@pytest.mark.parametrize("naming", [f"deploy {SOME_CHANGE}", f"{{{SOME_CHANGE}.1}}"],
                         ids=["by-its-label", "by-its-figure"])
def test_a_rule_out_on_rows_that_rule_nothing_out_naming_evidence_outside_is_kept(
        naming: str) -> None:
    # The metrics read as healthy after an earlier deploy: a rule-out of that
    # deploy, resting on the metrics, which is the model's to say.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(
                what=f"An earlier {naming}: the metrics read as healthy after it",
                cites=[THE_METRICS_READ, THE_ONSET])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([a_rule_out])
        )


@pytest.mark.unit
@pytest.mark.parametrize("words", ["Nothing was ruled out beyond the onset",
                                   "Nothing before {A5} was ruled out"],
                         ids=["naming-nothing", "naming-only-the-alert"])
def test_a_rule_out_on_rows_that_rule_nothing_out_naming_nothing_outside_is_dropped(
        words: str) -> None:
    # A write-up said "nothing was ruled out", under Ruled out, citing the
    # metrics read and the onset. The alert is what every rule-out is weighed
    # against, not something one rules out.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=words, cites=[THE_METRICS_READ, THE_ONSET])
        ) \
        .when(
            lambda: with_what_the_record_rules_out(
                _an_answer_ruling_out([a_rule_out]), SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            _ruled_out_as([])
        )


@pytest.mark.unit
def test_a_rule_out_resting_on_argus_s_read_is_said_by_code() -> None:
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[AN_EARLIER_READ])
        ) \
        .when(
            lambda: is_said_by_code(a_rule_out, SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            the_answer_was(True)
        )


@pytest.mark.unit
def test_a_rule_out_code_drops_is_said_by_code() -> None:
    # Dropped, none of its words reach a reader either.
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[THE_METRICS_READ])
        ) \
        .when(
            lambda: is_said_by_code(a_rule_out, SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            the_answer_was(True)
        )


@pytest.mark.unit
def test_a_rule_out_resting_on_an_action_is_the_model_s_own() -> None:
    Scenario() \
        .given(
            a_rule_out := SubmittedRuledOut(what=DONT_CARE_WORDS, cites=[THE_REVERT])
        ) \
        .when(
            lambda: is_said_by_code(a_rule_out, SOME_ROWS, SOME_OUTSIDE)
        ) \
        .then(
            the_answer_was(False)
        )


def _an_answer_ruling_out(rule_outs: list[SubmittedRuledOut]) -> SubmittedPostmortem:
    """An answer of one step, ruling out these, in this order."""
    return SubmittedPostmortem(causal_chain=[
        SubmittedStep(step=DONT_CARE_STEP, cites=DONT_CARE_STEP_CITES, ruled_out=rule_outs)])


def _ruled_out_as(expected: list[SubmittedRuledOut]) -> Assertion[SubmittedPostmortem]:
    def assertion(answer: SubmittedPostmortem) -> bool:
        ruled_out = answer.causal_chain[0].ruled_out if answer.causal_chain else None

        if ruled_out != expected:
            raise AssertionError(f"Expected the step to rule out {expected}, got {ruled_out}.")

        return True

    return assertion
