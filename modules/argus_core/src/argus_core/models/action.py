from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, Field

from argus_core.models.undo_descriptor import FlagUndo, UndoDescriptor


class Verdict(StrEnum):
    """What an attempted mitigation says about the hypothesis behind it.

    `CONFIRMED` and `REFUTED` are the two answers spec §7.3 asks Mitigation
    for. A confirmed action resolves the incident; a refuted one leaves it
    where it was, in `mitigating`, for the next explanation on the list.
    `ESCALATED` is not a third opinion on the hypothesis - it means no verdict
    was reached at all, because nothing could be done or because the
    environment was left in a state Argus cannot account for.

    `WITHDRAWN` is the other way no verdict is reached: the action was taken and
    then abandoned, because somebody took the incident back while the service
    was still being watched. It is not `REFUTED` - nothing was measured, and
    recording evidence against a hypothesis nobody finished testing is the one
    thing a stopped experiment must not leave behind. The change it made is
    still out there, which is why the outcome carries its undo descriptor.
    """

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    ESCALATED = "escalated"
    WITHDRAWN = "withdrawn"


class RevertFeatureFlag(BaseModel):
    """Putting one feature flag back where it was (spec §7.3, §13).

    Here rather than in `agent_mitigation` for the same reason `Hypothesis` is
    here: it crosses agent boundaries. Mitigation proposes one, the
    Orchestrator's gate node inspects it, the graph's state carries it between
    the two, and the `action` table stores what became of it - so it belongs to
    no single agent.

    `enabled` is the state to leave the flag in, which is whatever undoes the
    change that caused the incident - off for a flag that was switched on, on
    for one that was switched off. Stating the target state rather than "revert
    it" is what lets this one action serve both directions.

    `undo_descriptor` is populated at proposal time, before anything is called,
    and is *required*: this is an action type Argus can put back, and one of
    these without a way back is not a thing that should be expressible. What
    §13 refuses to take autonomously is an action of a kind that cannot be
    undone at all - a per-type fact, which the gate asks the strategy that
    proposed it rather than reading off an instance. An optional field here
    would answer the wrong question and would reach a withdrawal hours later as
    a `None` nobody can act on.
    """

    action_type: Literal["revert-feature-flag"] = "revert-feature-flag"
    flag: str
    enabled: bool
    undo_descriptor: FlagUndo


# One member today, spelled as the union it is. `action_type` is Argus's own
# word for what was done - it is a column on the `action` table and a field on
# the event a reader sees - so it tags the union, where the descriptor's `tool`
# is the write tier's wire vocabulary and does not.
type Action = Annotated[RevertFeatureFlag, Field(discriminator="action_type")]

# What any action calls itself. Named separately from the union because the
# things that render or store an action carry the tag alone: the event says
# what was done without carrying the proposal, and the row keeps a column.
type ActionType = Literal["revert-feature-flag"]

# The tag as a value, for the row and the event that carry it without carrying
# the action. Here beside the type rather than in the agent that proposes one:
# the column, the published event and the model would otherwise be three
# spellings of one word, and only two of them would fail to compile if they
# disagreed.
REVERT_FEATURE_FLAG: Final[ActionType] = "revert-feature-flag"


class Outcome(BaseModel):
    """What happened when an action was taken.

    `detail` is for the human reading the timeline, and carries what the
    verdict alone cannot - which flag was changed, and, where a restore failed,
    what the provider said about it. `undo_descriptor` is the one the write
    tier returned, which is the record of what was actually changed rather than
    what was intended; it is absent when nothing was changed at all.
    """

    verdict: Verdict
    detail: str
    undo_descriptor: UndoDescriptor | None = None
