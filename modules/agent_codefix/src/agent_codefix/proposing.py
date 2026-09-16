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
    Hypothesis,
    OpenedPullRequest,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResults,
    Turn,
)

# Aliased because `replay`'s no-op sink is called `nobody`, as `events`' is, and
# this module has no use for the other one to be confused with.
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing
from pydantic import ValidationError
from read_mcp_client import (
    list_repository_files,
    read_repository_file,
    search_repository,
)
from write_mcp_client import commit_to_new_branch, open_pull_request

from agent_codefix.prompting import (
    SUBMIT_FIX,
    SUBMIT_TOOL_NAME,
    SubmittedFix,
)
from agent_codefix.reasoning import (
    Conversation,
    Conversations,
    a_conversation_recorded_for,
)

# What the loop asks of the repository, said as the shape it calls with rather
# than as the function that answers today. `Protocol` rather than a `Callable`
# alias throughout, for the reason the investigator's retrieval channels are:
# a test stands each of these in with `create_autospec`, which needs something
# introspectable - and specing against the client functions would be specing
# against the wrong shape, since those take the connection they are asked over
# and the loop is asked about a repository.


class FixNotAnswered(Exception):
    """The agent never answered within the turns it had.

    Not a verdict on the code. "I read it and there is nothing to change" is a
    conclusion a human acts on; this is a run that stopped mid-sentence, and the
    two reached the same caller as `None` until a live incident spent twelve
    turns exploring and was recorded as having found no fix - a statement about
    the budget dressed as a statement about the service.

    Raised rather than returned because the caller's move differs: a verdict
    ends the question, where this is a job that did not get done and may be
    worth more turns, a narrower cause, or a person.
    """


class SourceSearcher(Protocol):
    def __call__(self, query: str, ref: str, /) -> list[str]: ...


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
                 hypothesis: Hypothesis | None,
                 incident_id: str, /) -> OpenedPullRequest | None: ...


SEARCH_TOOL = "search_repository"
LIST_FILES_TOOL = "list_repository_files"
READ_FILE_TOOL = "read_repository_file"

PATH_ARGUMENT = "path"
QUERY_ARGUMENT = "query"


class FixSettings(SettingsSlice):
    """What the fix loop is aimed and bounded by.

    `github_base_branch` is what a fix is cut from and proposed onto - the
    branch that is actually deployed, since a fix against anything else patches
    a repository nobody is running.
    """

    github_base_branch: str
    codefix_max_turns: int


SEARCH = ToolDefinition(
    name=SEARCH_TOOL,
    description=(
        "Find where something appears in the service's source. Answers with "
        "every matching line as 'path:line: text'. START HERE: the "
        "investigation has already named the cause, so search for it - the "
        "flag, the function, the message from the log line - and the answer "
        "tells you which files to read. Plain text, not a regular expression."
    ),
    properties={
        QUERY_ARGUMENT: {
            "type": "string",
            "description": (
                "The text to look for. Something distinctive from the cause - "
                "a flag name, a function name, an error message."
            )
        }
    },
    required=[QUERY_ARGUMENT]
)

LIST_FILES = ToolDefinition(
    name=LIST_FILES_TOOL,
    description=(
        "List every file in the service's repository, as paths from its root. "
        "A fallback for when searching found nothing and you need to see the "
        f"shape of the repository - prefer {SEARCH_TOOL}, which tells you "
        "which file to open rather than leaving you to guess from names."
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

TOOLS = [SEARCH, LIST_FILES, READ_FILE, SUBMIT_FIX]


def fixes_over(read: McpClient,
               write: McpClient,
               settings: FixSettings,
               recorder: Recorder = records_nothing) -> Fixer:
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
        search=partial(search_repository, client=read),
        list_files=partial(list_repository_files, client=read),
        read_file=partial(read_repository_file, client=read),
        write_branch=partial(commit_to_new_branch, client=write),
        open_pull_request=partial(open_pull_request, client=write),
        recorder=recorder
    )


def propose_fix(hypothesis: Hypothesis | None,
                incident_id: str,
                *,
                settings: FixSettings,
                search: SourceSearcher,
                list_files: FileLister,
                read_file: FileReader,
                write_branch: BranchWriter,
                open_pull_request: PullRequestOpener,
                converse: Conversation | None = None,
                recorder: Recorder = records_nothing,
                conversations: Conversations = a_conversation_recorded_for
                ) -> OpenedPullRequest | None:
    """Proposes a fix for `hypothesis` as a draft pull request, or nothing.

    `None` means the model answered and had nothing to change - "the fault is
    not in the code", which is a real conclusion and the one a human acts on. No
    pull request is opened for it: an empty proposal sends somebody to read a
    diff with nothing in it.

    Raises `FixNotAnswered` when the model never submitted within its turns,
    which is a different thing entirely and used to arrive looking identical.

    Raises whatever the repository raised. A push that was refused and a fix
    that was not found reach the same human, and only one of them is something
    somebody can go and fix - so the failure is not flattened into `None`.

    The collaborators are keyword seams: the real tool calls in production,
    doubles in a test, and no monkeypatching either way.

    `converse` is the exception among them, and defaults to nothing rather than
    to the real call. A conversation that files its receipts has to be built
    from this incident and this recorder, and neither is known until here - so
    what a caller omitting it gets is built below, and a caller injecting a
    scripted one never reaches the construction or the SDK behind it.

    `recorder` changes nothing about the answer and everything about what can be
    said afterwards. Code-Fix spends more than any other agent here and is the
    hardest to second-guess from outside: a patch it declined to write leaves
    nothing behind at all.
    """
    submitted = _what_the_model_submitted(
        hypothesis,
        settings=settings,
        search=search,
        list_files=list_files,
        read_file=read_file,
        converse=converse or conversations(incident_id, recorder)
    )

    if submitted is None:
        raise FixNotAnswered(
            f"the agent read for {settings.codefix_max_turns} turns without "
            f"submitting a fix"
        )

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


def _what_the_model_submitted(hypothesis: Hypothesis | None,
                              *,
                              settings: FixSettings,
                              search: SourceSearcher,
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
                _answer(call, settings, search, list_files, read_file)
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
            search: SourceSearcher,
            list_files: FileLister,
            read_file: FileReader) -> ToolResult:
    """One tool call, answered - including when answering it failed.

    A failure comes back as a result the model reads rather than as an
    exception the loop dies on. What it did wrong is usually recoverable in one
    turn, and what it cannot recover from it will simply fail to submit after,
    which is already an answer this loop knows how to report.
    """
    try:
        return ToolResult(
            call_id=call.id,
            content=_ran(call, settings, search, list_files, read_file)
        )
    except Exception as error:
        return ToolResult(
            call_id=call.id,
            content=f"{type(error).__name__}: {error}",
            failed=True
        )


def _ran(call: ToolCall,
         settings: FixSettings,
         search: SourceSearcher,
         list_files: FileLister,
         read_file: FileReader) -> str:
    if call.name == SEARCH_TOOL:
        found = search(
            str(call.arguments.get(QUERY_ARGUMENT, "")), settings.github_base_branch
        )

        # Said rather than left as an empty answer. A model handed nothing
        # reads it as a tool that failed and tries again with the same query;
        # told the repository does not contain the string, it searches for
        # something else, which is the move that finds the file.
        return "\n".join(found) if found else "no line in the repository matches that"

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


def _what_it_concluded(hypothesis: Hypothesis | None) -> str:
    """The finding in a sentence, or that there was none.

    Said rather than left blank, because the agent is asked either way: a walk
    that reached here having concluded nothing is still worth reading the code
    over, and "I looked and found nothing" is a different answer from "I never
    looked". An empty line after "the investigation concluded" reads as the
    second while claiming to be the first.
    """
    if hypothesis is None:
        return "nothing - no cause was identified, so read the code on its own terms"

    return hypothesis.summary


def _and_what_it_rests_on(hypothesis: Hypothesis | None) -> list[str]:
    """The evidence behind the conclusion, quoted rather than summarised.

    The summary says what broke; the evidence says where. This service's error
    boundary records the innermost frame, so one of these lines is a log line
    naming the file and the line the fault was raised on - and an agent handed
    only the sentence goes searching for a location it was already holding.

    Quoted as the investigation wrote them, because they are quotations: a log
    line restated in the model's own words is no longer something it can search
    the repository for.

    Empty where the investigation recorded none, and empty is right - a heading
    over nothing invites the model to wonder what it is missing.
    """
    if hypothesis is None or not hypothesis.supporting_evidence:
        return []

    return [
        "",
        "What that rests on:",
        *(f"  - {found.claim}" for found in hypothesis.supporting_evidence)
    ]


def _the_opening_message(hypothesis: Hypothesis | None) -> str:
    return "\n".join([
        "An incident has been investigated and traced to a cause in this "
        "service's code. Your job is to fix that cause permanently.",
        "",
        f"What the investigation concluded: {_what_it_concluded(hypothesis)}",
        *_and_what_it_rests_on(hypothesis),
        "",
        f"Start by searching. Take what is named above - the flag, the "
        f"function, the message - and {SEARCH_TOOL} for it: the answer names "
        f"the files the fault is in, which is what you would otherwise be "
        f"guessing at. Read those, then call {SUBMIT_TOOL_NAME} with every "
        f"file you are changing, in full.",
        "",
        "A mitigation has probably already hidden the symptom - a flag turned "
        "off, a version rolled back - so the code you are reading is the code "
        "that was broken, whether or not anything looks broken right now.",
        "",
        "A change that exposed a fault is not the fault. If switching a flag "
        "on broke the service, the fault is the code that could not survive "
        "that flag being on, and your job is to make it safe to turn back on. "
        "The same goes for a deploy, a config change or a new kind of input: "
        "something changed, and the code did not cope. Fix the not coping. "
        "Reverting was somebody buying time - it left the fault in place "
        "behind a switch nobody now dares touch, which is what you are here "
        "to end.",
        "",
        "Submit no files only if you have read the code and there is genuinely "
        "nothing in it to change - never merely because a configuration change "
        "triggered the incident. That is the common case and it is still a "
        "code fault."
    ])


def _the_case_for(submitted: SubmittedFix,
                  hypothesis: Hypothesis | None,
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
        f"The investigation concluded: {_what_it_concluded(hypothesis)}",
        "",
        "This is a draft. Argus cannot merge it - review it as you would any "
        "change from somebody who has not run the service."
    ])
