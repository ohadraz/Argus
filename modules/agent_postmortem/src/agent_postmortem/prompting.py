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
from typing import Any, Final

from argus_core import parse_iso, short_form, to_iso
from argus_core.models import (
    ActionItemType,
    Ask,
    ChangeEvent,
    CitedChange,
    CitedEvidence,
    Lessons,
    ThreadMessage,
    TimelineEntry,
    ToolDefinition,
    ToolResult,
    ToolResults,
    Transcript,
    Turn,
    labelled,
)
from pydantic import BaseModel, field_validator

from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels, Unmeasured
from agent_postmortem.evidence import ActionRecord, IncidentEvidence
from agent_postmortem.figures import (
    ACTED_FIGURE,
    ALERT_RAISED_FIGURE,
    BACK_TO_NORMAL_FIGURE,
    BEGAN_FIGURE,
    CLOSED_FIGURE,
    DURATION_FIGURE,
    ERRORS_AT_WORST_FIGURE,
    ERRORS_BEFORE_FIGURE,
    ERRORS_RISE_FIGURE,
    ERRORS_WHILE_BROKEN_FIGURE,
    HELD_FIGURE,
    RULE_WAITS_FIGURE,
    SERIES_AT_WORST_FIGURE,
    SERIES_BEFORE_FIGURE,
    SERIES_WHILE_BROKEN_FIGURE,
    UNOBSERVED_FROM_FIGURE,
    Figure,
    figures_of,
    named,
    the_evidence_figures,
    the_evidence_named,
    the_finding_named,
)
from agent_postmortem.log_groups import grouped
from agent_postmortem.measuring import Measurements
from agent_postmortem.revisions import revisions_of
from agent_postmortem.sections import (
    ACTION_PREFIX,
    CODE_READING_PREFIX,
    DEPLOYMENT_CHANGES_PREFIX,
    NO_VERDICT_RECORDED,
    PRODUCTION_CHANGE_PREFIX,
    OneCause,
    causes_of,
    label_of,
    labels_of_the_narration,
    record_action_items_of,
    said_of_a_line,
    the_alert_labelled,
)

# The tool's name and its fields, named once. Both ends of the exchange read
# them - the definition offered to the model, and the reader taking the call
# apart - and a spelling that differed between the two would leave a field
# quietly always missing.
SUBMIT_TOOL_NAME: Final = "submit_postmortem"
ROOT_CAUSE_FIELD: Final = "root_cause"
EXECUTIVE_SUMMARY_FIELD: Final = "executive_summary"
# What a reader saw go wrong, as the document's title says it.
SYMPTOM_FIELD: Final = "symptom"
ASSUMPTIONS_FIELD: Final = "assumptions"
# What each lead changed: one entry per lead, naming it by its label.
LEAD_EFFECTS_FIELD: Final = "lead_effects"
LEAD_FIELD: Final = "lead"
EFFECT_FIELD: Final = "effect"
# The cause as steps, each citing evidence by label (`T3`, `G3fa2`).
CAUSAL_CHAIN_FIELD: Final = "causal_chain"
STEP_FIELD: Final = "step"
CITES_FIELD: Final = "cites"
# The conditions that had to hold, each naming the action items that answer it.
CONTRIBUTING_FACTORS_FIELD: Final = "contributing_factors"
FACTOR_FIELD: Final = "factor"
ADDRESSED_BY_FIELD: Final = "addressed_by"
# What the model proposes be done, each of one of the four kinds.
ACTION_ITEMS_FIELD: Final = "action_items"
ITEM_FIELD: Final = "item"
ITEM_TYPE_FIELD: Final = "type"
# Google's three lists.
LESSONS_FIELD: Final = "lessons"
WENT_WELL_FIELD: Final = "went_well"
WENT_WRONG_FIELD: Final = "went_wrong"
GOT_LUCKY_FIELD: Final = "got_lucky"
# Whether the chain says why the change that set the incident off broke the
# service, rather than stopping at that change.
REACHES_A_CAUSE_FIELD: Final = "reaches_a_cause"

REQUIRED_FIELDS: Final = [
    ROOT_CAUSE_FIELD,
    EXECUTIVE_SUMMARY_FIELD,
    SYMPTOM_FIELD,
    CAUSAL_CHAIN_FIELD,
    CONTRIBUTING_FACTORS_FIELD,
    ACTION_ITEMS_FIELD,
    LESSONS_FIELD,
    REACHES_A_CAUSE_FIELD
]


class SubmittedStep(BaseModel):
    """One step of the cause as the model wrote it, and the labels it cited."""

    step: str
    cites: list[str]


class SubmittedFactor(BaseModel):
    """One contributing factor as the model wrote it, and the items it named."""

    factor: str
    addressed_by: list[str]


class SubmittedItem(BaseModel):
    """One action item the model proposed. Unnumbered: its number is its place
    after the record's own."""

    item: str
    type: ActionItemType


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
    executive_summary: str | None = None
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

    def sentences(self) -> Iterator[str]:
        """Every sentence the answer would publish as written.

        Beside `with_each_sentence`, and the two read the same fields: a field
        one of them leaves out is prose the other's rule never sees - a figure
        the check never refuses, or a name never written in.
        """
        yield from (prose for prose in (self.root_cause, self.executive_summary, self.symptom)
                    if prose is not None)
        yield from self.assumptions
        yield from self.lead_effects.values()
        yield from (step.step for step in self.causal_chain or [])
        yield from (factor.factor for factor in self.contributing_factors or [])
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
            EXECUTIVE_SUMMARY_FIELD: rewritten(self.executive_summary),
            SYMPTOM_FIELD: rewritten(self.symptom),
            ASSUMPTIONS_FIELD: [rewrite(each) for each in self.assumptions],
            LEAD_EFFECTS_FIELD: {lead: rewrite(effect)
                                 for lead, effect in self.lead_effects.items()},
            CAUSAL_CHAIN_FIELD: (None if self.causal_chain is None else
                                 [SubmittedStep(step=rewrite(step.step), cites=step.cites)
                                  for step in self.causal_chain]),
            CONTRIBUTING_FACTORS_FIELD: (None if self.contributing_factors is None else
                                         [SubmittedFactor(factor=rewrite(factor.factor),
                                                          addressed_by=factor.addressed_by)
                                          for factor in self.contributing_factors]),
            ACTION_ITEMS_FIELD: (None if self.action_items is None else
                                 [SubmittedItem(item=rewrite(item.item), type=item.type)
                                  for item in self.action_items]),
            LESSONS_FIELD: (None if self.lessons is None else
                            self.lessons.model_copy(update={
                                WENT_WELL_FIELD: [rewrite(each) for each in self.lessons.went_well],
                                WENT_WRONG_FIELD: [rewrite(each)
                                                   for each in self.lessons.went_wrong],
                                GOT_LUCKY_FIELD: [rewrite(each) for each in self.lessons.got_lucky]
                            }))
        })

    @field_validator(ROOT_CAUSE_FIELD, EXECUTIVE_SUMMARY_FIELD, SYMPTOM_FIELD, mode="before")
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
                               cites=_the_strings_in(entry.get(CITES_FIELD)))
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
            else SubmittedFactor(factor=entry[FACTOR_FIELD],
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
            else SubmittedItem(item=entry[ITEM_FIELD], type=ActionItemType(entry[ITEM_TYPE_FIELD]))
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


def _the_strings_in(value: Any) -> list[str]:
    """The sentences in a list, and nothing where there is no list."""
    if not isinstance(value, list):
        return []

    return [each for each in value if isinstance(each, str)]


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

# What a check the record does not show is written as, said in the two fields a
# missing safeguard is written in. Said once in the tool's description, a
# write-up still gave "nothing checked output quality before it reached
# production" as a factor and as what went wrong.
_A_SAFEGUARD_NOBODY_SAW: Final = (
    "A safeguard the record does not show is one not seen, never one absent: "
    "write that no check was seen, not that none ran."
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
        f"{{{ERRORS_AT_WORST_FIGURE} / {ERRORS_BEFORE_FIGURE}}}. The document "
        "works it out from the figures as you were shown them. Say any other "
        "size with no number in it, not even in a word - \"most requests\", "
        "\"for several minutes\", never \"twenty minutes\", \"a third\" or "
        "\"tripled\". A number is a figure even with a unit or a clock's marks "
        "on it (5m, 10ms, 3x, 12:05Z). Any other word with a digit in it is a "
        "name - a label you cite (T2, G3fa2, C1, AI-3), a version (v2), a "
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
                "for an engineer who was not on the call. Not the change that "
                "set it off - the document states the trigger itself. Say why "
                "that change broke the service, as far as the evidence goes."
            )
        },
        EXECUTIVE_SUMMARY_FIELD: {
            "type": "string",
            "description": (
                "The same incident for a reader who does not work on the "
                "service: what broke, for how long, who it affected, and what "
                "was done. No component names unless they are unavoidable."
            )
        },
        SYMPTOM_FIELD: {
            "type": "string",
            "description": (
                "What went wrong as somebody using the service saw it, in a few "
                "words with no number: 'Account pages failed'. Not the metric "
                "that paged, and not the cause - the document adds the change "
                "it began with itself."
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
                                           "merely happened at the same time.")}},
            [STEP_FIELD, CITES_FIELD],
            "The cause as the five whys, from the symptom down: the first step is "
            "what users saw, and each step after it answers why the one before "
            "happened. Every step cites at least one piece of evidence by its "
            "label. At the step that ties the incident to the change that set it "
            "off, say what else the record ruled out and why - an earlier "
            "change, a flag the provider showed unchanged, a candidate refuted - "
            "citing what ruled it out. Stop where the evidence stops."
        ),
        CONTRIBUTING_FACTORS_FIELD: _a_list_of(
            {FACTOR_FIELD: {"type": "string"},
             ADDRESSED_BY_FIELD: {**_SENTENCES,
                                  "description": "The action items that answer it: AI-2."}},
            [FACTOR_FIELD, ADDRESSED_BY_FIELD],
            "Conditions that had to hold for the incident to happen and did not "
            "cause it alone - a safeguard that did not stop it, a gap in detection "
            f"or review. {_A_SAFEGUARD_NOBODY_SAW} Each names at least one action "
            "item that answers it."
        ),
        ACTION_ITEMS_FIELD: _a_list_of(
            {ITEM_FIELD: {"type": "string"},
             ITEM_TYPE_FIELD: {"type": "string",
                               "enum": [kind.value for kind in ActionItemType]}},
            [ITEM_FIELD, ITEM_TYPE_FIELD],
            "What should be done that the record does not already hold, each "
            "one thing a person could take on. Empty where the record's own "
            "items answer every factor. Propose nothing to confirm a cause the "
            "record already confirmed - a mitigation that worked, a hypothesis "
            "marked confirmed."
        ),
        LESSONS_FIELD: {
            "type": "object",
            "properties": {WENT_WELL_FIELD: _SENTENCES,
                           WENT_WRONG_FIELD: _SENTENCES,
                           GOT_LUCKY_FIELD: _SENTENCES},
            "required": [WENT_WELL_FIELD, WENT_WRONG_FIELD, GOT_LUCKY_FIELD],
            "description": (
                "What went well, what went wrong, and where the incident got "
                "lucky - a risk that went unnoticed this time. Any list may be "
                f"empty. {_A_SAFEGUARD_NOBODY_SAW}"
            )
        },
        REACHES_A_CAUSE_FIELD: {
            "type": "boolean",
            "description": (
                "Whether the chain says why the change that set the incident off "
                "broke the service, rather than stopping at that change. A step "
                "resting only on F rows - a reading of the code nothing ran - "
                "counts only where it says the reading is unverified. That a new "
                "version does worse is what the change did, not why it broke the "
                "service: answer false where the chain says the evidence does not "
                "show why."
            )
        }
    },
    required=REQUIRED_FIELDS
)


def submit_postmortem_for(leads: Sequence[ThreadMessage]) -> ToolDefinition:
    """The tool for this incident: the one every incident gets, and a place to
    say what each lead changed where people wrote any.

    Only where they did. A field for leads offered on an incident nobody wrote
    about is a question about nothing, and a request that changed for every
    incident - so that one is sent exactly as it always was.

    Required where it is offered: the document owes the person who wrote a
    lead an answer, and an optional field is one a model leaves out whenever
    its prose reads well without it.
    """
    if not leads:
        return SUBMIT_POSTMORTEM

    return SUBMIT_POSTMORTEM.model_copy(update={
        "properties": {
            **SUBMIT_POSTMORTEM.properties,
            LEAD_EFFECTS_FIELD: {
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
        },
        "required": [*REQUIRED_FIELDS, LEAD_EFFECTS_FIELD]
    })


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
        *_how_long_the_rule_waits(measured, figures),
        *_how_long_it_was_broken(measured, evidence.credited_action, figures),
        f"Argus held the incident for {_shown(HELD_FIGURE, figures)}, "
        f"until {_shown(CLOSED_FIGURE, figures)}. That is how long the response took, "
        f"not how long the fault lasted - leave it out of your answer.",
        *_what_the_error_rate_did(measured.error_rates, measured.error_rates_unmeasured,
                                  figures),
        *_what_the_rules_series_did(measured.rule_series, evidence,
                                    measured.error_rates, figures),
        *(line
          for heading, cited in _the_evidence_by_kind(evidence)
          for line in ["", heading,
                       *(f"  - [{_its_labels(each)}] {_under_its_label(the_evidence_named(each))}"
                         for each in cited)]),
        "",
        "Action items the record already holds:",
        *(_the_record_items(evidence) or ["  - none"]),
        "",
        f"Cite evidence in {CAUSAL_CHAIN_FIELD} by its label, and name action items "
        f"in {CONTRIBUTING_FACTORS_FIELD} by their number. Items you propose in "
        f"{ACTION_ITEMS_FIELD} are numbered after these, in the order you give them.",
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
    """
    return figures_of(evidence, measured) | the_evidence_figures(_the_evidence_listed(evidence))


def the_evidence_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Every piece of evidence the model is shown, each under its own label:
    what the alert said, then the evidence listed beneath its headings.

    The label is what a step of the cause cites, so every line a claim could
    rest on has one and no two share it. Each kind is labelled on its own,
    and the logs by message rather than by place: a recorded answer is replayed
    in a run that read a different number of log lines, and a label counted
    across the kinds would then name a different line in every kind after the
    logs.
    """
    return [*the_alert_labelled(evidence), *_the_evidence_listed(evidence)]


def _the_evidence_listed(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """The evidence listed beneath its headings, in the order it is shown."""
    return [cited for _, cited_of_a_kind in _the_evidence_by_kind(evidence)
            for cited in cited_of_a_kind]


def _the_evidence_by_kind(evidence: IncidentEvidence
                          ) -> list[tuple[str, list[CitedEvidence]]]:
    """The evidence under the heading the model reads it beneath, in the order
    it is shown: the narration, the changes, the logs, the candidates, the
    actions - and what each deployment it looked into changed and what Code-Fix
    read in the source, where there is any: a heading over nothing tells the
    model there is something it has failed to see."""
    looked_into = the_deployment_changes_labelled(evidence)
    read_in_the_source = the_code_reading_labelled(evidence)

    return [
        ("What Argus did, in order:",
         [CitedEvidence(label=label, text=_a_line_of_the_narration(entry))
          for entry, label in zip(evidence.timeline,
                                  labels_of_the_narration(evidence.timeline),
                                  strict=True)]),
        ("Changes to production it read:",
         [CitedEvidence(label=cited.label, text=_a_change_as_a_line(cited.change))
          for cited in the_changes_labelled(evidence)]),
        ("Log lines it read, one per message:", grouped(evidence.log_lines)),
        ("Candidates it considered:", the_candidates_labelled(evidence)),
        ("Actions it took:",
         _numbered(ACTION_PREFIX, [_an_action_as_a_line(action) for action in evidence.actions])),
        *([("What each deployment it looked into changed:", looked_into)] if looked_into else []),
        *([("What Code-Fix read in the source - a static reading, nothing ran it:",
            read_in_the_source)] if read_in_the_source else [])
    ]


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

    Public because the document lists them under the same labels the prose
    cites them by, as it does the changes.
    """
    return _numbered(DEPLOYMENT_CHANGES_PREFIX,
                     ["\n".join(looked_into.said) for looked_into in evidence.deployment_changes])


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


def _the_record_items(evidence: IncidentEvidence) -> list[str]:
    return [f"  - {item.number} ({item.type}, {item.status}): {item.text}"
            for item in record_action_items_of(evidence)]


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
    """A cause in its best-ranked candidate's words, its failure mode, its
    confidence, and what became of it.

    Where the candidates it stands for read the move as different failures,
    each failure is said with the labels that read it so - the only thing the
    others said - and the confidence with the label it is the lead's, since
    after labelled failures a bare one reads as all of theirs.
    """
    lead, became = cause.lead, cause.became
    read_as: dict[str | None, list[str]] = {}
    for label, candidate in cause.members:
        read_as.setdefault(candidate.failure_mode, []).append(label)

    if len(read_as) == 1:
        return f"{lead.summary} [{lead.failure_mode}, confidence {lead.confidence}, {became}]"

    failures = "; ".join(f"{failure} ({', '.join(labels)})" for failure, labels in read_as.items())

    return f"{lead.summary} [{failures}, confidence {lead.confidence} ({cause.label}), {became}]"


def _an_action_as_a_line(action: ActionRecord) -> str:
    """An action, its verdict, and whether it still stands."""
    return f"{action.action} - {action.verdict or NO_VERDICT_RECORDED}, {action.standing}"


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
                            credited: ActionRecord | None,
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
    """
    dated_from = (
        "the onset" if measured.onset_at is not None
        else "the alert, since no onset could be measured"
    )

    if measured.unobserved_from is not None:
        # Not a stretch of trouble but a stretch nobody could see. Said as that,
        # because "had not recovered" would describe a broken service, and the
        # window before the onset would read as though it were the incident.
        return [
            f"No metrics were collected from "
            f"{_shown(UNOBSERVED_FROM_FIGURE, figures)} ({dated_from}) onwards: the "
            f"service was still unobserved when the incident closed. That is "
            f"{_shown(DURATION_FIGURE, figures)} nobody could see, not "
            f"a stretch the service is known to have spent in trouble, and the "
            f"error rates below cover none of it."
        ]

    if measured.back_to_normal_at is None:
        return [
            f"Broken from {_shown(BEGAN_FIGURE, figures)} ({dated_from}). The service "
            f"was not back to normal by {_shown(CLOSED_FIGURE, figures)}, when the "
            f"incident was closed, so it was broken for at least "
            f"{_shown(DURATION_FIGURE, figures)} - a lower bound, not a measurement, "
            f"and every impact figure below is bounded the same way."
        ]

    return [
        f"Broken from {_shown(BEGAN_FIGURE, figures)} ({dated_from}) to "
        f"{_shown(BACK_TO_NORMAL_FIGURE, figures)}, when the metrics show it back to "
        f"normal.",
        *_back_before(credited, measured, figures),
        f"That is {_shown(DURATION_FIGURE, figures)}, and every impact figure below "
        f"is measured over that stretch."
    ]


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
        f"{_shown(ACTED_FIGURE, figures)}, when {credited.action} was taken - the "
        f"action credited with ending it: the metrics show the service back before "
        f"that action, not because of it."
    ]


# Why the error rates went unmeasured, as the model is told it. Three gaps that
# read alike as an absent figure and are not alike: a read that came back empty
# is an outage of the metrics, and the other two are reads that answered - over
# a shorter memory than the fault's, or over none of the stretch it broke.
_WHY_NOT_KNOWN: Final[dict[Unmeasured, str]] = {
    Unmeasured.NOTHING_READ: "the metrics for the incident could not be read",
    Unmeasured.NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET: (
        "metrics were read, but none from the hour before the onset, so there is "
        "no calm level to measure a rise against"),
    Unmeasured.NO_MINUTE_WHILE_BROKEN: (
        "metrics were read, but none from while the service was broken")
}


# Said of a figure the calm before the incident was too short to hold up to
# how far the rate goes on its own.
_NOT_TOLD_APART: Final = "can't be told apart from its normal variation"


def _what_the_error_rate_did(rates: ErrorRates | None,
                             unmeasured: Unmeasured | None,
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
    """
    if rates is None:
        why = f" - {_WHY_NOT_KNOWN[unmeasured]}" if unmeasured is not None else ""

        return [f"Error rate: not known{why}."]

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


def _how_long_the_rule_waits(measured: Measurements,
                             figures: Mapping[str, Figure]) -> list[str]:
    """How long the paging rule waits with its condition holding before it
    fires, which is part of the time from the onset to the alert.

    Not told it, a write-up called the rule's own wait slow detection. Said as
    a rule that fires at once where it waits for nothing, and as unread where
    nobody could read it - which is not the same rule. Nothing where no rule
    paged.
    """
    if measured.rule_wait_unread:
        return ["How long the paging rule waits before it fires could not be read."]

    if measured.rule_waits is None:
        return []

    if not measured.rule_waits:
        return ["The paging rule fires as soon as its condition holds."]

    return [f"The paging rule waits {_shown(RULE_WAITS_FIGURE, figures)} with its "
            f"condition holding before it fires: that wait is part of the time from "
            f"the onset to the alert - count it before calling detection slow."]


def _what_the_rules_series_did(levels: RuleSeriesLevels | None,
                               evidence: IncidentEvidence,
                               rates: ErrorRates | None,
                               figures: Mapping[str, Figure]) -> list[str]:
    """The series the paging rule evaluates, at the error rate's levels.

    Nothing at all where the metrics carry no such series - not a line saying it
    sat at nothing, which would describe a service whose answers had gone
    entirely. Its direction is said with it, because its worst is its lowest or
    its highest according to the rule, and the number alone does not say which.

    Named by the words the alert was sent with, where it was sent any, and by
    its title otherwise: "the series the paging rule evaluates" says that
    something moved and not what, and a title is the rule's name - three latency
    rules share one - where the words say which percentile, which share. Its
    figures carry the names the alert's line shows them by, being the same
    figures.

    Plain numbers rather than percentages: the series is in whatever unit its
    rule watches, and only the rule knows what that is.

    A series that got worse is asked what that meant for the people using the
    service, whatever the failed requests did: the failed requests are a share
    of traffic, and say nothing of a purchase filed in the wrong place or a page
    that took a second longer. Where no rise in them was measured, the series is
    said to be the harm as well - every request succeeded, and a write-up
    reading the failed requests alone called the harm "small to none" while its
    series tripled. A series that held is asked neither: nothing is not a harm,
    and a model asked to say what it meant has to make a meaning up.
    """
    if levels is None:
        return []

    worse = "worse falling" if levels.worse_when == "below" else "worse rising"
    named = (the_finding_named(evidence.alert_finding) if evidence.alert_finding
             else evidence.alert_title)

    return [
        f"The series behind the alert ({named}), which its paging rule evaluates "
        f"and calls {worse}: {_shown(SERIES_BEFORE_FIGURE, figures)} before it began, "
        f"{_shown(SERIES_WHILE_BROKEN_FIGURE, figures)} on average while it was "
        f"broken, and {_shown(SERIES_AT_WORST_FIGURE, figures)} at its worst.",
        *_what_it_meant(levels, rates)
    ]


def _what_it_meant(levels: RuleSeriesLevels, rates: ErrorRates | None) -> list[str]:
    """What the model is asked of the series beyond its levels: nothing where it
    held, and what it meant for the people using the service where it got worse
    - as the harm itself where the failed requests did not rise."""
    if not levels.got_worse:
        return []

    if rates is not None and rates.a_rise_was_measured:
        return ["Failed requests rose as well, as a share of traffic - say also what "
                "this series getting worse meant for the people using the service."]

    return ["No rise in failed requests was measured, so the harm to report is "
            "what this series did: say what it meant for the people using the "
            "service, not that little or nothing failed."]
