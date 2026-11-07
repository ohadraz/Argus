from __future__ import annotations

from typing import Final

from pydantic import BaseModel

# What is known of a pull request Argus opened once it is open: nothing. Here
# rather than with whoever says it, because the page and the brief the model
# writes from both say it, and two spellings of one fact read as two facts.
NOTHING_RECORDED_AFTER_IT_WAS_OPENED: Final = "The record holds nothing about it after that"


class OpenedPullRequest(BaseModel):
    """A code fix Argus has proposed and cannot apply (spec §7.4, §13).

    A contract rather than the write tier's own return type, because four
    parties name it: the server that opens one, the client the Code-Fix agent
    calls through, the agent that decides a fix is worth proposing, and
    everything downstream that has to tell a human where it went - the incident
    view, the Communicator's message, the postmortem's account of how the
    incident ended.

    What it carries is what a person needs to go and look, which is why `url` is
    here at all: a number identifies a pull request to the API that issued it
    and to nobody else. Argus's last act on a bug is to hand the work to
    somebody, so the address is the payload.

    Nothing here says whether it was merged, and nothing ever will. A pull
    request Argus opened is a draft by construction, merging it is outside its
    autonomy entirely (§13), and a field for the answer would imply a caller
    that could go and get it.
    """

    number: int
    url: str
    # The branch the fix sits on, kept because it outlives the proposal: a
    # superseded pull request can be closed and re-opened from the same work,
    # and a later incident touching the same fault wants to know a branch for it
    # already exists.
    branch: str
    # Whether the fix carries a test. A fix to configuration alone may come
    # without one (§7.4), and the postmortem's review must not then send its
    # reader to run the fix's tests. Set by Code-Fix, which sees the files; the
    # write tier that opens the pull request never does.
    brings_a_test: bool = True

    @property
    def name(self) -> str:
        """The pull request by Argus's own name for it, "PR #7" - GitHub's is
        "#7" - one name wherever Argus mentions it, so every mention a reader
        follows leads to the same place."""
        return f"PR #{self.number}"
