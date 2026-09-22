"""What Code-Fix is asked, and the one shape its answer may take.

The answer is a patch, and a patch is whole files rather than a diff. A diff is
a second thing that can fail, and it fails by producing a file that is subtly
not what anyone wrote - where a whole file that came out wrong is wrong
visibly, on a branch, in front of the person who has to approve it.

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

from typing import Any, Final

from argus_core.models import ToolDefinition
from pydantic import BaseModel, field_validator

# The tool's name and its fields, named once. Both ends of the exchange read
# them - the definition offered to the model, and the reader taking the call
# apart - and a spelling that differed between the two would leave a field
# quietly always missing.
SUBMIT_TOOL_NAME: Final = "submit_fix"

# What is true of fixing a fault whatever the fault was, and so what Code-Fix
# is told once rather than at the top of each incident. It travels as the
# request's `system` (see `ModelPolicy.brief`), which is what lets it - and the
# tool list rendered before it - be read from cache on every incident after the
# first rather than re-sent and re-billed each time.
#
# Three things, and each is here because the model got it wrong without being
# told. A mitigation has usually already hidden the symptom, so the code reads
# as fine and is not. The change that exposed a fault is not the fault, which
# is the one every reader of an incident gets backwards. And submitting nothing
# is a conclusion that needs evidence, not a way out of a hard read.
#
# Nothing about a particular incident may be added here, ever. The saving is
# that the bytes do not change between incidents, so a single interpolated
# detail would not merely dilute it - it would end it, silently, with every
# test still passing.
STANDING_BRIEF: Final = "\n\n".join([
    "A mitigation has probably already hidden the symptom - a flag turned "
    "off, a version rolled back - so the code you are reading is the code "
    "that was broken, whether or not anything looks broken right now.",

    "A change that exposed a fault is not the fault. If switching a flag on "
    "broke the service, the fault is the code that could not survive that "
    "flag being on, and your job is to make it safe to turn back on. The same "
    "goes for a deploy, a config change or a new kind of input: something "
    "changed, and the code did not cope. Fix the not coping. Reverting was "
    "somebody buying time - it left the fault in place behind a switch nobody "
    "now dares touch, which is what you are here to end.",

    "Submit no files only if you have read the code and there is genuinely "
    "nothing in it to change - never merely because a configuration change "
    "triggered the incident. That is the common case and it is still a code "
    "fault."
])

SUMMARY_FIELD: Final = "summary"
EXPLANATION_FIELD: Final = "explanation"
FILES_FIELD: Final = "files"
PATH_FIELD: Final = "path"
CONTENT_FIELD: Final = "content"

REQUIRED_FIELDS: Final = [SUMMARY_FIELD, FILES_FIELD]


class ProposedFile(BaseModel):
    """One file of a patch: where it goes, and everything it says afterwards.

    `content` is the file's whole new text, not the part that changed. The model
    has read the file by the time it answers, so writing it out entire costs
    tokens and buys the one thing a diff cannot give - a result that is either
    the file the model meant or visibly not it.
    """

    path: str
    content: str


class SubmittedFix(BaseModel):
    """What the model submitted, said as fields rather than as a mapping.

    Every field is optional, because finding out what is missing is the point: a
    field the model left out is a fault to put back to it, not an answer that
    failed to arrive. `None` means unanswered.

    An empty `files` is a real answer and not a malformed one - "I looked and
    there is nothing here to change" is a conclusion a human acts on, and is
    different from a submission that could not be read. Whoever reads this has
    to be able to tell those apart, so both parse.

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
        """
        if not isinstance(value, list):
            return []

        return [
            entry for entry in value
            if isinstance(entry, dict)
            and isinstance(entry.get(PATH_FIELD), str)
            and isinstance(entry.get(CONTENT_FIELD), str)
        ]


SUBMIT_FIX = ToolDefinition(
    name=SUBMIT_TOOL_NAME,
    description=(
        "Submit the code fix for this incident. Give every file you are "
        "changing in full - its entire new contents, not a diff and not an "
        "excerpt - because what you send is written to the branch exactly as "
        "it stands. Read a file before you rewrite it. Submit no files only "
        "if you have read the code and there is genuinely nothing in it to "
        "change - a flag or a deploy that exposed a fault is still a fault in "
        "the code that could not survive it."
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
                "evidence. Empty means you read the code and found nothing to "
                "change, which is rare: an incident traced to a cause in this "
                "service usually has one."
            )
        }
    },
    required=REQUIRED_FIELDS
)
