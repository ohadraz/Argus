"""Proposing a permanent fix for the cause an incident was traced to (§7.4).

The loop. The model is handed what the investigation concluded, reads as much of
the repository as it needs to find the fault, and submits a patch; this module
writes that patch to a branch and opens a draft pull request. There is no
arrangement of tool calls that gets it further than a proposal - the tools to go
further are not on the server this reaches (§13).

It does not investigate. The cause is settled by the time Code-Fix is called,
and a model asked to find it again would spend its whole reading budget
rediscovering what it was already handed.

Bounded on three axes, like the investigation is, and for the same reason:
they fail differently and none implies the others. This is the agent a call
count alone cannot bound - it reads whole files and carries every one it has
read for the rest of the run, so it can be frugal in calls and ruinous in
tokens. No bound is ever expressed to the model, because one it could ask to
extend would not be one.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Final, Protocol

from argus_core import SettingsSlice
from argus_core.budget import Budget
from argus_core.llm import (
    AnswerTruncated,
    Conversation,
    Conversations,
    ModelRefused,
    a_conversation_recorded_for,
)
from argus_core.mcp_transport import McpClient
from argus_core.models import (
    Ask,
    CodeSearch,
    Effort,
    Exchange,
    Hypothesis,
    ModelPolicy,
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
    get_repository_index_freshness,
    list_repository_files,
    read_repository_file,
    search_repository,
    search_repository_by_meaning,
)
from write_mcp_client import commit_to_new_branch, open_pull_request

from agent_codefix.prompting import (
    SUBMIT_FIX,
    SUBMIT_TOOL_NAME,
    SubmittedFix,
)

# What the loop asks of the repository, said as the shape it calls with rather
# than as the function that answers today. `Protocol` rather than a `Callable`
# alias throughout, for the reason the investigator's retrieval channels are:
# a test stands each of these in with `create_autospec`, which needs something
# introspectable - and specing against the client functions would be specing
# against the wrong shape, since those take the connection they are asked over
# and the loop is asked about a repository.


class FixNotAnswered(Exception):
    """The agent never answered within the budget it had.

    Not a verdict on the code. "I read it and there is nothing to change" is a
    conclusion a human acts on; this is a run that stopped mid-sentence, and the
    two reached the same caller as `None` until a live incident spent twelve
    turns exploring and was recorded as having found no fix - a statement about
    the budget dressed as a statement about the service.

    Which bound ran out is carried in the message rather than assumed. It was
    always turns while turns were the only way to run out; there are three
    now, they are widened in three different places, and a reader told the
    wrong one widens a budget that was never the problem. An answer too large
    to write arrives here too - at the model's whole output ceiling that is a
    fix that cannot be expressed as whole files, which is a different
    afternoon again.

    Raised rather than returned because the caller's move differs: a verdict
    ends the question, where this is a job that did not get done and may be
    worth a wider bound, a narrower cause, or a person.
    """


def a_budget_for(settings: FixSettings) -> Budget:
    """What one attempt at a fix may spend, as this deployment configures it.

    Beside the settings it reads rather than on `Budget`, which is the
    kernel's and knows none of its callers by name. The investigator has one
    of these too, over fields of its own - what the two share is the
    arithmetic, not what their numbers are called.
    """
    return Budget(
        max_tool_calls=settings.codefix_max_tool_calls,
        max_tokens=settings.codefix_max_tokens,
        max_seconds=settings.codefix_max_seconds
    )


# What the model is told when one call is all that is left, ridden in on the
# last result rather than sent as a message of its own: it is not a separate
# thing to weigh, it is the condition the rest of the reply is read under.
#
# Without it a model spends its last call asking for one more file, and
# everything it read is thrown away as no fix proposed - which reads as a
# verdict on code nobody finished looking at. It costs more here than in the
# investigation, because the turns being discarded are whole files.
_ONE_CALL_LEFT: Final = (
    "\n\nThis is your last call: there is no budget for another read. Submit "
    "the fix now, from what you have already seen, or say there is nothing to "
    "change."
)


class FixDeclined(Exception):
    """The model was asked to write a fix and said no.

    Its own failure rather than one of the others, because none of their next
    moves is this one. More turns will not help - the same question over the
    same code is declined again, which is what separates this from running
    out of turns. Nothing is broken, so there is nothing to go and repair,
    which is what separates it from a repository that refused. And the code
    was never judged, so "there is nothing here to change" would be a verdict
    nobody reached.

    Told apart because it used to reach the walk's broad handler and be
    reported as a fix that could not be proposed - the same sentence a GitHub
    outage produces. A reader seeing no pull request and that reason goes
    looking for an outage that never happened.
    """


class SourceSearcher(Protocol):
    def __call__(self, query: str, ref: str, /) -> list[str]: ...


class MeaningSearcher(Protocol):
    """Finding code by describing what it does rather than by naming it.

    The other retrieval channel, and the same shape as the first on purpose:
    the loop answers both the same way, and a caller configured for one of
    them is offering the model a different tool rather than running different
    code.
    """

    def __call__(self, description: str, ref: str, /) -> list[str]: ...


class IndexNotice(Protocol):
    """What has to be said about the index before anything it answers is used.

    Asked once, before the conversation starts, rather than read off a search
    result: a model that learns the index is behind from a result it has
    already acted on has learned it a turn too late. Empty when there is
    nothing to say, which is the ordinary state.
    """

    def __call__(self, ref: str, /) -> str: ...


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
SEARCH_BY_MEANING_TOOL = "search_repository_by_meaning"
LIST_FILES_TOOL = "list_repository_files"
READ_FILE_TOOL = "read_repository_file"

PATH_ARGUMENT = "path"
QUERY_ARGUMENT = "query"
DESCRIPTION_ARGUMENT = "description"


class FixSettings(SettingsSlice):
    """What the fix loop is aimed and bounded by.

    `github_base_branch` is what a fix is cut from and proposed onto - the
    branch that is actually deployed, since a fix against anything else patches
    a repository nobody is running.
    """

    github_base_branch: str
    # Three bounds rather than one, for the reason the investigation has
    # three: they fail differently and none implies the others. This
    # agent is the case a call count alone cannot see - it reads whole
    # files and writes whole files, so a run can be frugal in calls and
    # ruinous in tokens. Measured, one that reads the three largest files
    # in the Target Service carries 47,950 tokens of source for every
    # remaining turn.
    #
    # Calls rather than turns, because a model may ask for several files
    # at once and a bound counting turns would let it read several times
    # what it was allowed while still looking healthy.
    codefix_max_tool_calls: int
    codefix_max_tokens: int
    codefix_max_seconds: float
    # Which model writes the fix and how hard it is asked to think. Here
    # with the bound rather than anywhere else because both are what a
    # deployment decides about one attempt at a fix, and both are read once
    # when the loop starts. This is the agent the choice matters most for:
    # its answers are whole files, which is the workload where the higher
    # efforts earn their cost and the cheaper models most obviously do not.
    codefix_model: str
    codefix_effort: Effort
    # Whole files, so far more room than any other agent needs, and past
    # the line where the answer has to be streamed to arrive at all.
    codefix_max_output_tokens: int
    # Which ways of finding code this deployment has, and so which the model
    # is offered. Both in production, where the model chooses per question;
    # one alone where the benchmark is comparing them, or where nothing builds
    # an index and a tool that could only ever answer nothing would teach the
    # model that the cause is not in the code.
    code_search: CodeSearch


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

SEARCH_BY_MEANING = ToolDefinition(
    name=SEARCH_BY_MEANING_TOOL,
    description=(
        "Find code by describing what it does, when you have no exact text to "
        "search for. Answers with passages of the service's source - each one "
        "'path:start-end' and the lines themselves - nearest in meaning to "
        f"your description. Use this where {SEARCH_TOOL} cannot help: the "
        "investigation described a behaviour ('the discount is divided by a "
        "count that can be zero') and the repository may not contain any of "
        "those words. Describe the behaviour and the mistake, not an "
        "identifier. Worth using alongside the other search rather than "
        "instead of it - one matches characters, this matches meaning."
    ),
    properties={
        DESCRIPTION_ARGUMENT: {
            "type": "string",
            "description": (
                "What the code you are looking for does, in a sentence - the "
                "behaviour and what is wrong with it, as you would describe "
                "it to another engineer."
            )
        }
    },
    required=[DESCRIPTION_ARGUMENT]
)


def tools_for(settings: FixSettings) -> list[ToolDefinition]:
    """The tools this deployment offers the model, in the order it meets them.

    Both implementations stay present whichever is chosen - what configuration
    decides is what the model is *offered*, not what this module can do. A
    channel switched off is one definition missing from a list, so a benchmark
    run comparing retrievers is running the same code either way.

    Searching comes first because the opening message tells the model to start
    there, and a list whose order contradicts its instructions is one more
    thing to be resolved by whichever the model is most used to.
    """
    searching = {
        CodeSearch.GREP: [SEARCH],
        CodeSearch.MEANING: [SEARCH_BY_MEANING],
        CodeSearch.BOTH: [SEARCH, SEARCH_BY_MEANING]
    }

    return [
        *searching[settings.code_search],
        LIST_FILES,
        READ_FILE,
        SUBMIT_FIX
    ]


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
        search_by_meaning=partial(search_repository_by_meaning, client=read),
        index_notice=partial(get_repository_index_freshness, client=read),
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
                search_by_meaning: MeaningSearcher,
                index_notice: IndexNotice,
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

    Raises `FixNotAnswered` when the model never submitted within its budget,
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
        search_by_meaning=search_by_meaning,
        index_notice=index_notice,
        list_files=list_files,
        read_file=read_file,
        converse=converse or conversations(
            incident_id,
            recorder,
            policy=ModelPolicy(
                model=settings.codefix_model,
                effort=settings.codefix_effort,
                max_output_tokens=settings.codefix_max_output_tokens
            )
        )
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
                              search_by_meaning: MeaningSearcher,
                              index_notice: IndexNotice,
                              list_files: FileLister,
                              read_file: FileReader,
                              converse: Conversation) -> SubmittedFix:
    """The conversation, until the model submits or runs out of budget.

    Every turn that is not a submission is answered and put back, including the
    ones that failed: a model guessing at a path is doing its job badly for one
    turn, not failing, and ending here would throw away every file it had read
    correctly up to then.

    Raises rather than returning nothing when the budget runs out. What
    stopped it is the whole of what a reader can act on, and only here is it
    known - a caller handed `None` would have to guess at which of three
    bounds bound, and the old one guessed "turns" because that was the only
    answer there was.
    """
    tools = tools_for(settings)
    transcript: list[Exchange] = [
        Ask(text=_the_opening_message(hypothesis, settings, index_notice))
    ]
    spend = a_budget_for(settings)

    while not spend.bounds_reached():
        try:
            turn = converse(transcript, tools)
        except ModelRefused as declined:
            # Final, and final for its own reason: the evidence would be
            # declined again, so the turns left are not worth spending.
            raise FixDeclined(f"the model declined to write a fix: {declined}") from declined
        except AnswerTruncated as cut_short:
            # A bound was too small, which is what `FixNotAnswered` already
            # means - but room rather than turns, and that difference is the
            # whole of what a reader can act on. Code-Fix asks for the
            # model's entire output ceiling, so an answer that still did not
            # fit is a fix too large to write as whole files, and neither a
            # wider budget nor another attempt changes that.
            raise FixNotAnswered(
                "the fix did not fit in the room the model had to write it: "
                f"{cut_short}"
            ) from cut_short

        spend.record(turn)
        transcript.append(turn)

        submitted = _the_submission_in(turn)

        if submitted is not None:
            return submitted

        transcript.append(_what_it_is_told_next(
            [
                _answer(
                    call, settings, search, search_by_meaning, list_files, read_file
                )
                for call in turn.tool_calls
            ],
            one_call_left=spend.is_on_its_last_call()
        ))

    # Which bound ended it, named for the human who has to act on it. It was
    # "turns" while the call count was the only way to run out; there are
    # three ways now, they are widened in three different places, and
    # widening the one that was never the problem is a wasted afternoon.
    raise FixNotAnswered(
        "the agent read until it ran out of "
        f"{', '.join(bound.value for bound in spend.bounds_reached())} "
        "without submitting a fix"
    )


def _what_it_is_told_next(results: list[ToolResult],
                          one_call_left: bool) -> ToolResults:
    """What comes back from one turn's requests, and the warning if it is due.

    The warning rides on the last result rather than travelling as a message
    of its own, because it is not a separate thing to weigh - it is the
    condition under which everything else in this reply should be read. The
    investigator's loop says it the same way, for the same reason.

    Without it a model spends its last call asking for one more file and
    everything it read is thrown away as no fix proposed - which reads as a
    verdict on code nobody finished looking at. That costs more here than
    anywhere else: the turns being discarded are whole files.
    """
    if not one_call_left or not results:
        return ToolResults(results=results)

    last = results[-1]

    return ToolResults(results=[
        *results[:-1],
        ToolResult(
            call_id=last.call_id,
            content=last.content + _ONE_CALL_LEFT,
            failed=last.failed
        )
    ])


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
            search_by_meaning: MeaningSearcher,
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
            content=_ran(
                call, settings, search, search_by_meaning, list_files, read_file
            )
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
         search_by_meaning: MeaningSearcher,
         list_files: FileLister,
         read_file: FileReader) -> str:
    if call.name == SEARCH_BY_MEANING_TOOL:
        near = search_by_meaning(
            str(call.arguments.get(DESCRIPTION_ARGUMENT, "")),
            settings.github_base_branch
        )

        # Answered in words for the reason the substring channel is, and with
        # more at stake: an empty answer here is ambiguous between an index
        # that holds nothing like this and an index that holds nothing at all,
        # and a model left to guess picks the reading that ends the work.
        return "\n\n".join(near) if near else (
            "no passage in the repository reads like that - try describing the "
            "behaviour differently, or search for an exact string instead"
        )

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


def _how_to_start_looking(settings: FixSettings) -> str:
    """Which search to reach for first, said in terms of the ones it has.

    An instruction rather than a hope: a model given tools and no order to use
    them in reaches for the one it is most used to. Which means the sentence
    has to name tools this deployment actually offers - telling a model to
    start with a search it was not given is the one way to make an opening
    message worse than none.
    """
    if settings.code_search is CodeSearch.MEANING:
        return (
            f"Start by searching. Describe what the broken code does - the "
            f"behaviour named above and what is wrong with it - and "
            f"{SEARCH_BY_MEANING_TOOL} for it: the answer is the passages "
            f"nearest that description, which is what you would otherwise be "
            f"guessing at."
        )

    if settings.code_search is CodeSearch.GREP:
        return (
            f"Start by searching. Take what is named above - the flag, the "
            f"function, the message - and {SEARCH_TOOL} for it: the answer "
            f"names the files the fault is in, which is what you would "
            f"otherwise be guessing at."
        )

    return (
        f"Start by searching, and you have two ways to. Take what is named "
        f"above - the flag, the function, the message - and {SEARCH_TOOL} for "
        f"it. Where the conclusion describes a behaviour rather than naming "
        f"anything the code would contain, {SEARCH_BY_MEANING_TOOL} with that "
        f"description instead: it answers with the passages nearest it in "
        f"meaning. Both beat guessing at file names."
    )


def _what_is_known_about_the_index(settings: FixSettings,
                                   index_notice: IndexNotice) -> list[str]:
    """What the model has to know about searching by meaning before it does.

    Empty when the index describes the commit being fixed, which is the
    ordinary state: a warning printed every run is a warning nobody reads, and
    that is how the run where it was true goes unnoticed.

    Not asked at all where the channel is off. The answer would be true and
    about a tool the model does not have, which is a paragraph spent teaching
    it to distrust something it cannot use.
    """
    if settings.code_search is CodeSearch.GREP:
        return []

    notice = index_notice(settings.github_base_branch)

    return ["", notice] if notice else []


def _the_opening_message(hypothesis: Hypothesis | None,
                         settings: FixSettings,
                         index_notice: IndexNotice) -> str:
    return "\n".join([
        "An incident has been investigated and traced to a cause in this "
        "service's code. Your job is to fix that cause permanently.",
        "",
        f"What the investigation concluded: {_what_it_concluded(hypothesis)}",
        *_and_what_it_rests_on(hypothesis),
        *_what_is_known_about_the_index(settings, index_notice),
        "",
        f"{_how_to_start_looking(settings)} Read the files it names, then "
        f"call {SUBMIT_TOOL_NAME} with every file you are changing, in full.",
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
