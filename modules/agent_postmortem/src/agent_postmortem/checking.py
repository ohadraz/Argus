"""What is wrong with an answer, said in words the model can act on.

Checked together because they are answered together. A required field the
model left out is the obvious fault - and a lead it said nothing about is one
of those, whose names only the incident knows. So is a step of the cause that
cites no evidence, cites a label nobody gave it, or cites a candidate cause - a
hypothesis, where the chain wants what was observed - and a contributing factor
no action item answers: an analysis without its evidence is a story, and one
without its actions is a document that prevents nothing.

The other kind is a figure the prose writes itself: an amount, a share, a time
or a date, a duration, a count. The document's figures are measured, and one the
prose states is written in by code from the name the model gives it (`figures`).
Prose writing one itself is either repeating it - rounded, or worked out again -
or inventing it, and the two cannot be told apart from the sentence, which
reaches the reader least able to check it. Said in words it is the same figure:
spelled out in a run of them, one nobody can read, or in one word that measures
something - "twenty minutes", "tripled", "a third" - one nobody can check. That
last was the rule's own hole: "about twenty minutes" for an incident six long
passed where "about 20 minutes" was refused, so it judged the spelling and not
the claim. Said with no number in it ("most requests", "several minutes"), a
magnitude carries what a sentence needs and claims no precision nobody
measured; a figure the incident never gave as one is a working of two it did
(`figures`). A count of things ("about a hundred shoppers") and a number that
describes rather than measures ("one-minute buckets") are no figure. A word
mixing letters and digits is no figure but a name - a label, a revision, a pod -
and is written as given. A revision is held to the ones the incident read
instead (`revisions`).

The rule reads the answer, not the run it is read in. One comparing the prose's
numbers with this run's measurements refused a recorded answer whenever the run
measured differently, which every run does. A figure's name is held to the
figures the incident gave, as a citation is held to the evidence: both are
names, which figures a run names follows from what it measured and read, and a
replay - rebuilding the world its recording was made in - gives the same ones.
So does a working's verdict (`figures`): a difference that comes out below
nothing, or a division by nothing, is read from the figures this run gave.

Faults are phrased for the model rather than for a log. "Missing field" and
"your answer writes [$1.2M] in digits - write the figure's name" are both
things a second attempt can be about; "invalid answer" is not, and a model told
only that its answer was wrong rewrites the part it liked least.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import pairwise
from typing import Final

from argus_core import the_revision_named
from argus_core.models import ThreadMessage, labelled
from pydantic import BaseModel

from agent_postmortem.figures import (
    AROUND_A_WORD,
    Figure,
    is_a_figure,
    names_in,
    workings_that_make_no_sense,
)
from agent_postmortem.prompting import (
    ACTION_ITEMS_FIELD,
    CAUSAL_CHAIN_FIELD,
    LEAD_EFFECTS_FIELD,
    REQUIRED_FIELDS,
    SubmittedPostmortem,
)
from agent_postmortem.revisions import unknown_revisions_in
from agent_postmortem.sections import action_item_number

# A number said in a word: a count, a ten, a power of ten, or the fraction a
# decimal is read out in.
_A_NUMBER_WORD: Final = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty"
    r"|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million"
    r"|billion|tenths|hundredths|thousandths)\b"
)

# What joins two number words into one figure: a space or a hyphen, and an
# "and" only where a figure has one - after a power of ten ("a hundred and
# five"), or before the fraction it ends in ("and thirty-one hundredths").
# Anywhere else an "and" joins two numbers, each judged on its own: "between
# one and two replicas" is two counts of things, not one figure.
_A_JOIN: Final = (
    r"(?:\s+|-"
    r"|(?:(?<=hundred)|(?<=thousand)|(?<=million)|(?<=billion))\s+and\s+"
    rf"|\s+and\s+(?=(?:{_A_NUMBER_WORD}(?:\s+|-))*(?:tenths|hundredths|thousandths)\b))"
)

# A figure spelled out: number words, two or more, joined into one.
_A_FIGURE_SPELLED_OUT: Final = re.compile(
    rf"\b{_A_NUMBER_WORD}(?:{_A_JOIN}{_A_NUMBER_WORD})+",
    re.IGNORECASE
)

# What a number measures when one follows it: time, a share, or how many times
# another thing. Anything else after one is a count of things.
_A_UNIT: Final = (
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?"
    r"|percent|per\s+cent|percentage\s+points?|times)\b"
)

# A figure said in one word: a number word, or a half, measuring something
# ("twenty minutes", "half an hour", "three times"); a word that is a multiple
# ("tripled", "twice"); or a fraction ("a third", "two thirds"). Joined to what
# it measures by a space only - "one-minute buckets" describes the buckets, and
# measures nothing.
_A_FIGURE_IN_A_WORD: Final = re.compile(
    rf"\b(?:{_A_NUMBER_WORD}|half(?:\s+an?)?)\s+{_A_UNIT}"
    r"|\b(?:doubled|tripled|quadrupled|halved|twice|thrice)\b"
    r"|\b(?:a|one|two|three|four)\s+(?:half|halves|thirds?|quarters?|fifths?|tenths?)\b",
    re.IGNORECASE
)

# The words after which a number is a place in a source file, not a figure.
_A_PLACE_IN_A_FILE: Final = frozenset({"line", "lines"})

# What every fault about a figure asks for instead.
_STATE_IT_BY_ITS_NAME: Final = (
    "write a figure the incident gave as the name shown after it, braces and all, "
    "or a working of two such names ({a - b}, {a / b}), and say any other size with "
    "no number in it (\"most requests\", \"several minutes\")"
)


class Given(BaseModel):
    """What the model was handed, as far as a check needs it: the labels it
    could cite and which of them name a hypothesis, how many action items the
    record already held, the revisions the incident read, and the figures it
    gave, by name."""

    labels: frozenset[str] = frozenset()
    hypotheses: frozenset[str] = frozenset()
    items_on_record: int = 0
    revisions: frozenset[str] = frozenset()
    figures: dict[str, Figure] = {}


def faults_in(answer: SubmittedPostmortem,
              leads: Sequence[ThreadMessage] = (),
              *,
              given: Given) -> list[str]:
    """Everything about this answer that has to be put right, or nothing."""
    return (_missing_fields(answer)
            + _leads_left_unanswered(answer, leads)
            + _steps_resting_on_nothing(answer, given)
            + _factors_nothing_answers(answer, given)
            + _numbers_in_digits(answer, given)
            + _figures_spelled_out(answer)
            + _figures_said_in_a_word(answer)
            + _figures_nobody_gave(answer, given)
            + _workings_that_make_no_sense(answer, given)
            + _revisions_nobody_read(answer, given))


def _leads_left_unanswered(answer: SubmittedPostmortem,
                           leads: Sequence[ThreadMessage]) -> list[str]:
    """Which leads the answer said nothing about, by the label it knows them by.

    A required field whose names only the incident knows, and refused as one:
    the person who wrote a lead is owed the line, and a model told which lead it
    skipped has one thing to put right.
    """
    return [f"the lead [{label}] was not answered - say in {LEAD_EFFECTS_FIELD} "
            f"whether it changed what was done"
            for label, _lead in labelled(leads)
            if label not in answer.lead_effects]


def _missing_fields(answer: SubmittedPostmortem) -> list[str]:
    """Which of the fields the tool declared required went unanswered.

    Read off the same list the tool declares, by name, rather than field by
    field: a field the model is told it must send and this does not check for
    is the pair going out of step in the direction nothing would notice.
    """
    return [f"the field [{field}] was missing from your answer"
            for field in REQUIRED_FIELDS
            if getattr(answer, field) is None]


def _steps_resting_on_nothing(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each step citing no evidence, each label cited that was never given, and
    each hypothesis cited as though it were evidence.

    A candidate cause is the Investigator's guess, written before anything was
    tried. The chain says what happened, so a step rests on what was observed;
    a guess cited there reads as a fact, even beside evidence that is real.
    """
    faults: list[str] = []

    for step in answer.causal_chain or []:
        if not step.cites:
            faults.append(f"the step [{step.step}] in {CAUSAL_CHAIN_FIELD} cites no "
                          f"evidence - cite the labels it rests on")

        faults.extend(_what_is_wrong_with_citing(step.step, label, given)
                      for label in step.cites
                      if label in given.hypotheses or label not in given.labels)

    return faults


def _what_is_wrong_with_citing(step: str, label: str, given: Given) -> str:
    """Why a step may not rest on this label, said for the model to act on."""
    if label in given.hypotheses:
        return (f"the step [{step}] cites [{label}], a candidate cause - a hypothesis, "
                f"not evidence; cite what was observed that shows it, or leave the step "
                f"out")

    return f"the step [{step}] cites [{label}], which is not a label you were given"


def _factors_nothing_answers(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each factor naming no action item, and each item named that does not exist.

    The items that exist are the record's and the answer's own proposals, which
    are numbered after the record's in the order the answer gave them.
    """
    proposed = len(answer.action_items or [])
    items = {action_item_number(position)
             for position in range(1, given.items_on_record + proposed + 1)}
    faults: list[str] = []

    for factor in answer.contributing_factors or []:
        if not factor.addressed_by:
            faults.append(f"the contributing factor [{factor.factor}] names no action "
                          f"item that answers it - name one in {ACTION_ITEMS_FIELD} or "
                          f"on the record")

        faults.extend(f"the contributing factor [{factor.factor}] names [{number}], "
                      f"which is not an action item"
                      for number in factor.addressed_by if number not in items)

    return faults


def _numbers_in_digits(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Every word of the prose that is a figure written in digits.

    Word by word, so the fault names the number as the reader would see it -
    `33.8%`, `$1,200,000`, `21:45` - rather than a fragment of it.

    Not a line of source. "line 47" says where in a file, not how much of
    anything, and refused it could only be spelled out - which is refused too.

    Nor a revision the incident read, named by a start that happens to be all
    digits: one in about thirty begins with seven digits, and its short form is the
    name the evidence gives it.
    """
    return [
        f"your answer writes [{word}] in digits - {_STATE_IT_BY_ITS_NAME}"
        for prose in answer.sentences()
        for before, word in pairwise(
            ["", *(each.strip(AROUND_A_WORD) for each in prose.split())]
        )
        if is_a_figure(word)
        and before.lower() not in _A_PLACE_IN_A_FILE
        and not _names_a_revision_read(word, given)
    ]


def _names_a_revision_read(word: str, given: Given) -> bool:
    """Whether `word` is the start of exactly one revision the incident read."""
    return the_revision_named(word, given.revisions) is not None


def _figures_spelled_out(answer: SubmittedPostmortem) -> list[str]:
    """Every run of number words in the prose that says one figure.

    The whole run, so the fault quotes the figure as the reader would meet it -
    `one thousand two hundred ninety-seven and thirty-one hundredths` - rather
    than a word of it.
    """
    return [
        f"your answer spells out [{spelled.group(0)}] in words - {_STATE_IT_BY_ITS_NAME}"
        for prose in answer.sentences()
        for spelled in _A_FIGURE_SPELLED_OUT.finditer(prose)
    ]


def _figures_said_in_a_word(answer: SubmittedPostmortem) -> list[str]:
    """Every figure the prose says in one word, as it says it.

    Not one inside a figure already spelled out: "twenty-four hours" is one
    figure, refused once, as spelled out.
    """
    return [
        f"your answer says [{said.group(0)}] in words - {_STATE_IT_BY_ITS_NAME}"
        for prose in answer.sentences()
        for spelled in [[out.span() for out in _A_FIGURE_SPELLED_OUT.finditer(prose)]]
        for said in _A_FIGURE_IN_A_WORD.finditer(prose)
        if not any(start < said.end() and said.start() < end for start, end in spelled)
    ]


def _figures_nobody_gave(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each figure's name in the prose that names no figure the incident gave.

    Written in, it would be a blank where a figure goes - and nothing here can
    know which figure it meant.
    """
    return [
        f"your answer names [{{{name}}}], which is no figure you were given - write a "
        f"figure's name exactly as it is shown after the figure, or say the size "
        f"with no number in it"
        for prose in answer.sentences()
        for name in names_in(prose)
        if name not in given.figures
    ]


def _workings_that_make_no_sense(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each working the prose asks for that works out to nothing, with why.

    Left in, it would reach the page in braces: nothing can be written in for
    a sum of two instants, or for a span below nothing.
    """
    return [
        f"your answer asks for [{written}], but {why}; or name one figure"
        for prose in answer.sentences()
        for written, why in workings_that_make_no_sense(prose, given.figures)
    ]


def _revisions_nobody_read(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each revision the prose names that starts like none the incident read.

    One a few characters off has been written as the real one before this is
    asked (`revisions`), so what is left is a name nothing can be looked up by.
    """
    return [
        f"your answer names revision [{named}], which is none the incident read - "
        f"name a revision as the evidence gives it"
        for prose in answer.sentences()
        for named in unknown_revisions_in(prose, given.revisions)
    ]

