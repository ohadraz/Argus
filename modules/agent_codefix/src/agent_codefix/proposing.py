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

What the model is offered is `tools`, what it is first told is `opening`, and what
it may spend is `budget`. What is left here is the conversation between them and
the proposal at the end of it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import partial
from typing import Final, Protocol

from argus_core.budget import StillWanted, wanted_throughout
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
    Exchange,
    Hypothesis,
    ModelPolicy,
    OpenedPullRequest,
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

from agent_codefix.budget import FixSettings, a_budget_for
from agent_codefix.opening import the_opening_message, what_it_concluded
from agent_codefix.prompting import (
    EXPLANATION_FIELD,
    REPORT_TOOL_NAME,
    STANDING_BRIEF,
    SUBMIT_TOOL_NAME,
    SubmittedFix,
    the_paths_whose_content_is_not_source,
)
from agent_codefix.retrieval import (
    FileLister,
    FileReader,
    IndexNotice,
    MeaningSearcher,
    SourceSearcher,
)
from agent_codefix.tools import the_answer_to, tools_for

logger = logging.getLogger(__name__)


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


class FixStopped(Exception):
    """The incident stopped being wanted while a fix was being worked out.

    Not a fix the model never answered, and not one it declined: nothing was
    too expensive and nobody said no to the code - somebody said stop. Its own
    exception because the walk's move is its own: report nothing attempted,
    and go no further. Raised rather than returned, because `None` already
    means "the fault is not in the code", which is a conclusion this is not.
    """


# What the proposal half asks of the write tier, and what the walk asks of this
# module - said as shapes for the reason the read channels are, in `retrieval`.


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
                 incident_id: str, /,
                 *,
                 still_wanted: StillWanted = ...) -> OpenedPullRequest | None: ...


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
                conversations: Conversations = a_conversation_recorded_for,
                still_wanted: StillWanted = wanted_throughout
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

    `still_wanted` is asked before every turn and once more before the branch
    is written, and `FixStopped` is raised on "no". A turn in flight comes back
    and is recorded; nothing after it is asked for, and nothing is written.
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
                max_output_tokens=settings.codefix_max_output_tokens,
                brief=STANDING_BRIEF
            )
        ),
        still_wanted=still_wanted
    )

    patch = submitted.patch()

    if not patch:
        return None

    # The branch and the pull request are changes to the world, and the turn
    # that produced this patch may have been answered after somebody said stop.
    if not still_wanted():
        logger.info("fix not proposed, incident no longer wanted")
        raise FixStopped("the incident is no longer wanted; the fix was not proposed")

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
                              converse: Conversation,
                              still_wanted: StillWanted) -> SubmittedFix:
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
        Ask(text=the_opening_message(
            hypothesis, settings, index_notice, list_files
        ))
    ]
    spend = a_budget_for(settings)

    while not spend.bounds_reached():
        if not still_wanted():
            logger.info("fix stopped, incident no longer wanted")
            raise FixStopped("the incident is no longer wanted")

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
            logger.warning("answer truncated")

            raise FixNotAnswered(
                "the fix did not fit in the room the model had to write it: "
                f"{cut_short}"
            ) from cut_short

        spend.record(turn)
        transcript.append(turn)

        verdict = _the_verdict_in(turn)

        if verdict is not None:
            return verdict

        submitted = _the_submission_in(turn)

        if submitted is not None and submitted.files:
            not_source = the_paths_whose_content_is_not_source(submitted.files)

            if not_source:
                # A patch that cannot be read as the language it is written in,
                # which is a submission to recover from rather than one to
                # propose. Put back for the reason an empty one is: the model has
                # decided what to write and is one turn from writing it properly.
                logger.warning("patch is not source", extra={"paths": not_source})
                transcript.append(_what_it_is_told_next(
                    [_that_is_not_source(turn, not_source)],
                    one_call_left=spend.is_on_its_last_call()
                ))

                continue

            return submitted

        if submitted is not None:
            # A patch with nothing in it, which the submission's own schema
            # refuses - so this is one whose every entry was dropped as
            # unreadable rather than one the model sent empty on purpose. It
            # meant to attach a patch, and put back it gets the turn to.
            #
            # Never read as a verdict, however often it arrives. The verdict is
            # a tool of its own, so a model that wanted it would have called
            # it, and reporting this as "there is nothing to change" would put
            # a conclusion in its mouth - which is what happened, on a live run
            # that submitted one naming the file and the bound it wanted. A
            # model that keeps sending this runs out instead, and running out
            # is what a reader is told.
            logger.warning("patch was empty")
            transcript.append(_what_it_is_told_next(
                [_no_patch_was_attached(turn)],
                one_call_left=spend.is_on_its_last_call()
            ))

            continue

        transcript.append(_what_it_is_told_next(
            [
                the_answer_to(
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


def _no_patch_was_attached(turn: Turn) -> ToolResult:
    """The submission put back, addressed to the call that made it.

    A failure rather than a remark, because `failed` is what tells the model
    this is something to recover from rather than evidence about the incident -
    and recovering is the whole point: it has already decided what to write.

    The other ending is named rather than left to be remembered. Told only that
    files were missing, a model that had in fact found nothing to change would
    invent a change to satisfy the complaint, which is the worse of the two
    failures this is guarding - so the way to say that is put in front of it.
    """
    submitting = next(
        (call for call in turn.tool_calls if call.name == SUBMIT_TOOL_NAME), None
    )

    return ToolResult(
        call_id=submitting.id if submitting is not None else "",
        content=(
            "That submission carried no files, so nothing was read from it. "
            "Submit again with the whole content of every file the fix touches. "
            "If what you meant is that the code needs no change, that is a "
            f"complete answer and {REPORT_TOOL_NAME} is how to give it."
        ),
        failed=True
    )


def _that_is_not_source(turn: Turn, paths: list[str]) -> ToolResult:
    """The submission put back because a file's content is not the language it is.

    A failure rather than a remark, as the empty patch's is, and for the same
    reason: this is something to recover from, not evidence about the incident.

    The paths are named. What happened on the run this exists for is that the
    model wrote the whole module into its explanation and pointed `content` at
    it - so a complaint that did not say which file it means would be answered by
    a model re-reading its own prose for the answer it already has.

    Said as "not source" rather than as the parser's message. A `SyntaxError` from
    line one of `(see above)` describes the placeholder rather than the mistake,
    and the mistake is that a pointer was sent where a file belongs.
    """
    submitting = next(
        (call for call in turn.tool_calls if call.name == SUBMIT_TOOL_NAME), None
    )

    return ToolResult(
        call_id=submitting.id if submitting is not None else "",
        content=(
            f"The content submitted for {', '.join(paths)} is not source - it "
            f"does not parse as Python, so writing it out would replace the file "
            f"with something nothing can read. Submit again with that file's "
            f"whole new text as the value of its content, and nothing referring "
            f"to text written anywhere else."
        ),
        failed=True
    )


def _the_verdict_in(turn: Turn) -> SubmittedFix | None:
    """The judgement that nothing needs changing, if this turn reached one.

    Said as a `SubmittedFix` carrying no files, because that is what it is to
    everything downstream: no branch, no proposal, and an explanation for the
    person who has to accept that no fix is coming. What the second tool buys
    is not a second type - it is that reaching this no longer depends on
    reading a patch that turned out to be empty.

    Believed the first time, unlike an empty patch. Only this tool means this,
    so there is no other reading to rule out.
    """
    reporting = next(
        (call for call in turn.tool_calls if call.name == REPORT_TOOL_NAME), None
    )

    if reporting is None:
        return None

    try:
        return SubmittedFix.model_validate(
            {EXPLANATION_FIELD: reporting.arguments.get(EXPLANATION_FIELD)}
        )
    except (ValidationError, TypeError):
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


def _a_branch_for(incident_id: str) -> str:
    """The branch a fix is written to, named for the incident that caused it.

    Two incidents patching the same file would otherwise write over each
    other's proposal, and a branch found weeks later would say nothing about
    where it came from.
    """
    return f"argus/fix-{incident_id}"


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
        f"The investigation concluded: {what_it_concluded(hypothesis)}",
        "",
        "This is a draft. Argus cannot merge it - review it as you would any "
        "change from somebody who has not run the service."
    ])
