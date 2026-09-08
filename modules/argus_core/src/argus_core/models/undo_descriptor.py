from __future__ import annotations

from datetime import datetime
from typing import Final

from pydantic import BaseModel

# The write tool a descriptor is undone by. Named once and imported, rather than
# spelled where each producer happens to build one: it is written into a JSONB
# column by one process and read out of it by another, and two spellings of the
# same tool would be two tools as far as either could tell.
SET_FEATURE_FLAG_TOOL: Final = "set_feature_flag"


class UndoDescriptor(BaseModel):
    """The record of one change, in the shape that puts it back (spec §7.3, §13).

    Here rather than in `agent_mitigation` for the reason `Action` is here: it
    crosses every boundary the change itself does. The write tier returns one,
    the Orchestrator's gate requires one before anything mutating is called, the
    `action` table stores it, and a withdrawal reads it back hours later to undo
    what the walk left behind.

    Modelled rather than carried as the tool's raw JSON because of that
    distance. Read out of a `dict` by hand, a descriptor that never recorded its
    flag surfaces as a `KeyError` inside the undo - the last thing an incident
    does, and the one moment where nothing can be done about it. The fields it
    cannot work without are required here, where the descriptor is built and a
    caller still has somewhere to go.

    `was_enabled` is the state that existed *before* the change, which is what
    restores it - not the state the flag was set to. There is no default: the
    two directions are equally real, and a guess would clear a flag that was on
    before Argus touched it while calling itself a restore.

    `written_at` is the provider's own time for the write, and absent is a
    meaning rather than a gap. An action chosen but not yet taken has nothing to
    date, and a provider that accepted a change without saying when leaves the
    same hole. Both reach an undo that has an answer for them - it reports the
    state could not be established - which it can only give if the record admits
    the moment is missing.
    """

    flag: str
    was_enabled: bool
    tool: str = SET_FEATURE_FLAG_TOOL
    # The provider environment the change was made in. Absent on a descriptor
    # built before the write, which is proposing a change rather than reporting
    # one and has no environment of its own to name.
    environment: str | None = None
    written_at: datetime | None = None
