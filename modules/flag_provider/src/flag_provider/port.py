"""What Argus asks of whatever serves and records its feature flags.

Split where the MCP servers are split (spec §12.1): one port that can only read
which flags are on, and one that can also change a flag, read what the provider
holds for one, and read the provider's history of changes - the last two because
the provider serves them to the credential that can change a flag and to no
other. The read server is handed
the first, so a change typed there does not type-check, and the line the two
servers draw holds in the code they run as well as in the processes they run in.

Every operation is named for what Argus wants rather than for the route that
answers it, and every answer is Argus's own value. Nothing here is a URL, a token
or an event name; those are an adapter's, and an adapter is named for its vendor.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from core.models import FlagChange, FlagState, FlagUndo


class FlagProviderReads(Protocol):
    """Which flags are on, and nothing that changes one.

    A failure raises `FlagProviderUnavailable`, never an empty answer: an
    outage read as "nothing is enabled" is an environment with no flag to
    revert.
    """

    def enabled(self) -> list[str]:
        """The flags evaluating true now, in the order the provider lists them."""
        ...


class FlagAudit(Protocol):
    """What the provider recorded as having changed, and whose change it was."""

    def changes_since(self, since: datetime, /) -> list[FlagChange]:
        """The flag toggles recorded at or after `since`, oldest first.

        A history that cannot be read raises `FlagProviderUnavailable`: "nothing
        changed" is a conclusion Mitigation escalates on.
        """
        ...

    def argus_changed_since(self, flag: str, since: datetime, /) -> bool | None:
        """Whether Argus's own change to `flag` was recorded at or after `since`.

        `None` where nobody can say - the history could not be read, or the
        provider cannot tell Argus's changes from anybody else's.
        """
        ...

    def others_changed_since(self, flag: str, since: datetime, /) -> bool | None:
        """Whether anybody but Argus changed `flag` at or after `since`.

        `None` where nobody can say, for the reasons the question above has.
        """
        ...


class FlagProviderWrites(FlagProviderReads, FlagAudit, Protocol):
    """What changing a flag can ask, beside everything reading and the audit can."""

    def state_of(self, flag: str, /) -> FlagState:
        """Whether `flag` is on, as the provider itself holds it, dated by the
        provider's own clock.

        What a change is planned over, and not the evaluation: evaluation is a
        cache, and says neither what the provider holds nor when. Dated by the
        provider because the history the change is later made over is stamped by
        it, and two clocks compared hide whatever they disagree by.

        A flag that cannot be read, or a read the provider did not date, raises
        `FlagProviderUnavailable`: a flag read as off because nothing was read is
        a change planned from a state the flag was never in.
        """
        ...

    def set(self, flag: str, enabled: bool, /) -> FlagUndo:
        """Sets `flag` on or off, returning only once evaluation agrees.

        Answers with what restores the state it replaced. A failure raises
        `FlagWriteFailed`, saying what it left behind.
        """
        ...
