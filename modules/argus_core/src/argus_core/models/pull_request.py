from __future__ import annotations

from pydantic import BaseModel


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
