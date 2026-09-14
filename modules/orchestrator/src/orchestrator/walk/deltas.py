"""What a node is allowed to change, and the one place it stops being a dict.

LangGraph takes a mapping of field names from every node and merges it into the
state. Written as a literal at each `return`, that mapping is unchecked in both
directions: `"action_outcom"` type-checks, runs, and silently drops the verdict
the walk turns on, and a field spelled right but typed wrong reaches the state
machine as whatever the node happened to build.

So a node returns this instead, and `with_status` - which every node already
passes through - is the single function that speaks LangGraph's convention. One
boundary rather than seven.

Only what a node sets is sent on. `model_fields_set` is what makes that true:
an absent field is absent from the update, where a default would be the node
quietly overwriting something another node decided. The values are read off the
model rather than dumped, so an `Action` arrives as an `Action` and not as a
dict of its fields.
"""

from __future__ import annotations

from typing import Any

from argus_core.models import Action, Attempt, Hypothesis, IncidentStatus, Reading, Verdict
from pydantic import BaseModel, ConfigDict


class Narration(BaseModel):
    """What a node says it just did, on its way past.

    One sentence, carried to the `StatusChanged` that accounts for the move it
    made. It used to be four fields, three of them the columns of a second
    account kept in a table of its own; that table is gone and so is the copy.

    Two fields for the one sentence, because the two are not always the same:
    `action` is what the node did, and `detail` is what the account should say
    where those differ - the Investigator's event names what the investigation
    did, while Mitigation's names what came back from the action. Defaulting
    `detail` to `action` keeps the ordinary case to one field.

    A node returns this alongside its work and never writes it anywhere.
    Nothing about narration is a node's to decide except the words - and a node
    that moved the incident nowhere may return one that nothing reads.
    """

    action: str
    detail: str | None = None

    def said(self) -> str:
        """The sentence the published account carries."""
        return self.detail if self.detail is not None else self.action


class StateDelta(BaseModel):
    """The fields a node may change, and nothing else.

    A narrower model than `IncidentState` on purpose: `incident_id` and `alert`
    are what the walk is about rather than what it decides, and a node that
    could rewrite either would be a node that could change which incident is
    being worked on.

    Extra fields are refused rather than ignored. Pydantic's default would drop
    a misspelt one in silence, which is the failure this model exists to end -
    said in a constructor instead of in a dict literal, but just as quiet.
    """

    model_config = ConfigDict(extra="forbid")

    status: IncidentStatus | None = None
    hypothesis: Hypothesis | None = None
    candidates: list[Hypothesis] | None = None
    candidate_index: int | None = None
    attempts: list[Attempt] | None = None
    already_read: list[Reading] | None = None
    rounds: int | None = None
    proposed_action: Action | None = None
    nothing_worth_trying: bool | None = None
    fix_found: bool | None = None
    confidence: float | None = None
    # The verdict itself, not its spelling. `str(verdict)` reaching the state
    # was how one value came to have two representations - the router branching
    # on `status` and the resume branching on the stringified outcome - and a
    # comparison against a misspelt literal is a branch that silently never
    # runs.
    action_outcome: Verdict | None = None
    # What the node says it did. Never a field of the state: `with_status`
    # takes it out, writes the row, and passes on what remains.
    narration: Narration | None = None

    def as_updates(self) -> dict[str, Any]:
        """What LangGraph is given: the fields this node actually set.

        `narration` is not among them even when set - it is the wrapper's, and
        left in it would become a field of `IncidentState`, checkpointed with
        the incident forever, describing whichever node happened to run last.
        """
        return {
            name: getattr(self, name)
            for name in self.model_fields_set
            if name != "narration"
        }
