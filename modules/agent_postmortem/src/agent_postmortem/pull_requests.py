"""The pull request an answer names, held to the one the record holds.

The record holds at most one pull request - the draft Code-Fix opened - and the
brief names it, by its name and by its address. So any pull request an answer
names is that one, and is written by its name: a number of its own is one the
answer was handed by another run, as a replay's recording was by the run that
recorded it, and a document saying it names a pull request nobody can open.

Where the record holds none, a pull request the answer names is left as
written: nothing here can say which one it meant.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from argus_core.models import OpenedPullRequest

# For the annotations alone, as in `revisions`: the answer's type is the
# prompt's.
if TYPE_CHECKING:
    from agent_postmortem.prompting import SubmittedPostmortem

# A pull request as prose names it: by Argus's name for it, in words, or by its
# address - each with its number, and the number whole.
_A_PULL_REQUEST: Final = re.compile(
    r"\bPR #\d+\b|\b[Pp]ull request #\d+\b|https?://[^\s()<>\"']+/pull/\d+\b")


def with_the_pull_request_named(answer: SubmittedPostmortem,
                                pull_request: OpenedPullRequest | None) -> SubmittedPostmortem:
    """The answer with every pull request it names written as the record's,
    by its name - and as it was where the record holds none."""
    if pull_request is None:
        return answer

    return answer.with_each_sentence(lambda prose: the_pull_request_named(prose, pull_request))


def the_pull_request_named(prose: str, pull_request: OpenedPullRequest | None) -> str:
    """`prose` with every pull request it names written as the record's, by
    its name - and as it was where the record holds none. Public for prose
    outside an answer: the executive overview is held to the same record."""
    if pull_request is None:
        return prose

    return _A_PULL_REQUEST.sub(pull_request.name, prose)
