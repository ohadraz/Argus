"""The one exchange with the model for the executive synopsis's overview.

Asked once, sent back once with what was wrong, and given up after that or
after the model fails to answer: an overview that is not right is not sent, so
there is nothing to keep but the reason. The postmortem keeps a third answer
whatever it holds, because a document admits its faults in its review; an
overview has no review to admit them in.

The overview names figures and code writes them in (`synopsis_checking`
refuses one the prose writes itself), after the check, which reads the names.
The model is shown each figure as its tile writes it, and the overview kept has
it written in as prose says it (`said`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Final

from argus_core.llm import LLMClient, ModelRefused, ModelUnavailable, RequestRejected
from argus_core.models import Ask, ToolResult, ToolResults, Transcript, Turn
from pydantic import BaseModel

from agent_postmortem.grounding import Flag, faults_of, flags_on
from agent_postmortem.synopsis_checking import overview_faults
from agent_postmortem.synopsis_prompting import (
    OVERVIEW_FIELD,
    OVERVIEW_TOOL_NAME,
    SUBMIT_EXECUTIVE_OVERVIEW,
    Paging,
    overview_ask,
)

logger = logging.getLogger(__name__)

# A floor as prose says it, and the same floor after an "at" of the overview's.
_AT_LEAST: Final = "at least"
_NO_LESS_THAN: Final = "no less than"
# Where a clause of the overview ends: punctuation that a space or the text's
# end follows, which a figure's own "1,840.01" never is.
_A_CLAUSE_ENDS: Final = r"[.,;:!?](?:\s|$)"

# What the grounding judge is told not to judge in an overview: what code
# writes in, and the plainer words it is asked for. What supports a claim is
# the judge's own brief, said once there for every answer.
OVERVIEW_SCOPE: Final = (
    "Names in braces, such as {duration}, are figures code writes in from the list of "
    "figures in the ask. They are not judged.",
    "The overview is written in plain words for the people who lead the company. A claim "
    "said more plainly than the postmortem says it is grounded where it means the same."
)


class Overview(BaseModel):
    """The overview kept, with its figures written in - or none, and why."""

    text: str | None
    withheld_because: str | None = None


def the_overview(llm: LLMClient,
                 *,
                 service: str,
                 symptom: str | None,
                 cause: str | None,
                 figures: Mapping[str, str],
                 said: Mapping[str, str],
                 paging: Paging,
                 disproven: bool,
                 resolution: Sequence[str],
                 judge: LLMClient | None,
                 document: str,
                 labels: frozenset[str],
                 incident_id: str) -> Overview:
    """The overview for the finished incident, asked of the model at most twice.

    A model that refuses or cannot be reached, or an API that rejects the
    request, gives the overview up rather than failing the walk: the incident
    is over and its postmortem written either way. A rejection is logged as an
    error all the same: it is a request built wrong, or in a replay a recording
    that no longer matches.

    An overview the checks pass is read by `judge`, where there is one, against
    the postmortem it was written from (`document`, whose rows go by `labels`)
    and the ask that defines each figure it names. A claim neither supports is
    sent back once, like any fault; on the last attempt a flag withholds
    nothing - the overview the checks passed is sent - and is said in the log
    instead, flag by flag.
    """
    asked = overview_ask(service, symptom, cause, figures, paging, disproven, resolution)
    grounding = _Grounding(judge, asked, document, labels, incident_id)
    try:
        submitted = llm.converse(asked, [SUBMIT_EXECUTIVE_OVERVIEW])
        first, faults = _reading_of(submitted, figures, said)
        if not faults:
            faults = faults_of(grounding.flags_on(_overview_from(submitted) or ""))
        if not faults:
            return Overview(text=first)

        logger.warning("executive overview rejected", extra={"faults": faults})
        resubmitted = llm.converse(_asking_again(asked, submitted, faults),
                                   [SUBMIT_EXECUTIVE_OVERVIEW])
    except (ModelRefused, ModelUnavailable) as failure:
        return Overview(text=None, withheld_because=f"the model did not answer: {failure}")
    except RequestRejected as rejected:
        # The overview is the walk's last word on an incident already written
        # up, so it is given up with the API's own reason rather than failing a
        # run nothing is left to do in - and the record says why no synopsis
        # was sent. Nothing reached the model, so it is not said to have not
        # answered: the reason says the API rejected the request.
        logger.error("executive overview given up", extra={"failure": str(rejected)})
        return Overview(text=None, withheld_because=str(rejected))

    second, still = _reading_of(resubmitted, figures, said)
    if not still:
        grounding.logged(_overview_from(resubmitted) or "")
        return Overview(text=second)

    logger.warning("executive overview given up", extra={"faults": still})

    return Overview(text=None,
                    withheld_because="the overview was refused twice: " + "; ".join(still))


class _Grounding:
    """The grounding judge as the overview's attempts call on it: on the first
    the checks passed, with its flags to send back - or, on the last, its flags
    said in the log. Nothing where there is no judge.

    It reads the overview as the model wrote it, each figure still a name in
    braces, against the postmortem and the ask whose list says what each name
    comes to."""

    def __init__(self, judge: LLMClient | None, asked: Transcript, document: str,
                 labels: frozenset[str], incident_id: str) -> None:
        self._judge = judge
        self._record = "\n".join([*(exchange.text for exchange in asked
                                    if isinstance(exchange, Ask)),
                                  "", "The postmortem it is written from:", document])
        self._labels = labels
        self._incident_id = incident_id

    def flags_on(self, overview: str) -> list[Flag]:
        if self._judge is None:
            return []
        return flags_on(self._judge, record=self._record, answer={OVERVIEW_FIELD: overview},
                        rows=self._labels, scope=OVERVIEW_SCOPE)

    def logged(self, overview: str) -> None:
        for flag in self.flags_on(overview):
            logger.warning("executive overview claim not grounded", extra={
                "incident_id": self._incident_id, "fields": list(flag.fields),
                "quote": flag.quote, "rows": list(flag.rows), "why": flag.why})


def _reading_of(turn: Turn,
                figures: Mapping[str, str],
                said: Mapping[str, str]) -> tuple[str, list[str]]:
    """The overview one turn submitted, with its figures written in as prose
    says them, and every fault found in it as the model wrote it."""
    overview = _overview_from(turn)
    if overview is None:
        return "", [f"you answered without calling {OVERVIEW_TOOL_NAME}"]

    faults = [fault for found in overview_faults(overview, figures).values() for fault in found]

    return _with_figures_written(overview, said), faults


def _overview_from(turn: Turn) -> str | None:
    """What the model submitted as the overview, or `None` where it made no
    call to the tool."""
    for call in turn.tool_calls:
        if call.name == OVERVIEW_TOOL_NAME:
            return str(call.arguments.get(OVERVIEW_FIELD) or "")

    return None


def _with_figures_written(overview: str, said: Mapping[str, str]) -> str:
    """The overview with each figure it names written in as prose says it."""
    for name, written in said.items():
        before, *afters = overview.split(f"{{{name}}}")
        for after in afters:
            before, figure = _said_once(before, written, after)
            before += figure + after
        overview = before

    return overview


def _said_once(before: str, written: str, after: str) -> tuple[str, str]:
    """The overview up to the figure, and `written` as it goes in after it:
    the figure less its qualifier in front - "at least" - where the overview
    says it just before, and less its qualifier behind - "so far" - where the
    figure's own clause says it anywhere. Each whole or not at all, and never
    the figure itself.

    Shown a floor's tile, a model writes "at least {duration}", and the duration
    as prose says it carries its own "at least": written in whole, it read "at
    least at least 7 days". The overview's own words are the ones kept, so a
    sentence it opens with "At least" keeps its capital. Whole, because a word
    of the qualifier alone is the overview's own: "the lost takings at
    {customer_loss}" lost its "at" to the figure's, and read "takings at least".
    Kept, the overview's "at" would read "at at least", so a floor after it is
    said "no less than" - the same floor in other words. And where the overview
    wrote the "at at least" itself, its "at least" is read as the figure's: the
    one place the overview's words give way, because keeping them is the
    doubled word.

    "So far" is looked for across the clause rather than beside the name: "the
    lost takings so far at {customer_loss}" says it two words before, and a
    clause says a thing once whichever end it says it at. Only the clause - a
    "so far" a sentence away is about something else.
    """
    words = written.split(" ")
    figured = [place for place, word in enumerate(words) if any(map(str.isdigit, word))]
    if not figured:
        return before, written

    # Before the first number; and after the last one and the unit it is in.
    in_front = figured[0]
    behind = len(words) - figured[-1] - 2
    qualifier = " ".join(words[:in_front])
    if (qualifier.lower() == _AT_LEAST
            and re.search(rf"(?:^|\W)at {_AT_LEAST} $", before, re.IGNORECASE)):
        before = before[:-len(f"{_AT_LEAST} ")]
    lead = in_front if in_front and re.search(
        rf"(?:^|\W){re.escape(qualifier)} $", before, re.IGNORECASE) else 0
    if (not lead and qualifier.lower() == _AT_LEAST
            and re.search(r"(?:^|\W)at $", before, re.IGNORECASE)):
        words = [*_NO_LESS_THAN.split(" "), *words[in_front:]]
    rest = words[lead:]
    tail = behind if behind > 0 and re.search(
        rf"(?:^|\W){re.escape(' '.join(rest[-behind:]))}(?:\W|$)",
        _the_clause_around(before, after), re.IGNORECASE) else 0

    return before, " ".join(rest[:len(rest) - tail])


def _the_clause_around(before: str, after: str) -> str:
    """The overview's words on either side of a figure, as far as the clause it
    is in reaches each way.

    A clause ends at punctuation followed by a space or by nothing, so the
    comma and the point inside "1,840.01 USD", already written in, end nothing.
    """
    return (re.split(_A_CLAUSE_ENDS, before)[-1] + " "
            + re.split(_A_CLAUSE_ENDS, after)[0])


def _asking_again(asked: Transcript, submitted: Turn, faults: list[str]) -> Transcript:
    """The second ask: the submission refused through its own call's result, so
    the model sees what it wrote and what was wrong - or, where it made no call,
    the same ask with what went wrong said after it."""
    said = "\n".join([*(f"  - {fault}" for fault in faults), "",
                      f"Call {OVERVIEW_TOOL_NAME} again with the whole overview, corrected."])
    if not submitted.tool_calls:
        return [*asked, Ask(text=f"Your previous answer could not be used:\n{said}")]

    return [*asked, submitted,
            ToolResults(results=[ToolResult(call_id=call.id,
                                            content=f"Your overview was not accepted:\n{said}",
                                            failed=True)
                                 for call in submitted.tool_calls])]
