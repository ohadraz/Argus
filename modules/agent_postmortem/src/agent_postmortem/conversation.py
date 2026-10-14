"""The one exchange with the model, and how much of it is worth keeping.

The model is asked for prose and answers with a tool call. Everything here is
about that call arriving in the shape the document needs - asked once, refused
once where it did not, and read for an answer either way.

Nothing here computes a figure, and the prose writes none: it names the figures
the incident gave, and the answer kept has each written in as this run
measured it (`figures`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from argus_core.llm import LLMClient
from argus_core.models import ThreadMessage, Transcript, Turn

from agent_postmortem.checking import Given, faults_in
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.figures import Figure, with_figures_written
from agent_postmortem.measuring import Measurements
from agent_postmortem.prompting import (
    SUBMIT_TOOL_NAME,
    SubmittedPostmortem,
    figures_shown,
    opening_ask,
    opening_ask_again,
    rejecting,
    submit_postmortem_for,
    the_evidence_labelled,
)
from agent_postmortem.revisions import revisions_of, with_revisions_corrected
from agent_postmortem.sections import record_action_items_of

logger = logging.getLogger(__name__)


def answer_worth_writing(llm: LLMClient,
                         evidence: IncidentEvidence,
                         measured: Measurements
                         ) -> tuple[SubmittedPostmortem, list[str]]:
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
    # The tool for this incident, which asks what each lead changed only where
    # people wrote any.
    submit = submit_postmortem_for(evidence.leads)
    # Every figure the answer may name, each written in as this run measured it.
    figures = figures_shown(evidence, measured)
    given = _what_was_given(evidence, figures)
    submitted = llm.converse(asked, [submit])

    first = _reading_of(submitted, evidence.leads, given, figures)
    _, faults = first
    if not faults:
        return first

    logger.warning("postmortem answer rejected", extra={"faults": faults})

    return _reading_of(llm.converse(_asking_again(asked, submitted, faults), [submit]),
                       evidence.leads,
                       given,
                       figures)


def _what_was_given(evidence: IncidentEvidence, figures: dict[str, Figure]) -> Given:
    """What the answer is held to: the labels it could cite, the items already
    on the record, the revisions the incident read, and the figures it may
    name."""
    return Given(
        labels=frozenset(cited.label for cited in the_evidence_labelled(evidence)),
        items_on_record=len(record_action_items_of(evidence)),
        revisions=revisions_of(evidence),
        figures=figures
    )


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
                leads: Sequence[ThreadMessage],
                given: Given,
                figures: dict[str, Figure]
                ) -> tuple[SubmittedPostmortem, list[str]]:
    """What one turn amounts to: its answer and whatever is wrong with it.

    The leads go with it, because whether every one was answered is a fault of
    the turn too, and what was given, because a citation is checked against it.
    A revision a few characters off is written as the real one first, since
    code knows which it was; only one starting like none is left to refuse.

    The figures are written in last, after the check: it reads the names, and
    a figure written in before it would read as one the model wrote in digits.
    """
    answer = with_revisions_corrected(_answer_from(turn), given.revisions)

    return with_figures_written(answer, figures), faults_in(answer, leads, given=given)


def _answer_from(turn: Turn) -> SubmittedPostmortem:
    """What the model submitted, or nothing at all.

    A turn carrying no call to the tool it was offered is an answer in the
    wrong shape rather than a failure to answer, and it is read as an empty
    one: the document is then written incomplete, which is what its review
    exists to say.
    """
    for call in turn.tool_calls:
        if call.name == SUBMIT_TOOL_NAME:
            return SubmittedPostmortem.model_validate(call.arguments)

    return SubmittedPostmortem()
