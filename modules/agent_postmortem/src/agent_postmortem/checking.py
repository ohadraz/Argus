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

from argus_core import A_REVISION, the_revision_named
from argus_core.models import ThreadMessage, Turn, labelled
from pydantic import BaseModel

from agent_postmortem.figures import (
    A_FIGURE_NAME,
    AROUND_A_WORD,
    Figure,
    is_a_figure,
    names_in,
    workings_that_make_no_sense,
)
from agent_postmortem.prompting import (
    ACTION_ITEMS_FIELD,
    ADDRESSED_BY_FIELD,
    ANSWERS_FIELD,
    CAUSAL_CHAIN_FIELD,
    CAUSE_IN_PLAIN_WORDS_FIELD,
    CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD,
    CONTRIBUTING_FACTORS_FIELD,
    HAD_IT_BEEN_OTHERWISE_FIELD,
    LEAD_EFFECTS_FIELD,
    LOGS_SHOW_SERVING_AS_BEFORE_FIELD,
    REQUIRED_FIELDS,
    ROOT_CAUSE_FIELD,
    STILL_AT_RISK_FIELD,
    SUBMIT_TOOL_NAME,
    SYMPTOM_FIELD,
    SYMPTOM_WORDS_AT_MOST,
    SubmittedPostmortem,
)
from agent_postmortem.revisions import unknown_revisions_in
from agent_postmortem.sections import (
    AS_IT_RAN_PREFIX,
    CODE_READING_PREFIX,
    CONTRIBUTING_FACTOR_PREFIX,
    DEPLOYMENT_CHANGES_PREFIX,
    action_item_number,
    contributing_factor_label,
    is_a_code_reading,
    label_of,
)

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

# A figure said in one word: a span of one unit ("a minute", "an hour and a
# half"); a number word, or a half, measuring something ("twenty minutes", "half
# an hour", "three times"); a word that is a multiple ("tripled", "twice"); or a
# fraction ("a third", "two thirds"). Joined to what it measures by a space only
# - "one-minute buckets" describes the buckets, and measures nothing.
#
# The span is first, and takes its "and a half" with it, so that one figure is
# one fault rather than a span and a fraction. Its units are the ones Argus
# measures between its own instants: "a second" is an ordinal as often as a span
# ("a second candidate"), and "a month" is the shop's own noun for a statement
# period, which no span here reaches.
_A_FIGURE_IN_A_WORD: Final = re.compile(
    r"\b(?:a|an)\s+(?:minute|hour|day|week)(?:\s+and\s+a\s+half)?\b"
    rf"|\b(?:{_A_NUMBER_WORD}|half(?:\s+an?)?)\s+{_A_UNIT}"
    r"|\b(?:doubled|tripled|quadrupled|halved|twice|thrice)\b"
    r"|\b(?:a|one|two|three|four)\s+(?:half|halves|thirds?|quarters?|fifths?|tenths?)\b",
    re.IGNORECASE
)

# The words after which a number is a place in a source file, not a figure.
_A_PLACE_IN_A_FILE: Final = frozenset({"line", "lines"})

# The words a range is opened with, and the dash a range figure is written
# with: "between {G}" where G writes in as "21:41–22:01" opens it twice. And
# the words that place a moment, after which a range is a span where the
# sentence wants one instant: "first appears at {G}" read "at 14:46–14:53".
_WORDS_THAT_OPEN_A_RANGE: Final = frozenset({"between", "from"})
_WORDS_THAT_PLACE_A_MOMENT: Final = frozenset({"at", "by", "since", "until", "before",
                                               "after"})
_WORDS_A_RANGE_MAY_NOT_FOLLOW: Final = _WORDS_THAT_OPEN_A_RANGE | _WORDS_THAT_PLACE_A_MOMENT
_A_RANGE_DASH: Final = re.compile(r"[–—]")

# Where one sentence ends and another begins: a stop with words after it. A
# sentence's own closing stop is not one.
_A_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+(?=\S)")

# A check said to be missing: nothing (seen) checks, or no (such) check. With
# a word allowed between, since "nothing seen checks" is how the rule that a
# safeguard is one not seen has the model say it. A standing check, in the
# present tense and never a test: "nothing verified" is the hedge an F-only
# step is asked for, and "no test was run" a limit of the evidence.
_A_MISSING_CHECK: Final = re.compile(
    r"\b(?:nothing|nobody|no one)(?:\s+\w+)?\s+(?:checks|verifies|validates|catches)\b"
    r"|\bno\s+(?:\w+\s+)?(?:checks?|safeguards?)\b",
    re.IGNORECASE)

# A factor's label written as a word of the prose.
_A_FACTOR_S_LABEL: Final = re.compile(rf"\b{re.escape(CONTRIBUTING_FACTOR_PREFIX)}\d+\b")

# What every fault about a figure asks for instead.
_STATE_IT_BY_ITS_NAME: Final = (
    "write a figure the incident gave as the name shown after it, braces and all, "
    "or a working of two such names ({a - b}, {a / b}), and say any other size with "
    "no number in it (\"most requests\", \"several minutes\")"
)


class Given(BaseModel):
    """What the model was handed, as far as a check needs it: the labels it
    could cite and which of them name a hypothesis, how many action items the
    record already held, the revisions the incident read and which of them the
    deploy that set it off went to, the figures it gave, by name, and each file
    shown as it ran, by label."""

    labels: frozenset[str] = frozenset()
    hypotheses: frozenset[str] = frozenset()
    items_on_record: int = 0
    revisions: frozenset[str] = frozenset()
    # `None` where no deploy set the incident off.
    trigger_revision: str | None = None
    figures: dict[str, Figure] = {}
    # Each file shown as it ran - its path at its revision - by its label.
    as_it_ran: dict[str, str] = {}
    # Whether it was asked if the logs show the service serving as before -
    # which it is wherever a line reaches into a stretch the metrics missed.
    serving_as_before_asked: bool = False


def faults_in(answer: SubmittedPostmortem,
              leads: Sequence[ThreadMessage] = (),
              *,
              given: Given) -> list[str]:
    """Everything about this answer that has to be put right, or nothing."""
    return (_missing_fields(answer)
            + _how_it_served_left_unanswered(answer, given)
            + _a_symptom_of_more_than_one_sentence(answer)
            + _a_symptom_over_its_words(answer)
            + _summary_sentences_of_more_than_one(answer)
            + _missing_checks_outside_the_factors(answer)
            + _the_trigger_said_again(answer, given)
            + _leads_left_unanswered(answer, leads)
            + _steps_resting_on_nothing(answer, given)
            + _readings_beside_no_file_as_it_ran(answer, given)
            + _a_reading_the_answer_says_otherwise_of(answer)
            + _factors_nothing_answers(answer, given)
            + _factor_labels_in_the_prose(answer)
            + _numbers_in_digits(answer, given)
            + _figures_spelled_out(answer)
            + _figures_said_in_a_word(answer)
            + _figures_nobody_gave(answer, given)
            + _ranges_after_an_opening_or_a_moment(answer, given)
            + _workings_that_make_no_sense(answer, given)
            + _revisions_nobody_read(answer, given))


def faults_in_the_turn(turn: Turn) -> list[str]:
    """Everything about the turn the answer came in that has to be put right,
    or nothing: a turn that submitted more than once.

    Refused rather than read, because two calls do not say which is the
    answer. In the turn that showed it the real one came first and a
    placeholder second, but a model revising its answer puts the real one
    second - so keeping either is a guess, and a refusal costs one more call
    only in a turn that is already malformed. Whoever reads the turn still
    reads its first call, for the attempt that has no second after it.
    """
    submitted = sum(1 for call in turn.tool_calls if call.name == SUBMIT_TOOL_NAME)
    if submitted <= 1:
        return []

    return [f"your turn called {SUBMIT_TOOL_NAME} {submitted} times - call it once, "
            f"with the whole answer"]


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
            if getattr(answer, field) is None and field not in _UNANSWERED_BEFORE_IT_WAS_ASKED]


# Required fields whose absence means an answer recorded before the question
# existed - a live call always sends them - and so is never put back: a retry
# would ask each such recording for a turn it does not hold.
_UNANSWERED_BEFORE_IT_WAS_ASKED: Final = frozenset({CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD})


def _how_it_served_left_unanswered(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """That the answer left out whether the logs show the service serving as
    before, where it was asked - a required field only some incidents are
    asked for, and refused as one: the document's sentence on that stretch is
    written from it."""
    if not given.serving_as_before_asked or answer.logs_show_serving_as_before is not None:
        return []

    return [f"the field [{LOGS_SHOW_SERVING_AS_BEFORE_FIELD}] was missing from your answer"]


def _a_reading_the_answer_says_otherwise_of(answer: SubmittedPostmortem) -> list[str]:
    """Where the answer's word on whether its cause rests on a reading nothing
    ran is one its own chain contradicts: no, beside a step citing a reading
    and nothing read that shows the code - so the box would be ticked beside a
    mechanism nothing read shows - or yes, with no step citing a reading at
    all, which leaves the document's sentence naming none.

    Not asked of an answer that never said, which was recorded before the
    question was."""
    said = answer.cause_rests_on_an_unrun_reading
    steps = answer.causal_chain or []

    if said is None:
        return []

    if said:
        if any(is_a_code_reading(cited) for step in steps for cited in step.cites):
            return []

        return [f"[{CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD}] says the cause rests on a reading "
                f"nothing ran, and no {CAUSAL_CHAIN_FIELD} step cites one: cite the "
                f"{CODE_READING_PREFIX} row it rests on, or answer false"]

    return [f"the {CAUSAL_CHAIN_FIELD} step [{step.step}] rests on "
            f"[{', '.join(cited for cited in step.cites if is_a_code_reading(cited))}], a "
            f"reading nothing ran, with no {AS_IT_RAN_PREFIX} or {DEPLOYMENT_CHANGES_PREFIX} "
            f"row beside it, and [{CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD}] says the cause rests "
            f"on more: answer true, or cite the row that shows the code"
            for step in steps
            if any(is_a_code_reading(cited) for cited in step.cites)
            and not any(_shows_the_code(cited) for cited in step.cites)]


def _shows_the_code(label: str) -> bool:
    """Whether `label` cites something read that shows the code itself: a file
    as it ran, or what a deployment changed."""
    return any(label.startswith(prefix) and label[len(prefix):].isdigit()
               for prefix in (AS_IT_RAN_PREFIX, DEPLOYMENT_CHANGES_PREFIX))


def _a_symptom_of_more_than_one_sentence(answer: SubmittedPostmortem) -> list[str]:
    """The symptom, where it runs past one sentence.

    The symptom is the document's title. Asked for in a few words, a write-up
    gave two sentences - what nobody saw, then what was seen instead - and the
    title ran to fifteen words. A sentence's own closing stop is not a
    second sentence; a stop with more words after it is.
    """
    symptom = answer.symptom
    if symptom is None or not _A_SENTENCE_END.search(symptom.strip()):
        return []

    return [f"the {SYMPTOM_FIELD} [{symptom}] is more than one sentence - it is the "
            f"document's title, so say it in one, of a few words"]


def _a_symptom_over_its_words(answer: SubmittedPostmortem) -> list[str]:
    """The symptom, where it runs past the words the field tells the model.

    Asked for a few words, a title ran to twenty, half of it how the fault was
    found - the longest of every write-up recorded. Counted on the spaces, as a
    reader counts words, so a hyphenated name is one.
    """
    symptom = answer.symptom
    words = len(symptom.split()) if symptom is not None else 0
    if words <= SYMPTOM_WORDS_AT_MOST:
        return []

    return [f"the {SYMPTOM_FIELD} [{symptom}] runs to {words} words: say it in "
            f"{SYMPTOM_WORDS_AT_MOST} or fewer, as short as it can be"]


def _summary_sentences_of_more_than_one(answer: SubmittedPostmortem) -> list[str]:
    """The cause in plain words and what is still at risk, each where it runs
    past one sentence.

    Each is one sentence of the summary code writes around it: two, and the
    model is writing the summary again beside the record's own account of
    when, how bad and what was done.
    """
    return [f"the {field} [{said}] is more than one sentence - it is one sentence of the "
            f"executive summary, which says the rest itself, so say it in one"
            for field, said in ((CAUSE_IN_PLAIN_WORDS_FIELD, answer.cause_in_plain_words),
                                (STILL_AT_RISK_FIELD, answer.still_at_risk))
            if said is not None and _A_SENTENCE_END.search(said.strip())]


def _missing_checks_outside_the_factors(answer: SubmittedPostmortem) -> list[str]:
    """The root cause and each step of the cause, where it says a check is
    missing.

    A missing check is a contributing factor: it did not cause the incident,
    it failed to stop it. Told so in both fields' descriptions, three
    write-ups said one in the root cause or the chain anyway, in the words of
    the reading of the code they cited. The fault names the rule, not the
    words, so the claim moves rather than being said again in others. And says
    what to write where the missing check is itself the mechanism - a read
    path that does not check what it loaded - which moved out would leave the
    root cause empty.

    By the sentence the check is in, not the whole field: handed the root
    cause entire, a model moved the check out by deleting its sentence, and
    the mechanism the rest of that sentence said went with it.
    """
    said = [prose for prose in [answer.root_cause,
                                *(step.step for step in answer.causal_chain or [])]
            if prose is not None]

    return [f"[{sentence}] says a check is missing - a missing check or safeguard is one "
            f"of the {CONTRIBUTING_FACTORS_FIELD}: say it there, not in the "
            f"{ROOT_CAUSE_FIELD} or the {CAUSAL_CHAIN_FIELD}. Move only the words saying "
            f"no check was seen, and keep the rest of the sentence - what the code does - "
            f"where it is; where the missing check is itself the mechanism, say what the "
            f"code does rather than what it lacks"
            for prose in said
            for sentence in _A_SENTENCE_END.split(prose.strip())
            if _A_MISSING_CHECK.search(sentence)]


def _the_trigger_said_again(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each start of the trigger's revision the root cause names.

    The document states the trigger in a section of its own, and the brief
    says which change that is. A root cause naming its revision says it again,
    and what it owes is why that change broke the service. Only a revision can
    be held to, and a root cause naming the change in other words passes."""
    revision = given.trigger_revision
    if revision is None or answer.root_cause is None:
        return []

    return [f"the {ROOT_CAUSE_FIELD} names [{named}] by its revision - the document states "
            f"which change set it off; say why that change broke the service"
            for named in A_REVISION.findall(answer.root_cause)
            if the_revision_named(named, frozenset({revision})) == revision]


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

        faults.extend(_what_is_wrong_with_citing(f"the step [{step.step}]", "step", label,
                                                 given)
                      for label in step.cites
                      if label in given.hypotheses or label not in given.labels)

        # What the step ruled out is held to what the step is - a ruling
        # resting on nothing is an assertion - and named as itself, so the
        # model puts that entry right rather than a step of the chain.
        for ruled in step.ruled_out:
            entry = f"what was ruled out, [{ruled.what}],"

            if not ruled.cites:
                faults.append(f"{entry} cites no evidence - cite what ruled it out")

            faults.extend(_what_is_wrong_with_citing(entry, "entry", label, given)
                          for label in ruled.cites
                          if label in given.hypotheses or label not in given.labels)

    return faults


def _readings_beside_no_file_as_it_ran(answer: SubmittedPostmortem,
                                       given: Given) -> list[str]:
    """Each step citing Code-Fix's reading and none of the files shown as it
    ran, where any was shown.

    Six of six write-ups called the scrape config "Code-Fix's reading, nothing
    ran" while the file as it ran sat beneath that reading. Which file a step's
    claim is about cannot be told from its words, so any of them will do - and
    the fault names them all. A matter of labels, not of what the step says.
    """
    if not given.as_it_ran:
        return []

    reading = label_of(CODE_READING_PREFIX, 1)
    shown = "; ".join(f"[{label}] {what}" for label, what in given.as_it_ran.items())

    return [f"the {CAUSAL_CHAIN_FIELD} step [{step.step}] cites [{reading}], Code-Fix's "
            f"reading, and none of the files as they ran - {shown}: cite the one it rests "
            f"on for what the file says"
            for step in answer.causal_chain or []
            if reading in step.cites and not set(step.cites) & set(given.as_it_ran)]


def _what_is_wrong_with_citing(said: str, kind: str, label: str, given: Given) -> str:
    """Why a step, or what it ruled out, may not rest on this label, said for
    the model to act on - `said` is how the fault names it, and `kind` what it
    is asked to leave out."""
    if label in given.hypotheses:
        return (f"{said} cites [{label}], a candidate cause - a hypothesis, not "
                f"evidence; cite what was observed that shows it, or leave that {kind} "
                f"out")

    return f"{said} cites [{label}], which is not a label you were given"


def _factors_nothing_answers(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each factor not under its place's label, naming an item that is not the
    record's, or answered by nothing - and each proposal answering a label no
    factor has.

    Each link runs back to what was written before it: a factor names the
    record's items, by the numbers the brief gave them, and a proposal names
    the factors it answers, by label. Told to cite the answer's own items from
    its factors - items not yet written, by numbers it had to work out - a
    write-up cited each one off, and every number it gave was an item's.
    """
    on_record = {action_item_number(position)
                 for position in range(1, given.items_on_record + 1)}
    factors = answer.contributing_factors or []
    labels = {contributing_factor_label(position) for position in range(1, len(factors) + 1)}
    proposals = answer.action_items or []
    answered = {label for item in proposals for label in item.answers}
    faults: list[str] = []

    for position, factor in enumerate(factors, start=1):
        placed = contributing_factor_label(position)
        if factor.label != placed:
            faults.append(f"the contributing factor [{factor.factor}] is labelled "
                          f"[{factor.label or 'nothing'}] where its place makes it "
                          f"[{placed}] - label the factors CF-1, CF-2 and so on, in the "
                          f"order you give them")

        # Blank as well as absent: a strict tool guarantees a string arrives,
        # not that it says anything.
        if not (factor.had_it_been_otherwise or "").strip():
            faults.append(f"the contributing factor [{factor.factor}] does not say what would "
                          f"have gone differently had it been otherwise - say it in "
                          f"{HAD_IT_BEEN_OTHERWISE_FIELD}, with what {ROOT_CAUSE_FIELD} says "
                          f"still true")

        if not factor.addressed_by and factor.label not in answered:
            faults.append(f"nothing answers the contributing factor [{factor.factor}] - name "
                          f"one of the record's action items in its {ADDRESSED_BY_FIELD}, or "
                          f"propose one in {ACTION_ITEMS_FIELD} whose {ANSWERS_FIELD} name it")

        faults.extend(f"the contributing factor [{factor.factor}] names [{number}] in its "
                      f"{ADDRESSED_BY_FIELD}, which is not one of the record's action items - "
                      f"an item you propose names the factors it answers, in its "
                      f"{ANSWERS_FIELD}"
                      for number in factor.addressed_by if number not in on_record)

    faults.extend(f"the action item [{item.item}] answers [{label}], which is not the label "
                  f"of one of your contributing factors"
                  for item in proposals for label in item.answers if label not in labels)

    return faults


def _factor_labels_in_the_prose(answer: SubmittedPostmortem) -> list[str]:
    """Each factor's label written into a sentence the document publishes.

    The reader never sees a factor's label - the document says which items
    answer a factor by their numbers - so one written in the prose is a name
    that leads nowhere.
    """
    return [f"your answer writes [{label}] in its prose - a factor's label is for an "
            f"item's {ANSWERS_FIELD} alone, and the reader never sees it: say the factor "
            f"in words"
            for prose in answer.sentences() for label in _A_FACTOR_S_LABEL.findall(prose)]


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


def _ranges_after_an_opening_or_a_moment(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each figure written in as a range that the prose opens a range, or
    places a moment, before.

    A range is written in whole, so "between {G}" reads "between 21:41–22:01" -
    the range opened twice - and "first appears at {G}" reads "at 14:46–14:53",
    a span where the sentence wants its first minute. A word before a figure's
    name, as "line" before a number is: what the figure says decides, not how
    the sentence reads.
    """
    return [
        f"your answer writes [{before} {{{name}}}] - [{{{name}}}] is a range and says "
        f"its own: write it alone, or say over or during"
        for prose in answer.sentences()
        for before, word in pairwise(["", *prose.split()])
        if before.strip(AROUND_A_WORD).lower() in _WORDS_A_RANGE_MAY_NOT_FOLLOW
        and (named := A_FIGURE_NAME.fullmatch(word.strip(AROUND_A_WORD))) is not None
        and (name := named.group(1)) in given.figures
        and _A_RANGE_DASH.search(given.figures[name].written) is not None
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

