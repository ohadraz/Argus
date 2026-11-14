"""A second model reading an answer against the record it was written from.

No code check can tell a claim the record holds from one it does not: "older
flag changes were not read" is a sentence about meaning, and a row that read
them says otherwise only to a reader. So a judge is asked - the industry's
grounding check - and what it says is held to what code can check: a flag
quoting words the answer does not hold, or citing a row the record does not
have, is the judge being wrong, and is dropped.

The judge says of every claim either where the record supports it or that it
does not. A judge free to name only what it doubts flags whatever it skimmed
past; made to look for the support first, it finds it. The support is its
working and nothing more: only the flags are kept.

What a claim needs to be supported, and what is not judged at all, is its
standing brief, the same for every answer. The record it is handed is what the
writer was handed, whole - facts and the instructions the writer wrote by - so
a sentence an instruction asked for is read as asked for, not as invented.

A quote is matched as a reader would match it, not byte for byte: case,
spacing, quote marks and dashes are left out of the comparison altogether,
since a judge changes or drops them as often as it copies them. A row is
matched as its label, whatever brackets or case the judge wrote it in.

Which part of the answer a quote is from is worked out here, by finding it:
asked of the judge, it would be one more thing for the judge to get wrong.

A judge that does not answer judges nothing, and says so in the log - which
is how a replay missing the judge's recording fails rather than passes
unjudged. The answer it was to judge is the writer's either way.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Final

from argus_core.llm import LLMClient, ModelRefused, ModelUnavailable, RequestRejected
from argus_core.models import Ask, Effort, ModelPolicy, ToolDefinition, Transcript
from pydantic import BaseModel, ValidationError

from agent_postmortem.prompting import WENT_WRONG_DESCRIPTION, WENT_WRONG_FIELD

logger = logging.getLogger(__name__)

JUDGE_TOOL_NAME: Final = "judge_claims"
SUPPORTED_FIELD: Final = "supported"
FLAGS_FIELD: Final = "flags"
QUOTE_FIELD: Final = "quote"
ROWS_FIELD: Final = "rows"
WHY_FIELD: Final = "why"

# What the log says when no judging happened, for whatever reason.
DID_NOT_ANSWER: Final = "grounding judge did not answer"

# Left out of a quote before it is looked for: quote marks and dashes of every
# kind a model writes.
_TYPOGRAPHY: Final = re.compile("[\"'`\u2018\u2019\u201c\u201d\u00ab\u00bb"
                                "\\-\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")
_SPACING: Final = re.compile(r"\s+")
# What a judge may wrap a row's label or a figure's name in, as the brief
# prints them.
_AROUND_A_LABEL: Final = "[]{} \t\n"
# A figure's name as the record prints it after the figure: {A4}, {T12.1},
# {duration}. Not a working such as {T3.1 - alert_raised}, which names two.
_A_FIGURE: Final = re.compile(r"\{([^{}\s]+)\}")
# What a row's label or a figure's name looks like - T14, AL1, C1.4, and a
# log group's G and four hex - as against a line named in its own words.
_LABEL_SHAPED: Final = re.compile(r"[A-Za-z]{1,3}\d+(?:\.\d+)?|G[0-9a-fA-F]{4}")

# The reason a flag is sent back with where the judge gave none to speak of.
NO_REASON_GIVEN: Final = "the record does not hold it as written"

# The judge's standing brief: its two jobs, what supports a claim, what is not
# judged at all, and what does not belong in went_wrong. A claim supported in
# none of the ways listed is flagged - there is no third outcome - so the list
# of ways is the whole of what a writer may say without a row saying it in
# those words.
#
# went_wrong is the one field judged for where a sentence sits. Its exclusions
# were the writer's alone, and a true sentence that broke them reached the page
# every time it was written: nobody paged, said again from a contributing
# factor; a refusal the record bore out, called no mitigation. Handed the
# field's own description and told only to flag a breach, the judge caught
# those in 2 draws of 5. Named as a job in the opening and taken out of what is
# not judged, it caught the repeat in every draw and the refusal in 1 of 5, and
# the refusal in every draw once the field named a refusal left to a person.
# Told a repeat is the same point, it flagged a different lesson drawn from the
# same facts in none of 10 draws, against 1 of 5 before.
JUDGE_BRIEF: Final = "\n".join([
    "You check a document about a software incident against the record it was written "
    "from. Another model wrote the document from that record. Your job is to find "
    "each claim in the document that the record does not support, and each "
    f"{WENT_WRONG_FIELD} item that its field excludes. Style, wording, tone, "
    "emphasis, length, and what the document leaves out are not yours to judge.",
    "",
    "A wrong flag costs as much as a missed one: every flag sends the document back to be "
    "rewritten, and a correct sentence rewritten can come back wrong.",
    "",
    "The record is what the writer was given, whole. Some of its facts carry a label, in "
    "brackets or bare - [T4], T4 |, AL1:, C1, G7e5d - and some stand as plain lines, such "
    "as the alert, its times and the list of figures. All of them are your evidence. Name "
    "a line by its label, or, where it has none, by a few of its own words. The record "
    "also holds instructions to the writer on what to say and how. They are not facts "
    "about the incident, but a sentence that does what an instruction asked for is not a "
    "fault for doing it.",
    "",
    "Go through the document claim by claim. A claim is a statement of fact about this "
    "incident: what happened, when, how much, who or what did it, what was read, what was "
    "found, what caused what. For each one, find the record's lines that support it and "
    "list it as supported, naming them - or, where you cannot, flag it.",
    "",
    "A claim is supported when:",
    "- a line of the record says it, in any words; a number matches the record's, "
    "rounded as the document rounds it;",
    "- it follows from lines of the record taken together - a duration from two times, "
    "which came first from their times, a difference or a sum of two numbers - and the "
    "working is right; name every line it rests on;",
    "- it says no such thing was seen - no other check, no blocking test - and the record "
    "holds none of it;",
    "- it says something was not found or not changed in a place that was read - the "
    "logs, the changes, the flag history - and the record shows that place read over that "
    "time with nothing of the kind;",
    "- it is said as a reading - suspected, likely, suggests, consistent with, may have, "
    "appears - and the record holds it as possible, as it does a candidate cause;",
    "- it is said to be someone's - Code-Fix reads the code as, the investigation "
    "suspected, a C or F row - and they said it; whether what they said is true is not "
    "the question;",
    "- it is a judgement that rests on facts - detection was slow, the rollback was quick "
    "- and the record holds the facts it rests on.",
    "",
    "Judge a claim with the whole of the sentence and the field it is in: a hedge, or a "
    "source named, anywhere in them covers it. A sentence saying what would have happened "
    "had something been otherwise is judged only for what it states did happen, never for "
    "the what-if.",
    "",
    "Every other claim is flagged: a fact no line says, a number the record does not give, "
    "something possible said as certain, a count or an all the record contradicts, two "
    "things said to be the same - the same stretch, the same minutes, the same count - "
    "where the record shows them differ, however little, a claim that no person knew of "
    "the incident or took part in it, where the record shows only that nobody was paged, "
    "and anything else the record does not hold.",
    "",
    "Not judged, and listed neither way: recommendations and action items, which propose "
    "rather than claim; general knowledge of how software works; and whatever the ask "
    "says is not judged. In a lesson, an opinion, or a verdict that something went well, "
    "went wrong or was lucky, only the verdict is not judged: every fact it states is "
    "judged like any other.",
    "",
    "One field is judged for where a sentence sits as well as for its facts: "
    f"{WENT_WRONG_FIELD}. The writer was told what does not belong in it: "
    f"\"{WENT_WRONG_DESCRIPTION}\" Flag a {WENT_WRONG_FIELD} item that says what this "
    "excludes, even where every fact in it is supported. Repeating is saying the same "
    "point again, not drawing a different lesson from the same facts. In why, say which "
    "part it breaks and where the document or the record already says it; in rows, name "
    "that line or field.",
    "",
    f"Answer by calling {JUDGE_TOOL_NAME} once, with every claim you judged."
])

JUDGE_CLAIMS: Final = ToolDefinition(
    name=JUDGE_TOOL_NAME,
    description=(
        "Submit every claim in the document, each either as supported or as flagged. "
        "Supported: the document's own words, quoted exactly, and the record's rows that "
        "support it. Flagged: the document's own words, quoted exactly, why, and the "
        "record's rows that contradict it (none where no row speaks to it at all). Empty "
        "lists say the document makes no claim to judge."
    ),
    properties={
        SUPPORTED_FIELD: {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    QUOTE_FIELD: {"type": "string"},
                    ROWS_FIELD: {"type": "array", "items": {"type": "string"}}
                },
                "required": [QUOTE_FIELD, ROWS_FIELD]
            }
        },
        FLAGS_FIELD: {
            "type": "array",
            "items": {
                "type": "object",
                # The reason before the rows: properties are written in the
                # schema's order, and a reason left to the end of a flag came
                # back empty.
                "properties": {
                    QUOTE_FIELD: {"type": "string"},
                    WHY_FIELD: {
                        "type": "string",
                        "description": "One sentence: what the record holds instead. Never "
                                       "empty."
                    },
                    ROWS_FIELD: {"type": "array", "items": {"type": "string"}}
                },
                "required": [QUOTE_FIELD, WHY_FIELD, ROWS_FIELD]
            }
        }
    },
    required=[SUPPORTED_FIELD, FLAGS_FIELD]
)


class Flag(BaseModel):
    """One claim the judge found the record does not support, as kept: its
    quote and reason as the judge wrote them, its rows as the record labels
    them, and the fields of the answer that hold it, found by code."""

    quote: str
    rows: tuple[str, ...]
    why: str
    fields: tuple[str, ...] = ()


class _Submitted(BaseModel):
    flags: list[Flag]


def judge_policy(model: str, effort: Effort) -> ModelPolicy:
    """The judge's model at the deployment's choice of model and effort, under
    its standing brief, for one tool call per turn: the record and the answer
    are in its one message."""
    return ModelPolicy(model=model, effort=effort, brief=JUDGE_BRIEF,
                       one_tool_call_per_turn=True)


def flags_on(judge: LLMClient,
             *,
             record: str,
             answer: Mapping[str, str],
             rows: frozenset[str],
             scope: Sequence[str]) -> list[Flag]:
    """Every claim in `answer` the judge finds `record` does not support,
    less those code can tell the judge got wrong.

    `answer` is each part of it by field, as the judge is to read it - the
    caller decides what is shown, and a quote is looked for in exactly that.
    `rows` are the labels a flag may cite, beside the figures `record` names;
    `scope` says what is not judged.
    What the judge found supported is its working, and is not read.
    """
    try:
        turn = judge.converse(_asked(record, answer, scope), [JUDGE_CLAIMS])
    except (ModelRefused, ModelUnavailable, RequestRejected) as failure:
        logger.warning(DID_NOT_ANSWER, extra={"failure": str(failure)})
        return []

    call = next((call for call in turn.tool_calls if call.name == JUDGE_TOOL_NAME), None)
    if call is None:
        logger.warning(DID_NOT_ANSWER, extra={"failure": "it answered without the call"})
        return []
    try:
        submitted = _Submitted.model_validate(call.arguments)
    except ValidationError as malformed:
        logger.warning(DID_NOT_ANSWER, extra={"failure": str(malformed)})
        return []

    return [kept for flag in submitted.flags
            if (kept := _kept(flag, answer, rows, record)) is not None]


def faults_of(flags: Sequence[Flag]) -> list[str]:
    """Each flag as a fault sent back to the writer: that one claim to
    correct or hedge, and the rest kept as it is.

    A reason of a word or none says nothing a writer can act on, and is sent
    as what every flag means: the record does not hold the claim as written."""
    return [f'correct or hedge this claim; keep everything else: "{flag.quote}" - '
            f"{_reason(flag.why)} ({_against(flag.rows)})"
            for flag in flags]


def _reason(why: str) -> str:
    return why.strip() if len(why.split()) > 1 else NO_REASON_GIVEN


def _against(rows: tuple[str, ...]) -> str:
    return f"against {', '.join(rows)}" if rows else "no row holds it"


def _kept(flag: Flag,
          answer: Mapping[str, str],
          rows: frozenset[str],
          record: str) -> Flag | None:
    """The flag with its rows as the record names them and the fields that
    hold its quote, or nothing where it quotes nothing the answer says or
    cites a label the record does not have.

    A citation is the record's where the record names it - a row by its
    label, or a figure by the name in braces it follows ({A4}, {T12.1}) -
    matched whatever case or brackets the judge wrote it in, and kept as the
    record spells it: a log group's label is minted with lower-case letters
    (`G7e5d`), and every other kind with none. A citation shaped like a label
    the record never names is the judge citing what nobody recorded, and the
    flag goes with it. Anything else is a line without a label named in its
    own words, as the brief allows: left out of the rows, and the flag kept."""
    quoted = _as_compared(flag.quote)
    if not quoted:
        return None

    named = ({figure.upper(): figure for figure in _A_FIGURE.findall(record)}
             | {row.upper(): row for row in rows})
    cited: list[str] = []
    for citation in flag.rows:
        bare = citation.strip(_AROUND_A_LABEL)
        spelled = named.get(bare.upper())
        if spelled is not None:
            cited.append(spelled)
        elif _LABEL_SHAPED.fullmatch(bare):
            return None

    fields = tuple(field for field, text in answer.items() if quoted in _as_compared(text))
    if not fields:
        return None

    return flag.model_copy(update={"rows": tuple(cited), "fields": fields})


def _as_compared(text: str) -> str:
    """Text as a quote is matched in it: folded, its quote marks and dashes
    left out, and its spacing made single."""
    return _SPACING.sub(" ", _TYPOGRAPHY.sub(" ", text.casefold())).strip()


def _asked(record: str, answer: Mapping[str, str], scope: Sequence[str]) -> Transcript:
    """The one message the judge gets: the record whole, the answer by field,
    and what it is not to judge."""
    return [Ask(text="\n".join([
        "The record:",
        record,
        "",
        "The document, by field:",
        *(f"{field}: {text}" for field, text in answer.items()),
        "",
        "Not to be judged:",
        *(f"  - {note}" for note in scope),
        "",
        f"Judge every claim in the document, and answer by calling {JUDGE_TOOL_NAME}."
    ]))]
