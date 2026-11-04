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
from functools import partial
from itertools import pairwise
from typing import Final

from argus_core import A_REVISION, the_revision_named
from argus_core.models import CodeUse, ThreadMessage, Turn, labelled
from pydantic import BaseModel

from agent_postmortem.figures import (
    A_FIGURE_NAME,
    AROUND_A_WORD,
    Figure,
    is_a_figure,
    names_in,
    units_against_their_figures,
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
    STOPS_THE_HARM_FIELD,
    SUBMIT_TOOL_NAME,
    SYMPTOM_FIELD,
    SYMPTOM_WORDS_AT_MOST,
    THE_CAUSE_FIELDS,
    TIMED_BY_FIELD,
    WENT_WELL_FIELD,
    WHY_IT_DID_NOT_HELP_FIELD,
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
from agent_postmortem.timing import LOWERED_AFTER_A_SPAN

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
# sentence wants one instant: "first appears at {G}" read "at 14:46–14:53",
# and "logged as on through {G}" read "through 14:46–14:53", where the
# sentence wants the minute the span ends.
_WORDS_THAT_OPEN_A_RANGE: Final = frozenset({"between", "from"})
_WORDS_THAT_PLACE_A_MOMENT: Final = frozenset({"at", "by", "since", "until", "till",
                                               "through", "to", "before", "after", "past",
                                               "around", "about", "near"})
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

# The Investigator, named in an item - the agent, not "the investigation",
# which reads fairly as the whole response.
_THE_INVESTIGATOR: Final = re.compile(r"\binvestigator\b", re.IGNORECASE)

# A flag named only as not the one that caused it: "the other flag change", "a
# second flag", "another flag", "an unrelated flag".
_ANOTHER_FLAG: Final = re.compile(r"\b(?:other|second|another|unrelated)\s+(?:\w+\s+)?flags?\b",
                                  re.IGNORECASE)

# A factor's label written as a word of the prose.
_A_FACTOR_S_LABEL: Final = re.compile(rf"\b{re.escape(CONTRIBUTING_FACTOR_PREFIX)}\d+\b")

# What a sentence says a line does with a stored figure beyond reading it: what
# the line takes it as, what it does in place of something else, whether it
# trusts or relies on it, how it treats it.
_A_ROLE: Final = re.compile(
    r"\bas (?:the|a|an|its|their|if|true|current)\b|\brather than\b|\binstead of\b"
    r"|\btrust|\brel(?:y|ies|ied|ying) on\b|\btreat",
    re.IGNORECASE)

# An "as" that says no role: "such as", "as well as", "as a result", and "as"
# a source says something ("as its docstring says").
_AN_AS_OF_NO_ROLE: Final = re.compile(
    r"\bsuch as\b|\bas well as\b|\bas a result\b"
    r"|\bas (?:(?!\bas\b)[^,.;])*?\b(?:says|said|shows)\b",
    re.IGNORECASE)

# What a line is said to do in place of reading the stored figure - work it
# out for itself - and what may stand between a list of lines and that: list
# words, and at most three words more.
_A_DERIVATION: Final = re.compile(
    r"\bderiv\w*|\bwork\w*(?:\s+\w+){0,3}\s+out\b|\badd\w*(?:\s+\w+){0,3}\s+up\b(?!\s+to\b)",
    re.IGNORECASE)
_A_LIST_GAP: Final = re.compile(r"(?:\s|,|\band\b|\bor\b|\bthe\b)*", re.IGNORECASE)
_CLOSE_AFTER: Final = re.compile(r"\s*(?:\w+\s+){0,3}")

# A working of two figures, as the model writes one: "{T13.1 - alert_raised}".
_A_WORKING: Final = re.compile(r"\{[^{}]+\s[-+*/]\s[^{}]+\}")
# What an item timed by a row may open with besides the first word of who said
# a line: an article the sentence lowers after the span, or Argus.
_A_TIMED_ITEM_S_OPENINGS: Final = frozenset({*LOWERED_AFTER_A_SPAN, "Argus"})
# What a first word may carry after the name it is - "Argus's", "Argus," - and
# still open the item with who did it.
_A_WORD_S_TAIL: Final = re.compile(r"(?:['’]s)?\W*$")

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
    deploy that set it off went to, the figures it gave, by name, each file
    shown as it ran, by label, and each change the walk alone read."""

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
    # Whether it was asked for the item that stops the harm - which it is
    # wherever a change put back left the harm standing.
    stops_the_harm_asked: bool = False
    # Whether it was asked for the item to find out why that change did not
    # help - which it is wherever the item that stops the harm is.
    why_it_did_not_help_asked: bool = False
    # Whether it was asked what the cause was - which it is wherever the
    # investigation named one (`undetermined`).
    cause_asked: bool = True
    # Each line outside Code-Fix's patch that uses what it changes, by label.
    uses: dict[str, CodeUse] = {}
    # Each change only Argus's own read of the flag provider's history found,
    # by label, with the flag it switched - the two ways the prose names a
    # change. Not one a candidate names, which the Investigator did weigh.
    read_by_the_walk_alone: dict[str, str] = {}
    # Each error rate the service's own log lines name ("account page error
    # rate"), lowercased - taken to be none of them the service's rate over all
    # its requests, which no log line names today.
    rates_the_logs_name: frozenset[str] = frozenset()
    # The first word of each name a line of the timeline is said by ("Argus",
    # "Investigator", "Code-Fix", a person's) - what an item timed by a row may
    # begin with, the document saying its time ahead of it.
    speakers: frozenset[str] = frozenset()
    # The labels of the timeline's own rows, the T and XW ones - the only rows
    # an item of what went well may be timed by: another row's first figure
    # is a claim's instant or a count, not when anything was done.
    timeline_rows: frozenset[str] = frozenset()
    # Each word in braces the evidence holds as its own text and no figure is
    # named - a format string a candidate or a diff quotes, '{amount_cents}'.
    # Quoted back, it is the evidence, and nothing is to be written in for it.
    quoted: frozenset[str] = frozenset()


def faults_in(answer: SubmittedPostmortem,
              leads: Sequence[ThreadMessage] = (),
              *,
              given: Given) -> list[str]:
    """Everything about this answer that has to be put right, or nothing."""
    return [fault for found in faults_by_check(answer, leads, given=given).values()
            for fault in found]


def faults_by_check(answer: SubmittedPostmortem,
                    leads: Sequence[ThreadMessage] = (),
                    *,
                    given: Given) -> dict[str, list[str]]:
    """What `faults_in` finds, under the check that found it and the place it
    is in - only those that found something.

    By the check and its place rather than by its words: a fault quotes the
    answer, so one the model was told of and wrote again in other words is a
    new string and the same fault, and one the same check finds somewhere new
    is a fault it was never told of. The place is the check's to say - the
    field, the lead, the step, the factor - and a figure's rule is one rule
    wherever the figure sits, so those are by the check alone."""
    checks: list[partial[_Placed] | partial[list[str]]] = [
        partial(_missing_fields, answer, given),
        partial(_how_it_served_left_unanswered, answer, given),
        partial(_what_stops_the_harm_left_unanswered, answer, given),
        partial(_why_it_did_not_help_left_unanswered, answer, given),
        partial(_a_symptom_of_more_than_one_sentence, answer),
        partial(_a_symptom_over_its_words, answer),
        partial(_summary_sentences_of_more_than_one, answer),
        partial(_missing_checks_outside_the_factors, answer),
        partial(_the_trigger_said_again, answer, given),
        partial(_one_role_said_of_lines_whose_rows_differ, answer, given),
        partial(_leads_left_unanswered, answer, leads),
        partial(_steps_resting_on_nothing, answer, given),
        partial(_readings_beside_no_file_as_it_ran, answer, given),
        partial(_a_reading_the_answer_says_otherwise_of, answer),
        partial(_factors_nothing_answers, answer, given),
        partial(_factor_labels_in_the_prose, answer),
        partial(_numbers_in_digits, answer, given),
        partial(_figures_spelled_out, answer),
        partial(_figures_said_in_a_word, answer),
        partial(_figures_nobody_gave, answer, given),
        partial(_ranges_after_an_opening_or_a_moment, answer, given),
        partial(_workings_that_make_no_sense, answer, given),
        partial(_units_against_their_figures, answer, given),
        partial(_the_service_s_rate_called_a_log_s, answer, given),
        partial(_revisions_nobody_read, answer, given),
        partial(_the_investigator_beside_what_it_never_read, answer, given),
        partial(_moments_timed_out_of_shape, answer, given)]

    found: dict[str, list[str]] = {}
    for check in checks:
        for fault in check():
            place, said = fault if isinstance(fault, tuple) else (None, fault)
            key = check.func.__name__ if place is None else f"{check.func.__name__} at {place}"
            found.setdefault(key, []).append(said)

    return found


# A fault with the place it is in, as the check that found it names the place.
type _Placed = list[tuple[str, str]]


def _a_step_s_place(position: int) -> str:
    """Where a step of the chain is, for a fault found in it."""
    return f"{CAUSAL_CHAIN_FIELD} {position}"


def _a_factor_s_place(position: int) -> str:
    """Where a contributing factor is, for a fault found in it."""
    return f"{CONTRIBUTING_FACTORS_FIELD} {position}"


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
                           leads: Sequence[ThreadMessage]) -> _Placed:
    """Which leads the answer said nothing about, by the label it knows them by.

    A required field whose names only the incident knows, and refused as one:
    the person who wrote a lead is owed the line, and a model told which lead it
    skipped has one thing to put right.
    """
    return [(label, f"the lead [{label}] was not answered - say in {LEAD_EFFECTS_FIELD} "
                    f"whether it changed what was done")
            for label, _lead in labelled(leads)
            if label not in answer.lead_effects]


def _missing_fields(answer: SubmittedPostmortem, given: Given) -> _Placed:
    """Which of the fields the tool declared required went unanswered.

    Read off the same list the tool declares, by name, rather than field by
    field: a field the model is told it must send and this does not check for
    is the pair going out of step in the direction nothing would notice. The
    cause fields only where they were asked for: where the investigation named
    no cause the tool leaves them out, and the document writes them itself.
    """
    not_asked = frozenset() if given.cause_asked else THE_CAUSE_FIELDS

    return [(field, f"the field [{field}] was missing from your answer")
            for field in REQUIRED_FIELDS
            if getattr(answer, field) is None
            and field not in _UNANSWERED_BEFORE_IT_WAS_ASKED
            and field not in not_asked]


# Required fields whose absence means an answer recorded before the question
# existed - a live call always sends them - and so is never sent back: a retry
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


def _what_stops_the_harm_left_unanswered(answer: SubmittedPostmortem,
                                         given: Given) -> list[str]:
    """That the answer left out the item that stops the harm, where it was
    asked - a required field only some incidents are asked for, and refused as
    one: an optional field is one a model leaves out whenever its prose reads
    well without it."""
    if not given.stops_the_harm_asked or answer.stops_the_harm is not None:
        return []

    return [f"the field [{STOPS_THE_HARM_FIELD}] was missing from your answer"]


def _why_it_did_not_help_left_unanswered(answer: SubmittedPostmortem,
                                         given: Given) -> list[str]:
    """That the answer left out the item to find out why the change put back did
    not help, where it was asked - refused for the reason the item that stops
    the harm is."""
    if not given.why_it_did_not_help_asked or answer.why_it_did_not_help is not None:
        return []

    return [f"the field [{WHY_IT_DID_NOT_HELP_FIELD}] was missing from your answer"]


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


def _summary_sentences_of_more_than_one(answer: SubmittedPostmortem) -> _Placed:
    """The cause in plain words and what is still at risk, each where it runs
    past one sentence.

    Each is one sentence of the summary code writes around it: two, and the
    model is writing the summary again beside the record's own account of
    when, how bad and what was done.
    """
    return [(field, f"the {field} [{said}] is more than one sentence - it is one sentence of "
                    f"the executive summary, which says the rest itself, so say it in one")
            for field, said in ((CAUSE_IN_PLAIN_WORDS_FIELD, answer.cause_in_plain_words),
                                (STILL_AT_RISK_FIELD, answer.still_at_risk))
            if said is not None and _A_SENTENCE_END.search(said.strip())]


def _missing_checks_outside_the_factors(answer: SubmittedPostmortem) -> _Placed:
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
    said = [(place, prose)
            for place, prose in [(ROOT_CAUSE_FIELD, answer.root_cause),
                                 *((_a_step_s_place(position), step.step)
                                   for position, step in enumerate(answer.causal_chain or [],
                                                                   start=1))]
            if prose is not None]

    return [(place,
             f"[{sentence}] says a check is missing - a missing check or safeguard is one "
             f"of the {CONTRIBUTING_FACTORS_FIELD}: say it there, not in the "
             f"{ROOT_CAUSE_FIELD} or the {CAUSAL_CHAIN_FIELD}. Move only the words saying "
             f"no check was seen, and keep the rest of the sentence - what the code does - "
             f"where it is; where the missing check is itself the mechanism, say what the "
             f"code does rather than what it lacks")
            for place, prose in said
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


def _one_role_said_of_lines_whose_rows_differ(answer: SubmittedPostmortem,
                                               given: Given) -> _Placed:
    """Each sentence of the prose that names lines outside Code-Fix's patch of
    both kinds - one taking the field's value, one setting it against what a
    function of its own file returns - and says one role of them all.

    Told what each line does, row by row, write-ups still said the statement,
    the summary and the reconciliation all read the stored month "as the
    month's figure": the reconciliation's own row sets it against the
    purchases added up again. That they all read it is true, and passes; a
    role said of them together is said of one row wrongly. Only a sentence
    naming both kinds can, and only lines shown in rows can be held to it. One
    saying what the checking line does - its own row's verb, or "against" -
    tells them apart, and is the sentence the fault asks for."""
    if not given.uses:
        return []

    said = [(ROOT_CAUSE_FIELD, ROOT_CAUSE_FIELD, answer.root_cause),
            (CAUSE_IN_PLAIN_WORDS_FIELD, CAUSE_IN_PLAIN_WORDS_FIELD, answer.cause_in_plain_words),
            (STILL_AT_RISK_FIELD, STILL_AT_RISK_FIELD, answer.still_at_risk),
            *((_a_step_s_place(position), CAUSAL_CHAIN_FIELD, step.step)
              for position, step in enumerate(answer.causal_chain or [], start=1)),
            *((f"{_a_factor_s_place(position)} {field}", field, prose)
              for position, factor in enumerate(answer.contributing_factors or [], start=1)
              for field, prose in ((CONTRIBUTING_FACTORS_FIELD, factor.factor),
                                   (HAD_IT_BEEN_OTHERWISE_FIELD,
                                    factor.had_it_been_otherwise)))]

    return [(place,
             f"the {field} [{sentence}] says one thing of code whose rows differ - "
             f"{'; '.join(f'[{label}] {given.uses[label].does}' for label in named)} - say of "
             f"each only what its own row says")
            for place, field, prose in said
            if prose is not None
            for sentence in _A_SENTENCE_END.split(prose.strip())
            for named in [_the_rows_named_in(sentence, given.uses)]
            if _says_one_role_of_both_kinds(sentence, named, given.uses)]


def _says_one_role_of_both_kinds(sentence: str,
                                 named: list[str],
                                 uses: dict[str, CodeUse]) -> bool:
    """Whether a sentence naming these rows names both kinds, says a role of
    them, and says nothing of what the checking lines do."""
    checking = [label for label in named if uses[label].set_against_a_call]
    if not checking or len(checking) == len(named):
        return False

    if re.search(r"\bagainst\b", sentence, re.IGNORECASE) or any(
            re.search(rf"\b{re.escape(stem)}(?:e|es|ed|ing|s)?\b", sentence, re.IGNORECASE)
            for stem in {_the_stem_of(uses[label].does) for label in checking}):
        return False

    return bool(_A_ROLE.search(_AN_AS_OF_NO_ROLE.sub(" ", sentence))
                or _a_list_of_both_kinds_said_to_derive(sentence, uses))


def _a_list_of_both_kinds_said_to_derive(sentence: str, uses: dict[str, CodeUse]) -> bool:
    """Whether a sentence names rows of both kinds in one list - names joined
    by list words alone - and says, straight after it, that they work the
    figure out: "until the statement, the summary and the reconciliation
    derived it themselves". After the list only, and close to it: "the sum the
    reconciliation adds up" said beside a reader is the checking line's own
    act, and "the month would be derived" before the names is what the change
    meant."""
    for end, rows in _the_lists_in(sentence, uses):
        derivation = _A_DERIVATION.search(sentence, end)
        if (len({uses[label].set_against_a_call for label in rows}) == 2
                and derivation is not None
                and _CLOSE_AFTER.fullmatch(sentence[end:derivation.start()])):
            return True

    return False


def _the_lists_in(sentence: str, uses: dict[str, CodeUse]) -> list[tuple[int, set[str]]]:
    """Each run of names joined by list words alone, as where it ends and the
    rows it names - the longest name kept where two overlap."""
    named = sorted(((match.start(), match.end(), label)
                    for label, use in uses.items()
                    for name in _names_of(label, use)
                    for match in re.finditer(
                        rf"(?<![\w/.]){_in_either_number(name)}(?![\w/])", sentence,
                        re.IGNORECASE)),
                   key=lambda span: (span[0], span[0] - span[1]))
    lists: list[tuple[int, set[str]]] = []

    for start, stop, label in named:
        if lists and (start < lists[-1][0] or _A_LIST_GAP.fullmatch(sentence[lists[-1][0]:start])):
            lists[-1] = (max(lists[-1][0], stop), lists[-1][1] | {label})
        else:
            lists.append((stop, {label}))

    return lists


def _the_stem_of(does: str) -> str:
    """The stem of the verb a row's line is said by, which its verb's forms
    are spelled from: "compares" as "compar", so "compare", "compared" and
    "comparing" are it too, and "comparison", a noun, is not."""
    return does.split(maxsplit=1)[0].removesuffix("s").removesuffix("e")


def _the_rows_named_in(sentence: str, uses: dict[str, CodeUse]) -> list[str]:
    """The label of each row whose label, file or function a sentence names:
    the file by its path, its stem, the stem with spaces for underscores, or
    the stem's last word - whole words, in the singular or the plural, whatever
    their case."""
    return [label for label, use in uses.items()
            if any(re.search(rf"(?<![\w/.]){_in_either_number(name)}(?![\w/])", sentence,
                             re.IGNORECASE)
                   for name in _names_of(label, use))]


def _names_of(label: str, use: CodeUse) -> set[str]:
    """Every name a sentence may call a line by."""
    stem = use.path.rsplit("/", 1)[-1].removesuffix(".py")

    return {label, use.path, stem, stem.replace("_", " "), stem.replace("_", "-"),
            stem.rsplit("_", 1)[-1], *([use.function] if use.function else [])}


def _in_either_number(name: str) -> str:
    """A pattern for a name, singular or plural: +s, +es, or y to ies."""
    if name.endswith("y"):
        return rf"(?:{re.escape(name)}|{re.escape(name[:-1])}ies)"

    return rf"{re.escape(name)}(?:e?s)?"


def _steps_resting_on_nothing(answer: SubmittedPostmortem, given: Given) -> _Placed:
    """Each step citing no evidence, each label cited that was never given, and
    each hypothesis cited as though it were evidence.

    A candidate cause is the Investigator's guess, written before anything was
    tried. The chain says what happened, so a step rests on what was observed;
    a guess cited there reads as a fact, even beside evidence that is real.
    """
    faults: _Placed = []

    for position, step in enumerate(answer.causal_chain or [], start=1):
        place = _a_step_s_place(position)

        if not step.cites:
            faults.append((place, f"the step [{step.step}] in {CAUSAL_CHAIN_FIELD} cites no "
                                  f"evidence - cite the labels it rests on"))

        faults.extend((place, _what_is_wrong_with_citing(f"the step [{step.step}]", "step",
                                                         label, given))
                      for label in step.cites
                      if label in given.hypotheses or label not in given.labels)

        # What the step ruled out is held to what the step is - a ruling
        # resting on nothing is an assertion - and named as itself, so the
        # model puts that entry right rather than a step of the chain.
        for ruled in step.ruled_out:
            entry = f"what was ruled out, [{ruled.what}],"

            if not ruled.cites:
                faults.append((place, f"{entry} cites no evidence - cite what ruled it out"))

            faults.extend((place, _what_is_wrong_with_citing(entry, "entry", label, given))
                          for label in ruled.cites
                          if label in given.hypotheses or label not in given.labels)

    return faults


def _readings_beside_no_file_as_it_ran(answer: SubmittedPostmortem,
                                       given: Given) -> _Placed:
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

    return [(_a_step_s_place(position),
             f"the {CAUSAL_CHAIN_FIELD} step [{step.step}] cites [{reading}], Code-Fix's "
             f"reading, and none of the files as they ran - {shown}: cite the one it rests "
             f"on for what the file says")
            for position, step in enumerate(answer.causal_chain or [], start=1)
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


def _factors_nothing_answers(answer: SubmittedPostmortem, given: Given) -> _Placed:
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
    faults: _Placed = []

    for position, factor in enumerate(factors, start=1):
        placed = contributing_factor_label(position)
        place = _a_factor_s_place(position)
        if factor.label != placed:
            faults.append((place, f"the contributing factor [{factor.factor}] is labelled "
                                  f"[{factor.label or 'nothing'}] where its place makes it "
                                  f"[{placed}] - label the factors CF-1, CF-2 and so on, in "
                                  f"the order you give them"))

        # Blank as well as absent: a strict tool guarantees a string arrives,
        # not that it says anything.
        if not (factor.had_it_been_otherwise or "").strip():
            faults.append((place, f"the contributing factor [{factor.factor}] does not say "
                                  f"what would have gone differently had it been otherwise - "
                                  f"say it in {HAD_IT_BEEN_OTHERWISE_FIELD}, with what "
                                  f"{ROOT_CAUSE_FIELD} says still true"))

        if not factor.addressed_by and factor.label not in answered:
            faults.append((place, f"nothing answers the contributing factor [{factor.factor}] "
                                  f"- name one of the record's action items in its "
                                  f"{ADDRESSED_BY_FIELD}, or propose one in {ACTION_ITEMS_FIELD} "
                                  f"whose {ANSWERS_FIELD} name it"))

        faults.extend((place, f"the contributing factor [{factor.factor}] names [{number}] in "
                              f"its {ADDRESSED_BY_FIELD}, which is not one of the record's "
                              f"action items - an item you propose names the factors it "
                              f"answers, in its {ANSWERS_FIELD}")
                      for number in factor.addressed_by if number not in on_record)

    faults.extend((f"{ACTION_ITEMS_FIELD} {position}",
                   f"the action item [{item.item}] answers [{label}], which is not the label "
                   f"of one of your contributing factors")
                  for position, item in enumerate(proposals, start=1)
                  for label in item.answers if label not in labels)

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
    a span where the sentence wants its first minute. A set of minutes says its
    own minutes the same way, and is known by what it is: one of a single
    minute has no dash. A word before a figure's
    name, as "line" before a number is: what the figure says decides, not how
    the sentence reads.
    """
    return [
        (f"your answer writes [{before} {{{name}}}] - [{{{name}}}] is a set of minutes and "
         f"says its own: write it alone, or say in"
         if given.figures[name].a_set_of_minutes else
         f"your answer writes [{before} {{{name}}}] - [{{{name}}}] is a range and says "
         f"its own: write it alone, or say over or during")
        for prose in answer.sentences()
        for before, word in pairwise(["", *prose.split()])
        if before.strip(AROUND_A_WORD).lower() in _WORDS_A_RANGE_MAY_NOT_FOLLOW
        and (named := A_FIGURE_NAME.fullmatch(word.strip(AROUND_A_WORD))) is not None
        and (name := named.group(1)) in given.figures
        and (given.figures[name].a_set_of_minutes
             or _A_RANGE_DASH.search(given.figures[name].written) is not None)
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
    know which figure it meant. Not a word the evidence itself holds in braces:
    that is the evidence's text, quoted, and is left as written.
    """
    return [
        f"your answer names [{{{name}}}], which is no figure you were given - write a "
        f"figure's name exactly as it is shown after the figure, or say the size "
        f"with no number in it"
        for prose in answer.sentences()
        for name in names_in(prose)
        if name not in given.figures and name not in given.quoted
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


def _units_against_their_figures(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each figure the prose follows with another unit of what its own measures.

    Written in, "{series_before} seconds" on a figure of 215 ms reads "215 ms
    seconds": a misreading of the figure's scale, which nothing but the model
    can settle. The same unit said again is no fault - the document writes it
    once (`figures`).
    """
    return [
        f"your answer writes [{written}], but the document writes that figure in "
        f"with its own unit, {unit}: write the name alone"
        for prose in answer.sentences()
        for written, unit in units_against_their_figures(prose, given.figures)
    ]


# An error rate a log line names: up to three words before "error rate".
_A_LOGGED_RATE: Final = re.compile(r"(?:[a-z]+[ -]){1,3}error[ -]rate")
# The figures of the service's error rate over all its requests (`prompting`).
_THE_SERVICE_S_RATE: Final = re.compile(r"\{errors_[a-z_]+\}")


def rates_named_in(lines: Sequence[str]) -> frozenset[str]:
    """Each error rate the log lines name, lowercased, as `Given` holds them."""
    return frozenset(found.group(0) for line in lines
                     for found in _A_LOGGED_RATE.finditer(line.lower()))


def _the_service_s_rate_called_a_log_s(answer: SubmittedPostmortem, given: Given) -> list[str]:
    """Each sentence giving the service's error rate over all its requests as a
    rate the service's own logs name.

    Labelled only "Error rate" and then over all its requests, a write-up still
    called the figure the account page's, beside a log line warning of that
    page's own rate - once in eight on the incident, in the item telling a
    reader how to see the harm end. The name comes off the record's own lines,
    so the rule holds for any service.
    """
    faults = []
    for prose in answer.sentences():
        for name in sorted(given.rates_the_logs_name):
            spelled = r"[ -]".join(re.escape(word) for word in re.split(r"[ -]", name))
            for found in re.finditer(rf"{spelled}[^.{{}}]{{0,80}}({_THE_SERVICE_S_RATE.pattern})",
                                     prose, re.IGNORECASE):
                faults.append(f"your answer gives [{found.group(1)}] as the {name}, but that "
                              f"figure is the service's error rate over all its requests - say "
                              f"it as the service's")
    return faults


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


def names_the_flag(prose: str, flag: str) -> bool:
    """Whether `prose` names `flag` as a whole name: not inside a longer one,
    which a flag's hyphens make a word boundary no help with - `checkout` is
    not named by `checkout-v2`."""
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", prose) is not None


def _the_investigator_beside_what_it_never_read(answer: SubmittedPostmortem,
                                                given: Given) -> _Placed:
    """Each item naming the Investigator beside a change it never read.

    Only Argus's own read of the flag provider's history found such a change,
    and write-ups said the Investigator ruled it out, set it aside, or picked
    another flag over it - two as "the other flag change", one by the flag's
    name. Its label is matched too, since the brief names the change by it. The
    whole item rather than a sentence, because one slip named the Investigator
    in the sentence before the one that set the flag aside.
    """
    if not given.read_by_the_walk_alone:
        return []

    faults: _Placed = []
    for place, item in answer.placed_sentences():
        if not _THE_INVESTIGATOR.search(item):
            continue

        named = [label for label, flag in given.read_by_the_walk_alone.items()
                 if re.search(rf"\b{re.escape(label)}\b", item) or names_the_flag(item, flag)]
        beside = named or (list(given.read_by_the_walk_alone)
                           if _ANOTHER_FLAG.search(item) else [])
        if beside:
            faults.append((place,
                           f"[{item}] names the Investigator beside [{', '.join(beside)}], found "
                           f"only by Argus's read of the flag provider's history - the "
                           f"Investigator never read it: credit it to that read, or leave the "
                           f"Investigator out of this item"))

    return faults


def _moments_timed_out_of_shape(answer: SubmittedPostmortem, given: Given) -> _Placed:
    """Each item of what went well the document cannot time as it stands: one
    saying a span of its own, or one timed by a row that is not the
    timeline's, or not opening with who did it.

    The document says the span ahead of the item, worked out from the row: a
    span of the model's says the time twice beside one, and is the model's
    span again beside none - which, set by the model, timed the wrong clause.
    Opening with who did it is what lets the item go on after the span as a
    sentence - "When the evidence could not support a cause, Argus escalated"
    does not. Nothing of an answer whose every item came as a plain sentence:
    that is the shape answers came in before rows were asked for.
    """
    if answer.lessons is None or answer.went_well_timed_by is None:
        return []

    faults: _Placed = []
    for position, (item, row) in enumerate(zip(answer.lessons.went_well, answer.went_well_timed_by,
                                               strict=False), start=1):
        place = f"{WENT_WELL_FIELD} {position}"
        if _A_WORKING.search(item):
            faults.append((place, f"[{item}] says a span of its own: the document says how "
                                  f"long after the alert a moment came, ahead of the item, "
                                  f"off the row named in {TIMED_BY_FIELD} - leave the span out"))
        if row is None:
            continue

        if row not in given.timeline_rows:
            faults.append((place, f"[{item}] is timed by [{row}], which is no row of the "
                                  f"timeline: name the T or XW row it happened on, or leave "
                                  f"{TIMED_BY_FIELD} out"))
        if (_A_WORD_S_TAIL.sub("", item.split(" ", 1)[0])
                not in _A_TIMED_ITEM_S_OPENINGS | given.speakers):
            faults.append((place, f"[{item}] is timed by [{row}], so the document says its "
                                  f"time ahead of it: begin it with who did it, as the row "
                                  f"names them"))

    return faults

