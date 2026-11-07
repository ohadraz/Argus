from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from argus_core.models.pull_request import OpenedPullRequest


class FixOutcome(StrEnum):
    """How Code-Fix's turn ended (spec §7.4).

    Five answers rather than a pull request and its absence. Four of these
    carry no proposal and they mean different things: `not-warranted` is a
    verdict on the code - Argus read it and there was nothing there to change -
    where `not-possible` is a repository that refused, which somebody can go
    and repair, and `not-answered` is Argus running out of turns mid-read,
    which is a budget that was too small rather than anything about the
    service. A reader told only that there is no pull request cannot tell those
    apart, and one live incident spent twelve turns exploring and was recorded
    as having found no fix - a statement about the budget dressed as a verdict.

    `declined` is the model itself saying no, and it is none of the other
    three. Nothing is broken, so there is nothing to go and repair; the code
    was never judged, so no verdict was reached; and more turns cannot help,
    because the same question over the same code is declined again. It shared
    `not-possible`'s sentence until somebody noticed that "could not propose a
    fix" sends a reader hunting for an outage that never happened.

    A value rather than a sentence, for the reason `Verdict` is one: the page,
    the relay and the postmortem all have to recognise which of the three
    happened, and three readers matching on prose are three readers who will
    eventually match on different prose.

    `not-opened` is a fix the model wrote and said helps nobody until code
    outside the repository changes too. It is neither a proposal - merged
    alone it spares no one - nor `not-warranted`, which would close the
    question the fix answers.

    This is not a status. A mitigated incident is mitigated whichever of these
    it carries (§10) - what Code-Fix found decides what the incident carries,
    not what state it is in.
    """

    PROPOSED = "proposed"
    NOT_WARRANTED = "not-warranted"
    NOT_POSSIBLE = "not-possible"
    NOT_ANSWERED = "not-answered"
    DECLINED = "declined"
    NOT_OPENED = "not-opened"


class FileAsItRan(BaseModel):
    """One file Code-Fix's reading names, read again at the revision running
    when the alert fired.

    `as_read` where it is the file the branch read holds, byte for byte - the
    reading then stands for what ran, and `content` is `None`. Otherwise the
    file as it ran, cut where it runs long and saying so: the one thing that
    shows what ran when the branch read is other text, or has no such file.
    """

    path: str
    revision: str
    as_read: bool
    content: str | None


class CodeUse(BaseModel):
    """One line outside a patch that uses something the patch changes, and what
    the line does with it - said by the syntax tree, not by a model.

    `name` is what it uses: a field the patch's changed code now writes, or a
    function whose definition the patch changes. `function` is the function the
    line sits in, `None` at a module's top level.

    The line is read on the branch the patch is against. `revision` is the one
    running when the alert fired that its file was compared at, `None` where
    none is known to have run; `as_read` is whether the file there is the file
    the branch holds, byte for byte - as `FileAsItRan.as_read` says of a file
    Code-Fix's reading names. Only where it is does the line say anything of
    what ran.

    `set_against_a_call` is whether the line compares what it uses with, or
    subtracts it from or by, a call of a function of its own file whose whole
    body is one `return` - what `does` quotes that function returning. A line
    that does reads it to check it, not as the figure it uses; one dividing or
    multiplying by such a call is a reader like any other.
    """

    name: str
    path: str
    line: int
    function: str | None
    does: str
    revision: str | None = None
    as_read: bool = False
    set_against_a_call: bool = False


class CodeOutsideThePatch(BaseModel):
    """What the code a patch does not change does with what it changes, and
    every name that code defines.

    The facts a model gets wrong when it speaks of code it did not change - a
    reader that checks a stored figure counted among the ones that trust it -
    so the tree says them instead. `defined` maps each function and class
    defined outside the patch's files to every file defining it: how a
    sentence about code outside the patch is recognised.
    """

    uses: list[CodeUse]
    defined: dict[str, list[str]]


class ProposedFix(BaseModel):
    """What Code-Fix answered: the draft pull request it opened, `None` where it
    judged there was nothing in the code to change - and what it said of the
    code either way.

    The explanation travels beside the proposal rather than only inside the
    pull request's body, because the write-up reads it too: it is the one
    account of the mechanism anybody read off the source, and "the fault is
    not in the code, because..." is a finding as much as a fix is. A static
    reading - nothing ran it - and `None` where the model gave none.

    `needs_code_outside` is a fix the model wrote and Argus did not keep,
    because the model said it helps nobody until code outside the repository
    changes too. Neither a proposal nor "nothing to change": the explanation is
    then what would have to change there, in the model's words.

    `holds_what_ran` is whether the branch read contains the revision running
    when the alert fired - `None` where that was not established, because no
    revision was known or the branch could not be asked. The write-up reads it:
    a fix written against a branch that does not hold what ran changes nothing
    that runs once merged, not until a deploy carries it. `branch_read` is that
    branch, by name - the sentence a reader acts on names it.
    """

    pull_request: OpenedPullRequest | None
    explanation: str | None
    needs_code_outside: bool = False
    holds_what_ran: bool | None = None
    branch_read: str | None = None
    # Each file the explanation names, read again at the revision that ran -
    # empty where no revision is known or nothing was said.
    as_it_ran: list[FileAsItRan] = []
    # How the code the patch does not touch uses what it changes, said by the
    # syntax tree - empty where nothing does, or the source could not be read.
    uses_outside: list[CodeUse] = []
