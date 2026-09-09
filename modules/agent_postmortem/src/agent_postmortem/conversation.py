"""The one exchange with the model, and how much of it is worth keeping.

The model is asked for prose and answers with a tool call. Everything here is
about that call arriving in the shape the document needs - asked once, refused
once where it did not, and read for an answer either way.

Nothing here computes a figure. The estimate travels through only so the check
can catch prose that names a different number from the one Argus measured.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from argus_core.llm.client import LLMClient
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn

from agent_postmortem.checking import faults_in
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.measuring import Measurements
from agent_postmortem.prompting import (
    SUBMIT_POSTMORTEM,
    SUBMIT_TOOL_NAME,
    opening_ask,
    opening_ask_again,
    rejecting,
)


def answer_worth_writing(llm: LLMClient,
                         evidence: IncidentEvidence,
                         measured: Measurements) -> tuple[dict[str, Any], list[str]]:
    """The model's answer, and whatever is still wrong with it.

    Two attempts at most (spec §7.6). The second is worth making because the
    faults are nameable - a missing field, a figure Argus never computed - and
    a model told which is a model that can fix it. A third would not be: an
    answer wrong twice in ways it was told about is not one attempt away from
    right, and the incident is over either way.

    Returns the faults rather than acting on them, because the caller is the
    one writing the document that has to admit to them.
    """
    asked = opening_ask(evidence, measured)
    submitted = llm.converse(asked, [SUBMIT_POSTMORTEM])

    first = _reading_of(submitted, measured.loss)
    _, faults = first
    if not faults:
        return first

    return _reading_of(llm.converse(_asking_again(asked, submitted, faults),
                                    [SUBMIT_POSTMORTEM]),
                       measured.loss)


def _asking_again(asked: Transcript, submitted: Turn, faults: list[str]) -> Transcript:
    """How the second attempt is put, which depends on what the first was.

    A submission is refused through the result of the call that made it, so
    the model sees its own answer and what was wrong with it. A model that
    made no call submitted nothing there is anything to refuse - so it is
    asked again from the start, which is the only shape left and the reason
    the choice lives here rather than in the prompt module.
    """
    if not submitted.tool_calls:
        return opening_ask_again(asked, faults)

    return rejecting(asked, submitted, faults)


def _reading_of(turn: Turn,
                estimate: Decimal | None) -> tuple[dict[str, Any], list[str]]:
    """What one turn amounts to: its answer and whatever is wrong with it.

    The estimate is no longer computed from anything the model said, so it is
    passed in rather than derived here - the only thing a turn can still get
    wrong about it is naming a different number in its prose.
    """
    answer = _answer_from(turn)

    return answer, faults_in(answer, estimate)


def _answer_from(turn: Turn) -> dict[str, Any]:
    """What the model submitted, or nothing at all.

    A turn carrying no call to the tool it was offered is an answer in the
    wrong shape rather than a failure to answer, and it is read as an empty
    one: the document is then written incomplete, which is what
    `checklist_complete` exists to say.
    """
    for call in turn.tool_calls:
        if call.name == SUBMIT_TOOL_NAME:
            return call.arguments

    return {}
