"""What Code-Fix is asked, and the one shape its answer may take.

The answer is a patch, and a patch is whole files rather than a diff. A diff is
a second thing that can fail, and it fails by producing a file that is subtly
not what anyone wrote - where a whole file that came out wrong is wrong
visibly, on a branch, in front of the person who has to approve it.

That is a decision rather than a constraint, and the cost of it is measured.
An answer is a pair, because the submission below asks for the test that
exposes the bug alongside the source it fixes - so both halves are what a
whole-file shape has to carry. The Target Service is 30,043 tokens of source
and 9,880 of tests, 39,923 entire; the largest pair in it is
`monthly_statement.py` at 21,593 with `test_monthly_statement.py` at 2,142,
23,735 together. Everything else is small - `account_page.py` 3,233 beside a
3,119-token test, and no other file over 1,500. Against a
`codefix_max_output_tokens` of 128,000, the premium a diff would save is one
file's tokens per file changed, bounded by those figures rather than
open-ended. Truncation used to be the argument against this shape; a
larger bound and a streamed answer removed it, which withdrew an argument
against whole files without supplying one for diffs.

Reopening it needs an experiment that can read the difference, and the fix
corpus cannot supply one: `grade_fixes` yields a single binary outcome per
walk over eight walks, and two arms of that separate only in total failure -
the same wall the model and effort comparisons hit. The prerequisite is a
grader with many more than eight outcomes in it, not a paid re-record against
a diff-shaped prompt.

It arrives as a tool call rather than as prose. Source parsed back out of a
fenced block is source that can be parsed wrongly, and every failure mode is
silent: a stray line of commentary becomes a line of Python, and a closing fence
the model forgot truncates the module at the point it was fixing.

The leniency below is deliberate, as the postmortem's is. A malformed entry
costs that entry and nothing else, because refusing a whole submission would
throw away three correct files over a fourth - and an incident that recorded
"no fix was found" would be describing the reader rather than the agent.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterable
from typing import Any, Final

from argus_core.models import ToolDefinition
from pydantic import BaseModel, field_validator, model_validator

# The tool's name and its fields, named once. Both ends of the exchange read
# them - the definition offered to the model, and the reader taking the call
# apart - and a spelling that differed between the two would leave a field
# quietly always missing.
SUBMIT_TOOL_NAME: Final = "submit_fix"
# The other ending, and a tool of its own rather than a shape of the first.
# "I read the code and there is nothing to change" and "here is the change I
# described" arrived as the same call while one tool answered both, and no
# reading of the prose separates them - a verdict carries an explanation as
# readily as a proposal does. Two names cannot be confused.
REPORT_TOOL_NAME: Final = "report_nothing_to_change"

# What is true of fixing a fault whatever the fault was, and so what Code-Fix
# is told once rather than at the top of each incident. It travels as the
# request's `system` (see `ModelPolicy.brief`), which is what lets it - and the
# tool list rendered before it - be read from cache on every incident after the
# first rather than re-sent and re-billed each time.
#
# Every line is here because the model got it wrong without being told, and
# nothing is here for completeness. Length is not free even where the bytes
# are: a model given a long list of rules follows the list, and what is wanted
# is a model reading code. So each point is made once, in the fewest words that
# still carry why.
#
# What each one cost before it was written down: a mitigation has usually
# hidden the symptom, so the code reads as fine and is not. The change that
# exposed a fault is not the fault - the thing every reader of an incident gets
# backwards. Submitting nothing is a conclusion needing evidence, not a way out
# of a hard read. And reading has no natural end, which is the expensive one:
# across eight recorded walks the agent spent thirteen to seventeen of every
# twenty-odd calls reading files, on a repository of sixteen, having been
# handed the file and the line - and three of those walks ran out mid-read and
# submitted nothing at all.
#
# Nothing about a particular incident may be added here, ever. The saving is
# that the bytes do not change between incidents, so a single interpolated
# detail would not merely dilute it - it would end it, silently, with every
# test still passing.
STANDING_BRIEF: Final = "\n\n".join([
    "A mitigation has probably already hidden the symptom - a flag off, a "
    "version rolled back. The code you are reading is the code that broke, "
    "whether or not anything looks broken now.",

    "The change that exposed a fault is not the fault. Make the code safe to "
    "turn back on, to take that deploy again, to meet that input again. "
    "Reverting bought time and left the fault behind a switch nobody dares "
    "touch.",

    "You have no test runner, so reading is your only evidence. Start from "
    "what the investigation named - read it before you search - and read its "
    "callers too: a fix that satisfies one file and breaks them is this job's "
    "characteristic mistake. Once you can name the fault and the file it lives "
    "in, read no further. Every call re-sends everything you have read, and a "
    "walk that runs out mid-read submits nothing at all.",

    f"Report that there is nothing to change only if you have read the code "
    f"and that is genuinely what you found - never because a configuration "
    f"change triggered the incident, which is the common case and still a code "
    f"fault. It is a separate answer with its own tool, "
    f"{REPORT_TOOL_NAME}, because it is a conclusion rather than an empty "
    f"patch. If you cannot name the fault, say so and fix what you can defend.",

    "Change as little as possible: you send whole files, so a tidy-up is "
    "invisible in your answer and enormous in the diff a person has to "
    "approve. Make the code safe in both "
    "states - flag on and off, field present and missing. Never silence the "
    "failure; a blanket except ends the symptom and the evidence together."
])

SUMMARY_FIELD: Final = "summary"
EXPLANATION_FIELD: Final = "explanation"
FILES_FIELD: Final = "files"
PATH_FIELD: Final = "path"
CONTENT_FIELD: Final = "content"

REQUIRED_FIELDS: Final = [SUMMARY_FIELD, FILES_FIELD]

# How a model writes a tool argument when it stops writing JSON and starts
# writing tags. Both halves are quoted from real submissions rather than
# guessed: the prose ends with the closing tag of the field it was in, and the
# patch that should have been an argument follows as the opening tag of the next
# one. Named here because two things read them - the recovery below, and anybody
# later wondering why an explanation would contain markup at all.
EXPLANATION_CLOSING_TAG: Final = "</explanation>"
FILES_PARAMETER_TAG: Final = '<parameter name="files">'

# The tag a model closed around a file it was asked for the contents of, named
# for the field rather than spelled at the point it is stripped: it is the
# field's own name that produced it, and the two have to move together.
_A_CLOSING_CONTENT_TAG: Final = f"</{CONTENT_FIELD}>"

# What a path has to end in before its content is read as Python. The suffix and
# not a guess at the content, because a file whose name says Python is one whose
# reader will treat it as Python whatever it holds.
_A_PYTHON_SUFFIX: Final = ".py"


def _the_patch_in(written: str) -> list[Any] | None:
    """The files written after a parameter tag, or `None` where there are none.

    A list of entries and nothing else. The recovery this serves rewrites the
    submission's own `files`, so anything that is not the shape of a patch has to
    leave it alone rather than replace a readable answer with a scalar - and the
    entries themselves are left exactly as they arrived, because the validator
    that reads a patch is the one that decides what counts as one.

    Trailing text after the array is tolerated, which is what `raw_decode` buys:
    a model that closed the tag, or wrote another paragraph after it, still wrote
    the patch.
    """
    try:
        decoded, _ = json.JSONDecoder().raw_decode(written.strip())
    except ValueError:
        return None

    return decoded if isinstance(decoded, list) else None


def _the_source_in(content: str) -> str:
    """The file's text, less a closing tag the model wrote around it.

    Shared by the two readers below rather than done in one of them, because
    they have to agree: the entry is dropped or kept by what the content *is*,
    and the content is written out by the same reading. A strip in one place
    only would judge an entry by its wrapping and then write the unwrapped
    thing, or the reverse.
    """
    without = content.rstrip()

    if not without.endswith(_A_CLOSING_CONTENT_TAG):
        return content

    return without[: -len(_A_CLOSING_CONTENT_TAG)]


def _is_only_a_placeholder(content: str) -> bool:
    """Whether this is the model eliding a file rather than writing one.

    A real answer, and the most expensive kind to accept: `PLACEHOLDER`, eleven
    characters, offered as the whole new contents of an 11KB module beside an
    explanation that named the fault correctly. Written out it replaces the
    module with one word, and nothing else here would have stopped it - the
    content is a string, it is not empty, and a bare name is valid Python, so
    parsing proves nothing.

    What gives it away is that a module somebody wrote always *does* something:
    an import, a definition, an assignment. A file that is nothing but bare
    expressions is an elision - `PLACEHOLDER`, `TODO`, `...` - and a docstring
    is the one exception, which is why a string constant is allowed to stand
    alone. That is the whole line between the two, and it is the reason this
    tests for what a module has rather than for how short it is: a length is a
    number somebody would have to defend.

    Anything that will not parse is not judged here. A file that is not Python is
    a different failure and this has no business deciding it - but it is a failure
    somebody has to decide, which for a while nobody did: `(see above)` parses as
    nothing, so it was neither an elision nor source and was written out as a
    module. `the_paths_whose_content_is_not_source` is where that is judged now,
    and a reader of this function should expect to find it there rather than
    conclude the case is unhandled.
    """
    try:
        parsed = ast.parse(content)
    except (SyntaxError, ValueError):
        return False

    if not parsed.body:
        return False

    return all(
        isinstance(statement, ast.Expr)
        and not isinstance(statement.value, ast.Constant)
        for statement in parsed.body
    )


def the_paths_whose_content_is_not_source(files: Iterable[ProposedFile]) -> list[str]:
    """Which of these files carry something that is not Python at all.

    The failure `_is_only_a_placeholder` names and declines: a module elided as a
    bare expression is that function's business, and one elided as prose - `(see
    above)`, pointing at a patch the model wrote into its explanation - parses as
    nothing and so was judged by nobody. It reached a branch, and the fix grader
    found a shop that would not import.

    Parsing is the whole of the evidence available here. Code-Fix never runs what
    it writes, so whether the content is source is the one thing that can be
    established before a branch exists. It also catches a file that ends mid-
    statement inside an answer that was otherwise complete, which is the half of
    truncation `AnswerTruncated` cannot see: that names a response the model ran
    out of room for, and says nothing about one that finished a file early.

    Python alone. A patch may carry a values file or a manifest, and a parser for
    one of those is a parser this would have to keep being right about; a file
    whose name says Python and whose content is not is the case that has actually
    happened, twice.

    Public, unlike its neighbours, because the loop is what puts a submission
    back and the judgement of what a file's content is belongs here beside the
    other readings of it.
    """
    return [
        proposed.path for proposed in files
        if proposed.path.endswith(_A_PYTHON_SUFFIX) and not _parses(proposed.content)
    ]


def _parses(content: str) -> bool:
    """Whether this text is Python, whatever it says."""
    try:
        ast.parse(content)
    except (SyntaxError, ValueError):
        return False

    return True


def _the_array_inside(submitted: str) -> Any:
    """The patch a model sent as text, where the array itself was asked for.

    A real answer, on the largest fix recorded: the model wrote `files` as a
    string holding the array's JSON - seventy-odd kilobytes of it - and dropped
    as "not a list" that fix reached a human as "there is nothing here to
    change", with the incident recording the verdict and nothing anywhere saying
    it was the shape of the answer rather than the state of the code. The
    wrapping was wrong; the answer was not.

    `None` for anything that is not JSON, which the caller reads as no patch. A
    path typed where an array belonged is a malformed submission however
    willingly it is read, and guessing at one would invent a patch the model did
    not send.
    """
    try:
        return json.loads(submitted)
    except ValueError:
        return None


class ProposedFile(BaseModel):
    """One file of a patch: where it goes, and everything it says afterwards.

    `content` is the file's whole new text, not the part that changed. The model
    has read the file by the time it answers, so writing it out entire costs
    tokens and buys the one thing a diff cannot give - a result that is either
    the file the model meant or visibly not it.
    """

    path: str
    content: str

    @field_validator(CONTENT_FIELD, mode="before")
    @classmethod
    def _without_a_tag_it_never_opened(cls, value: Any) -> Any:
        """The file's text, less a closing tag the model wrote around it.

        A real answer, across a whole recorded walk: every file in the patch
        ended with a literal `</content>` - the name of the field it was the
        value of - so all three were invalid Python, and the one that was a
        `conftest.py` took the Target Service's entire suite down with a
        `SyntaxError`. Nothing rejected it: the content was a string, and a
        non-empty one.

        Repaired rather than refused, for the reason the array inside a string
        is: the wrapping was wrong and the answer was not. A patch dropped here
        reaches a human as an agent that found nothing to change, which is a
        verdict nobody reached.

        Only at the end, and only that one tag. A `</content>` in the middle of a
        file is somebody's HTML and none of this function's business.
        """
        return _the_source_in(value) if isinstance(value, str) else value


class SubmittedFix(BaseModel):
    """What the model submitted, said as fields rather than as a mapping.

    Every field is optional, because finding out what is missing is the point: a
    field the model left out is a fault to put back to it, not an answer that
    failed to arrive. `None` means unanswered.

    An empty `files` is a real answer and not a malformed one - "I looked and
    there is nothing here to change" is a conclusion a human acts on, and is
    different from a submission that could not be read. Whoever reads this has
    to be able to tell those apart, so both parse.

    It parses, and it is put back once before it is believed. The same call
    also arrives from a model that described the change it wanted and attached
    nothing, and no amount of reading the prose separates the two - a verdict
    carries an explanation as readily as a proposal does. So the loop asks, and
    a model that meant the conclusion submits it again.

    The attribute names are the wire names above, and have to be: the call's
    arguments are validated into this as they stand.
    """

    summary: str | None = None
    explanation: str | None = None
    files: list[ProposedFile] = []

    def patch(self) -> dict[str, str]:
        """The patch as the write tier takes it - path to whole content.

        A file named twice keeps the later entry, which is a model that revised
        itself mid-answer. Keeping the first would write the version it changed
        its mind about, and refusing both would lose a fix over a duplication
        with an obvious reading.
        """
        return {proposed.path: proposed.content for proposed in self.files}

    @model_validator(mode="before")
    @classmethod
    def _the_patch_written_into_the_prose(cls, value: Any) -> Any:
        """The patch recovered from an explanation it was written inside.

        A real answer, five submissions across two paid runs and every one the
        same: the model closes the prose with `</explanation>`, opens
        `<parameter name="files">`, and writes the whole patch as JSON inside the
        explanation string - while the `files` argument that arrives properly
        holds a phrase pointing at it. Tool arguments in the tag form, in the
        middle of a JSON one.

        Nothing is lost when that happens and nothing is wrong with the fix. The
        patches recovered this way are the same 67KB module and its tests that
        every working recording of this walk holds. What it cost was the run,
        where the pointer was a bare word: dropped as the placeholder it is, the
        submission then carried no files, and the walk spent its whole clock
        resubmitting an answer it had written correctly the first time. Where the
        pointer was a phrase - `(see above)` - it cost the patch instead. It
        parses as nothing, so the reading below judged it as neither source nor an
        elision and kept it, and eleven characters reached a branch as a module.

        Repaired rather than refused, for the reason the stray closing tag is and
        the array inside a string before it - the wrapping was wrong and the
        answer was not.

        Recovered files replace what arrived rather than joining it. The two
        describe the same patch, and the one written in the tag is the one the
        model elided.

        Before every field validator, because those run on the fields this
        rewrites. Silent where the payload does not parse - which is not the rare
        case it reads as: a patch written into prose carries the files' own
        newlines, so the array is often not JSON at all. What is left then is
        whatever arrived in `files`, and the two put-backs are what catch it: no
        files, or a file whose content is not source.
        """
        if not isinstance(value, dict):
            return value

        explanation = value.get(EXPLANATION_FIELD)

        if not isinstance(explanation, str) or FILES_PARAMETER_TAG not in explanation:
            return value

        prose, _, written = explanation.partition(FILES_PARAMETER_TAG)
        files = _the_patch_in(written)

        if files is None:
            return value

        return {
            **value,
            EXPLANATION_FIELD: prose.strip().removesuffix(EXPLANATION_CLOSING_TAG).strip(),
            FILES_FIELD: files
        }

    @field_validator(SUMMARY_FIELD, EXPLANATION_FIELD, mode="before")
    @classmethod
    def _prose_however_it_arrived(cls, value: Any) -> Any:
        """A prose field made to cost only itself.

        A number is written out: a figure where a sentence was asked for is
        still an answer, and one dropped here would be a summary the model
        supplied and the proposal denies. Anything structural is read as
        unanswered instead - a dict stringified into a summary reaches a human
        as the words `{'a': 1}`, which reads as an answer and is not one.
        """
        if value is None or isinstance(value, str):
            return value

        return str(value) if isinstance(value, int | float) else None

    @field_validator(FILES_FIELD, mode="before")
    @classmethod
    def _however_many_were_readable(cls, value: Any) -> Any:
        """The patch, as the list of whole files it was asked for.

        An entry is kept only when it has both halves as text. A path with no
        readable content is the dangerous one: written out it would put an empty
        file over the module it was fixing, which is a patch that deletes the
        thing it was sent to repair. A path that is missing has nowhere to go at
        all.

        Dropped rather than refused, one entry at a time, so a model that got
        three files right and one wrong proposes the three.

        A submission that arrived as text is read for the array inside it before
        anything else, because a model asked for a large array sometimes sends
        one - see `_the_array_inside`, which is where what that cost is written
        down.
        """
        if isinstance(value, str):
            value = _the_array_inside(value)

        if not isinstance(value, list):
            return []

        return [
            entry for entry in value
            if isinstance(entry, dict)
            and isinstance(entry.get(PATH_FIELD), str)
            and isinstance(entry.get(CONTENT_FIELD), str)
            and not _is_only_a_placeholder(_the_source_in(entry[CONTENT_FIELD]))
        ]


SUBMIT_FIX = ToolDefinition(
    name=SUBMIT_TOOL_NAME,
    description=(
        "Submit the code fix for this incident. Give every file you are "
        "changing in full - its entire new contents, not a diff and not an "
        "excerpt - because what you send is written to the branch exactly as "
        "it stands. Read a file before you rewrite it. This tool is for a "
        f"patch; if you read the code and found nothing in it to change, call "
        f"{REPORT_TOOL_NAME} instead - a flag or a deploy that exposed a fault "
        "is still a fault in the code that could not survive it."
    ),
    properties={
        SUMMARY_FIELD: {
            "type": "string",
            "description": (
                "What the fix does, in one line, as a pull request title an "
                "engineer would scan in a list."
            )
        },
        EXPLANATION_FIELD: {
            "type": "string",
            "description": (
                "Why this is the fix: what the fault was, why the code behaved "
                "that way, and why this change ends it. Written for the person "
                "who has to approve it."
            )
        },
        FILES_FIELD: {
            "type": "array",
            # At least one, refused by the schema rather than read back out of
            # the answer. Strict mode constrains sampling, so an empty patch is
            # not a thing the model can send here - which is the whole of why
            # the verdict needed a tool of its own. `minItems` is honoured only
            # for 0 and 1, and 1 is the bound wanted.
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    PATH_FIELD: {
                        "type": "string",
                        "description": (
                            "The file's path from the repository root, exactly "
                            "as it was listed."
                        )
                    },
                    CONTENT_FIELD: {
                        "type": "string",
                        "description": "The file's entire new contents."
                    }
                },
                "required": [PATH_FIELD, CONTENT_FIELD]
            },
            "description": (
                "Every file the fix changes or adds, each in full - including "
                "the test. Bring the test that exposes the bug: the case that "
                "was failing, asserted to pass, alongside the service's other "
                "tests. A fix without one is a claim; a fix with one is "
                "evidence. The test has to fail against the code as it stands "
                "now, or it proves nothing: where the fault is slowness, assert "
                "a bound on how long the work takes or how much of it is done, "
                "because a test that only checks the answer passes against the "
                "slow code too. At least one file: this tool is how a patch is "
                "sent, and an incident traced to a cause in this service "
                "usually has one."
            )
        }
    },
    required=REQUIRED_FIELDS
)

REPORT_NOTHING_TO_CHANGE = ToolDefinition(
    name=REPORT_TOOL_NAME,
    description=(
        "Report that you read the code and there is genuinely nothing in it to "
        "change. This is a conclusion a person acts on, not a way out of a hard "
        "read: an incident traced to a cause in this service usually has a fix, "
        "and a flag or a deploy that exposed a fault is still a fault in the "
        f"code that could not survive it. Use {SUBMIT_TOOL_NAME} for anything "
        "you would change, however small."
    ),
    properties={
        EXPLANATION_FIELD: {
            "type": "string",
            "description": (
                "What you read, and why none of it needs changing. Written for "
                "the person who has to accept that no fix is coming."
            )
        }
    },
    required=[EXPLANATION_FIELD]
)
