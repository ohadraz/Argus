"""What the model is asked, and the one shape its answer may take.

The model is handed the incident and the figures Argus already computed, and
asked only for the parts prose can carry - what went wrong, in what words, for
which audience. It writes no figure itself. Every figure in the document is
measured, and a model's restatement of one - rounded, worked out again, or
spelled out in words - is a second answer nobody can tell apart from the first.
So every figure it is shown carries a name after it, and it writes the name
where the figure goes; code writes the figure in (`figures`).

The answer arrives as a tool call rather than as prose. A document parsed back
out of paragraphs is a document that can be parsed wrongly, and the failure is
silent: a summary that mentions a figure in passing becomes the figure. A tool
call has fields.

What it reads is said the way a reader says it: every instant to the second,
and every span in days, hours and minutes. The record keeps what it measured -
the timeline is sorted on it - but a model told "0.10 hours", or six digits past
the second, either does the arithmetic or repeats the figure.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

from argus_core import A_REVISION, parse_iso, short_form, the_revision_named, to_iso
from argus_core.models import (
    NOTHING_RECORDED_AFTER_IT_WAS_OPENED,
    ActionItemType,
    Ask,
    ChangeEvent,
    CitedChange,
    CitedEvidence,
    DeploymentComparison,
    FailureMode,
    Lessons,
    LogsInTheGap,
    OpenedPullRequest,
    ThreadMessage,
    TimelineEntry,
    ToolDefinition,
    ToolResult,
    ToolResults,
    Transcript,
    Turn,
    changes_not_listed,
    labelled,
    no_logs_listed,
    shorter_than_the_rules_wait,
    whether_it_can_be_put_back,
)
from pydantic import BaseModel, field_validator

from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels, Unmeasured
from agent_postmortem.evidence import ActionRecord, DeploymentChangesRecord, IncidentEvidence
from agent_postmortem.figures import (
    A_MINUTE,
    ACTED_FIGURE,
    AFTER_THE_WAIT_FIGURE,
    ALERT_RAISED_FIGURE,
    ALERTED_AFTER_THE_ONSET_FIGURE,
    ARGUS_STOPPED_FIGURE,
    BACK_TO_NORMAL_FIGURE,
    BEGAN_FIGURE,
    CUSTOMER_LOSS_FIGURE,
    DURATION_FIGURE,
    ERRORS_AT_WORST_FIGURE,
    ERRORS_BEFORE_FIGURE,
    ERRORS_RISE_FIGURE,
    ERRORS_WHILE_BROKEN_FIGURE,
    HELD_FIGURE,
    LOG_READING_ENDED_FIGURE,
    LOGS_REACH_UNTIL_FIGURE,
    RULE_LOOKS_BACK_FIGURE,
    RULE_WAITS_FIGURE,
    SERIES_AT_WORST_FIGURE,
    SERIES_BEFORE_FIGURE,
    SERIES_WHILE_BROKEN_FIGURE,
    UNOBSERVED_FROM_FIGURE,
    Figure,
    figures_of,
    named,
    the_day_it_began,
    the_evidence_figures,
    the_evidence_named,
    the_finding_named,
    the_narration_figures,
    what_came_after_the_wait,
)
from agent_postmortem.log_groups import grouped, labels_reaching_into
from agent_postmortem.measuring import Measurements
from agent_postmortem.revisions import revisions_of
from agent_postmortem.sections import (
    ACTION_PREFIX,
    AS_IT_RAN_PREFIX,
    CODE_READING_PREFIX,
    DEPLOYMENT_CHANGES_PREFIX,
    NO_VERDICT_RECORDED,
    PRODUCTION_CHANGE_PREFIX,
    USES_OUTSIDE_PREFIX,
    OneCause,
    a_hypothesis_of,
    causes_of,
    inside_a_sentence,
    label_of,
    labels_of_the_narration,
    record_action_items_of,
    said_of_a_line,
    the_alert_labelled,
    trigger_of,
)
from agent_postmortem.sources import EngagementAnswer, NotPaged

# The tool's name and its fields, named once. Both ends of the exchange read
# them - the definition offered to the model, and the reader taking the call
# apart - and a spelling that differed between the two would leave a field
# quietly always missing.
SUBMIT_TOOL_NAME: Final = "submit_postmortem"
ROOT_CAUSE_FIELD: Final = "root_cause"
# The two sentences of the executive summary only the model can write - the
# cause for a reader outside the service, and what is still at risk. Code
# writes the rest of it from the record (`summary`).
CAUSE_IN_PLAIN_WORDS_FIELD: Final = "cause_in_plain_words"
STILL_AT_RISK_FIELD: Final = "still_at_risk"
# What a reader saw go wrong, as the document's title says it.
SYMPTOM_FIELD: Final = "symptom"
# The longest a title may run, in words as a reader counts them. Told to the
# model as well as held by the check: a limit it is never shown is a turn spent
# sending back an answer it had no way to know was too long.
SYMPTOM_WORDS_AT_MOST: Final = 16
ASSUMPTIONS_FIELD: Final = "assumptions"
# What each lead changed: one entry per lead, naming it by its label.
LEAD_EFFECTS_FIELD: Final = "lead_effects"
LEAD_FIELD: Final = "lead"
EFFECT_FIELD: Final = "effect"
# The cause as steps, each citing evidence by label (`T3`, `G3fa2`).
CAUSAL_CHAIN_FIELD: Final = "causal_chain"
STEP_FIELD: Final = "step"
CITES_FIELD: Final = "cites"
# What else the record ruled out, on the step that ties the incident to the
# change: each what and why, citing what ruled it out.
RULED_OUT_FIELD: Final = "ruled_out"
WHAT_FIELD: Final = "what"
# The conditions that had to hold, each under a label of its own (`CF-1`) and
# naming the record's own action items that answer it.
CONTRIBUTING_FACTORS_FIELD: Final = "contributing_factors"
LABEL_FIELD: Final = "label"
FACTOR_FIELD: Final = "factor"
# What a factor, had it been otherwise, would have changed with the root cause
# still true - the question a restatement of the root cause cannot answer.
HAD_IT_BEEN_OTHERWISE_FIELD: Final = "had_it_been_otherwise"
ADDRESSED_BY_FIELD: Final = "addressed_by"
# What the model proposes be done, each of one of the four kinds and naming the
# factors it answers by their labels.
ACTION_ITEMS_FIELD: Final = "action_items"
ITEM_FIELD: Final = "item"
ITEM_TYPE_FIELD: Final = "type"
ANSWERS_FIELD: Final = "answers"
# Google's three lists.
LESSONS_FIELD: Final = "lessons"
WENT_WELL_FIELD: Final = "went_well"
WENT_WRONG_FIELD: Final = "went_wrong"
GOT_LUCKY_FIELD: Final = "got_lucky"
# Whether the chain says why the change that set the incident off broke the
# service, rather than stopping at that change.
REACHES_A_CAUSE_FIELD: Final = "reaches_a_cause"
# Whether that cause rests on a reading of the source nothing ran, with nothing
# read showing what it rests on - said by the document from the answer, beside
# the root cause and in the review's box, rather than by the model in prose.
CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD: Final = "cause_rests_on_an_unrun_reading"
# Whether the log lines reaching into a stretch the metrics did not watch show
# the service serving as before - asked only where one reaches in, and said by
# the document from the answer rather than by the model in prose.
LOGS_SHOW_SERVING_AS_BEFORE_FIELD: Final = "logs_show_serving_as_before"

REQUIRED_FIELDS: Final = [
    ROOT_CAUSE_FIELD,
    CAUSE_IN_PLAIN_WORDS_FIELD,
    STILL_AT_RISK_FIELD,
    SYMPTOM_FIELD,
    CAUSAL_CHAIN_FIELD,
    CONTRIBUTING_FACTORS_FIELD,
    ACTION_ITEMS_FIELD,
    LESSONS_FIELD,
    REACHES_A_CAUSE_FIELD,
    CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD
]

# What a list of things that happened says when nothing did. Said rather than
# left as a heading over nothing, which tells the model there is something it
# has failed to see - and an empty list is itself what happened.
NOTHING: Final = "none"


class SubmittedRuledOut(BaseModel):
    """Something else the record ruled out, as the model wrote it, and the
    labels of what ruled it out."""

    what: str
    cites: list[str]


class SubmittedStep(BaseModel):
    """One step of the cause as the model wrote it, the labels it cited, and
    what else it ruled out there."""

    step: str
    cites: list[str]
    ruled_out: list[SubmittedRuledOut] = []


class SubmittedFactor(BaseModel):
    """One contributing factor as the model wrote it, the label it wrote it
    under, what it would have changed had it been otherwise, and the record's
    items it named. `None` where it did not say, which `checking` names."""

    label: str | None = None
    factor: str
    had_it_been_otherwise: str | None = None
    addressed_by: list[str]


class SubmittedItem(BaseModel):
    """One action item the model proposed, and the labels of the factors it
    answers. Unnumbered: its number is its place after the record's own.

    The item names the factors rather than a factor naming the item: the
    factors are written first, and told to cite items it had not yet written,
    by numbers it had to work out, a write-up cited each one number off."""

    item: str
    type: ActionItemType
    answers: list[str] = []


class SubmittedPostmortem(BaseModel):
    """What the model submitted, said as fields rather than as a mapping.

    The answer is read by four modules on its way to the page - the one that
    takes the call apart, the one that finds faults in it, the one composing the
    disclosures, and the one filling in the columns - and as a mapping each of
    those named its fields in strings. A field renamed here is now a type error
    in all four rather than a key that quietly returns nothing in three.

    Every field is optional, because finding out what is missing is the point:
    a required field the model left out is a fault to put back to it (see
    `checking`), not an answer that failed to arrive. `None` means unanswered,
    and reaches the document as an absent column rather than an empty one.

    The attribute names are the wire names above, and have to be: the call's
    arguments are validated into this as they stand.

    Nothing here refuses a submission, which is what the validators below are
    for. A field that did not arrive in its declared shape costs that field and
    no other: refusing the whole call would throw away a root cause the model
    wrote over an `assumptions` it sent as a bare string, and the document would
    then record as unanswered something that was answered. This agent spends its
    whole discipline telling an absence that was measured from one that was
    never asked, and an absence manufactured here would be neither.
    """

    root_cause: str | None = None
    cause_in_plain_words: str | None = None
    # Empty where nothing is: an answer, unlike `None`, which is none given.
    still_at_risk: str | None = None
    symptom: str | None = None
    assumptions: list[str] = []
    # What each lead changed, by the label the prompt gave it. Empty where
    # there were no leads to ask about, which is what nothing said means then.
    lead_effects: dict[str, str] = {}
    # The template's prose sections. `None` where unanswered, as the prose
    # fields above are; an empty list is an answer of none.
    causal_chain: list[SubmittedStep] | None = None
    contributing_factors: list[SubmittedFactor] | None = None
    action_items: list[SubmittedItem] | None = None
    lessons: Lessons | None = None
    # Never `None`: an answer that did not say reads as a chain that stopped at
    # the change, which unticks one box of the review. So `checking`, which
    # names a required field that is `None`, never puts it back - a retry spent
    # on it would ask every answer recorded before the question for a turn more.
    reaches_a_cause: bool = False
    # `None` where unanswered, which a live call never is: only an answer
    # recorded before the question was asked. Never put back for the reason
    # `reaches_a_cause` is not, and read as that answer's own root cause and the
    # review's older rule already say it (`reviewing`).
    cause_rests_on_an_unrun_reading: bool | None = None
    # `None` where unanswered - which is an answer only where it was not asked
    # (`checking`).
    logs_show_serving_as_before: bool | None = None

    def sentences(self) -> Iterator[str]:
        """Every sentence the answer would publish as written.

        Beside `with_each_sentence`, and the two read the same fields: a field
        one of them leaves out is prose the other's rule never sees - a figure
        the check never refuses, or a name never written in.
        """
        yield from (prose for prose in (self.root_cause, self.cause_in_plain_words,
                                        self.still_at_risk, self.symptom)
                    if prose is not None)
        yield from self.assumptions
        yield from self.lead_effects.values()
        for step in self.causal_chain or []:
            yield step.step
            yield from (ruled.what for ruled in step.ruled_out)
        for factor in self.contributing_factors or []:
            yield factor.factor
            if factor.had_it_been_otherwise is not None:
                yield factor.had_it_been_otherwise
        yield from (item.item for item in self.action_items or [])

        if self.lessons is not None:
            yield from self.lessons.went_well
            yield from self.lessons.went_wrong
            yield from self.lessons.got_lucky

    def with_each_sentence(self, rewrite: Callable[[str], str]) -> SubmittedPostmortem:
        """The answer with `rewrite` applied to every sentence it would publish,
        field for field the ones `sentences` reads."""
        def rewritten(prose: str | None) -> str | None:
            return rewrite(prose) if prose is not None else None

        return self.model_copy(update={
            ROOT_CAUSE_FIELD: rewritten(self.root_cause),
            CAUSE_IN_PLAIN_WORDS_FIELD: rewritten(self.cause_in_plain_words),
            STILL_AT_RISK_FIELD: rewritten(self.still_at_risk),
            SYMPTOM_FIELD: rewritten(self.symptom),
            ASSUMPTIONS_FIELD: [rewrite(each) for each in self.assumptions],
            LEAD_EFFECTS_FIELD: {lead: rewrite(effect)
                                 for lead, effect in self.lead_effects.items()},
            CAUSAL_CHAIN_FIELD: (None if self.causal_chain is None else
                                 [SubmittedStep(step=rewrite(step.step), cites=step.cites,
                                                ruled_out=[SubmittedRuledOut(
                                                    what=rewrite(ruled.what),
                                                    cites=ruled.cites)
                                                    for ruled in step.ruled_out])
                                  for step in self.causal_chain]),
            CONTRIBUTING_FACTORS_FIELD: (None if self.contributing_factors is None else
                                         [factor.model_copy(update={
                                             FACTOR_FIELD: rewrite(factor.factor),
                                             HAD_IT_BEEN_OTHERWISE_FIELD: rewritten(
                                                 factor.had_it_been_otherwise)})
                                          for factor in self.contributing_factors]),
            ACTION_ITEMS_FIELD: (None if self.action_items is None else
                                 [item.model_copy(update={ITEM_FIELD: rewrite(item.item)})
                                  for item in self.action_items]),
            LESSONS_FIELD: (None if self.lessons is None else
                            self.lessons.model_copy(update={
                                WENT_WELL_FIELD: [rewrite(each) for each in self.lessons.went_well],
                                WENT_WRONG_FIELD: [rewrite(each)
                                                   for each in self.lessons.went_wrong],
                                GOT_LUCKY_FIELD: [rewrite(each) for each in self.lessons.got_lucky]
                            }))
        })

    @field_validator(ROOT_CAUSE_FIELD, CAUSE_IN_PLAIN_WORDS_FIELD, STILL_AT_RISK_FIELD,
                     SYMPTOM_FIELD, mode="before")
    @classmethod
    def _prose_however_it_arrived(cls, value: Any) -> Any:
        """A prose field made to cost only itself.

        A number is written out: a figure where a sentence was asked for is
        still an answer, and one dropped here would be a root cause the model
        supplied and the document denies. Anything structural is read as
        unanswered instead, which `checking` then names and asks about.
        """
        if value is None or isinstance(value, str):
            return value

        return str(value) if isinstance(value, int | float) else None

    @field_validator(ASSUMPTIONS_FIELD, mode="before")
    @classmethod
    def _however_many_were_stated(cls, value: Any) -> Any:
        """The assumptions, as the list they were asked for.

        A model with one thing to say sends it as a string often enough to be
        worth reading as the list containing it. Anything else in the list that
        is not a sentence is dropped rather than refused - a disclosure that
        cannot be read costs one line, and refusing it would cost the document.
        """
        if isinstance(value, str):
            return [value]

        if isinstance(value, list):
            return [stated for stated in value if isinstance(stated, str)]

        return []

    @field_validator(LEAD_EFFECTS_FIELD, mode="before")
    @classmethod
    def _each_effect_by_its_lead(cls, value: Any) -> Any:
        """What each lead changed, keyed by the lead it names.

        An entry that is not an object naming a lead and an effect in words is
        dropped rather than refused, as an unreadable assumption is: it costs
        that lead, which the check then names and asks about again. Two entries
        for one lead keep the later.

        Already keyed by lead, it is taken as it stands - which is the shape
        the answer has once read, and the one anything building it directly
        hands over.
        """
        if isinstance(value, dict):
            return {lead: effect for lead, effect in value.items()
                    if isinstance(lead, str) and isinstance(effect, str)}

        if not isinstance(value, list):
            return {}

        return {
            entry[LEAD_FIELD]: entry[EFFECT_FIELD]
            for entry in value
            if isinstance(entry, dict)
            and isinstance(entry.get(LEAD_FIELD), str)
            and isinstance(entry.get(EFFECT_FIELD), str)
        }

    @field_validator(CAUSAL_CHAIN_FIELD, mode="before")
    @classmethod
    def _each_step_that_says_something(cls, value: Any) -> Any:
        """The steps that carry words, each with whichever citations are labels.

        A step with no words is no step and is dropped. One whose citations
        arrived in the wrong shape still said something, so it is kept citing
        nothing - which the check then names, rather than this dropping a claim
        the model made.
        """
        if not isinstance(value, list):
            return None

        return [
            entry if isinstance(entry, SubmittedStep)
            else SubmittedStep(step=entry[STEP_FIELD],
                               cites=_the_strings_in(entry.get(CITES_FIELD)),
                               ruled_out=_what_was_ruled_out(entry.get(RULED_OUT_FIELD)))
            for entry in value
            if isinstance(entry, SubmittedStep)
            or (isinstance(entry, dict) and isinstance(entry.get(STEP_FIELD), str))
        ]

    @field_validator(CONTRIBUTING_FACTORS_FIELD, mode="before")
    @classmethod
    def _each_factor_that_says_something(cls, value: Any) -> Any:
        """The factors that carry words, each with whichever names are strings."""
        if not isinstance(value, list):
            return None

        return [
            entry if isinstance(entry, SubmittedFactor)
            else SubmittedFactor(label=_a_string_or_none(entry.get(LABEL_FIELD)),
                                 factor=entry[FACTOR_FIELD],
                                 had_it_been_otherwise=_a_string_or_none(
                                     entry.get(HAD_IT_BEEN_OTHERWISE_FIELD)),
                                 addressed_by=_the_strings_in(entry.get(ADDRESSED_BY_FIELD)))
            for entry in value
            if isinstance(entry, SubmittedFactor)
            or (isinstance(entry, dict) and isinstance(entry.get(FACTOR_FIELD), str))
        ]

    @field_validator(ACTION_ITEMS_FIELD, mode="before")
    @classmethod
    def _each_item_of_a_declared_kind(cls, value: Any) -> Any:
        """The proposals in words, each of one of the four kinds.

        A kind nobody declared is a proposal nobody can file, and costs that
        proposal alone.
        """
        if not isinstance(value, list):
            return None

        kinds = {kind.value for kind in ActionItemType}

        return [
            entry if isinstance(entry, SubmittedItem)
            else SubmittedItem(item=entry[ITEM_FIELD], type=ActionItemType(entry[ITEM_TYPE_FIELD]),
                               answers=_the_strings_in(entry.get(ANSWERS_FIELD)))
            for entry in value
            if isinstance(entry, SubmittedItem)
            or (isinstance(entry, dict)
                and isinstance(entry.get(ITEM_FIELD), str)
                and entry.get(ITEM_TYPE_FIELD) in kinds)
        ]

    @field_validator(LESSONS_FIELD, mode="before")
    @classmethod
    def _the_three_lists(cls, value: Any) -> Any:
        """Each list as far as it is sentences; a list left out is an empty one.

        Already three lists, it is taken as it stands - the shape anything
        building an answer directly hands over, as with every field here.
        """
        if isinstance(value, Lessons):
            return value

        if not isinstance(value, dict):
            return None

        return Lessons(went_well=_the_strings_in(value.get(WENT_WELL_FIELD)),
                       went_wrong=_the_strings_in(value.get(WENT_WRONG_FIELD)),
                       got_lucky=_the_strings_in(value.get(GOT_LUCKY_FIELD)))

    @field_validator(REACHES_A_CAUSE_FIELD, mode="before")
    @classmethod
    def _only_a_plain_yes(cls, value: Any) -> Any:
        """Yes only where the model said so plainly. The box this ticks is one a
        person signs off on, so "yes" in words, a one or a null reads as no."""
        return value is True

    @field_validator(LOGS_SHOW_SERVING_AS_BEFORE_FIELD, CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD,
                     mode="before")
    @classmethod
    def _a_plain_yes_or_no(cls, value: Any) -> Any:
        """Yes or no only where the model said one plainly. Anything else is
        unanswered, which `checking` asks about where it was asked - rather than
        a refusal of the whole call, or a guess the document then says."""
        return value if isinstance(value, bool) else None


def _the_strings_in(value: Any) -> list[str]:
    """The sentences in a list, and nothing where there is no list."""
    if not isinstance(value, list):
        return []

    return [each for each in value if isinstance(each, str)]


def _a_string_or_none(value: Any) -> str | None:
    """A sentence, or unanswered where what arrived is not one."""
    return value if isinstance(value, str) else None


def _what_was_ruled_out(value: Any) -> list[SubmittedRuledOut]:
    """What a step ruled out, read as a step is: an entry with no words is
    dropped, one citing in the wrong shape is kept citing nothing, and a list
    that is not one rules out nothing - the step stands either way."""
    if not isinstance(value, list):
        return []

    return [SubmittedRuledOut(what=entry[WHAT_FIELD],
                              cites=_the_strings_in(entry.get(CITES_FIELD)))
            for entry in value
            if isinstance(entry, dict) and isinstance(entry.get(WHAT_FIELD), str)]


def _a_list_of(item_properties: dict[str, Any],
               required: list[str],
               description: str) -> dict[str, Any]:
    """An array-of-objects property, each object in the shape given."""
    return {
        "type": "array",
        "items": {"type": "object", "properties": item_properties, "required": required},
        "description": description
    }


_SENTENCES: Final[dict[str, Any]] = {"type": "array", "items": {"type": "string"}}

# What another agent's words are not, said where its rows are shown. The
# candidates' "the shop itself kept serving normally" and Code-Fix's "samples
# stop while the shop keeps serving" came back in thirteen root causes of
# fifteen as what happened.
_NOT_WHAT_HAPPENED: Final = "is not what happened unless a row of the record shows it"

# What a check the record does not show is written as, said in the two fields a
# missing safeguard is written in. Said once in the tool's description, a
# write-up still gave "nothing checked output quality before it reached
# production" as a factor and as what went wrong.
_A_SAFEGUARD_NOBODY_SAW: Final = (
    "A safeguard the record does not show is one not seen, never one absent: "
    "write that no check was seen, not that none ran."
)

# Said beneath what Code-Fix read. Its reading was restated more absolutely
# than it was given, both ways: "nothing in main does that" became "nothing in
# the running code works it out", and "by default it only reports" became
# "report-only".
_SAY_IT_NO_WIDER_THAN_IT_WAS_READ: Final = (
    "Say what the files Code-Fix read do, with the conditions it gives - a "
    "default as a default, never as all it does - and no wider: 'nothing in the "
    "files it read', never 'nothing in the code'."
)


SUBMIT_POSTMORTEM = ToolDefinition(
    name=SUBMIT_TOOL_NAME,
    description=(
        "Submit the postmortem for this incident. Every field is required. "
        "Write no figure yourself anywhere in your answer - no time, duration, "
        "percentage, count or amount, not in digits and not spelled out in "
        "words. Every figure you are shown is followed by its name in braces, "
        f"like {{A3}} or {{{DURATION_FIGURE}}}: where your prose states one, write "
        "its name, braces and all, and the document writes the figure in. A "
        "figure you were not shown but could work out from two you were - the "
        "span between two instants, how far one share is above another, how "
        "many times one is the other - is written as that working, braces and "
        f"all: {{{BACK_TO_NORMAL_FIGURE} - {BEGAN_FIGURE}}}, "
        f"{{T3.1 - {ALERT_RAISED_FIGURE}}}, "
        f"{{{ERRORS_AT_WORST_FIGURE} / {ERRORS_BEFORE_FIGURE}}}. The document "
        "works it out from the figures as you were shown them. Say any other "
        "size with no number in it, not even in a word - \"most requests\", "
        "\"for several minutes\", never \"twenty minutes\", \"a third\" or "
        "\"tripled\". A number is a figure even with a unit or a clock's marks "
        "on it (5m, 10ms, 3x, 12:05Z). Any other word with a digit in it is a "
        "name - a label you cite (T2, G3fa2, C1, AI-1), a version (v2), a "
        "revision, a pod - and is written as given. State only what the "
        "evidence you are shown says: where the record does not show something "
        "- a check that was or was not run, how many replicas - leave it out "
        "or say it was not seen."
    ),
    properties={
        ROOT_CAUSE_FIELD: {
            "type": "string",
            "description": (
                "What caused the incident, in one or two sentences, written "
                "for an engineer who was not on the call: the mechanism - why the "
                "change that set it off broke the service, as far as the evidence "
                "goes, a missing protection or not. Not the trigger, how it was "
                "confirmed, what resolved it or what was ruled out - the document "
                f"states each of those itself. Not one of the {CONTRIBUTING_FACTORS_FIELD}: "
                "a safeguard that would have stopped it with this mechanism unchanged "
                "is said there, not here. What the service did over the stretch the "
                "metrics did not watch is not the mechanism: the document says it itself. "
                "Whether it was verified the document says itself, from your answer to "
                f"{CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD} - do not say it."
            )
        },
        # Asked for the whole summary, write-ups left out how long, told the
        # reader what the brief told them, and called a draft fix a correction.
        # Code writes the record's part of it now (`summary`); these are the two
        # sentences it cannot.
        CAUSE_IN_PLAIN_WORDS_FIELD: {
            "type": "string",
            "description": (
                "What caused the incident, in one sentence for a reader who does not "
                "work on the service: no component names unless they are unavoidable. "
                "When it began, for how long, how bad it got, what customers lost and "
                "what was done the document says itself - say none of them. Say only "
                "what the record says - of a change, of the service, of the people - "
                "and nothing it does not. Where part of it rests only on a reading "
                "nothing ran, say that part as likely, in plain words, without "
                "mentioning the reading."
            )
        },
        STILL_AT_RISK_FIELD: {
            "type": "string",
            "description": (
                "What was still at risk when Argus stopped working on the incident, "
                "in one sentence for the same reader - what the fault still in place "
                "then could yet do, or the same thing able to happen again. Empty where "
                "nothing was. Not whether the service or its metrics were back, nor "
                "why - the summary says both. Not what Argus left to a person - a "
                "draft fix, automatic sync left off, a recommended action - which the "
                "document says itself. Say only what the record says: "
                "nothing after Argus stopped was read."
            )
        },
        SYMPTOM_FIELD: {
            "type": "string",
            "description": (
                "What went wrong as somebody using the service saw it, as short as "
                "it can be: it is the document's title. One sentence with no number "
                f"in it, never over {SYMPTOM_WORDS_AT_MOST} words - the thing that "
                "went wrong and what happened to it, with an active verb: 'Account "
                "pages failed'. Not the metric the alert fired on, not the cause - "
                "the document adds the change it began with itself - and not how it "
                "was found, which the document's Detection says. Where nobody using "
                "the service saw anything wrong, say that and what was seen instead, "
                "in that one sentence."
            )
        },
        ASSUMPTIONS_FIELD: {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Anything else the reader should know was assumed rather than "
                "measured. Empty is a valid answer."
            )
        },
        CAUSAL_CHAIN_FIELD: _a_list_of(
            {STEP_FIELD: {"type": "string"},
             CITES_FIELD: {**_SENTENCES,
                           "description": ("The labels of the evidence that shows "
                                           "this step: T3, G3fa2. Not rows that "
                                           "merely happened at the same time.")},
             RULED_OUT_FIELD: _a_list_of(
                 {WHAT_FIELD: {"type": "string"},
                  CITES_FIELD: {**_SENTENCES,
                                "description": "The labels of what ruled it out."}},
                 [WHAT_FIELD, CITES_FIELD],
                 "What else the record ruled out at this step, each what it was and "
                 "why. Empty on every step but the one that ties the incident to the "
                 "change that set it off.")},
            [STEP_FIELD, CITES_FIELD, RULED_OUT_FIELD],
            "The cause as the five whys, from the symptom down: the first step is "
            "what users saw - or, where nobody using the service saw anything "
            "wrong, that and what was seen instead - and each step after it answers "
            "why the step directly before it happened. The first why says why the "
            "symptom happened, not the symptom again in more detail. Where the "
            "incident needed two things at once - something going wrong, and "
            "nothing in place to contain it - follow the one that leads to what set "
            f"it off; the other is one of the {CONTRIBUTING_FACTORS_FIELD}, not "
            "named in the chain. A safeguard that did not stop it is never a step "
            f"of its own: it is one of the {CONTRIBUTING_FACTORS_FIELD}. "
            "Every step cites at least one piece of "
            "evidence by its label. Date a change by its own row's instant - the T "
            "or P row that records it - never by an effect it had. A state a row "
            "read - how many replicas run a revision, which way a flag is set - is "
            "known as of the row that read it, by that row's instant, which is its "
            "first figure, as T3.1 is T3's - not from when the change was made. "
            "What else the record ruled out - an earlier change, a flag the "
            "provider showed unchanged, a candidate refuted - goes in the "
            f"{RULED_OUT_FIELD} of the step that ties the incident to the change "
            "that set it off, citing what ruled it out, and never as a step. An "
            "earlier change is ruled out only by the service measured healthy with "
            "it in place - in metrics read between it and the onset, in an alert "
            "that dates the first harm itself at or after a later change (at, where "
            "the two instants are the same), or after a "
            "confirmed action that left it there - never by how long before the "
            "onset it came. Where the record shows none of these, it was not ruled out: "
            "say so in that step itself. Stop where the evidence stops."
        ),
        CONTRIBUTING_FACTORS_FIELD: _a_list_of(
            {LABEL_FIELD: {
                 "type": "string",
                 "description": (
                     "CF-1 for the first factor, CF-2 for the next, and so on in the "
                     f"order you give them. Written here and in an item's {ANSWERS_FIELD}, "
                     "never in your prose: the reader never sees it."
                 )
             },
             FACTOR_FIELD: {"type": "string"},
             HAD_IT_BEEN_OTHERWISE_FIELD: {
                 "type": "string",
                 "description": (
                     "What would have gone differently had this been otherwise - "
                     "stopped, shortened or caught sooner - with what "
                     f"{ROOT_CAUSE_FIELD} says still true. A factor that only says the "
                     "root cause again cannot answer this: leave it out of the list."
                 )
             },
             ADDRESSED_BY_FIELD: {
                 **_SENTENCES,
                 "description": (
                     "The record's own action items that answer it, by the numbers the "
                     "record gives them: AI-1. Empty where none of them does. Never an "
                     "item you propose: that item names, in its own "
                     f"{ANSWERS_FIELD}, the factors it answers."
                 )
             }},
            [LABEL_FIELD, FACTOR_FIELD, HAD_IT_BEEN_OTHERWISE_FIELD, ADDRESSED_BY_FIELD],
            "Conditions that had to hold for the incident to happen and did not "
            "cause it alone - a safeguard that did not stop it, a gap in detection "
            "or review. A factor held before the incident began: what the response "
            "did, declined or left behind - an action taken or not, automatic sync "
            f"left off - is not one; where it went wrong, say it under {WENT_WRONG_FIELD}. "
            "Not the root cause again in other words: a factor is something that, "
            "had it been otherwise, would have stopped or shortened the incident "
            f"even with what {ROOT_CAUSE_FIELD} says still true. "
            f"{_A_SAFEGUARD_NOBODY_SAW} An alert finds what its rule watches, not the "
            "cause behind it: say a fault was found only by what the record shows "
            "found it. Each is answered by at least one action item: one of the "
            f"record's, named in its {ADDRESSED_BY_FIELD}, or one you propose, whose "
            f"{ANSWERS_FIELD} name it."
        ),
        ACTION_ITEMS_FIELD: _a_list_of(
            {ITEM_FIELD: {"type": "string"},
             ITEM_TYPE_FIELD: {"type": "string",
                               "enum": [kind.value for kind in ActionItemType]},
             ANSWERS_FIELD: {**_SENTENCES,
                             "description": (
                                 "The labels of the contributing factors it answers: "
                                 "CF-1. Empty where it answers none."
                             )}},
            [ITEM_FIELD, ITEM_TYPE_FIELD, ANSWERS_FIELD],
            "What should be done that the record does not already hold, each "
            "one thing a person could take on: two things to do are two items. "
            "Empty where the record's own "
            "items answer every factor. Propose nothing to confirm a cause the "
            "record already confirmed - a mitigation that worked, a hypothesis "
            "marked confirmed - and no check of what the evidence you are shown "
            "already shows: a diff states what changed. Where an F row says to "
            "check something a D row shows, say what the D row shows, and the item "
            "is what follows from it."
        ),
        LESSONS_FIELD: {
            "type": "object",
            # Said in the list the praise is written in: told how to work a
            # span out only in the tool's description, a write-up praised Argus
            # for acting "within seconds" when it took 41.
            "properties": {WENT_WELL_FIELD: {
                               **_SENTENCES,
                               "description": (
                                   "Where one says how quickly Argus did something, "
                                   "write the span as a working of two instants - a "
                                   "T or P row's instant is its first figure, as T3.1 "
                                   f"is T3's: {{T3.1 - {ALERT_RAISED_FIGURE}}}, not in "
                                   "words (\"within seconds\"). Set the span beside "
                                   "what it times - the thing its later instant dates "
                                   "- not after something else in the same sentence. "
                                   "Name what Code-Fix proposed without saying what it "
                                   "does: the action items and Code-Fix's own reading "
                                   "say that, with its conditions."
                               )
                           },
                           # Left off so a rollback holds, automatic sync was
                           # listed here as well as in the resolution and the
                           # record's own item - and called a failure when it
                           # went as designed. So was a draft fix nothing ran,
                           # and a stretch the metrics did not cover, which is
                           # a limit of the evidence rather than of the response.
                           WENT_WRONG_FIELD: {
                               **_SENTENCES,
                               "description": (
                                   "A change the response left in place on purpose, "
                                   "which one of the record's own action items undoes "
                                   "(automatic sync left off), went as designed and "
                                   "did not go wrong; so did what the design leaves "
                                   "to a person - a draft fix to review and merge. "
                                   "Not a limit of what the record shows - logs "
                                   "nobody read, metrics that stop short of the "
                                   "onset: the document says what was read, and "
                                   f"anything assumed is said in {ASSUMPTIONS_FIELD}. "
                                   "Not the root cause or a contributing factor again "
                                   "- the document says those already."
                               )
                           },
                           # Told only that any list may be empty, write-ups
                           # filled this one with what kind of fault it was
                           # and with a limit of the evidence - neither luck.
                           GOT_LUCKY_FIELD: {
                               **_SENTENCES,
                               "description": (
                                   "Something the record shows went the fortunate way "
                                   "by chance, and would have made it worse had it not. "
                                   "Empty where the record shows none. Not what kind of "
                                   "fault it was, which the impact already says, nor a "
                                   "limit of what the record shows, which is said in "
                                   f"{ASSUMPTIONS_FIELD} as what was assumed."
                               )
                           }},
            "required": [WENT_WELL_FIELD, WENT_WRONG_FIELD, GOT_LUCKY_FIELD],
            # Asked to weigh it, three write-ups of one incident in a row
            # weighed nothing. Every part of it is measured, so code writes
            # that lesson (`detection_lesson`), and none of the lists is the
            # place to say it again.
            "description": (
                "What went well, what went wrong, and where the incident got "
                "lucky - a risk that went unnoticed this time. Any list may be "
                f"empty. {_A_SAFEGUARD_NOBODY_SAW} How soon the alert came is "
                "weighed by the document already, from what was measured: say "
                "nothing of it here."
            )
        },
        REACHES_A_CAUSE_FIELD: {
            "type": "boolean",
            "description": (
                "Whether the chain says why the change that set the incident off "
                "broke the service, rather than stopping at that change. A step "
                "resting on F rows - a reading of the code nothing ran - counts: "
                "whether that leaves the cause unverified is "
                f"{CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD}'s to say. That a new "
                "version does worse is what the change did, not why it broke the "
                "service: answer false where the chain says the evidence does not "
                "show why."
            )
        },
        CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD: {
            "type": "boolean",
            "description": (
                f"Whether the mechanism in {ROOT_CAUSE_FIELD} rests on an F row - a "
                "reading of the code nothing ran - with no S or D row showing what it "
                "rests on. Where you answer true, the document says itself, beside the "
                "root cause, that the cause is unverified, and leaves its root-cause "
                f"review box for a person: say neither in {ROOT_CAUSE_FIELD}."
            )
        }
    },
    required=REQUIRED_FIELDS
)


def submit_postmortem_for(leads: Sequence[ThreadMessage],
                          logs_in_the_gap: LogsInTheGap | None = None) -> ToolDefinition:
    """The tool for this incident: the one every incident gets, a place to say
    what each lead changed where people wrote any, and one to say whether the
    logs show the service serving as before where any reach into a stretch the
    metrics did not watch.

    Only where they do. A field offered on an incident it does not fit is a
    question about nothing, and a request that changed for every incident - so
    that one is sent exactly as it always was.

    Required where offered: the document owes the person who wrote a lead an
    answer, and says how the service did over the stretch from the other, and
    an optional field is one a model leaves out whenever its prose reads well
    without it.
    """
    offered: dict[str, Any] = {}

    if leads:
        offered[LEAD_EFFECTS_FIELD] = _LEAD_EFFECTS

    if logs_in_the_gap is not None and logs_in_the_gap.labels:
        offered[LOGS_SHOW_SERVING_AS_BEFORE_FIELD] = _LOGS_SHOW_SERVING_AS_BEFORE

    if not offered:
        return SUBMIT_POSTMORTEM

    return SUBMIT_POSTMORTEM.model_copy(update={
        "properties": {**SUBMIT_POSTMORTEM.properties, **offered},
        "required": [*REQUIRED_FIELDS, *offered]
    })


# Where what each lead changed is said, offered only where people wrote any.
_LEAD_EFFECTS: Final[dict[str, Any]] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            LEAD_FIELD: {
                "type": "string",
                "description": "The lead's label, as the incident gives it: L1, L2."
            },
            EFFECT_FIELD: {
                "type": "string",
                "description": (
                    "One sentence: whether this lead changed what was "
                    "done, and how - or that it did not."
                )
            }
        },
        "required": [LEAD_FIELD, EFFECT_FIELD]
    },
    "description": (
        "One entry for every lead people wrote in the incident's thread, "
        "saying whether it changed what was done."
    )
}

# Whether the logs show the service serving as before, offered only where a
# line reaches into a stretch the metrics did not watch. Told to bound the
# claim, a write-up bounded it in one sentence and said it unbounded in the
# next, two to four times in five; answered here and said by the document, no
# write-up of five said it anywhere else.
_LOGS_SHOW_SERVING_AS_BEFORE: Final[dict[str, Any]] = {
    "type": "boolean",
    "description": (
        "Whether the log lines that reach into the stretch the metrics did not "
        "watch show the service serving as it had before the metrics stopped. The "
        "document writes that sentence itself, bounded to when the logs were read."
    )
}


def opening_ask(evidence: IncidentEvidence, measured: Measurements) -> Transcript:
    """The whole incident in one message, with nothing left to go and fetch.

    A single `Ask` rather than a conversation: by the time a postmortem is
    written the evidence is settled, and a model given tools to read more
    would re-open an investigation that has already finished.
    """
    return [Ask(text="\n".join([
        _the_whole_incident(evidence, measured),
        "",
        f"Call {SUBMIT_TOOL_NAME} with your answer."
    ]))]


def _the_whole_incident(evidence: IncidentEvidence, measured: Measurements) -> str:
    """Everything Argus knows, written once and used by both asks.

    Every figure in it is shown with its name after it, which is how the
    answer states one.
    """
    figures = figures_shown(evidence, measured)

    return "\n".join([
        "Write the postmortem for the incident below.",
        "",
        f"Alert: {evidence.alert_title}",
        # The sender's own words, where it wrote any: for a check that measured
        # what it paged on - how many totals were wrong, since when - they are
        # the incident's first measurement, and shown the title alone a model
        # credited those figures to the Investigator and hedged them.
        *([f"What the alert said [{cited.label}]: {the_finding_named(cited.text)}"
           for cited in the_alert_labelled(evidence)]),
        f"Alert raised: {_shown(ALERT_RAISED_FIGURE, figures)}",
        _whether_anybody_was_paged(measured.engaged),
        *_how_long_the_rule_waits(evidence, measured, figures),
        *_how_long_it_was_broken(measured, evidence, figures),
        f"Argus held the incident for {_shown(HELD_FIGURE, figures)}, "
        f"until {_shown(ARGUS_STOPPED_FIGURE, figures)}. That is how long the response took, "
        f"not how long the fault lasted - leave it out of your answer.",
        *_what_the_error_rate_did(measured.error_rates, measured.error_rates_unmeasured,
                                  measured.unobserved_from is not None,
                                  _the_logs_reaching_in(evidence, measured), figures),
        *_what_the_rules_series_did(measured.rule_series, measured.rule_series_query,
                                    measured.rule_series_unit, evidence,
                                    measured.error_rates, figures,
                                    is_the_error_rate=measured.rule_series_is_the_error_rate),
        _what_customers_lost(measured, figures),
        *(line
          for heading, cited, beneath in _the_evidence_by_kind(evidence,
                                                               measured.unobserved_from)
          for line in ["", heading,
                       *(f"  - [{_its_labels(each)}] {_under_its_label(the_evidence_named(each))}"
                         for each in cited),
                       *([] if beneath is None else [f"  - {beneath}"])]),
        "",
        "Action items the record already holds:",
        *(_the_record_items(evidence, measured) or [f"  - {NOTHING}"]),
        *([note] if (note := _rewriting_is_left_to_a_person(evidence)) else []),
        *_what_the_record_holds_of_the_fix(evidence.pull_request),
        *_what_set_it_off(evidence),
        "",
        f"Cite evidence in {CAUSAL_CHAIN_FIELD} by its label. In a contributing "
        f"factor's {ADDRESSED_BY_FIELD}, name the record's own action items that answer "
        f"it, by their number; an item you propose names the factors it answers in its "
        f"{ANSWERS_FIELD}, by their labels.",
        *_what_people_told_it(evidence.leads)
    ])


def _its_labels(cited: CitedEvidence) -> str:
    """The label a piece of evidence is shown under, and every other it goes by:
    `C1, also C2`."""
    return ", also ".join([cited.label, ", ".join(cited.also)] if cited.also else [cited.label])


def _under_its_label(text: str) -> str:
    """A row of several lines - a diff - with each line after the first
    indented under the row's label, so they read as the row's and not as rows
    of their own."""
    return text.replace("\n", "\n      ")


def figures_shown(evidence: IncidentEvidence, measured: Measurements) -> dict[str, Figure]:
    """Every figure the model is shown, by its name: what Argus measured, what
    the alert said, and what each piece of evidence states.

    One list for the asking and the reading of the answer alike - a figure
    shown and not on it is one the check refuses and nothing writes in.

    The walk's own lines apart from the rest: a time of day in one is Argus's,
    on a day it said, and in anything else is in its writer's words.
    """
    listed = _the_evidence_listed(evidence, measured.unobserved_from)
    walked = _the_walk_s_labels(evidence)
    day = the_day_it_began(evidence, measured)

    return (figures_of(evidence, measured)
            | the_evidence_figures([cited for cited in listed if cited.label not in walked], day)
            | the_narration_figures([cited for cited in listed if cited.label in walked], day))


def _the_walk_s_labels(evidence: IncidentEvidence) -> set[str]:
    """The labels of the narration's lines the walk said, not those outside it."""
    return {label
            for entry, label in zip(evidence.timeline, labels_of_the_narration(evidence.timeline),
                                    strict=True)
            if not entry.outside_the_walk}


def the_evidence_labelled(evidence: IncidentEvidence,
                          metrics_stopped_at: datetime | None = None) -> list[CitedEvidence]:
    """Every piece of evidence the model is shown, each under its own label:
    what the alert said, then the evidence listed beneath its headings.

    The label is what a step of the cause cites, so every line a claim could
    rest on has one and no two share it. Each kind is labelled on its own,
    and the logs by message rather than by place: a recorded answer is replayed
    in a run that read a different number of log lines, and a label counted
    across the kinds would then name a different line in every kind after the
    logs.

    `metrics_stopped_at` is where the logs are split (`grouped`), and every
    reader of what the model was shown passes it, so the text a step cites is
    the text it was shown.
    """
    return [*the_alert_labelled(evidence), *_the_evidence_listed(evidence, metrics_stopped_at)]


def _the_evidence_listed(evidence: IncidentEvidence,
                         metrics_stopped_at: datetime | None) -> list[CitedEvidence]:
    """The evidence listed beneath its headings, in the order it is shown."""
    return [cited
            for _, cited_of_a_kind, _ in _the_evidence_by_kind(evidence, metrics_stopped_at)
            for cited in cited_of_a_kind]


def _the_evidence_by_kind(evidence: IncidentEvidence,
                          metrics_stopped_at: datetime | None
                          ) -> list[tuple[str, list[CitedEvidence], str | None]]:
    """The evidence under the heading the model reads it beneath, in the order
    it is shown, with what is said beneath its rows - `None` where nothing is.

    The narration, the changes, the logs, the candidates and the actions are
    shown whether or not they hold anything: a heading over nothing tells the
    model there is something it has failed to see. Empty, the narration, the
    candidates and the actions say none - nothing happened, and that is what
    happened. The changes and the logs say what came of reading them instead,
    in the page's words: "none" there reads as asked and nothing there, and a
    model told that of a deploy history nobody asked says no change preceded
    the onset. The changes say it of each kind with no row, beneath the rows
    of the other: a toggle alone says nothing of the deploys, and is read as
    though it did.

    What each deployment it looked into changed and what Code-Fix read in the
    source are shown only where there is any: most incidents look into none,
    and a heading for them would say a read was missed.
    """
    narration = [CitedEvidence(label=label, text=_a_line_of_the_narration(entry))
                 for entry, label in zip(evidence.timeline,
                                         labels_of_the_narration(evidence.timeline),
                                         strict=True)]
    changes = the_changes_labelled(evidence)
    log_lines = grouped(evidence.log_lines, metrics_stopped_at)
    candidates = the_candidates_labelled(evidence)
    actions = _numbered(ACTION_PREFIX,
                        [_an_action_as_a_line(action) for action in evidence.actions])
    looked_into = the_deployment_changes_labelled(evidence)
    read_in_the_source = the_code_reading_labelled(evidence)
    as_it_ran = the_files_as_they_ran_labelled(evidence)
    uses_outside = the_uses_outside_labelled(evidence)

    return [
        ("What Argus did, in order:", narration, None if narration else NOTHING),
        ("Changes to production it read:",
         [CitedEvidence(label=cited.label, text=_a_change_as_a_line(cited.change))
          for cited in changes],
         changes_not_listed(evidence.deploys_reading, evidence.flags_reading,
                            {cited.change.kind for cited in changes})),
        ("Log lines it read, one per message:", log_lines,
         None if log_lines else no_logs_listed(evidence.logs_reading)),
        (f"Candidates it considered, in the Investigator's words - cite them; what they "
         f"claim {_NOT_WHAT_HAPPENED}:", candidates, None if candidates else NOTHING),
        ("Actions it took:", actions, None if actions else NOTHING),
        *([("What each deployment it looked into changed:", looked_into,
            _what_each_whole_diff_leaves_as_it_was(evidence, looked_into))]
          if looked_into else []),
        *([(f"What Code-Fix read in the source and proposed, in Code-Fix's words - nothing "
            f"ran its test or its fix, and what it claims {_NOT_WHAT_HAPPENED}:",
            read_in_the_source,
            " ".join(note for note in (_SAY_IT_NO_WIDER_THAN_IT_WAS_READ,
                                       _what_its_branch_did_not_hold(evidence),
                                       _what_it_read_as_it_ran(evidence),
                                       _the_diffs_of_what_it_names(evidence, looked_into))
                     if note) or None)]
          if read_in_the_source else []),
        *([("What ran, read at the revision running when the alert fired:", as_it_ran, None)]
          if as_it_ran else []),
        *([(f"How the code outside Code-Fix's patch uses what it changes, "
            f"{_where_the_uses_were_read(evidence)} by Argus:", uses_outside,
            " ".join(note for note in (
                f"Where [{label_of(CODE_READING_PREFIX, 1)}] says otherwise of these lines, "
                f"they stand.",
                _what_the_uses_say_of_what_ran(evidence)) if note))]
          if uses_outside else [])
    ]


def _what_each_whole_diff_leaves_as_it_was(evidence: IncidentEvidence,
                                           looked_into: list[CitedEvidence]) -> str | None:
    """Beneath the deployments: of each whose diff lists every file it
    changed, that a file it does not list is as it was before it - or nothing,
    where none does.

    A write-up called one side of a cause unverified three times, though the
    diff listed every file the deploy changed and the file that side rests on
    was not among them. Said only of a diff that lists them all: one cut short
    leaves the rest unknown.
    """
    said = [f"A file [{diff.label}] does not list is as it was at the revision [{diff.label}] "
            f"compares against."
            for record, diff in zip(evidence.deployment_changes, looked_into, strict=True)
            if record.lists_every_file]

    return " ".join(said) or None


def _what_its_branch_did_not_hold(evidence: IncidentEvidence) -> str | None:
    """Beneath what Code-Fix read: that the branch it read does not contain the
    revision that ran, and what follows - or nothing, where it does or nobody
    established it.

    Production ran a revision deployed from a branch never merged into the one
    Code-Fix read. A write-up's thinking saw it and its answer dropped it:
    nothing it was shown said that merged, the fix changes what runs only once
    a deploy carries it.
    """
    if evidence.fix_holds_what_ran is not False or evidence.fix_branch_read is None:
        return None

    return (f"[{label_of(CODE_READING_PREFIX, 1)}] was written against "
            f"{evidence.fix_branch_read}, which does not contain the revision running "
            f"when the alert fired: merged, its fix changes what runs only once a "
            f"deploy carries it.")


def _the_diffs_of_what_it_names(evidence: IncidentEvidence,
                                looked_into: list[CitedEvidence]) -> str | None:
    """Beneath what Code-Fix read: each revision it names whose own diff was
    read, and the row that diff is - or nothing, where it names none.

    Code-Fix reads a branch, and says when the deployed revision is not one it
    read. A write-up then asked somebody to check what that revision holds,
    beside the diff showing it: the reading and the diff were both in front of
    it, and nothing between them said they were about one revision. Only a
    deployment that was compared has a diff to say.
    """
    if evidence.fix_explanation is None:
        return None

    reading = label_of(CODE_READING_PREFIX, 1)
    named = A_REVISION.findall(evidence.fix_explanation)
    tied = [f"[{reading}] names revision {short} and [{diff.label}] is that revision's own "
            f"diff - say what it shows rather than ask for it to be checked."
            for record, diff in zip(evidence.deployment_changes, looked_into, strict=True)
            if record.comparison is DeploymentComparison.COMPARED
            for short in named
            if the_revision_named(short, frozenset({record.revision})) == record.revision]

    return " ".join(dict.fromkeys(tied)) or None


def _rewriting_is_left_to_a_person(evidence: IncidentEvidence) -> str | None:
    """Beneath the record's action items: that rewriting what the incident
    wrote wrong is a person's to do - or nothing, where the leading candidate is
    not that what was written is wrong. Said whether or not Code-Fix read
    anything: an incident with no reading can list the same thing.

    A write-up listed under what went wrong that only Code-Fix's repair script,
    which nothing had run, mends the totals already written short: a person
    running it is the design, and what is left short is still at risk."""
    leading = evidence.candidates[0] if evidence.candidates else None
    if leading is None or leading.failure_mode != FailureMode.SILENT_DATA_CORRUPTION:
        return None

    return (f"Rewriting what the incident wrote wrong is left to a person by design: say it "
            f"in {STILL_AT_RISK_FIELD} and the action items, never under {WENT_WRONG_FIELD}.")


def _what_it_read_as_it_ran(evidence: IncidentEvidence) -> str | None:
    """Beneath what Code-Fix read: the files it names that the revision that
    ran holds as the branch read does - or nothing, where there are none.

    Said rather than shown: the reading stands for what ran, and a row would
    repeat the file the reading already describes. For those files alone, and
    said so: told only that it stood for what ran, a write-up carried "nothing
    in main does that" - said of the whole branch - over to the running code.
    Not "of the branch alone" for the rest: told that, write-ups doubted what
    the record shows of other revisions, and proposed checking it.

    Said as the files it names, not ones it read: these are every file its
    reading names, and one it saw only three search lines of was said to have
    been read.
    """
    read = [ran for ran in evidence.files_as_they_ran if ran.as_read]
    if not read:
        return None

    reading = label_of(CODE_READING_PREFIX, 1)
    branch = evidence.fix_branch_read or "the branch it read"
    as_it_was = "as it was" if len(read) == 1 else "as they were"
    those = "that file" if len(read) == 1 else "those files"

    return (f"[{reading}] names {', '.join(ran.path for ran in read)} on {branch} "
            f"{as_it_was} at {read[0].revision[:7]}, which ran. What [{reading}] says of "
            f"{those} holds for what ran; what it says of the rest of {branch} does not.")


def _where_the_uses_were_read(evidence: IncidentEvidence) -> str:
    """Where the lines outside Code-Fix's patch were read: on the branch it
    read, where that is known. Said "read off the code" otherwise, which is all
    there is to say."""
    if evidence.fix_branch_read is None:
        return "read off the code"

    return f"read on {evidence.fix_branch_read}"


def _what_the_uses_say_of_what_ran(evidence: IncidentEvidence) -> str | None:
    """Beneath the lines outside Code-Fix's patch: which of their files ran as
    the branch holds them, and so which lines hold for what ran - or nothing,
    where no revision is known to have run.

    The lines are read on the branch, and a write-up applied them to the
    revision that ran - true that once only because nothing else had changed.
    Said as F1's files are: named where they hold, the rest said not to."""
    compared = [use for use in evidence.uses_outside if use.revision is not None]
    if not compared:
        return None

    branch = evidence.fix_branch_read or "the branch it read"
    revision = (compared[0].revision or "")[:7]
    holding = list(dict.fromkeys(use.path for use in compared if use.as_read))
    not_holding = [path for path in dict.fromkeys(use.path for use in compared)
                   if path not in holding]

    if not holding:
        return (f"These lines were read on {branch}, not at {revision}, which ran: what they "
                f"say does not hold for what ran.")

    one = len(holding) == 1
    said = (f"{_listed(holding)} {'is' if one else 'are'} on {branch} as "
            f"{'it was' if one else 'they were'} at {revision}, which ran: what these lines "
            f"say of {'it' if one else 'them'} holds for what ran")

    if not not_holding:
        return f"{said}."

    return f"{said}; what they say of {_listed(not_holding)} does not."


def _listed(names: list[str]) -> str:
    """Names as a sentence lists them."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def the_files_as_they_ran_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Each file Code-Fix's reading names that ran as other text than the
    branch read, under the label the model is shown it by - named by its path
    and the revision, then the file - or nothing, where there is none.

    Six of six write-ups called the file the cause turned on "Code-Fix's
    reading, nothing ran": right about where the text came from, since nothing
    in the record held the file as it ran. Public because the document lists
    it under the same label the prose cites it by, as it does the changes.

    Numbered in the order of their paths, not the order the reading names
    them: a reworded reading swapped two files' labels under a write-up
    recorded against the old ones, citing each for the other's claim.
    """
    shown = sorted((ran for ran in evidence.files_as_they_ran
                    if not ran.as_read and ran.content),
                   key=lambda ran: ran.path)

    return [CitedEvidence(label=label_of(AS_IT_RAN_PREFIX, position),
                          text=f"{ran.path} at {ran.revision[:7]}\n{ran.content}")
            for position, ran in enumerate(shown, start=1)]


def the_uses_outside_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Each line outside Code-Fix's patch that uses what it changes, and what
    the line does, under the label the model is shown it by - or nothing, where
    there is none.

    A write-up wrote "nothing derived the month from history" from a reading
    that counted the one reader adding the month up to check it among the ones
    trusting it. What each of those lines does is the code's to say. Public
    because the document lists it under the same label the prose cites it by,
    as it does the changes.
    """
    return [CitedEvidence(label=label_of(USES_OUTSIDE_PREFIX, position),
                          text=f"{use.name} at {use.path}:{use.line}"
                               f"{f', in {use.function}' if use.function else ''}: {use.does}")
            for position, use in enumerate(evidence.uses_outside, start=1)]


def the_code_reading_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """What Code-Fix said of the code, under the label the model is shown it
    by - or nothing, where it said nothing.

    Public because the document lists it under the same label the prose cites
    it by, as it does the changes.
    """
    if evidence.fix_explanation is None:
        return []

    return [CitedEvidence(label=label_of(CODE_READING_PREFIX, 1), text=evidence.fix_explanation)]


def the_deployment_changes_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """What each deployment the investigation looked into changed, under the
    label the model is shown it by - every line as it was read, one to a line.

    A deployment nothing was compared for is said in the write-up's own words:
    the read tier's answer was written for the Investigator, bracketed for a
    model and with advice to one - "what it shipped can [be read], by reading
    the repository" - which write-ups proposed as an item. It is a fact about
    the history rather than a diff, and its row says what the history held.

    Public because the document lists them under the same labels the prose
    cites them by, as it does the changes.
    """
    return _numbered(DEPLOYMENT_CHANGES_PREFIX,
                     [_what_a_deployment_read_found(looked_into)
                      for looked_into in evidence.deployment_changes])


def _what_a_deployment_read_found(looked_into: DeploymentChangesRecord) -> str:
    """A deployment's diff, every line as it was read - or, where nothing was
    compared, what the history held instead."""
    match looked_into.comparison:
        case DeploymentComparison.COMPARED:
            return "\n".join(looked_into.said)
        case DeploymentComparison.NOTHING_BEFORE_IT:
            return (f"{looked_into.revision} is the earliest deployment of "
                    f"{looked_into.service} the deployment history holds, so there was "
                    f"nothing before it to compare it against, and what it changed was not "
                    f"read.")
        case DeploymentComparison.NOT_DEPLOYED:
            return (f"The deployment history holds no deployment of {looked_into.service} "
                    f"at revision {looked_into.revision}, so nothing was compared.")


def the_changes_labelled(evidence: IncidentEvidence) -> list[CitedChange]:
    """Each change to production the investigation read, under the label the
    model is shown it by, with its reference as the prose writes it.

    Public because the document lists the changes under the same labels the
    prose cites them by, and a second counting would be a second chance to
    disagree about which change `P2` is. A revision is written short as the
    prose writes it (`revisions`), so a row and a sentence name it alike.
    """
    revisions = revisions_of(evidence)

    return [CitedChange(label=label_of(PRODUCTION_CHANGE_PREFIX, position),
                        change=change,
                        short_reference=(short_form(change.reference, revisions)
                                         if change.reference in revisions
                                         else change.reference))
            for position, change in enumerate(evidence.changes, start=1)]


def the_candidates_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Each candidate cause the investigation formed, under the label the model
    is shown it by.

    Public because a step of the cause may not rest on one - a candidate is a
    hypothesis, not evidence - and the check refusing such a step has to know
    which labels these are.
    """
    return [CitedEvidence(label=cause.label, also=cause.also, text=_a_cause_as_a_line(cause))
            for cause in causes_of(evidence.candidates)]


def _numbered(prefix: str, lines: list[str]) -> list[CitedEvidence]:
    return [CitedEvidence(label=label_of(prefix, position), text=line)
            for position, line in enumerate(lines, start=1)]


def _the_record_items(evidence: IncidentEvidence, measured: Measurements) -> list[str]:
    return [f"  - {item.number} ({item.type}, {item.status}): {item.text}"
            for item in record_action_items_of(evidence, measured.back_to_normal_at)]


def _what_the_record_holds_of_the_fix(pull_request: OpenedPullRequest | None) -> list[str]:
    """What Argus did with the fix it proposed, and that nothing after is known.

    Told only "Review and merge the proposed fix", write-ups said the fix passed
    review, and that a gap stayed open until a human reviewed it - neither in the
    record. Nor is the opposite: Argus never reads a pull request after opening
    it, and the incident went to a person with it in hand, so the claim it can
    make is what it did. Both directions are refused, since either one is a state
    nobody read. Told that, a summary said it to its reader, which the document
    already does beside the pull request. And that nothing ran the fix: told only
    it was a draft, a write-up praised it for correcting what it changed.
    Nothing where no pull request was opened.
    """
    if pull_request is None:
        return []

    return [f"{pull_request.name} is a draft Argus opened for a person to review "
            f"and merge. {NOTHING_RECORDED_AFTER_IT_WAS_OPENED}: do not say it "
            f"was reviewed, approved or merged, or that it was not - nor that the "
            f"record holds nothing, which the document says itself. Nothing ran its "
            f"test or its fix: say what it proposes, not that it corrects anything."]


def _what_set_it_off(evidence: IncidentEvidence) -> list[str]:
    """Which change the document states set the incident off - or nothing,
    where it states none.

    Told only that "the document states the trigger itself", write-ups still
    opened the root cause with the change: nothing they were shown said which
    change the document names, so the sentence pointed at nothing. Named, and
    nothing more: a root cause naming the change on its way to the mechanism
    is right, and "do not open with it" contradicted the brief's own account of
    what the root cause is.
    """
    trigger = trigger_of(evidence)
    if trigger is None:
        return []

    change = the_change_that_set_it_off(evidence)
    named = (f"the change [{change.label}]" if change is not None
             else _the_move_of(trigger.subject, trigger.from_state, trigger.to_state))
    suspected = " - suspected, not confirmed" if trigger.suspected else ""

    return [f"The document already states what set it off, in a section of its own: "
            f"{named}{suspected}."]


def _the_move_of(subject: str, from_state: str | None, to_state: str | None) -> str:
    """A trigger no change read dates, said as the move its candidate names -
    as the document's Trigger section says it, an end nobody recorded as
    unknown. It always names one end: a trigger nothing moved and nothing read
    dates is no trigger (`trigger_of`)."""
    return f"{subject} went from {from_state or 'unknown'} to {to_state or 'unknown'}"


def the_change_that_set_it_off(evidence: IncidentEvidence) -> CitedChange | None:
    """The change read that the document states set the incident off, under
    the label the model is shown it by - the deploy that carried it where one
    did, and the change dating the trigger otherwise. `None` where no trigger
    was established, or none of the changes read is it.

    Public because the answer is held to it (`conversation`): a root cause
    naming that deploy's revision says the trigger again.
    """
    trigger = trigger_of(evidence)
    if trigger is None:
        return None

    label = trigger.carried_by or trigger.dated_by
    if label is None:
        return None

    return next((cited for cited in the_changes_labelled(evidence) if cited.label == label), None)


def _a_line_of_the_narration(entry: TimelineEntry) -> str:
    """One line of the narration, worded as the document's timeline words it -
    the candidates it formed named by label."""
    return f"{to_iso(entry.at)} {entry.who}: {said_of_a_line(entry)}"


def _a_change_as_a_line(change: ChangeEvent) -> str:
    """A change the investigation read: when, what kind, to what, by whom, and
    what it did.

    The instant to the second whatever its source wrote, and a change nobody is
    named for said to be, rather than shown with a blank where the name goes.
    """
    return (f"{to_iso(parse_iso(change.occurred_at))} {change.kind} {change.reference} "
            f"by {change.actor or 'someone unnamed'}: {change.summary}")


def _a_cause_as_a_line(cause: OneCause) -> str:
    """A cause in its candidate's words, its failure mode, its confidence, and
    what became of it - or, where it stands for several, a line naming the
    move they blame and each of them so on a line of its own.

    Said in the best-ranked one's words alone, a cause standing for several
    shows one candidate's words and confidence as all of theirs, and the
    verdict as reached by each. So each says what became of it as the page's
    row does (`result_of`): two spellings of one fact read as two facts.
    """
    if not cause.also:
        lead = cause.lead
        return _in_its_own_words(lead.summary, lead.failure_mode, lead.confidence, cause.became)

    considered = a_hypothesis_of(cause)

    return "\n".join([
        f"Candidates blaming the same move of {cause.lead.subject}, each in its own words:",
        *(f"{member.label}: " + _in_its_own_words(member.summary, member.failure_mode,
                                                  member.confidence,
                                                  considered.result_of(member))
          for member in considered.members)
    ])


def _in_its_own_words(summary: str,
                      failure_mode: str | None,
                      confidence: float | None,
                      became: str) -> str:
    return f"{summary} [{failure_mode}, confidence {confidence}, {became}]"


def _an_action_as_a_line(action: ActionRecord) -> str:
    """An action, whether it left anything to put back, its verdict, and
    whether it still stands.

    Whether it can be put back is said in the page's own words: the brief said
    nothing of it, and a model guessed "reversible" a section away from a row
    saying "irreversible" - both the autonomy tier's words, about a restart.
    Only where there is a way back: one with none stands as "nothing to put
    back", and the same words beside it said it twice on one line.
    """
    way_back = (f" ({whether_it_can_be_put_back(action.has_a_way_back)})"
                if action.has_a_way_back else "")
    return (f"{action.action}{way_back} - "
            f"{action.verdict or NO_VERDICT_RECORDED}, {action.standing}")


def _what_people_told_it(leads: Sequence[ThreadMessage]) -> list[str]:
    """What people wrote in the incident's thread, each with what the
    investigation made of it - and the ask to say what each changed.

    The standing travels with the words because the two are one fact: the
    words alone read as advice Argus followed, and the standing alone as a
    verdict on nothing. A lead written too late to be weighed is said to be,
    rather than shown bare as one nobody doubted. And when it was weighed is
    said: before anything was tried, so a lead refuted then can name the
    cause an action later confirmed, and a document reporting the standing
    bare would say the person was wrong.

    Only where somebody wrote: a heading over nothing tells the model there is
    something it has failed to see.
    """
    if not leads:
        return []

    return [
        "",
        "What people working the incident wrote in its thread:",
        *(f"  - {_a_lead_as_a_line(label, lead)}" for label, lead in labelled(leads)),
        "Each was weighed on what the investigation had read, before anything was "
        "tried. Where the actions above say otherwise, the actions are the later word.",
        f"For each, say in {LEAD_EFFECTS_FIELD} whether it changed what was done."
    ]


def _a_lead_as_a_line(label: str, lead: ThreadMessage) -> str:
    """One lead: its label, who wrote it and when, its words, and its standing.

    Who by name where the chat platform gave one, and by its id for them where
    it could not: the one name Argus holds, and one a reader can look up.
    """
    who = lead.person_name or lead.person_id
    line = f"{label} ({who}, {to_iso(lead.written_at)}): \"{lead.text}\""

    if lead.weighing is None:
        return f"{line} - never weighed by the investigation"

    return (f"{line} - the investigation found it {lead.weighing.standing.value}: "
            f"{lead.weighing.reason}")


def opening_ask_again(asked: Transcript, faults: list[str]) -> Transcript:
    """The same incident put again, for a model that answered with no call.

    The last resort, and only reachable when there is no submission to refuse
    (see `rejecting`). It repeats what was asked rather than referring back to
    it, because a conversation the model did not take part in the shape of is
    not a conversation to continue.
    """
    return [
        *asked,
        Ask(text="\n".join([
            "Your previous answer could not be used:",
            *(f"  - {fault}" for fault in faults),
            "",
            f"Answer by calling {SUBMIT_TOOL_NAME}, and not in prose."
        ]))
    ]


def rejecting(asked: Transcript, submitted: Turn, faults: list[str]) -> Transcript:
    """The same conversation, with the submission answered and refused.

    Not a second conversation. The model's answer was a tool call, and a call
    is answered by its result - which is exactly where a refusal belongs: the
    model sees what it submitted, is told what was wrong with it, and corrects
    that rather than writing a fresh document from an instruction that arrived
    out of nowhere. It is also the only shape a provider will take, since one
    that has seen a tool call expects its result next.

    The result is marked failed, which is how a tool says "this is something
    to fix" rather than "this is what I found out".

    Every call the turn made is answered, not only the first: a provider
    expects one result per call, together, and a model that submitted twice -
    the second a placeholder - would otherwise be refused in a conversation
    the provider will not continue.
    """
    refusal = "\n".join([
        "Your postmortem was not accepted:",
        *(f"  - {fault}" for fault in faults),
        "",
        f"Call {SUBMIT_TOOL_NAME} again with the whole answer, corrected."
    ])

    return [
        *asked,
        submitted,
        ToolResults(results=[ToolResult(call_id=call.id, content=refusal, failed=True)
                             for call in submitted.tool_calls])
    ]


def _shown(name: str, figures: Mapping[str, Figure]) -> str:
    """The figure of that name as the model is shown it, with its name after it."""
    return named(name, figures[name])


def _how_long_it_was_broken(measured: Measurements,
                            evidence: IncidentEvidence,
                            figures: Mapping[str, Figure]) -> list[str]:
    """When the service broke, when it came back, and how long that was.

    Both endpoints, and the figure between them. A duration printed beside one
    of its ends invites the subtraction and loses it: the alert is not the
    onset, they differ by however long the rule took to trip, and a reader
    taking the difference between the alert and the recovery gets a number
    Argus did not report. A stated endpoint that disagrees with a stated value
    is the same defect this whole measurement was corrected for, one field
    further on.

    The start is the onset where one was measured, and the alert where none
    was - said either way, because a stretch dated from the alert is dated
    from the wrong end and a reader has to be able to see that it was.

    Separately, whether the figure is a measurement or a floor. A duration
    ending at a recovery the metrics showed and one cut short by the metrics
    running out are different facts, and printed alike the second reads as the
    first.

    A floor ends where Argus stopped working on the incident, and is said as
    that rather than as the incident closing: an escalated incident has not
    closed, and a model told it had wrote that it had - over a blind stretch
    that was still running.
    """
    dated_from = (
        "the onset" if measured.onset_at is not None
        else "the alert, since no onset could be measured"
    )

    if measured.unobserved_from is not None:
        # Not a stretch of trouble but a stretch the metrics did not cover. Said
        # as that, because "had not recovered" would describe a broken service,
        # and the window before the onset would read as though it were the
        # incident. And not as one nobody saw: told so, a model holding the
        # shop's own logs from inside it wrote that the record could not say how
        # the shop was doing - so the logs that reach into it are named.
        return [
            f"No metrics were collected from "
            f"{_shown(UNOBSERVED_FROM_FIGURE, figures)} ({dated_from}) onwards: the "
            f"metrics had still not resumed when Argus stopped working on the "
            f"incident. That is {_shown(DURATION_FIGURE, figures)} the metrics did "
            f"not cover, not a stretch the service is known to have spent in "
            f"trouble.",
            _the_logs_reaching_into(evidence, measured.unobserved_from, figures),
            # Where a line reaches in, the document says it from the answer named
            # here, which is asked for only then. Where none does, nothing is
            # known of it: told nothing either, a model is free to say the
            # service kept serving, unbounded. And how to cite them where the
            # chain says nobody saw anything wrong: those lines are what shows
            # it, so told only to say nothing of them elsewhere, a first step
            # citing them still said what they show.
            f"How the service did over that stretch is said by the document "
            f"itself, from your answer to {LOGS_SHOW_SERVING_AS_BEFORE_FIELD}: say "
            f"nothing of it anywhere else. Where the chain's first step says nobody "
            f"using the service saw anything wrong, cite those log lines for it "
            f"without saying what they show."
            if labels_reaching_into(evidence.log_lines, measured.unobserved_from) else
            "Nothing is known of how the service did over that stretch: say nothing of it."
        ]

    if measured.back_to_normal_at is None:
        return [
            f"Broken from {_shown(BEGAN_FIGURE, figures)} ({dated_from}). The service "
            f"was not back to normal by {_shown(ARGUS_STOPPED_FIGURE, figures)}, when Argus "
            f"stopped working on the incident, so it was broken for at least "
            f"{_shown(DURATION_FIGURE, figures)} - a lower bound, not a measurement, "
            f"and every impact figure below is bounded the same way."
        ]

    return [
        f"Broken from {_shown(BEGAN_FIGURE, figures)} ({dated_from}) to "
        f"{_shown(BACK_TO_NORMAL_FIGURE, figures)}, when the metrics show it back to "
        f"normal.",
        *_back_before(evidence.credited_action, measured, figures),
        f"That is {_shown(DURATION_FIGURE, figures)}, and every impact figure below "
        f"is measured over that stretch."
    ]


def _the_logs_reaching_into(evidence: IncidentEvidence,
                            metrics_stopped_at: datetime,
                            figures: Mapping[str, Figure]) -> str:
    """Which log lines read reach into the stretch the metrics did not cover,
    and how far - or that none do, said rather than left out, since an absent
    list reads the same as one nobody looked for. And where no logs were read,
    that: told none reached in, a model is told logs were looked at and said
    nothing of it. A read that came back empty is a read, not that: where the
    metrics stopped, the service gone quiet in its logs too is not nobody
    having looked.

    How far as a figure: told only which lines reached in, a model wrote that
    nothing was known after the onset. And what they are: told which and how
    far, one still wrote that the service could not be seen through the
    stretch, and quoted what the lines said of it in its next sentence.

    Then where the reading ended, since where the lines stop is as often where
    the reading did as where the service did: told only how far they reach, a
    model wrote that nothing was known of the shop after them.

    And that the service was seen through them: told they are its account, a
    write-up still said it kept serving while it went unobserved, citing them.
    Up to where they reach and no further - where they end before the reading
    did, the service may have stopped with its metrics.
    """
    if not evidence.log_lines and evidence.logs_read_until is None:
        return "No logs were read."

    labels = labels_reaching_into(evidence.log_lines, metrics_stopped_at)
    reached = (
        f"Log lines read reach into it until {_shown(LOGS_REACH_UNTIL_FIGURE, figures)}: "
        f"{', '.join(f'[{label}]' for label in labels)}. They are the service's own account "
        f"of that stretch: what they report there is what is known of how it was doing, "
        f"and up to then the service was seen through them."
        if labels else "No log line read reaches into it."
    )

    return f"{reached}{_where_the_reading_ended(evidence, figures)}"


def _where_the_reading_ended(evidence: IncidentEvidence, figures: Mapping[str, Figure]) -> str:
    """Where the furthest read of the logs ended, as a sentence to follow the
    lines' own - and at the alert, where it ended there, which is where it
    ends unless the investigation asked for more. Nothing where no read is
    recorded."""
    if evidence.logs_read_until is None:
        return ""

    when = ", when the alert was raised" if evidence.logs_read_until == evidence.alerted_at else ""

    return (f" The logs were read up to {_shown(LOG_READING_ENDED_FIGURE, figures)}{when} - "
            f"nothing after that was read.")


def _the_logs_reaching_in(evidence: IncidentEvidence, measured: Measurements) -> list[str]:
    """The labels of the log lines read that reach into a stretch the metrics
    did not cover - none where they covered it all."""
    if measured.unobserved_from is None:
        return []

    return labels_reaching_into(evidence.log_lines, measured.unobserved_from)


def _back_before(credited: ActionRecord | None,
                 measured: Measurements,
                 figures: Mapping[str, Figure]) -> list[str]:
    """That the service was back before the action credited with bringing it
    back - or nothing, where it was not.

    Said rather than left to the two times: a model shown an action credited
    with a recovery credits it, whatever order the times beside it are in.
    """
    if not measured.back_before_the_action or credited is None:
        return []

    return [
        f"It was back to normal by {_shown(BACK_TO_NORMAL_FIGURE, figures)}, before "
        f"{_shown(ACTED_FIGURE, figures)}, when Argus {inside_a_sentence(credited.action)} - "
        f"the action credited with ending it: the metrics show the service back before "
        f"that action, not because of it."
    ]


# Why the error rates went unmeasured, as the model is told it. Three gaps that
# read alike as an absent figure and are not alike: a read that came back empty
# is an outage of the metrics, and the other two are reads that answered - over
# a shorter memory than the fault's, or over none of the stretch it broke.
_WHY_UNMEASURED: Final[dict[Unmeasured, str]] = {
    Unmeasured.NOTHING_READ: "the metrics for the incident could not be read",
    Unmeasured.NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET: (
        "metrics were read, but none from the hour before the onset, so there is "
        "no calm level to measure a rise against"),
    Unmeasured.NO_MINUTE_WHILE_BROKEN: (
        "metrics were read, but none from while the service was broken")
}

# The same gap where the metrics stopped at the onset. Its own sentence, because
# the line before it says that stretch is not known to have been trouble, and
# "while the service was broken" would say it was.
_NONE_WHILE_UNOBSERVED: Final = "none were collected after the metrics stopped"


# Said of a figure the calm before the incident was too short to hold up to
# how far the rate goes on its own.
_NOT_TOLD_APART: Final = "can't be told apart from its normal variation"


def _what_the_error_rate_did(rates: ErrorRates | None,
                             unmeasured: Unmeasured | None,
                             unobserved: bool,
                             logs_reaching_in: Sequence[str],
                             figures: Mapping[str, Figure]) -> list[str]:
    """The error rate at every level worth reporting, each named for itself.

    One line per question. The rise answers attribution - how much of the
    traffic failed that would not have failed anyway - and the levels answer
    severity, which is what a reader means by "how bad was it". A single
    figure labelled as the error rate was being asked both: handed one, a
    model said in its own assumptions that the number was unusable and went to
    the per-minute logs for the severity it actually needed.

    Where it was not measured, why not. Every gap was once told to the model as
    metrics that could not be read, about a read that had returned six hours of
    them - all after an onset a week earlier - and the write-up described a
    monitoring outage.

    Said as the metrics' gap rather than the record's. Told the error rate was
    not known, a model that had cited the shop's own warned rate from its logs
    wrote that no error rate existed, and asked for the logs it had already read
    to be reviewed. And where the stretch was unobserved, its minutes are not
    called the ones the service was broken in: nothing says it was. The
    log lines reaching into it are pointed to: told only that the metrics did
    not measure it, a model wrote that the error rate over the stretch could
    not be measured, of one the shop's own logged rate covered. And by label:
    told only that they were the service's own account, a write-up still said
    no error rate existed for the stretch, beside a row whose figures there
    were the shop's logged rate. Not called a rate, since what a line's figures
    measure is the line's to say. And what they show is left to the field that
    says it: told here to say it, beside a gap paragraph telling it to say it
    nowhere else, the brief asked both ways.
    """
    if rates is None:
        reason = (
            _NONE_WHILE_UNOBSERVED
            if unobserved and unmeasured is Unmeasured.NO_MINUTE_WHILE_BROKEN
            else _WHY_UNMEASURED[unmeasured] if unmeasured is not None
            else None
        )
        why = f" - {reason}" if reason is not None else ""
        labels = ", ".join(f"[{label}]" for label in logs_reaching_in)
        logged = (f"; the log lines that reach into that stretch, {labels}, are the "
                  f"service's own account of it, so do not say nothing was measured; what "
                  f"they show is said by the document itself, from your answer to "
                  f"{LOGS_SHOW_SERVING_AS_BEFORE_FIELD}" if logs_reaching_in else "")

        return [f"Error rate: not measured by the metrics{why}{logged}."]

    return [
        f"Error rate before it began: {_shown(ERRORS_BEFORE_FIGURE, figures)}.",
        f"Error rate while it was broken: {_shown(ERRORS_WHILE_BROKEN_FIGURE, figures)}, "
        f"peaking at {_shown(ERRORS_AT_WORST_FIGURE, figures)}{_the_peak_held_to(rates)}.",
        _the_rise(rates, figures)
    ]


def _the_peak_held_to(rates: ErrorRates) -> str:
    """What the peak is beside how high the worst minutes go on their own -
    nothing where it went higher, which is the peak the line already says."""
    match rates.peaked_beyond_its_variation:
        case False:
            return " - no higher than the worst minutes of stretches as long before it began"
        case None:
            return f" - which {_NOT_TOLD_APART}"
        case True:
            return ""


def _the_rise(rates: ErrorRates, figures: Mapping[str, Figure]) -> str:
    """How much of the traffic failed that would not have otherwise - or that
    none did, or none anyone can tell from the rate's own variation.

    A rise at or below nothing is no rise. "-0.3% of traffic failed" says the
    opposite of what it means, and a model handed it explains a failure nobody
    measured; the levels beside it already say what the rate was. The figure
    itself stays unclamped where it is measured (`ErrorRates.rise`).

    Nor is a rise that stretches as long before it began reached on their own:
    a service idling between one and two percent goes above its average in
    half its quiet stretches, and a write-up told each one was a rise blames
    the incident for noise.
    """
    if rates.rise <= 0:
        return ("Rise above baseline: none - no more of the traffic failed while "
                "it was broken than before it began.")

    match rates.rose_beyond_its_variation:
        case False:
            return ("Rise above baseline: none beyond its normal variation - stretches as "
                    "long before it began averaged as high on their own.")
        case None:
            return (f"Rise above baseline: {_NOT_TOLD_APART} - the calm before it began was "
                    f"too short to say how high the rate goes on its own.")
        case True:
            return (f"Rise above baseline: {_shown(ERRORS_RISE_FIGURE, figures)} of traffic "
                    f"failed that otherwise would not have.")


def _what_customers_lost(measured: Measurements, figures: Mapping[str, Figure]) -> str:
    """The customer loss, as the page says it, and how it was measured.

    Argus's one direct measure of who the incident affected: never told it, a
    write-up over a loss of nothing said the shop only "appears to have kept
    serving". How it was measured, so it is weighed as a shortfall in takings
    rather than as a count of shoppers. A floor where the service was not seen
    back to normal, since the takings were counted with it still going.
    """
    if measured.loss is None:
        return "Customer loss: not estimated."

    unended = measured.back_to_normal_at is None
    bound = "; a lower bound, counted with the service not seen back to normal" if unended else ""

    if not measured.loss:
        return (f"Customer loss: none{' so far' if unended else ''} - the shop's takings over "
                f"the incident fell short of the same hours whole weeks earlier by no more "
                f"than those hours vary on their own, if at all{bound}.")

    return (f"Customer loss: {'at least ' if unended else ''}"
            f"{_shown(CUSTOMER_LOSS_FIGURE, figures)} - how far the shop's takings over the "
            f"incident fell short of the same hours whole weeks earlier, beyond how much "
            f"those hours vary on their own{bound}.")


def _whether_anybody_was_paged(engaged: EngagementAnswer | NotPaged | None) -> str:
    """Whether a person was paged for the incident, and the word for each act.

    Never told it, a model fills the gap from habit - an alert pages somebody -
    and a write-up said "the alert paged" in its chain of an incident its own
    assumptions said nobody was paged for. Told the fact, it has no gap to fill;
    told that a rule fires and a person is paged, it has one word for each.
    """
    if isinstance(engaged, NotPaged):
        paged = "Nobody was paged: no on-call incident was linked to this one."
    elif engaged is None:
        paged = "Whether anybody was paged could not be read."
    else:
        paged = "Somebody was paged: an on-call incident was linked to this one."

    return f"{paged} An alert rule fires; a person is paged."


def _how_long_the_rule_waits(evidence: IncidentEvidence,
                             measured: Measurements,
                             figures: Mapping[str, Figure]) -> list[str]:
    """How long the alert rule waits with its condition holding before it
    fires, which is part of the time from the onset to the alert - and how the
    alert came against that wait.

    Not told it, a write-up called the rule's own wait slow detection. Told it
    and not what was left of the gap after it, another counted the wait and
    called detection slow anyway. Said as a rule that fires at once where it
    waits for nothing, and as unread where nobody could read it - which is not
    the same rule. Nothing where no rule fired.
    """
    if measured.rule_wait_unread:
        return ["How long the alert rule waits before it fires could not be read."]

    if measured.rule_waits is None:
        return []

    if not measured.rule_waits:
        return [f"The alert rule fires as soon as its condition holds."
                f"{_the_alert_against_no_wait(evidence, measured, figures)}"
                f"{_the_condition_s_window(measured, figures)}"]

    return [f"The alert rule waits {_shown(RULE_WAITS_FIGURE, figures)} with its "
            f"condition holding before it fires: that wait is part of the time from "
            f"the onset to the alert - count it before calling detection slow."
            f"{_the_alert_against_its_wait(evidence, measured, figures)}"
            f"{_the_condition_s_window(measured, figures)}"]


def _the_alert_against_no_wait(evidence: IncidentEvidence,
                               measured: Measurements,
                               figures: Mapping[str, Figure]) -> str:
    """How long after the onset the alert of a rule that waits for nothing
    came, as a sentence to follow the rule's own - or nothing, where no onset
    was measured to take a gap from.

    Told only that the rule fires at once, a write-up left the whole gap from
    the onset to the alert unweighed. From a minute up, by its figure; under
    one, in words, as a wait's own gap is said.
    """
    after_the_onset = what_came_after_the_wait(evidence, measured)

    if after_the_onset is None:
        return ""

    if after_the_onset < timedelta(0):
        return " The alert came before the measured onset."

    if after_the_onset < A_MINUTE:
        return (" The alert came as soon as its condition held, as near as a measured "
                "onset - a whole minute - can tell.")

    return (f" The alert came {_shown(ALERTED_AFTER_THE_ONSET_FIGURE, figures)} after the "
            f"onset.")


def _the_condition_s_window(measured: Measurements, figures: Mapping[str, Figure]) -> str:
    """How far back the rule's condition looks, as a sentence to follow the
    wait's own - or nothing, for a check that looks back over no range.

    Part of the time from the onset to the alert can be that window filling:
    "5m with no sample" holds only once five minutes have passed with none.
    Told only that it may be, a write-up was left to find how much in the
    alert's words and subtract it.
    """
    if not measured.rule_looks_back:
        return ""

    return (f" Its condition looks back over {_shown(RULE_LOOKS_BACK_FIGURE, figures)}: up to "
            f"that much of the time from the onset to the alert is that window filling - "
            f"count it before calling detection slow.")


def _the_alert_against_its_wait(evidence: IncidentEvidence,
                                measured: Measurements,
                                figures: Mapping[str, Figure]) -> str:
    """How the alert came against its rule's wait, as a sentence to follow the
    wait's own - or nothing, where no onset was measured to take a gap from.

    From a minute after the wait, by its figure. Under a minute, in words: a
    measured onset is a whole minute, so seconds after the wait are inside
    what it can tell, and named they read as a lag. Sooner than the wait, as
    the page says it beside the gap - the condition held before the measured
    onset, or the series did not bear that out. Before the onset, as the page
    says that: no time from the onset is shorter than a wait when it is no
    time at all.
    """
    after_the_wait = what_came_after_the_wait(evidence, measured)

    if after_the_wait is None:
        return ""

    if measured.onset_at is not None and evidence.alerted_at < measured.onset_at:
        return " The alert came before the measured onset."

    if after_the_wait >= A_MINUTE:
        return (f" The alert came {_shown(AFTER_THE_WAIT_FIGURE, figures)} after that "
                f"wait ended.")

    if after_the_wait >= timedelta(0):
        return (" The alert came as soon as that wait allowed, as near as a measured "
                "onset - a whole minute - can tell.")

    shorter = shorter_than_the_rules_wait(_shown(RULE_WAITS_FIGURE, figures),
                                          measured.rule_held_before_the_onset)

    return f" The time from the onset to the alert is {shorter}."


def _what_the_rules_series_did(levels: RuleSeriesLevels | None,
                               query: str | None,
                               unit: str | None,
                               evidence: IncidentEvidence,
                               rates: ErrorRates | None,
                               figures: Mapping[str, Figure],
                               is_the_error_rate: bool) -> list[str]:
    """The series the alert rule evaluates, at the error rate's levels.

    Nothing at all where the metrics carry no such series - not a line saying it
    sat at nothing, which would describe a service whose answers had gone
    entirely. Its direction is said with it, because its worst is its lowest or
    its highest according to the rule, and the number alone does not say which.

    Named by the rule's query, where its series could be followed to one: the
    alert's words are the rule's condition - its threshold and its wait - and a
    series named by them is named by when it fires. The query goes as written,
    because its numbers are none of the incident's and tagged as figures they
    would be offered as some; and the model is asked to say it in words, since
    a reader does not read PromQL. Beside it, what the alert said - the words it
    was sent with, or its title where it was sent none - said as the alert's:
    a title is the rule's name, and three latency rules share one, where the
    words say which percentile, which share. Their figures carry the names the
    alert's line shows them by, being the same figures.

    In the unit the rule's panel or its metric's name says, which the figures
    carry - a share of one as a percentage. Where neither says one, that is said
    rather than left for the model to fill: a bare number beside an alert in
    percent reads as a second scale, and a unit supplied is one nobody measured.

    A series that got worse is asked what that meant for the people using the
    service, whatever the failed requests did: the failed requests are a share
    of traffic, and say nothing of a purchase filed in the wrong place or a page
    that took a second longer. Where no rise in them was measured, the series is
    said to be the harm as well - every request succeeded, and a write-up
    reading the failed requests alone called the harm "small to none" while its
    series tripled. A series that held is asked neither: nothing is not a harm,
    and a model asked to say what it meant has to make a meaning up. Nor is a
    series that is the error rate itself: what it getting worse meant for the
    people using the service is the symptom, said already, and asked it again
    write-ups said the symptom twice.
    """
    if levels is None:
        return []

    worse = "worse falling" if levels.worse_when == "below" else "worse rising"
    alert_said = (f'its alert said "{the_finding_named(evidence.alert_finding)}"'
                  if evidence.alert_finding
                  else f'its alert is titled "{evidence.alert_title}"')
    named = (f", `{query}` - {alert_said} -" if query is not None
             else f" - {alert_said} -")
    in_words = " Say what it measures in words, not by its query." if query is not None else ""
    no_unit = (" The rule does not say what unit its series is in, so give these as "
               "numbers alone, with no unit." if unit is None else "")

    return [
        f"The series behind the alert{named} which its alert rule evaluates "
        f"and calls {worse}: {_shown(SERIES_BEFORE_FIGURE, figures)} before it began, "
        f"{_shown(SERIES_WHILE_BROKEN_FIGURE, figures)} on average while it was "
        f"broken, and {_shown(SERIES_AT_WORST_FIGURE, figures)} at its worst."
        f"{no_unit}{in_words}",
        *_what_it_meant(levels, rates, is_the_error_rate)
    ]


def _what_it_meant(levels: RuleSeriesLevels, rates: ErrorRates | None,
                   is_the_error_rate: bool) -> list[str]:
    """What the model is asked of the series beyond its levels: nothing where it
    held or is the error rate itself, and what it meant for the people using the
    service where it got worse - as the harm itself where the failed requests
    did not rise."""
    if not levels.got_worse or is_the_error_rate:
        return []

    if rates is not None and rates.a_rise_was_measured:
        return ["Failed requests rose as well, as a share of traffic - say also what "
                "this series getting worse meant for the people using the service."]

    return ["No rise in failed requests was measured, so the harm to report is "
            "what this series did: say what it meant for the people using the "
            "service, not that little or nothing failed."]
