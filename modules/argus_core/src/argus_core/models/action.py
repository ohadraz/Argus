from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, Field, GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

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


class UnreadVerdict(str):
    """A verdict on file that no `Verdict` spells.

    A verdict and not an `Outcome`, which is the other thing in this module
    that a stored action produces: an `Outcome` is a verdict with the detail
    and the way back beside it, and this is the one field of it that could not
    be read. Every branch that meets one asks `isinstance(..., Verdict)`, which
    is the question the name has to answer.

    The `action` table stores its outcome as text and goes on storing it as
    text: a row written before a verdict was renamed is history, and history
    still has to come back out of the table. So the column has three states
    rather than two, and this is the third - not the absence of an outcome,
    which means the worker died between acting and recording what it found,
    and is the one case a resuming walk has to ask the provider about.

    A `str`, because `Verdict` is a `StrEnum` and every destination that shows
    an outcome shows this one the same way: the timeline, the dashboard and the
    evidence the postmortem reads all interpolate whichever they were handed
    and print what the column holds. A state carrying no spelling would tell an
    operator less than the row does, and leave an escalation unable to name
    what stopped it.

    Which is also why it refuses a spelling `Verdict` knows. Both are `str`, so
    `UnreadVerdict("confirmed")` would compare equal to `Verdict.CONFIRMED`
    while failing every `isinstance` narrowing decided against it - read as a
    verdict where an outcome is shown, and absent where one is judged. Nothing
    on the read path can produce such a value, since a spelling a verdict has
    becomes that verdict; the invariant is here so that nothing off the read
    path can produce one either.
    """

    def __new__(cls, spelling: str) -> UnreadVerdict:
        if spelling in _THE_SPELLINGS_OF_A_VERDICT:
            raise ValueError(
                f"[{spelling}] is how a `Verdict` is spelled, so it is not a "
                f"verdict nobody can read - `Verdict({spelling!r})` is."
            )

        return super().__new__(cls, spelling)

    @classmethod
    def __get_pydantic_core_schema__(cls,
                                     source: Any,
                                     handler: GetCoreSchemaHandler) -> CoreSchema:
        """Validated as a string and then built through the constructor above.

        Pydantic knows nothing about a bare `str` subclass, and a field
        annotated with one is a schema error rather than a default. Saying so
        here keeps the refusal on the way in: a model handed a spelling a
        verdict has raises where it is built, not somewhere downstream that
        expected the narrowing to hold.
        """
        return core_schema.no_info_after_validator_function(cls,
                                                            core_schema.str_schema())


_THE_SPELLINGS_OF_A_VERDICT: Final = frozenset(verdict.value for verdict in Verdict)


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
