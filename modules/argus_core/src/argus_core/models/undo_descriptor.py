from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, Field, TypeAdapter

# The write tool a descriptor is undone by. Named once and imported, rather than
# spelled where each producer happens to build one: it is written into a JSONB
# column by one process and read out of it by another, and two spellings of the
# same tool would be two tools as far as either could tell.
SET_FEATURE_FLAG_TOOL: Final = "set_feature_flag"
ROLL_BACK_DEPLOYMENT_TOOL: Final = "roll_back_deployment"


class FlagUndo(BaseModel):
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

    # What kind of change this puts back, in Argus's own vocabulary. Not `tool`,
    # though one tool performs it today: the tool name is the write tier's MCP
    # wire word, and tagging stored descriptors by it would re-type every row
    # already written the day a tool is renamed - and would promise one tool per
    # kind of change for ever, in both directions.
    kind: Literal["feature-flag"] = "feature-flag"
    flag: str
    was_enabled: bool
    tool: str = SET_FEATURE_FLAG_TOOL
    # The provider environment the change was made in. Absent on a descriptor
    # built before the write, which is proposing a change rather than reporting
    # one and has no environment of its own to name.
    environment: str | None = None
    written_at: datetime | None = None


class DeploymentRollbackUndo(BaseModel):
    """The record of a deployment rolled back, in the shape that puts it back.

    Two pieces of prior state rather than one, and that is the whole of what
    makes this descriptor different from the flag's. Rolling a deployment back
    requires suspending the platform's own reconciliation first - it refuses
    otherwise, and would re-apply the revision being rolled away from at the
    next pass - so the action changed two things and an undo that restored
    only the revision would leave the deployment silently receiving nothing
    anybody ships to it.

    `was_on_history_id` is what a rollback is addressed to, and
    `was_on_revision` is the commit that entry deployed. Both, because they
    answer different questions: the identifier is what the platform's API
    takes, and the commit is what a human reading the record can look up. A
    descriptor holding only the identifier would be a number nobody can
    interpret once the history has moved on.

    `was_syncing_itself` is the setting as it was found, never a default.
    An application somebody had already stopped reconciling must be left
    stopped - putting it back to "on" because that is the usual arrangement
    would be Argus turning on a thing it did not turn off.
    """

    kind: Literal["deployment-revision"] = "deployment-revision"
    application: str
    was_on_history_id: int
    was_on_revision: str
    was_syncing_itself: bool
    tool: str = ROLL_BACK_DEPLOYMENT_TOOL
    written_at: datetime | None = None


# Two members, and the tag is what chooses between them. Everything that
# matches on `kind` carries a branch for each, which is what this was a tagged
# union for while it still had only one.
type UndoDescriptor = Annotated[
    FlagUndo | DeploymentRollbackUndo, Field(discriminator="kind")
]

_descriptors = TypeAdapter[UndoDescriptor](UndoDescriptor)


def parse_undo_descriptor(stored: Mapping[str, Any]) -> UndoDescriptor:
    """One descriptor, read back out of the JSONB column or off the wire.

    Here rather than at each reader for the reason `parse_event` is: the union
    decides which member a stored object is, and a caller that reached for a
    member directly would be deciding that for itself - correctly today, and
    silently wrongly the first time a second kind of change is stored.
    """
    return _descriptors.validate_python(stored)
