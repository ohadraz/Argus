"""Proposing a permanent fix for the cause an incident was traced to (§7.4).

The loop. The model is handed what the investigation concluded, reads as much of
the repository as it needs to find the fault, and submits a patch; this module
writes that patch to a branch and opens a draft pull request. There is no
arrangement of tool calls that gets it further than a proposal - the tools to go
further are not on the server this reaches (§13).

It does not investigate. The cause is settled by the time Code-Fix is called,
and a model asked to find it again would spend its whole reading budget
rediscovering what it was already handed.

Bounded, like the investigation is, and for the same reason: a model reading
file after file without ever answering is a run that has to end somewhere. The
bound is never expressed to the model, because a bound it could ask to extend
would not be one.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Protocol

from argus_core import SettingsSlice
from argus_core.mcp_transport import McpClient
from argus_core.models import (
    Ask,
    Exchange,
    OpenedPullRequest,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResults,
    Turn,
)
from pydantic import ValidationError
from read_mcp_client import list_repository_files, read_repository_file
from write_mcp_client import commit_to_new_branch, open_pull_request

from agent_codefix.prompting import (
    SUBMIT_FIX,
    SUBMIT_TOOL_NAME,
    SubmittedFix,
)
from agent_codefix.reasoning import Conversation, converse

# What the loop asks of the repository, said as the shape it calls with rather
# than as the function that answers today. `Protocol` rather than a `Callable`
# alias throughout, for the reason the investigator's retrieval channels are:
# a test stands each of these in with `create_autospec`, which needs something
# introspectable - and specing against the client functions would be specing
# against the wrong shape, since those take the connection they are asked over
# and the loop is asked about a repository.


class FileLister(Protocol):
    def __call__(self, ref: str, /) -> list[str]: ...


class FileReader(Protocol):
    def __call__(self, path: str, ref: str, /) -> str: ...


class BranchWriter(Protocol):
    def __call__(self,
                 *,
                 branch: str,
                 base_branch: str,
                 files: Mapping[str, str],
                 message: str) -> str: ...


class PullRequestOpener(Protocol):
    def __call__(self,
                 *,
                 head_branch: str,
                 base_branch: str,
                 title: str,
                 body: str) -> OpenedPullRequest: ...


class Fixer(Protocol):
    """What a bound fix channel looks like to whoever walks an incident.

    The shape the Orchestrator's `ProposeFix` names, said here too rather than
    imported from there: the kernel's layering runs the other way, and an agent
    that imported the walk to describe its own answer would have the walk depend
    on itself through it.
    """

    def __call__(self,
                 hypothesis: str,
                 incident_id: str, /) -> OpenedPullRequest | None: ...


LIST_FILES_TOOL = "list_repository_files"
READ_FILE_TOOL = "read_repository_file"

PATH_ARGUMENT = "path"


class FixSettings(SettingsSlice):
    """What the fix loop is aimed and bounded by.

    `github_base_branch` is what a fix is cut from and proposed onto - the
    branch that is actually deployed, since a fix against anything else patches
    a repository nobody is running.
    """

    github_base_branch: str
    codefix_max_turns: int


LIST_FILES = ToolDefinition(
    name=LIST_FILES_TOOL,
    description=(
        "List every file in the service's repository, as paths from its root. "
        "Call this first: it names the whole repository in one call, and what "
        "you read afterwards is chosen out of it."
    ),
    properties={},
    required=[]
)

READ_FILE = ToolDefinition(
    name=READ_FILE_TOOL,
    description=(
        "Read one file's entire contents. Read a file before you rewrite it - "
        "what you submit replaces what is there, so a file you did not read is "
        "a file you are overwriting blind."
    ),
    properties={
        PATH_ARGUMENT: {
            "type": "string",
            "description": "The file's path from the repository root."
        }
    },
    required=[PATH_ARGUMENT]
)

TOOLS = [LIST_FILES, READ_FILE, SUBMIT_FIX]


def fixes_over(read: McpClient,
               write: McpClient,
               settings: FixSettings) -> Fixer:
    """The fix channel, over a connection to each tier it needs.

    Two clients rather than one, because the two halves of proposing a fix are
    two tiers by design: the repository is *read* from the process that cannot
    write, and the branch and the proposal come from the one that can (§13).
    That split is the whole guarantee, and this is the one place both ends of it
    are held at once.

    Bound where a process starts, so the walk is handed something it can call
    with an incident rather than the means to build one.
    """
    return partial(
        propose_fix,
        settings=settings,
        list_files=partial(list_repository_files, client=read),
        read_file=partial(read_repository_file, client=read),
        write_branch=partial(commit_to_new_branch, client=write),
        open_pull_request=partial(open_pull_request, client=write),
        converse=converse
    )


def propose_fix(hypothesis: str,
                incident_id: str,
                *,
                settings: FixSettings,
                list_files: FileLister,
                read_file: FileReader,
                write_branch: BranchWriter,
                open_pull_request: PullRequestOpener,
                converse: Conversation) -> OpenedPullRequest | None:
    """Proposes a fix for `hypothesis` as a draft pull request, or nothing.

    `None` has two meanings and they are both honest answers: the model
    submitted a patch with no files in it - "the fault is not in the code",
    which is true of every flag scenario - or it never submitted at all within
    its turns. Neither is an error, and neither opens a pull request: an empty
    proposal sends a human to read a diff with nothing in it.

    Raises whatever the repository raised. A push that was refused and a fix
    that was not found reach the same human, and only one of them is something
    somebody can go and fix - so the failure is not flattened into `None`.

    The collaborators are keyword seams: the real tool calls in production,
    doubles in a test, and no monkeypatching either way.
    """
    submitted = _what_the_model_submitted(
        hypothesis,
        settings=settings,
        list_files=list_files,
        read_file=read_file,
        converse=converse
    )

    if submitted is None:
        return None

    patch = submitted.patch()

    if not patch:
        return None

    branch = _a_branch_for(incident_id)
    title = submitted.summary or f"fix for incident {incident_id}"

    write_branch(
        branch=branch,
        base_branch=settings.github_base_branch,
        files=patch,
        message=title
    )

    return open_pull_request(
        head_branch=branch,
        base_branch=settings.github_base_branch,
        title=title,
        body=_the_case_for(submitted, hypothesis, incident_id)
    )


def _what_the_model_submitted(hypothesis: str,
                              *,
                              settings: FixSettings,
                              list_files: FileLister,
                              read_file: FileReader,
                              converse: Conversation) -> SubmittedFix | None:
    """The conversation, until the model submits or runs out of turns.

    Every turn that is not a submission is answered and put back, including the
    ones that failed: a model guessing at a path is doing its job badly for one
    turn, not failing, and ending here would throw away every file it had read
    correctly up to then.
    """
    transcript: list[Exchange] = [Ask(text=_the_opening_message(hypothesis))]

    for _ in range(settings.codefix_max_turns):
        turn = converse(transcript, TOOLS)
        transcript.append(turn)

        submitted = _the_submission_in(turn)

        if submitted is not None:
            return submitted

        transcript.append(
            ToolResults(results=[
                _answer(call, settings, list_files, read_file)
                for call in turn.tool_calls
            ])
        )

    return None


def _the_submission_in(turn: Turn) -> SubmittedFix | None:
    """The fix, if this turn carried one that could be read.

    A submission that will not validate is treated as no submission, which
    leaves the loop running and the model free to answer again. Every field of
    `SubmittedFix` is optional and its validators drop rather than refuse, so
    reaching here at all takes an argument payload that is not an object.
    """
    submitting = next(
        (call for call in turn.tool_calls if call.name == SUBMIT_TOOL_NAME), None
    )

    if submitting is None:
        return None

    try:
        return SubmittedFix.model_validate(submitting.arguments)
    except (ValidationError, TypeError):
        return None


def _answer(call: ToolCall,
            settings: FixSettings,
            list_files: FileLister,
            read_file: FileReader) -> ToolResult:
    """One tool call, answered - including when answering it failed.

    A failure comes back as a result the model reads rather than as an
    exception the loop dies on. What it did wrong is usually recoverable in one
    turn, and what it cannot recover from it will simply fail to submit after,
    which is already an answer this loop knows how to report.
    """
    try:
        return ToolResult(call_id=call.id, content=_ran(call, settings, list_files, read_file))
    except Exception as error:
        return ToolResult(
            call_id=call.id,
            content=f"{type(error).__name__}: {error}",
            failed=True
        )


def _ran(call: ToolCall,
         settings: FixSettings,
         list_files: FileLister,
         read_file: FileReader) -> str:
    if call.name == LIST_FILES_TOOL:
        return "\n".join(list_files(settings.github_base_branch))

    if call.name == READ_FILE_TOOL:
        return read_file(
            str(call.arguments.get(PATH_ARGUMENT, "")), settings.github_base_branch
        )

    return f"there is no tool called {call.name}"


def _a_branch_for(incident_id: str) -> str:
    """The branch a fix is written to, named for the incident that caused it.

    Two incidents patching the same file would otherwise write over each
    other's proposal, and a branch found weeks later would say nothing about
    where it came from.
    """
    return f"argus/fix-{incident_id}"


def _the_opening_message(hypothesis: str) -> str:
    return "\n".join([
        "An incident has been investigated and traced to a cause in this "
        "service's code. Your job is to fix that cause permanently.",
        "",
        f"What the investigation concluded: {hypothesis}",
        "",
        "Read the repository until you have found the fault, then call "
        f"{SUBMIT_TOOL_NAME} with every file you are changing, in full.",
        "",
        "Two things worth knowing. A mitigation may already have hidden the "
        "symptom - a flag turned off, a version rolled back - so the code you "
        "are reading is the code that was broken, whether or not anything is "
        "broken right now. And if the cause is not in the code at all, submit "
        "no files and say so: that is a real answer and a useful one."
    ])


def _the_case_for(submitted: SubmittedFix,
                  hypothesis: str,
                  incident_id: str) -> str:
    """What a person reads before deciding whether to merge.

    The model's explanation, and the incident it came from, said plainly. The
    provenance is not decoration: whoever opens this needs to know an agent
    proposed it and which incident it answers, so the change can be judged
    against something rather than taken on trust.
    """
    return "\n".join([
        submitted.explanation or "No explanation was given.",
        "",
        "---",
        "",
        f"Proposed by Argus for incident `{incident_id}`.",
        f"The investigation concluded: {hypothesis}",
        "",
        "This is a draft. Argus cannot merge it - review it as you would any "
        "change from somebody who has not run the service."
    ])
