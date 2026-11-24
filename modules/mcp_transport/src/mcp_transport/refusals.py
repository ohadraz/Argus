"""A write tool's refusal, as the value both ends of the call read.

A tool that refuses answers with an error result, and what the caller does
next turns on which refusal it was and what the refused call left behind. That
travelled once as tokens at the front of the words and a JSON payload at the
end of them, read back by finding substrings; it travels now as structured
content beside the words (`REFUSAL_KEY`), written by the server's own catch
(`TracedMCPServer`) and read by the client's (`McpClient`).

Named apart from `core.models.Refusal`, which is the gate's: one word, one
meaning.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from core.models import UndoDescriptor
from pydantic import BaseModel, ConfigDict, model_validator

# Where in an error result's structured content the refusal is said. Prefixed
# with the project's name, as MCP asks of a key that is not its own.
REFUSAL_KEY: Final = "argus/refusal"


class ToolRefusalKind(StrEnum):
    """Which refusal a write tool gave, and so what its caller does next."""

    # The claim the call was made for is one the run has moved past: the walk
    # is somebody else's now, and the caller stops.
    RUN_LOST = "run-lost"
    # The action is spent - a deployment already as large as Argus may make
    # it - and nothing was touched: the caller tries something else.
    EXHAUSTED = "exhausted"
    # The platform the action acts through did not answer: every action
    # through it is unavailable, and the caller passes over them.
    PLATFORM_UNREACHABLE = "platform-unreachable"
    # Somebody else changed what the action would change since it was planned:
    # the caller hands the incident to a person.
    CHANGED_SINCE = "changed-since"
    # An ordinary refusal that says the whole of what it left behind.
    LEFT_BEHIND_KNOWN = "left-behind-known"
    # A refusal that cannot vouch for the estate - a change request whose answer
    # was lost - carrying what it knows it left and no more.
    UNACCOUNTED = "unaccounted"


# The refusals raised before anything was touched, which can leave nothing.
_CHANGED_NOTHING: Final = frozenset({ToolRefusalKind.RUN_LOST, ToolRefusalKind.EXHAUSTED})


class ToolRefusal(BaseModel):
    """A write tool's refusal: which it was, in whose words, what the refused
    call left behind, and - for the two kinds that carry them - the platform
    that did not answer and whether the action's own change had landed.

    `words` is what a person reads, in the timeline, the postmortem and a
    Slack line; the rest is what the caller acts on."""

    model_config = ConfigDict(frozen=True)

    kind: ToolRefusalKind
    said: str
    left_behind: UndoDescriptor | None = None
    platform: str | None = None
    performed: bool = False

    @model_validator(mode="after")
    def _says_only_what_its_kind_can(self) -> ToolRefusal:
        """A platform on, and only on, a platform that did not answer; performed only on
        a change somebody overtook; and nothing left behind by a refusal raised
        before anything was touched."""
        unreachable = self.kind is ToolRefusalKind.PLATFORM_UNREACHABLE
        if unreachable and self.platform is None:
            raise ValueError("a refusal saying a platform did not answer names the platform, "
                             "and this one names none")
        if not unreachable and self.platform is not None:
            raise ValueError(f"a {self.kind} refusal names a platform only where the platform "
                             f"did not answer, and this one names {self.platform!r}")
        if self.performed and self.kind is not ToolRefusalKind.CHANGED_SINCE:
            raise ValueError(f"only a change somebody overtook says it was performed, not a "
                             f"{self.kind} refusal")
        if self.left_behind is not None and self.kind in _CHANGED_NOTHING:
            raise ValueError(f"a {self.kind} refusal is raised before anything is touched, and "
                             f"leaves nothing behind")
        return self

    @property
    def left_behind_known(self) -> bool:
        """Whether what it left behind is all of it: so for every refusal but one
        that cannot vouch for the estate."""
        return self.kind is not ToolRefusalKind.UNACCOUNTED

    @property
    def words(self) -> str:
        """The refusal as a person reads it: its words, after the platform that
        did not answer where one did not."""
        said = f"{self.platform} {self.said}" if self.platform is not None else self.said

        return said.strip()


class ToolRefused(Exception):
    """What a write tool raises to refuse: the refusal, carried whole to the
    server's catch, which answers the call with it.

    Its words are its message, so a log line and a span say what a person
    reads."""

    def __init__(self, refusal: ToolRefusal) -> None:
        super().__init__(refusal.words)
        self.refusal = refusal
