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
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Final, NamedTuple, Protocol

from argus_core import was_lost
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
    CodeOutsideThePatch,
    CodeUse,
    Exchange,
    Hypothesis,
    Leads,
    ModelPolicy,
    OpenedPullRequest,
    ProposedFix,
    ToolCall,
    ToolResult,
    ToolResults,
    Turn,
    WhatArgusDid,
    no_leads,
    not_yet_shown,
)

# Aliased because `replay`'s no-op sink is called `nobody`, as `events`' is, and
# this module has no use for the other one to be confused with.
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing
from pydantic import ValidationError
from read_mcp_client import (
    branch_contains_revision,
    get_code_outside_the_patch,
    get_repository_index_freshness,
    list_repository_files,
    offered,
    read_repository_file,
    search_repository,
    search_repository_by_meaning,
)
from write_mcp_client import commit_to_new_branch, open_pull_request

from agent_codefix.as_it_ran import the_files_as_they_ran, the_uses_as_they_ran
from agent_codefix.budget import FixSettings, a_budget_for
from agent_codefix.grouping import the_group_outside
from agent_codefix.opening import (
    the_opening_message,
    what_it_concluded,
    what_people_wrote_since,
    whether_it_holds_what_ran,
)
from agent_codefix.prompting import (
    ANSWER_TOOL_NAME,
    EXPLANATION_FIELD,
    NOT_AN_ANSWER,
    NOT_RUN_WHILE_ASKED,
    NOT_RUN_WHILE_SENT_BACK,
    REPORT_TOOL_NAME,
    STANDING_BRIEF,
    SUBMIT_TOOL_NAME,
    THE_QUESTION_A_SUBMISSION_IS_ASKED,
    AnswerToTheQuestion,
    SubmittedFix,
    brings_a_test,
    the_paths_whose_content_is_not_source,
)
from agent_codefix.retrieval import (
    BranchMembership,
    CodeOutsideReader,
    FileLister,
    FileReader,
    IndexNotice,
    MeaningSearcher,
    ReadTierTools,
    SourceSearcher,
)
from agent_codefix.tools import READ_TIER_HELD, the_answer_to, tools_for

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


class FixNotProposed(Exception):
    """A fix the model wrote that the repository would not take a proposal of.

    Raised carrying what the model said of the code, and the branch the fix
    was written to - `None` where the branch was refused too. GitHub answered
    500 to one pull request, and both went with the failure: the write-up had
    no account of the mechanism, and the fix sat on its branch with nothing
    saying it was there to open.

    The message is the failure's own, as it was before this carried anything:
    what stopped it is the one outcome somebody can act on.
    """

    def __init__(self, reason: str, *, reading: ProposedFix, branch: str | None) -> None:
        super().__init__(reason)
        self.reading = reading
        self.branch = branch


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
                 still_wanted: StillWanted = ...,
                 leads: Leads = ...,
                 done: Sequence[WhatArgusDid] = ...,
                 deployed: str | None = ...) -> ProposedFix: ...


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

# What a turn that asked for nothing is answered with, as the investigator's
# loop answers one. Some answer has to go back, because the API refuses an
# empty reply; and the empty one this replaced ended a live walk on a 400
# rather than on anything the model concluded.
_A_TURN_THAT_ASKED_FOR_NOTHING: Final = (
    "That turn asked for nothing. Read what you need, submit the fix with "
    f"{SUBMIT_TOOL_NAME}, or say there is nothing to change with "
    f"{REPORT_TOOL_NAME}."
)


# What a submission speaking of several pieces of code outside its patch at once
# is told, around the paragraph that does it and what that code does.
_SPOKEN_OF_TOGETHER: Final = (
    "That submission was not opened. A paragraph of its explanation speaks of "
    "several pieces of code outside your patch at once:"
)
_SAY_ONLY_YOUR_OWN: Final = (
    "Submit again with every line of code as it was, and the explanation and the "
    "comments in your files saying what the files your patch changes do - nothing "
    "of what code outside them does or does not do, beyond what the "
    "investigation's evidence names."
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
        # The repository tools this deployment's way of finding source holds,
        # as the read tier declares them.
        read_tier_tools=partial(offered, READ_TIER_HELD[settings.code_search], client=read),
        search=partial(search_repository, client=read),
        search_by_meaning=partial(search_repository_by_meaning, client=read),
        index_notice=partial(get_repository_index_freshness, client=read),
        list_files=partial(list_repository_files, client=read),
        contains=partial(branch_contains_revision, client=read),
        read_file=partial(read_repository_file, client=read),
        code_outside=partial(get_code_outside_the_patch, client=read),
        write_branch=partial(commit_to_new_branch, client=write),
        open_pull_request=partial(open_pull_request, client=write),
        recorder=recorder
    )


def propose_fix(hypothesis: Hypothesis | None,
                incident_id: str,
                *,
                settings: FixSettings,
                read_tier_tools: ReadTierTools,
                search: SourceSearcher,
                search_by_meaning: MeaningSearcher,
                index_notice: IndexNotice,
                list_files: FileLister,
                contains: BranchMembership,
                read_file: FileReader,
                code_outside: CodeOutsideReader,
                write_branch: BranchWriter,
                open_pull_request: PullRequestOpener,
                converse: Conversation | None = None,
                recorder: Recorder = records_nothing,
                conversations: Conversations = a_conversation_recorded_for,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                done: Sequence[WhatArgusDid] = (),
                deployed: str | None = None
                ) -> ProposedFix:
    """Proposes a fix for `hypothesis` as a draft pull request, or nothing -
    with what the model said of the code either way.

    No pull request means the model answered and had nothing to change - "the
    fault is not in the code", which is a real conclusion and the one a human
    acts on. None is opened for it: an empty proposal sends somebody to read a
    diff with nothing in it. Why there was nothing comes back all the same,
    since it is as much a finding about the code as a fix would be.

    No pull request with `needs_code_outside` is a fix the model wrote and
    said helps nobody until code outside the repository changes too. Nothing is
    written for it either: merged alone it spares no one, and what comes back
    is what would have to change there.

    Raises `FixNotAnswered` when the model never submitted within its budget,
    which is a different thing entirely and used to arrive looking identical.

    Raises whatever the repository raised. A push that was refused and a fix
    that was not found reach the same human, and only one of them is something
    somebody can go and fix - so the failure is not flattened into no proposal.

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

    `leads` is what people have told the incident in its thread, each with the
    standing the Investigator gave it or none. Asked before the conversation,
    for the opening, and again after every turn: a lead written since rides on
    the next result, and each is shown once.

    `done` is what Argus did about the incident, each action with its verdict
    and whether its change still stands. Said beside the leads in the opening,
    as the later word on what they were weighed as, and nowhere without one.

    `deployed` is the revision running when the alert fired, where one is
    known. `contains` is asked once whether the branch read has it: the
    opening says so only where it does not, and the answer comes back on
    whatever is proposed, for the write-up.

    `read_tier_tools` is the repository tools the model is offered, as the read
    tier declares them - asked once, before the conversation starts.
    """
    holds_what_ran = whether_it_holds_what_ran(settings, deployed, contains)
    submitted, uses_outside = _what_the_model_submitted(
        hypothesis,
        settings=settings,
        read_tier_tools=read_tier_tools,
        search=search,
        search_by_meaning=search_by_meaning,
        index_notice=index_notice,
        list_files=list_files,
        holds_what_ran=holds_what_ran,
        deployed=deployed,
        read_file=read_file,
        code_outside=code_outside,
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
        still_wanted=still_wanted,
        leads=leads,
        done=done
    )

    # Read once the model has answered, and only read: no request it is sent
    # changes, and the write-up can show what ran.
    as_it_ran = the_files_as_they_ran(submitted.explanation,
                                      branch=settings.github_base_branch,
                                      deployed=deployed,
                                      list_files=list_files,
                                      read_file=read_file)
    uses_outside = the_uses_as_they_ran(uses_outside,
                                        branch=settings.github_base_branch,
                                        deployed=deployed,
                                        read_file=read_file)

    if isinstance(submitted, AnswerToTheQuestion):
        # Written and not kept: merged alone it spares nobody. What comes
        # back is what would have to change outside, for whoever takes it
        # there.
        logger.info("fix not kept, it needs code outside the repository")
        return ProposedFix(pull_request=None,
                           explanation=submitted.explanation,
                           needs_code_outside=True,
                           holds_what_ran=holds_what_ran,
                           branch_read=settings.github_base_branch,
                           as_it_ran=as_it_ran,
                           uses_outside=uses_outside)

    patch = submitted.patch()

    if not patch:
        return ProposedFix(pull_request=None, explanation=submitted.explanation,
                           holds_what_ran=holds_what_ran,
                           branch_read=settings.github_base_branch,
                           as_it_ran=as_it_ran)

    # The branch and the pull request are changes to the world, and the turn
    # that produced this patch may have been answered after somebody said stop.
    if not still_wanted():
        logger.info("fix not proposed, incident no longer wanted")
        raise FixStopped("the incident is no longer wanted; the fix was not proposed")

    branch = _a_branch_for(incident_id)
    title = submitted.summary or f"fix for incident {incident_id}"
    reading = ProposedFix(pull_request=None,
                          explanation=submitted.explanation,
                          holds_what_ran=holds_what_ran,
                          branch_read=settings.github_base_branch,
                          as_it_ran=as_it_ran,
                          uses_outside=uses_outside)
    written: str | None = None

    try:
        write_branch(
            branch=branch,
            base_branch=settings.github_base_branch,
            files=patch,
            message=title
        )
        written = branch

        opened = open_pull_request(
            head_branch=branch,
            base_branch=settings.github_base_branch,
            title=title,
            body=_the_case_for(submitted, hypothesis, incident_id, uses_outside)
        )
    except Exception as error:
        # A lost run is another claim's walk, and nothing is said of it here.
        if was_lost(error):
            raise

        raise FixNotProposed(str(error) or type(error).__name__,
                             reading=reading, branch=written) from error

    return reading.model_copy(update={"pull_request": opened})


def _what_the_model_submitted(hypothesis: Hypothesis | None,
                              *,
                              settings: FixSettings,
                              read_tier_tools: ReadTierTools,
                              search: SourceSearcher,
                              search_by_meaning: MeaningSearcher,
                              index_notice: IndexNotice,
                              list_files: FileLister,
                              holds_what_ran: bool | None,
                              deployed: str | None,
                              read_file: FileReader,
                              code_outside: CodeOutsideReader,
                              converse: Conversation,
                              still_wanted: StillWanted,
                              leads: Leads,
                              done: Sequence[WhatArgusDid]
                              ) -> tuple[SubmittedFix | AnswerToTheQuestion, list[CodeUse]]:
    """The conversation, until the model submits and answers for its patch, or
    runs out of budget - with how the code outside that patch uses what it
    changes.

    A submission whose explanation speaks of several pieces of code outside
    its patch at once is sent back before it is asked anything, with what those
    pieces do as the code says it. Every slip of that kind was a sentence about
    a group: each piece said right alone, and the sentence about all of them
    counting among them the one that does something else.

    Every turn that is not a submission is answered and sent back, including the
    ones that failed: a model guessing at a path is doing its job badly for one
    turn, not failing, and ending here would throw away every file it had read
    correctly up to then.

    A submission is not the end. It is asked whether it helps this incident's
    users only once code outside the repository changes too, and the answer
    decides: no, and the submission comes back to be opened; yes, and the answer
    comes back instead, to be held. A patch sent on the last call the budget
    allows gets one more for its answer, and one sent back there one more for
    its rewrite - each is part of the submission, not another read - and a
    report made once asked is a verdict like any other. Each stretch is given
    once: a model resubmitting in the room for its answer is not given another.

    Raises rather than returning nothing when the budget runs out. What
    stopped it is the whole of what a reader can act on, and only here is it
    known - a caller handed `None` would have to guess at which of three
    bounds bound, and the old one guessed "turns" because that was the only
    answer there was.
    """
    tools = tools_for(read_tier_tools())
    # Every lead the model has been shown, in the order it was shown them.
    shown = leads()
    transcript: list[Exchange] = [
        Ask(text=the_opening_message(
            hypothesis, settings, index_notice, list_files, shown, done,
            deployed=deployed, holds_what_ran=holds_what_ran
        ))
    ]
    spend = a_budget_for(settings)
    # The submission the question is open about, and how the code outside its
    # patch uses what it changes.
    asked: SubmittedFix | None = None
    asked_outside: list[CodeUse] = []
    # Whether a submission has been sent back for speaking of code outside its
    # patch as a group - which happens once.
    sent_back = False
    # Whether the last submission was sent back, for any reason, with nothing
    # submitted since.
    last_sent_back = False
    # Whether the budget is stretched past its bounds by one call, for the
    # rewrite of a submission sent back or for the answer to its question - and
    # whether the answer's has been given. Each is given once, and the
    # rewrite's never after the answer's: a rewrite then would be written and
    # never asked about.
    room_for_its_rewrite = False
    room_for_its_answer = False
    answer_room_given = False

    while not spend.bounds_reached() or room_for_its_rewrite or room_for_its_answer:
        room_for_its_rewrite = room_for_its_answer = False

        if not still_wanted():
            logger.info("fix stopped, incident no longer wanted")
            raise FixStopped("the incident is no longer wanted")

        try:
            turn = converse(transcript, tools)
        except ModelRefused as declined:
            # Final, and final for its own reason: the evidence would be
            # declined again, so the turns left are not worth spending.
            #
            # Without the refusal's own account, which is the adapter's - a stop
            # reason - and nothing the model wrote: a refusal comes with no
            # words, and that one reached the walk, Slack and the postmortem as
            # "(stop_reason=refusal)". Kept as the cause, for the log.
            raise FixDeclined("the model declined to write a fix") from declined
        except AnswerTruncated as cut_short:
            # A bound was too small, which is what `FixNotAnswered` already
            # means - but room rather than turns, and that difference is the
            # whole of what a reader can act on. Code-Fix asks for the
            # model's entire output ceiling, so an answer that still did not
            # fit is a fix too large to write as whole files, and neither a
            # wider budget nor another attempt changes that.
            #
            # Said without the truncation's own account, the adapter's stop
            # reason, for the reason a refusal is. Kept as the cause.
            logger.warning("answer truncated")

            raise FixNotAnswered(
                "the fix did not fit in the room the model had to write it"
            ) from cut_short

        spend.record(turn)
        transcript.append(turn)

        verdict = _the_verdict_in(turn)

        if verdict is not None:
            return verdict, []

        submitted = _the_submission_in(turn)
        answered = _the_answer_in(turn)

        results: list[ToolResult]

        if submitted is not None and submitted.files and not (
            the_paths_whose_content_is_not_source(submitted.files)
        ) and brings_a_test(submitted.files):
            outside = _the_code_outside(submitted, settings, code_outside, list_files)
            group = (the_group_outside(submitted.explanation or "", submitted.patch(),
                                       outside.listing, outside.read.defined)
                     if outside is not None and not sent_back else None)

            if outside is not None and group is not None:
                # Sent back before it is asked anything, with what the code
                # outside the patch does said by the code itself - once, as an
                # empty patch is, before it is believed: a rewrite that still
                # trips the check is asked its question rather than sent back
                # until the budget runs out and the fix with it.
                logger.info("explanation speaks of code outside the patch as a group")
                sent_back = last_sent_back = True
                room_for_its_rewrite = bool(spend.bounds_reached()) and not answer_room_given
                results = _sent_back(turn, _spoken_of_together(turn, group, outside.read))
            else:
                # Asked about rather than returned. A second submission
                # replaces the first, and is asked about in turn.
                last_sent_back = False
                asked = submitted
                asked_outside = outside.read.uses if outside is not None else []
                room_for_its_answer = bool(spend.bounds_reached()) and not answer_room_given
                answer_room_given = answer_room_given or room_for_its_answer
                results = [_the_question_or_not_run(call) for call in turn.tool_calls]
        elif answered is not None and asked is not None and submitted is None:
            # The answer about the patch in hand. Yes holds it back; no lets it
            # be opened.
            return (answered if answered.answer else asked), asked_outside
        elif submitted is not None and submitted.files and (
            not_source := the_paths_whose_content_is_not_source(submitted.files)
        ):
            # A patch that cannot be read as the language it is written in,
            # which is a submission to recover from rather than one to
            # propose. Sent back for the reason an empty one is: the model has
            # decided what to write and is one turn from writing it properly.
            logger.warning("patch is not source", extra={"paths": not_source})
            last_sent_back = True
            results = _sent_back(turn, _that_is_not_source(turn, not_source))
        elif submitted is not None and submitted.files:
            # A patch that brings no test, which proves nothing however sound
            # it is. Sent back every time, as one that is not source is: a
            # model that keeps sending it runs out, and no pull request is
            # opened on a fix its postmortem would send a reader to test.
            logger.warning("patch brings no test")
            last_sent_back = True
            results = _sent_back(turn, _no_test_was_brought(turn))
        elif submitted is not None:
            # A patch with nothing in it, which the submission's own schema
            # refuses - so this is one whose every entry was dropped as
            # unreadable rather than one the model sent empty on purpose. It
            # meant to attach a patch, and sent back it gets the turn to.
            #
            # Never read as a verdict, however often it arrives. The verdict is
            # a tool of its own, so a model that wanted it would have called
            # it, and reporting this as "there is nothing to change" would put
            # a conclusion in its mouth - which is what happened, on a live run
            # that submitted one naming the file and the bound it wanted. A
            # model that keeps sending this runs out instead, and running out
            # is what a reader is told.
            logger.warning("patch was empty")
            last_sent_back = True
            results = _sent_back(turn, _no_patch_was_attached(turn))
        else:
            results = [
                _an_answer_that_counts_for_nothing(call, asked)
                if call.name == ANSWER_TOOL_NAME
                else the_answer_to(
                    call, settings, search, search_by_meaning, list_files, read_file
                )
                for call in turn.tool_calls
            ]

        if last_sent_back:
            # A submission sent back withdraws the one asked before it, as a
            # second submission replaces the first: what is awaited now is the
            # submission sent again, and no question is open.
            asked, asked_outside = None, []

        # Asked after every turn, as `still_wanted` is before one: a person
        # writes while the model reads, and what they wrote rides on this
        # reply rather than waiting for a fix there may never be another of.
        written_since = not_yet_shown(leads(), shown)
        shown = [*shown, *written_since]

        # No warning to submit while a question is open: what is wanted then
        # is the answer, and "submit the fix now" would ask for the patch
        # already sent.
        transcript.append(_what_it_is_told_next(
            results,
            one_call_left=spend.is_on_its_last_call() and asked is None,
            news=what_people_wrote_since(written_since),
            question_open=asked is not None
        ))

    if asked is not None:
        raise FixNotAnswered(
            "the agent submitted a fix and never said whether it needs code "
            "outside the repository"
        )

    # Which bound ended it, named for the human who has to act on it. It was
    # "turns" while the call count was the only way to run out; there are
    # three ways now, they are widened in three different places, and
    # widening the one that was never the problem is a wasted afternoon.
    bounds = ", ".join(bound.value for bound in spend.bounds_reached())

    # A submission was made and sent back, which is not the same as none made:
    # told none was, a reader looks at an agent that never got as far as a fix.
    if last_sent_back:
        raise FixNotAnswered(
            f"the agent's last submission was sent back, and it ran out of {bounds} "
            "before submitting again"
        )

    raise FixNotAnswered(
        f"the agent read until it ran out of {bounds} without submitting a fix"
    )


def _what_it_is_told_next(results: list[ToolResult],
                          one_call_left: bool,
                          news: str = "",
                          question_open: bool = False) -> Exchange:
    """What comes back from one turn's requests, and the warning if it is due.

    The warning rides on the last result rather than travelling as a message
    of its own, because it is not a separate thing to weigh - it is the
    condition under which everything else in this reply should be read. The
    investigator's loop says it the same way, for the same reason. `news` -
    what people wrote in the thread since the last turn - rides the same way,
    for the reason it arrives at all: between two turns, never inside one.

    A turn that asked for nothing has no result to ride on, so it is answered
    in words of its own and both ride on those instead. Dropped there, the news
    would be counted as shown and never sent, and the thread would not be asked
    about it again.

    Without it a model spends its last call asking for one more file and
    everything it read is thrown away as no fix proposed - which reads as a
    verdict on code nobody finished looking at. That costs more here than
    anywhere else: the turns being discarded are whole files.

    With `question_open`, a turn that asked for nothing is asked the question
    again: what is wanted then is the answer, not another read or patch.
    """
    postscript = news + (_ONE_CALL_LEFT if one_call_left else "")

    if not results:
        reply = (THE_QUESTION_A_SUBMISSION_IS_ASKED if question_open
                 else _A_TURN_THAT_ASKED_FOR_NOTHING)

        return Ask(text=reply + postscript)

    if not postscript:
        return ToolResults(results=results)

    last = results[-1]

    return ToolResults(results=[
        *results[:-1],
        ToolResult(
            call_id=last.call_id,
            content=last.content + postscript,
            failed=last.failed
        )
    ])


def _sent_back(turn: Turn, submission: ToolResult) -> list[ToolResult]:
    """What each call in a turn whose submission was sent back is told.

    One result for every call, as a turn asked its question has: the API
    refuses a request whose calls are not all answered. The submission gets
    why it was sent back; anything sent with it waits for the submission sent
    again - including an answer, which no question is open for.
    """
    return [
        submission if call.id == submission.call_id
        else ToolResult(call_id=call.id, content=NOT_AN_ANSWER, failed=True)
        if call.name == ANSWER_TOOL_NAME
        else ToolResult(call_id=call.id, content=NOT_RUN_WHILE_SENT_BACK)
        for call in turn.tool_calls
    ]


def _no_patch_was_attached(turn: Turn) -> ToolResult:
    """The submission sent back, addressed to the call that made it.

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
    """The submission sent back because a file's content is not the language it is.

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


def _no_test_was_brought(turn: Turn) -> ToolResult:
    """The submission sent back because none of its files is a test.

    A failure rather than a remark, as a patch that is not source is: something
    to recover from, not evidence about the incident.

    It says how a fix to a file no code reads is tested, because that is the
    reason the recorded walk gave for bringing none - and the fix recorded
    before it, to the same file, brought a test that read the file. The other
    ending is named, as the empty patch's is: told only that a test is missing,
    a model that had found nothing to change would invent a change to test.
    """
    submitting = next(
        (call for call in turn.tool_calls if call.name == SUBMIT_TOOL_NAME), None
    )

    return ToolResult(
        call_id=submitting.id if submitting is not None else "",
        content=(
            "That submission brought no test, so it was not proposed. Submit again "
            "with the test that exposes the fault beside the fix, in a file named "
            "test_*.py: it fails against the code as it stands and passes with your "
            "change. A fix to a file no code reads, such as a values file, is tested "
            "by a test that reads that file and checks what the fix sets in it. If "
            "what you meant is that the code needs no change, that is a complete "
            f"answer and {REPORT_TOOL_NAME} is how to give it."
        ),
        failed=True
    )


class _OutsideRead(NamedTuple):
    """How the code outside a patch uses what it changes, and every file the
    repository holds - what a sentence about that code is recognised by."""

    read: CodeOutsideThePatch
    listing: list[str]


def _the_code_outside(submitted: SubmittedFix,
                      settings: FixSettings,
                      code_outside: CodeOutsideReader,
                      list_files: FileLister) -> _OutsideRead | None:
    """How the code outside a submission's patch uses what it changes - `None`
    where the read tier could not say.

    Checked rather than blocked on: a source that could not be fetched is no
    reason to hold back a fix, and the warning is the one place a skipped check
    is said to have been skipped."""
    try:
        return _OutsideRead(
            read=code_outside(submitted.patch(), settings.github_base_branch),
            listing=list_files(settings.github_base_branch)
        )
    except Exception:
        logger.warning("code outside the patch could not be read", exc_info=True)

        return None


def _spoken_of_together(turn: Turn, paragraph: str, outside: CodeOutsideThePatch) -> ToolResult:
    """The submission sent back, quoting the paragraph that speaks of several
    pieces of code outside its patch at once, with what that code does said by
    the code itself.

    A failure rather than a remark, as a patch that is not source is: something
    to recover from. Every file stays as it was - nothing is wrong with the
    patch - and what is asked again is the words: the explanation, and the
    comments in the files, where the same sentence was found living too.
    """
    submitting = next(
        (call for call in turn.tool_calls if call.name == SUBMIT_TOOL_NAME), None
    )
    names = list(dict.fromkeys(use.name for use in outside.uses))
    rows = "\n".join(_a_row(use) for use in outside.uses)
    what_it_does = (
        f"How the code outside your patch uses {_listed(names)}, which your patch "
        f"changes, is published beside the explanation, said by Argus from the code "
        f"itself:\n{rows}\n\nSo the explanation does not say it. "
        if outside.uses else ""
    )

    return ToolResult(
        call_id=submitting.id if submitting is not None else "",
        content=(
            f"{_SPOKEN_OF_TOGETHER}\n\n{paragraph}\n\n{what_it_does}{_SAY_ONLY_YOUR_OWN}"
        ),
        failed=True
    )


def _a_row(use: CodeUse) -> str:
    """One line outside a patch, where it is and what it does - said the same
    way to the model and to whoever reads the pull request."""
    function = f", in {use.function}" if use.function else ""

    return f"  {use.path}:{use.line}{function}: {use.does}"


def _listed(names: list[str]) -> str:
    """Names as a sentence lists them."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


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


def _the_answer_in(turn: Turn) -> AnswerToTheQuestion | None:
    """The answer to the question a submission is asked, if this turn gave one
    that could be read."""
    answering = next(
        (call for call in turn.tool_calls if call.name == ANSWER_TOOL_NAME), None
    )

    if answering is None:
        return None

    try:
        return AnswerToTheQuestion.model_validate(answering.arguments)
    except (ValidationError, TypeError):
        return None


def _the_question_or_not_run(call: ToolCall) -> ToolResult:
    """What each call in a turn that submitted a patch is told.

    The submission is asked its question. Anything else sent with it waits for
    the answer - including an answer, which was given before anything was
    asked and so is not the answer to it.
    """
    if call.name == SUBMIT_TOOL_NAME:
        return ToolResult(call_id=call.id, content=THE_QUESTION_A_SUBMISSION_IS_ASKED)

    if call.name == ANSWER_TOOL_NAME:
        return ToolResult(call_id=call.id, content=NOT_AN_ANSWER, failed=True)

    return ToolResult(call_id=call.id, content=NOT_RUN_WHILE_ASKED)


def _an_answer_that_counts_for_nothing(call: ToolCall,
                                       asked: SubmittedFix | None) -> ToolResult:
    """An answer with no question open, or one that could not be read.

    With no patch asked about, it is told so. With one, the answer did not
    parse, so the question is put again.
    """
    if asked is None:
        return ToolResult(call_id=call.id, content=NOT_AN_ANSWER, failed=True)

    return ToolResult(
        call_id=call.id, content=THE_QUESTION_A_SUBMISSION_IS_ASKED, failed=True
    )


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
                  incident_id: str,
                  uses_outside: list[CodeUse]) -> str:
    """What a person reads before deciding whether to merge.

    The model's explanation, and the incident it came from, said plainly. The
    provenance is not decoration: whoever opens this needs to know an agent
    proposed it and which incident it answers, so the change can be judged
    against something rather than taken on trust.

    Beside the explanation, how the code the patch does not touch uses what it
    changes, said by the code itself - what a model got wrong when it said it,
    and what Code-Fix is told is published here.
    """
    outside = [
        "",
        "How the code outside this patch uses what it changes, read by Argus off "
        "the code itself:",
        *(_a_row(use) for use in uses_outside)
    ] if uses_outside else []

    return "\n".join([
        submitted.explanation or "No explanation was given.",
        *outside,
        "",
        "---",
        "",
        f"Proposed by Argus for incident `{incident_id}`.",
        f"The investigation concluded: {what_it_concluded(hypothesis)}",
        "",
        "This is a draft. Argus cannot merge it - review it as you would any "
        "change from somebody who has not run the service."
    ])
