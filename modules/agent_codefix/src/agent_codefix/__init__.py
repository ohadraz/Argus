"""The Code-Fix agent: a permanent fix for the cause, where there is one.

The last thing tried, and the only one that outlives the incident - a reverted
flag is a change somebody has to come back to, and a fix is the reason they do
not (spec §7.4).

It reads the service's source over the read tier, writes a patch to a branch of
its own over the write tier, and opens a draft pull request. That is as far as
it goes, by construction rather than by restraint: merging is a deploy, and the
tool for it exists nowhere on either server (§13).

`SubmittedFix` is a door because one thing outside has to answer the question
"what would be written to the branch?" - the grader that runs each recorded
patch against the Target Service's own tests. It read the recordings itself and
kept its own copy of this leniency, which made it a grade of what the model said
rather than of what a human would review, and the two part company the moment
anything here repairs a malformed answer.
"""

from __future__ import annotations

from agent_codefix.budget import FixSettings
from agent_codefix.prompting import SubmittedFix
from agent_codefix.proposing import (
    FixDeclined,
    FixNotAnswered,
    fixes_over,
    propose_fix,
)

__all__ = [
    "FixDeclined",
    "FixNotAnswered",
    "FixSettings",
    "SubmittedFix",
    "fixes_over",
    "propose_fix"
]
