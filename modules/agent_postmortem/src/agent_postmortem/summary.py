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

from collections.abc import Callable
from typing import Final

from argus_core.models import whether_it_can_be_put_back

from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.figures import (
    ACTED_FIGURE,
    ARGUS_STOPPED_FIGURE,
    BACK_TO_NORMAL_FIGURE,
    BEGAN_FIGURE,
    CUSTOMER_LOSS_FIGURE,
    DURATION_FIGURE,
    ERRORS_BEFORE_FIGURE,
    ERRORS_WHILE_BROKEN_FIGURE,
    LOG_READING_ENDED_FIGURE,
    LOGS_REACH_UNTIL_FIGURE,
    SERIES_AT_WORST_FIGURE,
    SERIES_BEFORE_FIGURE,
    UNOBSERVED_FROM_FIGURE,
    figures_of,
)
from agent_postmortem.measuring import Measurements
from agent_postmortem.sections import causes_of, resolution_of

type _Written = Callable[[str], str]

# A rank as a sentence says it, as far as an investigation ranks causes.
_RANKS: Final = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                 "eighth", "ninth", "tenth")


def the_executive_summary(evidence: IncidentEvidence,
                          measured: Measurements,
                          cause: str | None,
                          still_at_risk: str | None) -> str:
    """The summary in one paragraph: the record's facts around the model's two
    sentences, either left out where the model gave none."""
    figures = figures_of(evidence, measured)

    def written(name: str) -> str:
        return figures[name].written

    def written_if_any(name: str) -> str | None:
        return figures[name].written if name in figures else None

    return " ".join([
        *_when_and_for_how_long(measured, bool(evidence.log_lines), written, written_if_any),
        *_how_bad(measured, written),
        _what_customers_lost(measured, written),
        *([cause] if cause else []),
        *_what_argus_did(evidence, measured, written),
        *_what_it_left_to_a_person(evidence),
        *([still_at_risk] if still_at_risk else [])
    ])


def _when_and_for_how_long(measured: Measurements,
                           read: bool,
                           written: _Written,
                           written_if_any: Callable[[str], str | None]) -> list[str]:
    """When it broke and for how long, on the three stretches the brief tells
    apart: back to normal, never seen back, and unseen because the metrics
    stopped - this last with how far the service's own logs reach into it and
    where their reading ended, said apart, since where the lines stop is as
    often where the reading did.

    With no onset measured, said so, and the time counted from the alert
    rather than from when it broke: the alert is when the rule fired.
    """
    onset = measured.onset_at is not None
    said = [] if onset else [f"No onset was measured; the alert came at {written(BEGAN_FIGURE)}."]

    if measured.unobserved_from is not None:
        return [*said,
                f"No metrics were collected from {written(UNOBSERVED_FROM_FIGURE)} on, and "
                f"they had not resumed when Argus stopped working on the incident at "
                f"{written(ARGUS_STOPPED_FIGURE)}, {written(DURATION_FIGURE)} later.",
                _what_the_logs_show(read, written_if_any)]

    broke = f"The service broke at {written(BEGAN_FIGURE)} and was" if onset else "The service was"
    later = "later" if onset else "after the alert"

    if measured.back_to_normal_at is None:
        return [*said,
                f"{broke} not back to normal when Argus stopped working on the incident at "
                f"{written(ARGUS_STOPPED_FIGURE)}, at least {written(DURATION_FIGURE)} {later}."]

    return [*said,
            f"{broke} back to normal at {written(BACK_TO_NORMAL_FIGURE)}, "
            f"{written(DURATION_FIGURE)} {later}."]


def _what_the_logs_show(log_lines: bool,
                        written_if_any: Callable[[str], str | None]) -> str:
    """How far the service's own logs reach into the stretch the metrics did
    not cover, and where their reading ended - said apart, since where the
    lines stop is as often where the reading did. And said where they show
    nothing: a summary silent on the logs reads the same as one whose logs
    nobody looked at."""
    if not log_lines:
        return "No logs were read."

    reach = written_if_any(LOGS_REACH_UNTIL_FIGURE)
    ended = written_if_any(LOG_READING_ENDED_FIGURE)
    logs = (f"The service's own logs show it until {reach}" if reach is not None
            else "No log line read reaches into that stretch")

    return f"{logs}, and the logs were read up to {ended}." if ended is not None else f"{logs}."


def _how_bad(measured: Measurements, written: _Written) -> list[str]:
    """Failed requests where they rose beyond what the service reaches alone,
    and the series its alert watches where that got worse - each on its own,
    since the series is harm whatever the failed requests did: a fault in what
    the service answers fails no request, and a latency incident with a small
    rise in failures is not summed up by them."""
    said = []

    rates = measured.error_rates
    if rates is not None and rates.a_rise_was_measured:
        said.append(f"{written(ERRORS_WHILE_BROKEN_FIGURE)} of requests failed while it was "
                    f"broken, against {written(ERRORS_BEFORE_FIGURE)} before it began.")

    levels = measured.rule_series
    if levels is not None and levels.got_worse:
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

    so_far = " so far" if measured.back_to_normal_at is None else ""
    fell_short = "The shop's takings fell short of the same hours on earlier weeks by"

    if not measured.loss:
        return f"{fell_short} no more than those hours vary on their own{so_far}, if at all."

    return (f"{fell_short} {'at least ' if so_far else ''}{written(CUSTOMER_LOSS_FIGURE)}"
            f"{so_far}, beyond how much those hours vary on their own.")


def _what_argus_did(evidence: IncidentEvidence,
                    measured: Measurements,
                    written: _Written) -> list[str]:
    """Each action with what it came to, in the resolution's words - and where
    the service was back before the action credited with it, that it was, so
    the action is not read as what brought it back."""
    taken = [f"{step.action} ({whether_it_can_be_put_back(step.has_a_way_back)}) - "
             f"{step.outcome}"
             for step in resolution_of(evidence) if step.label is not None]
    said = [f"What Argus did: {'; '.join(taken)}."] if taken else []

    credited = evidence.credited_action
    if measured.back_before_the_action and credited is not None:
        said.append(f"The service was back to normal at {written(BACK_TO_NORMAL_FIGURE)}, "
                    f"before {credited.action} at {written(ACTED_FIGURE)} - so not because "
                    f"of it.")

    return said


def _what_it_left_to_a_person(evidence: IncidentEvidence) -> list[str]:
    """Each cause Argus held back from testing, with why in its own words - not
    its row's "never tried: ...", which would say it twice - the draft fix, and
    the action recommended and not taken. Never as having fixed anything:
    nothing ran the fix, and nothing took the recommendation.

    A cause by its rank, not its summary: that is the investigator's own
    sentences, and set inside this one they run on into the reason. Its label
    after the rank, which leads to its row on the page and to nothing where
    the summary is said on its own."""
    held_back = [f"Argus did not test the cause it ranked {_ranked(rank)} ({cause.label}): "
                 f"{cause.decided.result.rstrip('.')}."
                 for rank, cause in enumerate(causes_of(evidence.candidates), start=1)
                 if not cause.decided.tested and cause.decided.result]
    pull_request = evidence.pull_request
    recommended = evidence.recommended_action

    return [*held_back,
            *([f"Argus opened a draft fix, pull request #{pull_request.number}, for a person "
               f"to review and merge."] if pull_request is not None else []),
            *([f"Argus recommends this and did not take it: {recommended.rstrip('.')}."]
              if recommended else [])]


def _ranked(rank: int) -> str:
    """A rank counted from one, as a sentence says it."""
    return _RANKS[rank - 1] if rank <= len(_RANKS) else f"{rank}th"
