"""The executive summary, written by code.

Asked to write it, write-ups left out how long the incident ran, told the reader
what the brief told the model, and said a draft fix "corrects" what nothing ran.
Everything in it but the cause is a fact the record holds - when it broke and
for how long, how bad it got, what customers lost, what Argus did and what it
left to a person - so it is said here, in the words the rest of the document
says it in, every figure as the page writes it (`figures`). The model gives
only what code cannot: the cause in plain words, and what is still at risk.

The order is the one a reader asks in: when and for how long, how bad, why,
what was done, and what is left.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from argus_core.models import ResolutionStep, whether_it_can_be_put_back

from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.figures import (
    ACTED_FIGURE,
    ARGUS_STOPPED_FIGURE,
    BACK_TO_NORMAL_FIGURE,
    BEGAN_FIGURE,
    CUSTOMER_LOSS_FIGURE,
    DURATION_FIGURE,
    ERRORS_AT_WORST_FIGURE,
    ERRORS_BEFORE_FIGURE,
    ERRORS_WHILE_BROKEN_FIGURE,
    LOG_READING_ENDED_FIGURE,
    LOGS_REACH_UNTIL_FIGURE,
    SERIES_AT_WORST_FIGURE,
    SERIES_BEFORE_FIGURE,
    UNOBSERVED_FROM_FIGURE,
    figures_of,
    the_day_said_off_the_page,
    with_every_day_said,
)
from agent_postmortem.measuring import Measurements
from agent_postmortem.sections import (
    CANDIDATE_PREFIX,
    SYNC_GOES_BACK_ON,
    UNTIL_SYNC_IS_BACK_ON,
    causes_of,
    inside_a_sentence,
    resolution_of,
)

type _Written = Callable[[str], str]

# A rank as a sentence says it, as far as an investigation ranks causes.
_RANKS: Final = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                 "eighth", "ninth", "tenth")

# A candidate's label as the summary writes it after the candidate's rank.
_A_CANDIDATES_LABEL: Final = re.compile(rf" \({CANDIDATE_PREFIX}\d+\)")


def the_executive_summary(evidence: IncidentEvidence,
                          measured: Measurements,
                          cause: str | None,
                          still_at_risk: str | None) -> str:
    """The summary in one paragraph: the record's facts around the model's two
    sentences, either left out where the model gave none.

    Every instant with its day where Argus stopped on another day than the one
    the incident began: the paragraph is posted where no head dates the
    incident, and there a bare time reads as the day it is read."""
    figures = figures_of(evidence, measured)
    if (day := the_day_said_off_the_page(evidence, measured)) is not None:
        figures = with_every_day_said(figures, day)

    def written(name: str) -> str:
        return figures[name].written

    def written_if_any(name: str) -> str | None:
        return figures[name].written if name in figures else None

    return " ".join([
        *_when_and_for_how_long(measured,
                                bool(evidence.log_lines) or evidence.logs_read_until is not None,
                                written, written_if_any),
        *_how_bad(measured, written),
        _what_customers_lost(measured, written),
        *([cause] if cause else []),
        *_what_argus_did(evidence, measured, written),
        *_what_it_left_to_a_person(evidence),
        *([still_at_risk] if still_at_risk else [])
    ])


def said_off_the_page(summary: str) -> str:
    """The summary as said where the document's rows are not: without the
    label after each candidate's rank, which leads to its row on the page and
    to nothing anywhere else. The rank before it still says which it was."""
    return _A_CANDIDATES_LABEL.sub("", summary)


def _when_and_for_how_long(measured: Measurements,
                           read: bool,
                           written: _Written,
                           written_if_any: Callable[[str], str | None]) -> list[str]:
    """When it broke and for how long, on the four stretches the brief tells
    apart: back to normal, ended by a person's report, never seen back, and
    unseen because the metrics stopped - this last with how far the service's
    own logs reach into it and where their reading ended, said apart, since
    where the lines stop is as often where the reading did.

    An end a person reported is said as their report, never as back to normal:
    that is what the metrics showing it means everywhere else, and the metrics
    showed nothing of this end.

    With no onset measured, said so, and the time counted from the alert
    rather than from when it broke: the alert is when the rule fired.

    A stretch never seen back ends at the incident's ending, said as the
    instant it was still not back by rather than as when Argus stopped
    working on it: a walk ending in a recommendation or a mitigation goes on
    to Code-Fix after it.
    """
    onset = measured.onset_at is not None
    said = [] if onset else [f"No onset was measured; the alert came at {written(BEGAN_FIGURE)}."]

    if measured.unobserved_from is not None:
        return [*said,
                f"No metrics were collected from {written(UNOBSERVED_FROM_FIGURE)} on, and "
                f"they had not resumed by {written(ARGUS_STOPPED_FIGURE)}, "
                f"{written(DURATION_FIGURE)} later.",
                _what_the_logs_show(read, written_if_any)]

    later = "later" if onset else "after the alert"

    if measured.reported_by is not None:
        return [*said,
                *([f"The service broke at {written(BEGAN_FIGURE)}."] if onset else []),
                f"{measured.reported_by} reported the incident resolved at "
                f"{written(BACK_TO_NORMAL_FIGURE)}, {written(DURATION_FIGURE)} {later}."]

    broke = f"The service broke at {written(BEGAN_FIGURE)} and was" if onset else "The service was"

    if measured.back_to_normal_at is None:
        return [*said,
                f"{broke} not back to normal by {written(ARGUS_STOPPED_FIGURE)}, "
                f"at least {written(DURATION_FIGURE)} {later}."]

    return [*said,
            f"{broke} back to normal at {written(BACK_TO_NORMAL_FIGURE)}, "
            f"{written(DURATION_FIGURE)} {later}."]


def _what_the_logs_show(read: bool,
                        written_if_any: Callable[[str], str | None]) -> str:
    """How far the service's own logs reach into the stretch the metrics did
    not cover, and where their reading ended - said apart, since where the
    lines stop is as often where the reading did. And said where they show
    nothing: a summary silent on the logs reads the same as one whose logs
    nobody looked at. A read that came back empty is a read: the service gone
    quiet in its logs too is not nobody having looked.

    Once where the two are the same instant as written: said twice, one
    instant reads as two facts."""
    if not read:
        return "No logs were read."

    reach = written_if_any(LOGS_REACH_UNTIL_FIGURE)
    ended = written_if_any(LOG_READING_ENDED_FIGURE)
    if reach is None:
        logs, they = "No log line read reaches into that stretch", "the logs"
    else:
        logs, they = f"The service's own logs reach into that stretch until {reach}", "they"

    if ended is None:
        return f"{logs}."

    if ended == reach:
        return f"{logs}, as far as they were read."

    return f"{logs}, and {they} were read up to {ended}."


def _how_bad(measured: Measurements, written: _Written) -> list[str]:
    """Failed requests where they rose beyond what the service reaches alone,
    and the series its alert watches where that got worse - each on its own,
    since the series is harm whatever the failed requests did: a fault in what
    the service answers fails no request, and a latency incident with a small
    rise in failures is not summed up by them.

    Except where the series is the error rate itself: then it is the failed
    requests already said, and only how bad its worst minute got is new."""
    said = []

    rates = measured.error_rates
    rose = rates is not None and rates.a_rise_was_measured
    if rose:
        said.append(f"{written(ERRORS_WHILE_BROKEN_FIGURE)} of requests failed while it was "
                    f"broken, against {written(ERRORS_BEFORE_FIGURE)} before it began.")

    levels = measured.rule_series
    if levels is not None and levels.got_worse and rose and measured.rule_series_is_the_error_rate:
        said.append(f"At its worst, {written(ERRORS_AT_WORST_FIGURE)} failed.")
    elif levels is not None and levels.got_worse:
        said.append(f"What its alert watches went from {written(SERIES_BEFORE_FIGURE)} before "
                    f"it began to {written(SERIES_AT_WORST_FIGURE)} at its worst.")

    return said


def _what_customers_lost(measured: Measurements, written: _Written) -> str:
    """The loss in the brief's words - how far the shop's takings fell short
    beyond how much those hours vary, a floor so far where the service was not
    seen back - or why none was estimated, by its own reason. A loss of
    nothing as the brief says it too: "took no less" reads as at least as
    much, where the shop may have taken less within the variation."""
    if measured.loss is None:
        why = ("no onset was measured to count it from" if measured.onset_at is None
               else "the shop's takings could not be read")
        return f"No loss was estimated: {why}."

    unended = measured.back_to_normal_at is None
    fell_short = (f"{'So far, the' if unended else 'The'} shop's takings fell short of the "
                  f"same hours on earlier weeks by")

    if not measured.loss:
        return f"{fell_short} no more than those hours vary on their own, if at all."

    return (f"{fell_short} {'at least ' if unended else ''}{written(CUSTOMER_LOSS_FIGURE)}, "
            f"beyond how much those hours vary on their own.")


def _what_argus_did(evidence: IncidentEvidence,
                    measured: Measurements,
                    written: _Written) -> list[str]:
    """Each action with what it came to, in the resolution's words - and where
    the service was back before the action credited with it, that it was, so
    the action is not read as what brought it back."""
    taken = [_an_action_taken(step)
             for step in resolution_of(evidence) if step.label is not None]
    said = [f"What Argus did: {'; '.join(taken)}."] if taken else []

    credited = evidence.credited_action
    if measured.back_before_the_action and credited is not None:
        said.append(f"The service was back to normal at {written(BACK_TO_NORMAL_FIGURE)}, "
                    f"before Argus {inside_a_sentence(credited.action)} at "
                    f"{written(ACTED_FIGURE)} - so not because of it.")

    return said


def _an_action_taken(step: ResolutionStep) -> str:
    """An action and what it came to, with whether it can be put back only
    where it can: one with no way back comes to "nothing to put back", and the
    same words beside it said it twice in one clause."""
    way_back = (f" ({whether_it_can_be_put_back(step.has_a_way_back)})"
                if step.has_a_way_back else "")
    return f"{inside_a_sentence(step.action)}{way_back} - {step.outcome}"


def _what_it_left_to_a_person(evidence: IncidentEvidence) -> list[str]:
    """That Argus handed the incident to a person, where it ran out of moves;
    each cause Argus held back from testing, with why in its own words - not
    its row's "never tried: ...", which would say it twice - the draft fix,
    automatic sync an action left off, and the action recommended and not
    taken. Never as having fixed anything: nothing ran the fix, and nothing
    took the recommendation.

    Sync left off with when it goes back on and what sooner does: it decides
    whether merging the draft does anything, and turning it on too soon is the
    one move that puts the fault back. Once for each application, after the
    fix, as the action items take it.

    A cause by its rank, not its summary: that is the investigator's own
    sentences, and set inside this one they run on into the reason. Its rank
    as its label counts it - candidates blaming one move are one row, and the
    label still counts each - and its label after it, which leads to its row
    on the page and to nothing where the summary is said on its own."""
    held_back = [f"Argus did not test the candidate it ranked "
                 f"{_ranked(int(cause.label.removeprefix(CANDIDATE_PREFIX)))} ({cause.label}): "
                 f"{cause.decided.result.rstrip('.')}."
                 for cause in causes_of(evidence.candidates)
                 if not cause.decided.tested and cause.decided.result]
    pull_request = evidence.pull_request
    recommended = evidence.recommended_action
    left_off = dict.fromkeys(action.paused_sync_of for action in evidence.actions
                             if action.paused_sync_of is not None)

    return [*(["Argus handed the incident to a person."] if evidence.escalated else []),
            *held_back,
            *([f"Argus opened a draft fix, {pull_request.name}, for a person to review and "
               f"merge.{_what_merging_it_alone_does(evidence)}"]
              if pull_request is not None else []),
            *(f"Argus left automatic sync of {application} off, to be turned back on "
              f"{SYNC_GOES_BACK_ON}: {UNTIL_SYNC_IS_BACK_ON}."
              for application in left_off),
            *([f"Argus recommends this and did not take it: "
               f"{inside_a_sentence(recommended).rstrip('.')}."]
              if recommended else [])]


def _what_merging_it_alone_does(evidence: IncidentEvidence) -> str:
    """That the draft fix changes what runs only once a deploy carries it,
    where the branch it was written against does not contain the revision that
    ran - or nothing, where it does or nobody established it.

    Said by the document rather than asked of the model: told it in the brief,
    write-ups said it in fifteen of fifteen and then in two of five, the rest
    dropping it, and with it that merging alone changes nothing that runs.
    """
    if evidence.fix_holds_what_ran is not False or evidence.fix_branch_read is None:
        return ""

    return (f" It was written against {evidence.fix_branch_read}, which does not contain "
            f"the revision that ran: merged, it changes what runs only once a deploy "
            f"carries it.")


def _ranked(rank: int) -> str:
    """A rank counted from one, as a sentence says it."""
    return _RANKS[rank - 1] if rank <= len(_RANKS) else f"{rank}th"
