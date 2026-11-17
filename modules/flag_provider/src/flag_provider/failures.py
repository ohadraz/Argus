"""How the flag provider fails to do what was asked, in two kinds.

Two because the two callers want different things of a failure. A read that
could not be answered must never become an empty answer - "the provider was
down" and "no flag is on", or "nothing changed", are opposite facts - so it
raises one name, and the caller decides what an outage means to it. A write
that failed has a second question to answer: what it left behind, which only
the adapter that saw the request go out can say.
"""

from __future__ import annotations

from core.models import FlagUndo


class FlagProviderError(Exception):
    """The provider did not do what was asked, for either reason below.

    Caught by name where the difference does not matter - a caller that only
    needs to know nothing it asked for happened.
    """


class FlagProviderUnavailable(FlagProviderError):
    """The provider could not be asked, or its answer could not be read.

    Deliberately not an empty list. "The provider was down" and "no flag is on"
    are opposite facts, and a reader that reports the first as the second hands
    Mitigation an environment that appears to have nothing to revert - so an
    outage would end an incident by making its cause invisible. The same holds
    of the history: "nothing changed" is a conclusion Mitigation escalates on.
    """


class FlagWriteFailed(FlagProviderError):
    """A flag did not reach the state asked for, and what that left behind.

    `known_not_applied` says the write is known not to have landed: it was never
    sent, or the provider read it and refused it. False where its answer was
    lost, which says nothing either way.

    `left_behind` is the undo of a write the provider *took* and nobody saw
    evaluating: the flag is flipped whatever evaluation says yet, and recorded
    nowhere else it is a flag no withdrawal would ever put back. `None` where
    the provider never took the write.
    """

    def __init__(self,
                 said: str,
                 *,
                 known_not_applied: bool = False,
                 left_behind: FlagUndo | None = None) -> None:
        super().__init__(said)
        self.known_not_applied = known_not_applied
        self.left_behind = left_behind
