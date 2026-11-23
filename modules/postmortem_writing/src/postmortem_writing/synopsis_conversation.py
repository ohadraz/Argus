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
from collections.abc import Mapping, Sequence
from typing import Final

from core.llm import (
    LLMClient,
    ModelDidNotAnswer,
    ModelUnavailable,
    RequestRejected,
    sent_back,
    the_call,
)
from core.models import Ask, Transcript, Turn
from pydantic import BaseModel

from postmortem_writing.figures import Figure, written_in
from postmortem_writing.grounding import Flagging, Grounding, GroundingFor, faults_of
from postmortem_writing.synopsis_checking import overview_faults
from postmortem_writing.synopsis_prompting import (
    OVERVIEW_FIELD,
    OVERVIEW_TOOL_NAME,
    SUBMIT_EXECUTIVE_OVERVIEW,
    Paging,
    overview_ask,
)

logger = logging.getLogger(__name__)

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
                 incident_id: str,
                 grounding_for: GroundingFor = Grounding,
                 outage_ends_it: bool = False) -> Overview:
    """The overview for the finished incident, asked of the model at most twice.

    A model that does not answer - it refused, ran out of room, or paused - or
    an API that rejects the request gives the overview up rather than failing
    the walk: the incident is over and its postmortem written either way. A
    rejection is logged as an error all the same: it is a request built wrong,
    or in a replay a recording that no longer matches. A model that cannot be
    reached gives it up only where `outage_ends_it`, on the run's last try; on
    any other the run is tried again from here, which an outage can outlast.

    An overview the checks pass is read by `judge`, where there is one, against
    the postmortem it was written from (`document`, whose rows go by `labels`)
    and the ask that defines each figure it names. A claim neither supports is
    sent back once, like any fault; on the last attempt a flag withholds
    nothing - the overview the checks passed is sent - and is said in the log
    instead, flag by flag.

    `grounding_for` is how the judge is called on: a seam, so this module's suite
    holds what the judge is handed and when, and leaves the grounding to its own.
    """
    asked = overview_ask(service, symptom, cause, figures, paging, disproven, resolution)
    grounding = _the_grounding(grounding_for, judge, asked, document, labels, incident_id)
    try:
        submitted = llm.converse(asked, [SUBMIT_EXECUTIVE_OVERVIEW])
        first, faults = _reading_of(submitted, figures, said)
        if not faults:
            faults = faults_of(grounding.flags_on(
                {OVERVIEW_FIELD: _overview_from(submitted) or ""}))
        if not faults:
            return Overview(text=first)

        logger.warning("executive overview rejected", extra={"faults": faults})
        resubmitted = llm.converse(_asking_again(asked, submitted, faults),
                                   [SUBMIT_EXECUTIVE_OVERVIEW])
    except ModelDidNotAnswer as failure:
        return Overview(text=None, withheld_because=f"the model did not answer: {failure}")
    except ModelUnavailable as unreachable:
        if not outage_ends_it:
            raise

        return Overview(text=None,
                        withheld_because=f"the model could not be reached: {unreachable}")
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
        grounding.logged({OVERVIEW_FIELD: _overview_from(resubmitted) or ""})
        return Overview(text=second)

    logger.warning("executive overview given up", extra={"faults": still})

    return Overview(text=None,
                    withheld_because="the overview was refused twice: " + "; ".join(still))


def _the_grounding(grounding_for: GroundingFor, judge: LLMClient | None, asked: Transcript,
                   document: str, labels: frozenset[str], incident_id: str) -> Flagging:
    """The grounding judge as the overview's attempts call on it: on the first
    the checks passed, with its flags to send back - or, on the last, its flags
    said in the log.

    It reads the overview as the model wrote it, each figure still a name in
    braces, against the postmortem and the ask whose list says what each name
    comes to."""
    record = "\n".join([*(exchange.text for exchange in asked if isinstance(exchange, Ask)),
                        "", "The postmortem it is written from:", document])

    return grounding_for(judge, record, labels, OVERVIEW_SCOPE, incident_id, logger=logger,
                         logged_as="executive overview claim not grounded")


def _reading_of(turn: Turn,
                figures: Mapping[str, str],
                said: Mapping[str, str]) -> tuple[str, list[str]]:
    """The overview one turn submitted, with its figures written in as prose
    says them, and every fault found in it as the model wrote it."""
    overview = _overview_from(turn)
    if overview is None:
        return "", [f"you answered without calling {OVERVIEW_TOOL_NAME}"]

    faults = [fault for found in overview_faults(overview, figures).values() for fault in found]

    return _with_figures_written(overview, figures, said), faults


def _overview_from(turn: Turn) -> str | None:
    """What the model submitted as the overview, or `None` where it made no
    call to the tool."""
    submitting = the_call(turn, OVERVIEW_TOOL_NAME)

    return None if submitting is None else str(submitting.arguments.get(OVERVIEW_FIELD) or "")


def _with_figures_written(overview: str,
                          figures: Mapping[str, str],
                          said: Mapping[str, str]) -> str:
    """The overview with each figure it names written in as prose says it, by
    the one engine a postmortem's sentences are written in by (`written_in`):
    each figure as its tile shows it (`figures`), which a working works from,
    and as prose says it (`said`), which goes in."""
    return written_in(overview, {name: Figure(given=figures.get(name, written), written=written)
                                 for name, written in said.items()})


def _asking_again(asked: Transcript, submitted: Turn, faults: list[str]) -> Transcript:
    """The second ask: the submission refused through its own call's result, so
    the model sees what it wrote and what was wrong - or, where it made no call,
    the same ask with what went wrong said after it."""
    said = "\n".join([*(f"  - {fault}" for fault in faults), "",
                      f"Call {OVERVIEW_TOOL_NAME} again with the whole overview, corrected."])
    if not submitted.tool_calls:
        return [*asked, Ask(text=f"Your previous answer could not be used:\n{said}")]

    return sent_back(asked, submitted, f"Your overview was not accepted:\n{said}")
