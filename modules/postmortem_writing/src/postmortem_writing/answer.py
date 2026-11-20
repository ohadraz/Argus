"""The one shape the model's answer may take, and its fields' names.

Beneath the prompt and everything that rewrites the answer: the prompt offers
these fields, the conversation reads the call into this shape, and the figures,
the revisions and the checks each take it as it stands. Kept in the prompt, it
made each of those and the prompt import one another.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Final

from core.models import ActionItemType, Lessons
from pydantic import BaseModel, field_validator, model_validator

from postmortem_writing.labels import is_a_code_reading

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
# The row a moment that went well happened on, by its label - which the
# document times from the alert, so the model writes no span of its own.
TIMED_BY_FIELD: Final = "timed_by"
# Where the answer keeps those rows beside the items - its own, not the wire's.
_TIMED_BY_ATTRIBUTE: Final = "went_well_timed_by"
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
# The item that stops the harm still going on where the walk put a change back
# that did not help - asked only where one was put back while nothing ended the
# harm, and listed after the model's own proposals.
STOPS_THE_HARM_FIELD: Final = "stops_the_harm"
# How long that item is kept, said by the document after the model's own words
# rather than asked of them: asked, a write-up dropped it two times in five.
# A sentence of its own, so it reads right whatever clause the model ends on.
KEPT_UNTIL_THE_FAULT_IS_FIXED: Final = "Keep it in place until the fault is fixed."
# The item to find out why that change did not help - asked wherever the item
# that stops the harm is, and listed after it.
WHY_IT_DID_NOT_HELP_FIELD: Final = "why_it_did_not_help"
# The item listed after that one, by the document rather than the model: asked
# what to find out about the change, a write-up answered whether it reached the
# service there and dropped the check for next time - three in four on the
# field's input - which every write-up of the incident before it had.
CONFIRM_IT_REACHED_THE_SERVICE: Final = (
    "Before the Mitigator judges a change it made, have it confirm from the "
    "service's own logs that the change reached the service."
)

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

# The fields that say what the cause was, which the document writes itself and
# the model is not asked for where the investigation named none (`undetermined`).
THE_CAUSE_FIELDS: Final = frozenset({
    ROOT_CAUSE_FIELD,
    CAUSE_IN_PLAIN_WORDS_FIELD,
    REACHES_A_CAUSE_FIELD,
    CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD
})


class SubmittedRuledOut(BaseModel):
    """Something else the record ruled out, as the model wrote it, and the
    labels of what ruled it out - or, where it rests on Argus's own reads
    alone, as code said it from them (`ruling`)."""

    what: str
    cites: list[str]
    # Whether code wrote `what` from the rows it cites. Never read from the
    # model: `_what_was_ruled_out` builds this from the call's `what` and
    # `cites` alone.
    by_the_record: bool = False


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
    a required field the model left out is a fault to send back to it (see
    `checking`), not an answer that failed to arrive. `None` means unanswered,
    and reaches the document as an absent column rather than an empty one.

    The attribute names are the wire names above, and have to be: the call's
    arguments are validated into this as they stand.

    Nothing here refuses a submission, which is what the validators below are
    for. A field that did not arrive in its declared shape costs that field and
    no other: refusing the whole call would throw away a root cause the model
    wrote over an `assumptions` it sent as a bare string, and the document would
    then record as unanswered something that was answered. The Postmortem Writer spends its
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
    # The row each item of what went well happened on, by its label, in the
    # items' order - `None` for one whose time is not the point of it, or sent
    # as a plain sentence. The whole list `None` where every item came as a
    # plain sentence, as recordings made before the rows were asked for did:
    # the shape is the answer's, and `checking` holds only the new one to it.
    # Read off the same list the items are (`_the_rows_each_happened_on`); not
    # a wire name, so set from that.
    went_well_timed_by: list[str | None] | None = None
    # The places, as `placed_sentences` names them, whose words code says
    # instead or drops - an item of what went well said as its row (`timing`),
    # a rule-out said by the record or resting on nothing (`ruling`). None of
    # the model's words there reach a reader, so no rule is held to them. Set
    # by `conversation` on the answer the checks read; never the model's to say.
    said_by_code: frozenset[str] = frozenset()
    # Never `None`: an answer that did not say reads as a chain that stopped at
    # the change, which unticks one box of the review. So `checking`, which
    # names a required field that is `None`, never sends it back - a retry spent
    # on it would ask every answer recorded before the question for a turn more.
    reaches_a_cause: bool = False
    # `None` where unanswered, which a live call never is: only an answer
    # recorded before the question was asked. Never sent back for the reason
    # `reaches_a_cause` is not, and read as that answer's own root cause and the
    # review's older rule already say it (`reviewing`).
    cause_rests_on_an_unrun_reading: bool | None = None
    # `None` where unanswered - which is an answer only where it was not asked
    # (`checking`).
    logs_show_serving_as_before: bool | None = None
    # `None` where unanswered - which is an answer only where it was not asked
    # (`checking`).
    stops_the_harm: str | None = None
    # `None` where unanswered - which is an answer only where it was not asked
    # (`checking`).
    why_it_did_not_help: str | None = None

    def root_cause_as_written(self) -> str | None:
        """The root cause as the document writes it: the model's, and - where it
        says the cause rests on a reading of the source nothing ran - the
        document's own sentence saying it is unverified, naming the readings
        the chain cites.

        The document's rather than the model's, so the root cause and the
        review's box are written from one answer: told to say it in prose,
        eight write-ups called the cause unverified beside a box ticked
        complete. Here rather than beside the document, because the grounding
        judge reads the root cause as the page says it too.
        """
        if self.root_cause is None or not self.cause_rests_on_an_unrun_reading:
            return self.root_cause

        readings = list(dict.fromkeys(cited for step in self.causal_chain or []
                                      for cited in step.cites if is_a_code_reading(cited)))
        rests = f"It rests on {', '.join(readings)}, a" if readings else "It rests on a"

        return f"{self.root_cause} {rests} reading of the source nothing ran, so it is unverified."

    def sentences(self) -> Iterator[str]:
        """Every sentence the answer would publish as written.

        Beside `with_each_sentence`, and the two read the same fields: a field
        one of them leaves out is prose the other's rule never sees - a figure
        the check never refuses, or a name never written in.
        """
        yield from (prose for _, prose in self.placed_sentences())

    def placed_sentences(self) -> Iterator[tuple[str, str]]:
        """Every sentence the answer would publish in the model's words, with
        the place it is in - the field, and its position where the field is a
        list. Not one at a place code says instead or drops (`said_by_code`).

        What a check that finds a fault in one item returns, so a fault moved
        into another item is one the model was never told of (`checking`).
        """
        yield from ((place, prose) for place, prose in self._every_placed_sentence()
                    if place not in self.said_by_code)

    def _every_placed_sentence(self) -> Iterator[tuple[str, str]]:
        yield from ((field, prose)
                    for field, prose in ((ROOT_CAUSE_FIELD, self.root_cause),
                                         (CAUSE_IN_PLAIN_WORDS_FIELD, self.cause_in_plain_words),
                                         (STILL_AT_RISK_FIELD, self.still_at_risk),
                                         (SYMPTOM_FIELD, self.symptom),
                                         (STOPS_THE_HARM_FIELD, self.stops_the_harm),
                                         (WHY_IT_DID_NOT_HELP_FIELD, self.why_it_did_not_help))
                    if prose is not None)
        yield from ((f"{ASSUMPTIONS_FIELD} {position}", assumption)
                    for position, assumption in enumerate(self.assumptions, start=1))
        yield from ((f"{LEAD_EFFECTS_FIELD} {lead}", effect)
                    for lead, effect in self.lead_effects.items())
        for position, step in enumerate(self.causal_chain or [], start=1):
            yield f"{CAUSAL_CHAIN_FIELD} {position}", step.step
            yield from ((f"{CAUSAL_CHAIN_FIELD} {position} {RULED_OUT_FIELD} {ruled_at}",
                         ruled.what)
                        for ruled_at, ruled in enumerate(step.ruled_out, start=1))
        for position, factor in enumerate(self.contributing_factors or [], start=1):
            yield f"{CONTRIBUTING_FACTORS_FIELD} {position}", factor.factor
            if factor.had_it_been_otherwise is not None:
                yield (f"{CONTRIBUTING_FACTORS_FIELD} {position} {HAD_IT_BEEN_OTHERWISE_FIELD}",
                       factor.had_it_been_otherwise)
        yield from ((f"{ACTION_ITEMS_FIELD} {position}", item.item)
                    for position, item in enumerate(self.action_items or [], start=1))

        if self.lessons is not None:
            for field, said in ((WENT_WELL_FIELD, self.lessons.went_well),
                                (WENT_WRONG_FIELD, self.lessons.went_wrong),
                                (GOT_LUCKY_FIELD, self.lessons.got_lucky)):
                yield from ((f"{field} {position}", lesson)
                            for position, lesson in enumerate(said, start=1))

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
            STOPS_THE_HARM_FIELD: rewritten(self.stops_the_harm),
            WHY_IT_DID_NOT_HELP_FIELD: rewritten(self.why_it_did_not_help),
            ASSUMPTIONS_FIELD: [rewrite(each) for each in self.assumptions],
            LEAD_EFFECTS_FIELD: {lead: rewrite(effect)
                                 for lead, effect in self.lead_effects.items()},
            CAUSAL_CHAIN_FIELD: (None if self.causal_chain is None else
                                 [step.model_copy(update={
                                     STEP_FIELD: rewrite(step.step),
                                     RULED_OUT_FIELD: [
                                         ruled.model_copy(update={WHAT_FIELD: rewrite(ruled.what)})
                                         for ruled in step.ruled_out]})
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
                     SYMPTOM_FIELD, STOPS_THE_HARM_FIELD, WHY_IT_DID_NOT_HELP_FIELD,
                     mode="before")
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

        return Lessons(went_well=[item for item, _ in _what_went_well(value.get(WENT_WELL_FIELD))],
                       went_wrong=_the_strings_in(value.get(WENT_WRONG_FIELD)),
                       got_lucky=_the_strings_in(value.get(GOT_LUCKY_FIELD)))

    @model_validator(mode="before")
    @classmethod
    def _the_rows_each_happened_on(cls, value: Any) -> Any:
        """The row each item of what went well happened on, beside the items,
        off the same list - so the two cannot fall out of step. None at all
        where every item is a plain sentence, the shape of the old recordings."""
        if (not isinstance(value, dict) or _TIMED_BY_ATTRIBUTE in value
                or not isinstance(lessons := value.get(LESSONS_FIELD), dict)):
            return value

        went_well = lessons.get(WENT_WELL_FIELD)
        if not isinstance(went_well, list) or all(isinstance(entry, str) for entry in went_well):
            return value

        return {**value, _TIMED_BY_ATTRIBUTE: [row for _, row in _what_went_well(went_well)]}

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


def _what_went_well(value: Any) -> list[tuple[str, str | None]]:
    """Each item of what went well, with the row it happened on - `None` where
    it names none, or names it in nothing but blanks. An item sent as a plain
    sentence is one, timed by nothing: recordings made before the rows were
    asked for sent them so."""
    if not isinstance(value, list):
        return []

    return [(entry, None) if isinstance(entry, str)
            else (entry[ITEM_FIELD], row.strip() or None
                  if isinstance(row := entry.get(TIMED_BY_FIELD), str) else None)
            for entry in value
            if isinstance(entry, str)
            or isinstance(entry, dict) and isinstance(entry.get(ITEM_FIELD), str)]


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
